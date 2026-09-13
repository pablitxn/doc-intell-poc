"""The entrypoint must fail before paid work and allow upload-only recovery."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import shlex
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
        with patch.dict("sys.modules", {"phoenix.client": phoenix, "httpx": httpx}), \
             patch.object(run, "read_json", return_value={"prompt_root": None}), \
             patch.object(run, "validate_current_report"):
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

    def test_failed_upload_retry_preserves_the_dataset_and_phoenix_destination(self):
        dataset = 'datasets/full dataset'
        endpoint = 'http://127.0.0.1:7777'
        code, _, _, _, log = self.execute(
            ['--harness-command', 'my-harness', '--dataset', dataset,
             '--phoenix-url', endpoint],
            upload_error=ConnectionError())
        self.assertEqual(code, 1)
        retry = next(line.split('retry with ', 1)[1] for line in log.splitlines()
                     if 'retry with ' in line)
        self.assertEqual(shlex.split(retry), [
            './run.py', '--dataset', dataset, '--phoenix-url', endpoint,
            '--upload-only', 'runs/test'])

    def test_upload_only_never_constructs_or_executes_a_harness(self):
        code, factory, runner, upload, _ = self.execute(["--upload-only", "runs/test"])
        self.assertEqual(code, 0)
        factory.assert_not_called()
        runner.assert_not_called()
        self.assertEqual(upload.call_args.args[2], Path("runs/test"))

    def test_import_never_constructs_a_harness_or_regrades_saved_answers(self):
        with patch('evals.reporting.importer.import_report', return_value={
                'complete': True, 'experiment_id': 'imported'}) as importer, \
             patch.object(run, 'code_definitions', side_effect=AssertionError('must not load current scoring')):
            code, factory, runner, upload, _ = self.execute([
                '--import-run', 'runs/historical', '--output-dir', 'runs/restored',
                '--phoenix-url', 'http://localhost:7777'])
        self.assertEqual(code, 0)
        factory.assert_not_called()
        runner.assert_not_called()
        upload.assert_not_called()
        self.assertEqual(importer.call_args.args[2:], (Path('runs/historical'), Path('runs/restored/imports')))

    def test_incompatible_upload_is_rejected_before_any_remote_publication(self):
        with patch('sys.argv', ['run.py', '--upload-only', 'runs/old']), \
             patch.object(run, 'read_json', return_value={'complete': True}), \
             patch.object(run, 'prepare_dataset') as dataset, \
             patch.object(run, 'register_evaluators') as registry, \
             patch.object(run, 'publish_traces') as traces, \
             redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            code = run.main()
        self.assertEqual(code, 1)
        dataset.assert_not_called()
        registry.assert_not_called()
        traces.assert_not_called()

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
