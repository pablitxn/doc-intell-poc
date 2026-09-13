"""Invoke an installed harness with UTF-8 text on stdin and JSON on stdout."""

import math
import os
import shutil
import signal
import subprocess

from evals.contracts import HarnessAdapter
from evals.json_io import strict_json_loads


def command_harness(command: list[str], timeout_seconds: float = 120.0) -> HarnessAdapter:
    """Resolve the command once; launch a fresh process for each input text."""
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(arg, str) or "\0" in arg for arg in command)
        or not command[0]
    ):
        raise ValueError("Harness command must be a nonempty list of arguments")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("Harness timeout must be a finite positive number")
    executable = shutil.which(command[0])
    if executable is None:
        raise ValueError("Harness executable was not found on PATH")
    argv = (executable, *command[1:])

    def run(input_text: str) -> object:
        if not isinstance(input_text, str):
            raise ValueError("Harness input must be text")
        payload = input_text.encode("utf-8")
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=os.name == "posix",
            )
        except OSError:
            raise RuntimeError("Could not start the harness executable") from None

        try:
            stdout, _ = process.communicate(payload, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            # npm launchers may spawn Node children. POSIX groups cover both.
            # Other platforms can only terminate the direct process here.
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            process.communicate()
            raise TimeoutError("Harness command timed out") from None

        if process.returncode != 0:
            raise RuntimeError(f"Harness command exited with status {process.returncode}")
        try:
            return strict_json_loads(stdout)
        except ValueError:
            raise ValueError("Harness stdout must contain one JSON response") from None

    return run
