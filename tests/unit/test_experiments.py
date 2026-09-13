"""Repeated native runs keep failures, isolated inputs, traces and publication IDs."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from evals.contracts import HarnessResult
from evals.datasets.loader import load_examples, read_json
from evals.experiments.runner import run_experiment
from tests.support.paths import ROOT

DATASET = ROOT / 'datasets/tax-mini-poc'


class RepeatedExperimentTests(unittest.TestCase):
    def test_native_invocations_get_no_ground_truth_and_keep_all_attempts(self):
        examples, _ = load_examples(DATASET)
        answers = {example.input.task_id: example.expected for example in examples}
        received = []

        class Adapter:
            def invoke(self, invocation):
                received.append(invocation)
                if invocation.repetition == 2:
                    return HarnessResult(status='timeout', error='HarnessTimeout')
                return HarnessResult(output=deepcopy(answers[invocation.task_id]), usage={'input_tokens': 0})

        with TemporaryDirectory() as temporary:
            run_dir = run_experiment(DATASET, Adapter(), Path(temporary), adapter_name='native-test',
                                     task_id='reconcile_case', repetitions=3, prompt_root=Path('/workspace'))
            report = read_json(run_dir / 'report.json')
            traces = read_json(run_dir / 'traces.json')
            self.assertEqual(report['summary']['tasks_evaluated'], 3)
            self.assertEqual(report['summary']['tasks_passed'], 2)
            self.assertEqual(report['summary']['fields_evaluated'], 18)
            self.assertEqual(report['summary']['execution_status_counts'], {'success': 2, 'timeout': 1})
            self.assertEqual(report['summary']['groups']['reconciliation']['tasks_evaluated'], 3)
            self.assertEqual([row['repetition'] for row in report['rows']], [1, 2, 3])
            self.assertEqual(len({row['trace_id'] for row in report['rows']}), 3)
            self.assertEqual({span['trace_id'] for span in traces}, {row['trace_id'] for row in report['rows']})
            self.assertTrue(report['complete'])
            self.assertEqual(len((run_dir / 'scores.csv').read_text().splitlines()), 4)
        for invocation in received:
            self.assertNotIn('ground_truth', invocation.input_text)
            self.assertNotIn(str(DATASET), invocation.input_text)
            self.assertIn('/workspace/inputs/', invocation.input_text)
            self.assertFalse(hasattr(invocation, 'expected'))

    def test_invalid_repetitions_fail_before_calls_or_artifacts(self):
        for repetitions in (0, -1, True, 1.5):
            with self.subTest(repetitions=repetitions), TemporaryDirectory() as temporary:
                with self.assertRaises(ValueError):
                    run_experiment(DATASET, lambda _: self.fail('must not call'), Path(temporary), repetitions=repetitions)
                self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_native_metadata_and_zero_usage_survive(self):
        with TemporaryDirectory() as temporary:
            run_dir = run_experiment(DATASET, lambda _: HarnessResult(output={}, usage={'input_tokens': 0},
                metadata={'session_id': 'session-1'}), Path(temporary), task_id='extract_doc_001',
                harness_metadata={'model': 'shared-model', 'version': '1.2.3'})
            report = read_json(run_dir / 'report.json')
            self.assertEqual(report['harness_metadata']['model'], 'shared-model')
            self.assertEqual(report['rows'][0]['usage']['input_tokens'], 0)
            self.assertEqual(report['rows'][0]['telemetry']['session_id'], 'session-1')


if __name__ == '__main__':
    unittest.main()
