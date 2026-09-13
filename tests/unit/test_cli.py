"""CLITests for the shared evaluation application."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import unittest
from unittest.mock import patch
from evals.__main__ import main
from tests.support.answers import empty_response


class CLITests(unittest.TestCase):
    def test_harness_command_is_required(self):
        with patch("sys.argv", ["evals"]), redirect_stderr(StringIO()):
            with patch("evals.application.command_harness") as factory, patch("evals.application.run_experiment") as runner:
                with self.assertRaises(SystemExit) as error:
                    main()
                self.assertEqual(error.exception.code, 2)
                factory.assert_not_called()
                runner.assert_not_called()

    def test_missing_executable_does_not_start_an_experiment(self):
        with patch("sys.argv", ["evals", "--harness-command", "missing"]), redirect_stderr(StringIO()):
            with patch("evals.application.command_harness", side_effect=ValueError("Executable not found")):
                with patch("evals.application.run_experiment") as runner:
                    with self.assertRaises(SystemExit) as error:
                        main()
                    self.assertEqual(error.exception.code, 2)
                    runner.assert_not_called()

    def test_cli_passes_command_as_arguments_and_run_options(self):
        argv = ["evals", "--harness-command", 'my-harness run --label "two words"',
                "--dataset", "custom-dataset", "--task", "reconcile_case",
                "--output-dir", "custom-runs", "--timeout", "30"]
        summary = {"tasks_passed": 1, "tasks_evaluated": 1, "fields_evaluated": 6}
        with patch("sys.argv", argv), redirect_stdout(StringIO()):
            with patch("evals.application.command_harness", return_value=empty_response) as factory:
                with patch("evals.application.run_experiment", return_value=Path("custom-runs/run-id")) as runner:
                    with patch("evals.__main__.read_json", return_value={"summary": summary}):
                        main()
            factory.assert_called_once_with(["my-harness", "run", "--label", "two words"], timeout_seconds=30.0)
            runner.assert_called_once_with(
                Path("custom-dataset"), empty_response, Path("custom-runs"),
                adapter_name="my-harness", task_id="reconcile_case",
            )
