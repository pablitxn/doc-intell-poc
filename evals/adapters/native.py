"""Run prepared native CLIs with bounded stdin/stdout and process cleanup."""

from contextlib import AbstractContextManager
import math
import os
import selectors
import signal
import subprocess
import time
from typing import Callable

from evals.contracts import HarnessInvocation, HarnessResult, ProcessSpec
from evals.json_io import strict_json_loads as _strict_json
from .streams import EventCollector, OUTPUT_MODES, StreamFailure


MAX_STDOUT_BYTES = 16 * 1024 * 1024
MAX_LINE_BYTES = 2 * 1024 * 1024


def _kill_group(process: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:
            process.kill()
    except ProcessLookupError:
        pass


class NativeHarness:
    """Run one prepared CLI process per invocation, with no shell expansion."""

    def __init__(self, profile: dict,
                 prepare: Callable[[HarnessInvocation], AbstractContextManager[ProcessSpec]],
                 timeout_seconds: float = 120.0):
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise ValueError("Harness timeout must be a finite positive number")
        if not isinstance(profile, dict) or profile.get("output_mode") not in OUTPUT_MODES:
            raise ValueError("Unsupported harness output mode")
        self.profile = dict(profile)
        self.prepare = prepare
        self.timeout_seconds = timeout_seconds

    def invoke(self, invocation: HarnessInvocation) -> HarnessResult:
        if not isinstance(invocation.input_text, str):
            raise ValueError("Harness input must be text")
        collector = EventCollector(self.profile["output_mode"])
        result = None
        try:
            with self.prepare(invocation) as spec:
                result = self._execute(spec, invocation.input_text.encode("utf-8"), collector)
            return result
        except Exception:
            # Preparation/cleanup can contain provider paths or credentials in
            # their exception text. Preserve telemetry, never echo that text.
            return collector.result(status="adapter_error", error="PreparationError")

    def _execute(self, spec: ProcessSpec, payload: bytes, collector: EventCollector) -> HarnessResult:
        if (not isinstance(spec.argv, (tuple, list)) or not spec.argv
                or any(not isinstance(arg, str) or "\0" in arg for arg in spec.argv)
                or not spec.argv[0]):
            return collector.result(status="adapter_error", error="InvalidCommand")
        try:
            process = subprocess.Popen(
                spec.argv, cwd=spec.cwd, env=spec.env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False,
                start_new_session=os.name == "posix", bufsize=0,
            )
        except (OSError, ValueError):
            return collector.result(status="adapter_error", error="ProcessStartError")
        deadline = time.monotonic() + self.timeout_seconds
        pending = bytearray()
        total_bytes = 0
        sent = 0
        failure = None
        try:
            with selectors.DefaultSelector() as selector:
                os.set_blocking(process.stdout.fileno(), False)
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                if payload:
                    os.set_blocking(process.stdin.fileno(), False)
                    selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
                else:
                    process.stdin.close()
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise StreamFailure("Timeout")
                    for key, _mask in selector.select(min(remaining, 0.1)):
                        if key.data == "stdin":
                            try:
                                sent += os.write(key.fd, payload[sent:sent + 65536])
                            except BrokenPipeError:
                                sent = len(payload)
                            if sent >= len(payload):
                                selector.unregister(key.fileobj)
                                process.stdin.close()
                            continue
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        total_bytes += len(chunk)
                        if total_bytes > MAX_STDOUT_BYTES:
                            raise StreamFailure("OutputLimit")
                        pending.extend(chunk)
                        if collector.mode != "json":
                            while b"\n" in pending:
                                line, _, rest = pending.partition(b"\n")
                                if len(line) > MAX_LINE_BYTES:
                                    raise StreamFailure("OutputLimit")
                                collector.accept(line)
                                pending = bytearray(rest)
                            if len(pending) > MAX_LINE_BYTES:
                                raise StreamFailure("OutputLimit")
                if collector.mode != "json" and pending:
                    collector.accept(pending)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise StreamFailure("Timeout")
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    raise StreamFailure("Timeout") from None
        except StreamFailure as exc:
            failure = exc.category
        except (OSError, ValueError):
            failure = "TransportError"
        finally:
            # Also reap descendants when a launcher exits while leaving children.
            _kill_group(process)
            process.wait()
            process.stdin.close()
            process.stdout.close()
        if failure:
            return collector.result(status="timeout" if failure == "Timeout" else "adapter_error", error=failure)
        if process.returncode != 0:
            return collector.result(status="adapter_error", error="ProcessExitError")
        if collector.harness_error or collector.last_assistant_failed:
            return collector.result(status="adapter_error", error="HarnessError")
        if collector.protocol_error:
            return collector.result(status="invalid_response", error="InvalidStream")
        if collector.mode != "json" and not collector.completed:
            return collector.result(status="invalid_response", error="IncompleteStream")
        if collector.mode != "json" and collector.final_text is None:
            return collector.result(status="invalid_response", error="MissingFinalResponse")
        try:
            final = pending.decode("utf-8") if collector.mode == "json" else collector.final_text
            output = _strict_json(final)
        except (ValueError, UnicodeError, RecursionError):
            return collector.result(status="invalid_response", error="InvalidJSONResponse")
        result = collector.result()
        result.output = output
        return result
