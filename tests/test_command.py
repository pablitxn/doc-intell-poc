"""Exercise the executable boundary with harmless local subprocesses."""

import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import time
import traceback
import unittest
from unittest.mock import patch

from evals.adapters.command import command_harness


def python_harness(code, **kwargs):
    return command_harness([sys.executable, "-c", code], **kwargs)


class CommandHarnessTests(unittest.TestCase):
    def test_passes_exact_text_on_stdin_without_shell_interpretation(self):
        with TemporaryDirectory() as tmp:
            marker = Path(tmp) / "must-not-exist"
            input_text = f"Dataset: /dataset with spaces/\n¿Qué dice?\n$(touch '{marker}') `id`; $HOME\n"
            command = [sys.executable, "-c", (
                "import json,sys; "
                "print(json.dumps({'text': sys.stdin.read(), 'args': sys.argv[1:]}))"
            ), f"$(touch '{marker}')"]
            output = command_harness(command)(input_text)
            self.assertEqual(output, {"text": input_text, "args": command[3:]})
            self.assertFalse(marker.exists())

    def test_uses_a_fresh_process_for_each_call(self):
        run = python_harness("import json,os; print(json.dumps({'pid': os.getpid()}))")
        self.assertNotEqual(run("first")["pid"], run("second")["pid"])

    def test_inherits_environment_without_exposing_stderr(self):
        sentinel = "synthetic-secret-for-command-test"
        run = python_harness(
            "import json,os,sys; value = os.environ['EVAL_TEST_SENTINEL']; "
            "print(value, file=sys.stderr); print(json.dumps({'received': value}))"
        )
        with patch.dict(os.environ, {"EVAL_TEST_SENTINEL": sentinel}):
            self.assertEqual(run("task"), {"received": sentinel})

    def test_resolves_installed_executable_on_path(self):
        with TemporaryDirectory() as tmp:
            executable = Path(tmp) / "eval-test-harness"
            executable.symlink_to(sys.executable)
            with patch.dict(os.environ, {"PATH": tmp}):
                run = command_harness([executable.name, "-c", "print('{}')"])
            self.assertEqual(run("task"), {})

    def test_command_is_snapshotted_at_construction(self):
        command = [sys.executable, "-c", "print('{}')"]
        run = command_harness(command)
        command[-1] = "raise RuntimeError('must not run')"
        self.assertEqual(run("task"), {})

    def test_nonzero_exit_has_safe_error_without_diagnostics(self):
        run = python_harness(
            "import sys; print('private stdout'); "
            "print('private stderr', file=sys.stderr); sys.exit(9)"
        )
        try:
            run("task")
        except RuntimeError:
            diagnostic = traceback.format_exc()
        else:
            self.fail("Expected RuntimeError")
        self.assertIn("exited with status 9", diagnostic)
        self.assertNotIn("private stdout", diagnostic)
        self.assertNotIn("private stderr", diagnostic)

    def test_invalid_or_extra_stdout_is_a_safe_response_error(self):
        for output in ("private invalid output", "{}\n{}", "log line\n{}", ""):
            with self.subTest(output=output):
                run = python_harness(f"import sys; sys.stdout.write({output!r})")
                with self.assertRaisesRegex(ValueError, "one JSON response"):
                    run("task")

    def test_invalid_utf8_stdout_is_a_response_error(self):
        run = python_harness("import sys; sys.stdout.buffer.write(b'\\xff')")
        with self.assertRaisesRegex(ValueError, "one JSON response"):
            run("task")

    def test_duplicate_object_keys_are_rejected_instead_of_silently_overwritten(self):
        payloads = (
            '{"values":{},"values":{"amount":42}}',
            '{"values":{"amount":1,"amount":42}}',
            r'{"evidence":{"private-key-sentinel":1,"private-key-sentinel":2}}',
            r'{"values":{"amount":1,"\u0061mount":42}}',
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                run = python_harness(f"import sys; sys.stdout.write({payload!r})")
                with self.assertRaisesRegex(ValueError, "one JSON response") as raised:
                    run("task")
                self.assertNotIn("private-key-sentinel", str(raised.exception))

    def test_nonfinite_json_numbers_are_rejected_including_numeric_overflow(self):
        for number in ("NaN", "Infinity", "-Infinity", "1e999", "-1e999"):
            with self.subTest(number=number):
                payload = '{"values":{"amount":' + number + '}}'
                run = python_harness(f"import sys; sys.stdout.write({payload!r})")
                with self.assertRaisesRegex(ValueError, "one JSON response"):
                    run("task")

    def test_same_keys_in_distinct_objects_and_finite_numbers_remain_valid(self):
        payload = '{"values":[{"amount":1.25},{"amount":-2e3}]}'
        run = python_harness(f"import sys; sys.stdout.write({payload!r})")
        self.assertEqual(run("task"), {"values": [{"amount": 1.25}, {"amount": -2000.0}]})

    def test_timeout_terminates_harness_and_hides_diagnostics(self):
        run = python_harness(
            "import sys,time; print('private diagnostic', file=sys.stderr, flush=True); time.sleep(5)",
            timeout_seconds=0.2,
        )
        started = time.monotonic()
        with self.assertRaisesRegex(TimeoutError, "Harness command timed out"):
            run("task")
        self.assertLess(time.monotonic() - started, 2)

    @unittest.skipUnless(os.name == "posix", "Process groups require POSIX")
    def test_timeout_also_terminates_children_holding_output_pipes(self):
        run = python_harness(
            "import subprocess,sys,time; "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3)']); "
            "time.sleep(3)",
            timeout_seconds=0.3,
        )
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            run("task")
        # A surviving child would retain stdout/stderr and delay pipe cleanup.
        self.assertLess(time.monotonic() - started, 2)

    def test_rejects_invalid_command_before_invocation(self):
        for command in (None, "harness", [], [""], [123], [sys.executable, None], ["bad\0name"]):
            with self.subTest(command=command), self.assertRaises(ValueError):
                command_harness(command)
        with patch.object(shutil, "which", return_value=None):
            with self.assertRaisesRegex(ValueError, "not found on PATH"):
                command_harness(["missing-harness"])

    def test_rejects_invalid_timeout_before_invocation(self):
        for timeout in (0, -1, float("nan"), float("inf"), -float("inf"), True, "3", None):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(ValueError, "finite positive"):
                command_harness([sys.executable], timeout)

    def test_rejects_nontext_input(self):
        run = python_harness("print('{}')")
        with self.assertRaisesRegex(ValueError, "input must be text"):
            run({"task": "not text"})


if __name__ == "__main__":
    unittest.main()
