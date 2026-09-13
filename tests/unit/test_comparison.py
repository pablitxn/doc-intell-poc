from pathlib import Path
import json
from tempfile import TemporaryDirectory
import unittest

from evals.datasets.loader import read_json
from evals.experiments.runner import run_experiment
from evals.experiments.comparison import write_comparison
from tests.support.paths import ROOT

DATASET = ROOT / 'datasets/tax-mini-poc'


class ComparisonTests(unittest.TestCase):
    def test_comparison_keeps_failures_null_consumption_and_original_evidence(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            def fail(_):
                raise TimeoutError()
            runs = [run_experiment(DATASET, fail, root, adapter_name=name, task_id='reconcile_case',
                                  harness_metadata={'model':'same', 'provider':'same', 'thinking':'medium'})
                    for name in ('pi', 'tau')]
            path = write_comparison(runs, root)
            data = read_json(path)
            self.assertTrue(data['same_model_configuration'])
            self.assertEqual([r['tasks_passed'] for r in data['harnesses']], [0, 0])
            self.assertTrue(all(r['input_tokens'] is None for r in data['harnesses']))
            self.assertTrue(all(Path(r['report']).exists() for r in data['harnesses']))
            self.assertEqual(len(path.with_suffix('.csv').read_text().splitlines()), 3)

    def test_different_task_membership_cannot_be_compared(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = [run_experiment(DATASET, lambda _: {}, root, task_id=task)
                    for task in ('extract_doc_001', 'reconcile_case')]
            with self.assertRaisesRegex(ValueError, 'membership'):
                write_comparison(runs, root)

    def test_unknown_model_is_not_reported_as_controlled_comparison(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = [run_experiment(DATASET, lambda _: {}, root, task_id='reconcile_case') for _ in range(2)]
            self.assertFalse(read_json(write_comparison(runs, root))['same_model_configuration'])

    def test_partial_reports_cannot_be_compared_as_finished_experiments(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = [run_experiment(DATASET, lambda _: {}, root, task_id='reconcile_case') for _ in range(2)]
            report = read_json(runs[0] / 'report.json')
            report['complete'] = False
            (runs[0] / 'report.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, 'complete'):
                write_comparison(runs, root)

    def test_changed_evaluator_code_cannot_be_compared_under_same_version_label(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = [run_experiment(DATASET, lambda _: {}, root, task_id='reconcile_case') for _ in range(2)]
            report = read_json(runs[0] / 'report.json')
            report['grader_sha256'] = 'changed-code'
            (runs[0] / 'report.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, 'matching'):
                write_comparison(runs, root)



    def test_runtime_sources_can_differ_with_matching_contract_and_scoring(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = [run_experiment(DATASET, lambda _: {}, root, task_id='reconcile_case') for _ in range(2)]
            report = read_json(runs[1] / 'report.json')
            report['eval_code_sha256'] = 'a' * 64
            report['runtime_code_sha256'] = 'b' * 64
            (runs[1] / 'report.json').write_text(json.dumps(report))
            comparison = read_json(write_comparison(runs, root))
            self.assertEqual(comparison['compatibility_mode'], 'contract-and-scoring')
            self.assertNotEqual(comparison['harnesses'][0]['eval_code_sha256'],
                                comparison['harnesses'][1]['eval_code_sha256'])

    def test_changed_contract_or_scoring_blocks_comparison(self):
        for key in ('contract_sha256', 'scoring_sha256'):
            with self.subTest(key=key), TemporaryDirectory() as temporary:
                root = Path(temporary)
                runs = [run_experiment(DATASET, lambda _: {}, root, task_id='reconcile_case') for _ in range(2)]
                report = read_json(runs[1] / 'report.json')
                report[key] = 'a' * 64
                (runs[1] / 'report.json').write_text(json.dumps(report))
                with self.assertRaisesRegex(ValueError, 'matching'):
                    write_comparison(runs, root)

    def test_legacy_requires_matching_whole_source_and_cannot_mix_with_modern(self):
        keys = ('fingerprint_version', 'contract_sha256', 'scoring_sha256', 'runtime_code_sha256')
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = [run_experiment(DATASET, lambda _: {}, root, task_id='reconcile_case') for _ in range(2)]
            reports = [read_json(run / 'report.json') for run in runs]
            for key in keys:
                reports[0].pop(key)
            (runs[0] / 'report.json').write_text(json.dumps(reports[0]))
            with self.assertRaisesRegex(ValueError, 'migrate legacy'):
                write_comparison(runs, root)
            for key in keys:
                reports[1].pop(key)
            (runs[1] / 'report.json').write_text(json.dumps(reports[1]))
            self.assertEqual(read_json(write_comparison(runs, root))['compatibility_mode'], 'legacy-full-source')
            reports[1]['eval_code_sha256'] = 'a' * 64
            (runs[1] / 'report.json').write_text(json.dumps(reports[1]))
            with self.assertRaisesRegex(ValueError, 'matching'):
                write_comparison(runs, root)

    def test_partial_fingerprint_metadata_cannot_fall_back_to_legacy(self):
        for key in ('fingerprint_version', 'contract_sha256', 'scoring_sha256', 'runtime_code_sha256'):
            self._assert_invalid_comparison_field(key, [None, '', ' ', 0, False, {}, []], 'metadata')

    def test_missing_repetitions_cannot_hide_behind_complete_true(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = [run_experiment(DATASET, lambda _: {}, root, task_id='reconcile_case', repetitions=2)
                    for _ in range(2)]
            for run in runs:
                report = read_json(run / 'report.json')
                report['rows'].pop()
                (run / 'report.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, 'complete task/repetition'):
                write_comparison(runs, root)


    def _assert_invalid_comparison_field(self, key, invalid_values, message):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = [run_experiment(DATASET, lambda _: {}, root, task_id='reconcile_case') for _ in range(2)]
            originals = [(run / 'report.json').read_text() for run in runs]
            output = root / 'comparisons'
            output.mkdir()
            missing = object()
            for value in [missing, *invalid_values]:
                with self.subTest(key=key, value='missing' if value is missing else repr(value)):
                    # Corrupt both reports equally: equality alone must not
                    # treat missing or malformed metadata as a valid match.
                    for run, original in zip(runs, originals):
                        report = json.loads(original)
                        if value is missing:
                            report.pop(key)
                        else:
                            report[key] = value
                        (run / 'report.json').write_text(json.dumps(report))
                    with self.assertRaisesRegex(ValueError, message):
                        write_comparison(runs, output)
                    self.assertEqual(list(output.iterdir()), [])

    def test_complete_must_be_explicit_boolean_true(self):
        self._assert_invalid_comparison_field(
            'complete', [False, None, 0, 1, 'true', [], {}], 'complete')

    def test_comparison_metadata_and_hashes_must_be_nonempty_text(self):
        for key in ('dataset_version', 'prompt_version', 'evaluator_version',
                    'grader_sha256', 'eval_code_sha256', 'document_access'):
            self._assert_invalid_comparison_field(key, [None, '', '  ', 1, True, [], {}], 'metadata')

    def test_repetitions_must_be_a_positive_integer(self):
        self._assert_invalid_comparison_field(
            'repetitions', [None, 0, -1, True, False, 1.0, '1'], 'repetitions')
