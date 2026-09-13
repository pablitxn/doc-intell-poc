"""The entrypoint must fail before paid work and allow upload-only recovery."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import run


class RunEntrypointTests(unittest.TestCase):
    def execute(self, arguments, *, preflight_error=None, upload_error=None):
        phoenix = ModuleType("phoenix.client")
        phoenix.Client = MagicMock()
        httpx = ModuleType("httpx")
        httpx.Client = MagicMock()
        dataset = SimpleNamespace(name="test-dataset")
        log = StringIO()
        with patch.dict("sys.modules", {"phoenix.client": phoenix, "httpx": httpx}), patch.object(run, "read_json", return_value={"prompt_root": None}):
            with patch("sys.argv", ["run.py", *arguments]), redirect_stdout(log), redirect_stderr(log):
                with patch.object(run, "command_harness") as factory, patch.object(run, "run_experiment", return_value=Path("runs/test")) as runner:
                    with patch.object(run, "prepare_dataset", return_value=dataset, side_effect=preflight_error):
                        with patch.object(run, "register_evaluators", return_value={}), patch.object(run, "publish_report", side_effect=upload_error, return_value={"experiment_id": "exp"}) as upload:
                            code = run.main()
        return code, factory, runner, upload, log.getvalue()

    def test_phoenix_unavailable_never_calls_the_harness(self):
        code, _, runner, upload, _ = self.execute(["--harness-command", "my-harness"], preflight_error=ConnectionError())
        self.assertEqual(code, 1)
        runner.assert_not_called()
        upload.assert_not_called()

    def test_failed_upload_reports_local_artifact_for_recovery(self):
        code, _, runner, _, log = self.execute(["--harness-command", "my-harness"], upload_error=ConnectionError())
        self.assertEqual(code, 1)
        runner.assert_called_once()
        self.assertIn("--upload-only runs/test", log)

    def test_upload_only_never_constructs_or_executes_a_harness(self):
        code, factory, runner, upload, _ = self.execute(["--upload-only", "runs/test"])
        self.assertEqual(code, 0)
        factory.assert_not_called()
        runner.assert_not_called()
        self.assertEqual(upload.call_args.args[2], Path("runs/test"))

    def test_all_finishes_local_comparison_when_one_publication_fails(self):
        adapters = [(name, MagicMock(), {}) for name in ('pi', 'tau', 'codex')]
        with patch.object(run, 'native_adapters', return_value=adapters), \
             patch.object(run, 'write_comparison', return_value=Path('runs/comparison.json')) as comparison:
            code, _, runner, upload, log = self.execute(
                ['--harness', 'all'], upload_error=[ConnectionError(), {'experiment_id':'two'}, {'experiment_id':'three'}])
        self.assertEqual(code, 1)
        self.assertEqual(runner.call_count, 3)
        self.assertEqual(upload.call_count, 3)
        comparison.assert_called_once()
        self.assertIn('--upload-only runs/test', log)


if __name__ == "__main__":
    unittest.main()
