"""Bounded, observable subprocess adapters for the native harness CLIs.

Wire contracts: Pi docs/json.md, Tau src/tau_agent/{events,messages}.py,
and Codex codex-rs/exec/src/exec_events.rs in their official repositories.
Only normalized lifecycle metadata crosses this boundary; raw diagnostics,
tool arguments/results, and intermediate model text are never persisted here.
"""

from contextlib import AbstractContextManager
import hashlib
import json
import math
import os
import re
import selectors
import signal
import subprocess
import time
from typing import Callable

from evals.contracts import HarnessInvocation, HarnessResult, ProcessSpec
from evals.json_io import strict_json_loads as _strict_json


MAX_STDOUT_BYTES = 16 * 1024 * 1024
MAX_LINE_BYTES = 2 * 1024 * 1024
MAX_EVENTS = 20000
_MODES = {"json", "pi-jsonl", "tau-jsonl", "codex-jsonl"}
_USAGE_KEYS = (
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
    "reasoning_tokens",
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:/-]{1,200}\Z")


def _identifier(value: object) -> str | None:
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


def _event_identifier(value: object) -> str | None:
    """Normalize opaque wire IDs without rejecting valid provider punctuation.

    Pi/Tau's Codex provider joins call and item IDs with a pipe. Other providers
    may use different opaque strings. Hash non-simple IDs so lifecycle pairing
    survives while arbitrary text cannot enter the saved metadata.
    """
    if not isinstance(value, str) or not value:
        return None
    return _identifier(value) or "opaque-" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _counter(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _pick(mapping: dict, *keys: str) -> object:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _usage(value: object, *, codex: bool = False) -> dict:
    source = value if isinstance(value, dict) else {}
    aliases = (
        ("input_tokens",), ("output_tokens",), ("cached_input_tokens",),
        ("cache_write_input_tokens",), ("reasoning_output_tokens",),
    ) if codex else (
        ("input",), ("output",), ("cacheRead", "cache_read"),
        ("cacheWrite", "cache_write"), ("reasoning",),
    )
    normalized = {name: _counter(_pick(source, *fields)) for name, fields in zip(_USAGE_KEYS, aliases)}
    # Pi/Tau expose fresh input separately; Codex exposes total prompt input.
    # Normalize to total input while retaining cache subsets independently.
    if not codex and normalized["input_tokens"] is not None:
        normalized["input_tokens"] += sum(
            normalized[key] or 0 for key in ("cache_read_tokens", "cache_write_tokens")
        )
    return normalized


class _TransportFailure(Exception):
    def __init__(self, category: str):
        self.category = category


class _Collector:
    def __init__(self, mode: str):
        self.mode = mode
        self.events: list[dict] = []
        self.metadata: dict = {"timestamp_source": "observed"}
        self.usages: dict[str, dict] = {}
        self.final_text: str | None = None
        self.protocol_error = False
        self.harness_error = False
        self.last_assistant_failed = False
        self.completed = False
        self._seen_messages: set[str] = set()
        self._seen_events: set[tuple[str, str]] = set()
        self._active_message: str | None = None
        self._message_number = 0
        self._turn_number = 0

    def emit(self, kind: str, identifier: str, timestamp: int, **fields) -> None:
        key = (kind, identifier)
        if key in self._seen_events:
            return
        if len(self.events) >= MAX_EVENTS:
            raise _TransportFailure("OutputLimit")
        self._seen_events.add(key)
        self.events.append({
            "kind": kind, "id": identifier, "timestamp_ns": timestamp,
            "timestamp_source": "observed", **fields,
        })

    def accept(self, line: bytes) -> None:
        if not line.strip():
            return
        timestamp = time.time_ns()
        try:
            event = _strict_json(line.decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError):
            self.protocol_error = True
            return
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            self.protocol_error = True
            return
        if self.mode == "codex-jsonl":
            self._codex(event, timestamp)
        else:
            self._pi_tau(event, timestamp)

    def _pi_tau(self, event: dict, timestamp: int) -> None:
        kind = event["type"]
        if kind == "agent_start":
            self.completed = False
            self.final_text = None
        elif kind in {"agent_end", "agent_settled"}:
            self.completed = True
        elif kind == "session":
            session = _identifier(event.get("id"))
            if session:
                self.metadata["session_id"] = session
        elif kind == "error" and event.get("recoverable") is not True:
            self.harness_error = True
        elif kind in {"message_start", "message_end"}:
            message = event.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                return
            if kind == "message_start":
                self._message_number += 1
                self._active_message = f"llm-{self._message_number}"
                self.emit("llm_start", self._active_message, timestamp)
                return
            # message_end is authoritative. turn_end/agent_end contain copies;
            # never count their messages again or treat tool results as answers.
            fingerprint = hashlib.sha256(
                json.dumps(message, sort_keys=True, ensure_ascii=True).encode()
            ).hexdigest()
            if fingerprint in self._seen_messages:
                return
            self._seen_messages.add(fingerprint)
            if self._active_message is None:
                self._message_number += 1
            identifier = self._active_message or f"llm-{self._message_number}"
            self._active_message = None
            usage = _usage(message.get("usage"))
            self.usages[identifier] = usage
            reason = _pick(message, "stopReason", "stop_reason")
            self.last_assistant_failed = reason in {"error", "aborted"}
            self.emit("llm_end", identifier, timestamp, usage=usage,
                      status="error" if self.last_assistant_failed else "success")
            for key in ("provider", "model"):
                value = _identifier(message.get(key))
                if value and value != "unknown":
                    self.metadata[key] = value
            for key, aliases in (
                ("response_model", ("responseModel", "response_model")),
                ("response_provider", ("responseProvider", "response_provider")),
            ):
                value = _identifier(_pick(message, *aliases))
                if value:
                    self.metadata[key] = value
            content = message.get("content")
            self.final_text = None
            if isinstance(content, list):
                tool_calls = any(isinstance(block, dict) and block.get("type") == "toolCall"
                                 for block in content)
                if not tool_calls and reason != "toolUse":
                    blocks = [block for block in content
                              if isinstance(block, dict) and block.get("type") == "text"
                              and isinstance(block.get("text"), str)]
                    final_blocks = []
                    has_phases = False
                    for block in blocks:
                        signature = _pick(block, "textSignature", "text_signature")
                        try:
                            parsed = _strict_json(signature) if isinstance(signature, str) else None
                        except (ValueError, RecursionError):
                            parsed = None
                        phase = parsed.get("phase") if isinstance(parsed, dict) else None
                        if phase in {"commentary", "final_answer"}:
                            has_phases = True
                        if phase == "final_answer":
                            final_blocks.append(block)
                    # OpenAI Responses may place commentary and final blocks in
                    # one message. Its explicit phase is authoritative when present.
                    selected = final_blocks if has_phases else blocks
                    self.final_text = "".join(block["text"] for block in selected)
        elif kind in {"tool_execution_start", "tool_execution_end"}:
            identifier = _event_identifier(_pick(event, "toolCallId", "tool_call_id"))
            if identifier is None:
                self.protocol_error = True
                return
            name = _identifier(_pick(event, "toolName", "tool_name"))
            fields = {"name": name} if name else {}
            if kind.endswith("end"):
                fields["status"] = "error" if _pick(event, "isError", "is_error") is True else "success"
            self.emit("tool_start" if kind.endswith("start") else "tool_end",
                      identifier, timestamp, **fields)

    def _codex(self, event: dict, timestamp: int) -> None:
        kind = event["type"]
        if kind == "thread.started":
            identifier = _identifier(event.get("thread_id"))
            if identifier:
                self.metadata["session_id"] = identifier
        elif kind == "turn.started":
            self._turn_number += 1
            self.completed = False
            self.final_text = None
        elif kind == "turn.completed":
            self.usages[f"turn-{self._turn_number}"] = _usage(event.get("usage"), codex=True)
            self.completed = True
        elif kind in {"turn.failed", "error"}:
            self.harness_error = True
        elif kind in {"item.started", "item.completed"}:
            item = event.get("item")
            if not isinstance(item, dict):
                self.protocol_error = True
                return
            item_type = item.get("type")
            if item_type == "agent_message" and kind == "item.completed":
                self.final_text = item.get("text") if isinstance(item.get("text"), str) else None
            elif item_type in {"command_execution", "mcp_tool_call", "collab_tool_call", "web_search", "file_change"}:
                identifier = _event_identifier(item.get("id"))
                if identifier is None:
                    self.protocol_error = True
                    return
                name = _identifier(item.get("tool")) or item_type
                fields = {"name": name}
                if kind == "item.completed":
                    failed = item.get("status") in {"failed", "declined"}
                    if item_type == "command_execution":
                        failed = failed or item.get("exit_code") not in (None, 0)
                    fields["status"] = "error" if failed else "success"
                self.emit("tool_start" if kind == "item.started" else "tool_end",
                          identifier, timestamp, **fields)
            # Codex exec aggregates model usage at turn completion. Its message
            # items are not LLM request boundaries; do not fabricate LLM spans.

    def result(self, *, status="success", error=None) -> HarnessResult:
        totals = {}
        for key in _USAGE_KEYS:
            values = [usage[key] for usage in self.usages.values()]
            totals[key] = sum(values) if values and all(value is not None for value in values) else None
        return HarnessResult(status=status, error=error, events=self.events,
                             usage=totals, metadata=self.metadata)


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
        if not isinstance(profile, dict) or profile.get("output_mode") not in _MODES:
            raise ValueError("Unsupported harness output mode")
        self.profile = dict(profile)
        self.prepare = prepare
        self.timeout_seconds = timeout_seconds

    def invoke(self, invocation: HarnessInvocation) -> HarnessResult:
        if not isinstance(invocation.input_text, str):
            raise ValueError("Harness input must be text")
        collector = _Collector(self.profile["output_mode"])
        result = None
        try:
            with self.prepare(invocation) as spec:
                result = self._execute(spec, invocation.input_text.encode("utf-8"), collector)
            return result
        except Exception:
            # Preparation/cleanup can contain provider paths or credentials in
            # their exception text. Preserve telemetry, never echo that text.
            return collector.result(status="adapter_error", error="PreparationError")

    def _execute(self, spec: ProcessSpec, payload: bytes, collector: _Collector) -> HarnessResult:
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
                        raise _TransportFailure("Timeout")
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
                            raise _TransportFailure("OutputLimit")
                        pending.extend(chunk)
                        if collector.mode != "json":
                            while b"\n" in pending:
                                line, _, rest = pending.partition(b"\n")
                                if len(line) > MAX_LINE_BYTES:
                                    raise _TransportFailure("OutputLimit")
                                collector.accept(line)
                                pending = bytearray(rest)
                            if len(pending) > MAX_LINE_BYTES:
                                raise _TransportFailure("OutputLimit")
                if collector.mode != "json" and pending:
                    collector.accept(pending)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _TransportFailure("Timeout")
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    raise _TransportFailure("Timeout") from None
        except _TransportFailure as exc:
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
