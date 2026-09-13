"""Harness implementation changes must not quietly change a scoring cohort."""

import hashlib
import json
from pathlib import Path
import shutil
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from evals.datasets.loader import read_json
from evals.experiments.comparison import write_comparison
from evals.experiments.fingerprints import (
    REPO_ROOT, SCORING_FILES, code_fingerprints, legacy_code_sha256, migrate_baseline, source_manifest,
)
from evals.experiments.runner import run_experiment

DATASET = REPO_ROOT / 'datasets/tax-mini-poc'
ARTIFACTS = REPO_ROOT / 'artifacts/2026-09-13'


class FingerprintTests(unittest.TestCase):
    def copied_source(self, root):
        shutil.copytree(REPO_ROOT / 'evals', root / 'evals', ignore=shutil.ignore_patterns('__pycache__'))
        (root / 'datasets/tax-mini-poc').mkdir(parents=True)
        shutil.copy(DATASET / 'grade.py', root / 'datasets/tax-mini-poc/grade.py')

    def test_adapter_reporting_and_runner_changes_are_runtime_only(self):
        for name in ('adapters/native.py', 'reporting/phoenix.py', 'experiments/runner.py'):
            with self.subTest(name=name), TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.copied_source(root)
                before, old_full = code_fingerprints(root), legacy_code_sha256(root)
                path = root / 'evals' / name
                path.write_text(path.read_text() + '\n# Runtime implementation change\n')
                after = code_fingerprints(root)
                self.assertEqual(before['contract_sha256'], after['contract_sha256'])
                self.assertEqual(before['scoring_sha256'], after['scoring_sha256'])
                self.assertNotEqual(before['runtime_code_sha256'], after['runtime_code_sha256'])
                self.assertNotEqual(old_full, legacy_code_sha256(root))

    def test_runtime_context_does_not_change_public_task_contract(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.copied_source(root)
            before = code_fingerprints(root)
            path = root / 'evals/contracts.py'
            path.write_text(path.read_text().replace('    run_id: str = ""', '    run_id: str = ""\n    local_only: str = ""'))
            after = code_fingerprints(root)
            self.assertEqual(before['contract_sha256'], after['contract_sha256'])
            self.assertNotEqual(before['runtime_code_sha256'], after['runtime_code_sha256'])
            path.write_text(path.read_text().replace('    tax_year: int', '    tax_year: str'))
            self.assertNotEqual(after['contract_sha256'], code_fingerprints(root)['contract_sha256'])

    def test_contract_and_scoring_changes_have_separate_fingerprints(self):
        for name, key in (
            ('evals/experiments/prompt.py', 'contract_sha256'),
            ('evals/datasets/loader.py', 'contract_sha256'),
            ('evals/json_io.py', 'contract_sha256'),
            ('evals/evaluators/schema.py', 'scoring_sha256'),
            ('datasets/tax-mini-poc/grade.py', 'scoring_sha256'),
            ('evals/evaluators/new_helper.py', 'scoring_sha256'),
        ):
            with self.subTest(name=name), TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.copied_source(root)
                before = code_fingerprints(root)
                path = root / name
                path.write_text((path.read_text() if path.exists() else '') + '\n# Reviewed behavior changed\n')
                after = code_fingerprints(root)
                self.assertNotEqual(before[key], after[key])
                other = 'contract_sha256' if key == 'scoring_sha256' else 'scoring_sha256'
                self.assertEqual(before[other], after[other])

    def test_snapshot_is_complete_private_and_hashed_even_for_one_selected_task(self):
        calls = []
        with TemporaryDirectory() as temporary:
            run = run_experiment(DATASET, lambda text: calls.append(text) or {}, Path(temporary),
                                 task_id='reconcile_case', prompt_root=Path('/workspace'))
            report = read_json(run / 'report.json')
            snapshot_bytes = (run / 'dataset-snapshot.json').read_bytes()
            snapshot = json.loads(snapshot_bytes)
            self.assertEqual(report['dataset_snapshot_sha256'], hashlib.sha256(snapshot_bytes).hexdigest())
            self.assertEqual(len(snapshot['examples']), 6)
            self.assertEqual(snapshot['dataset_version'], report['dataset_version'])
            self.assertEqual(snapshot['prompt_version'], report['prompt_version'])
            selected = next(row for row in snapshot['examples'] if row['task_id'] == 'reconcile_case')
            self.assertEqual(selected['input'], calls[0])
            self.assertIn('values', selected['expected'])
            self.assertNotIn('ground_truth', calls[0])
            self.assertNotIn('snapshot', calls[0])
            self.assertEqual(list(run.glob('tasks/*/dataset-snapshot.json')), [])


class BaselineMigrationTests(unittest.TestCase):
    def restore_baseline(self, root, index=0):
        manifest = read_json(ARTIFACTS / 'baseline-compatibility.json')
        entry = manifest['runs'][index]
        run = root / 'original' / entry['run_id']
        with tarfile.open(ARTIFACTS / 'runs.tar.gz') as archive:
            for item in entry['files']:
                path = run / item['path']
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.extractfile('runs/' + entry['run_id'] + '/' + item['path']).read())
        return run

    def test_exact_archive_migrates_without_rewriting_original_results(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.restore_baseline(root)
            old_bytes = (original / 'report.json').read_bytes()
            with patch('evals.experiments.prompt.build_prompt', side_effect=AssertionError('Must use saved input')), \
                 patch('evals.experiments.runner.build_dataset_snapshot', side_effect=AssertionError('Must use saved input')):
                migrated = migrate_baseline(original, root / 'migrated', historical_only=True)
            self.assertEqual((original / 'report.json').read_bytes(), old_bytes)
            before, after = json.loads(old_bytes), read_json(migrated / 'report.json')
            for key, value in before.items():
                self.assertEqual(after[key], value)
            self.assertEqual((migrated / 'traces.json').read_bytes(), (original / 'traces.json').read_bytes())
            self.assertEqual((migrated / 'phoenix.json').read_bytes(), (original / 'phoenix.json').read_bytes())
            self.assertEqual(after['runtime_fingerprint_basis'], 'legacy-whole-evals')
            self.assertEqual(after['scoring_sha256'], code_fingerprints()['scoring_sha256'])
            manifest = read_json(ARTIFACTS / 'baseline-compatibility.json')
            self.assertEqual(after['contract_sha256'], manifest['contract_sha256'])
            self.assertNotEqual(after['contract_sha256'], code_fingerprints()['contract_sha256'])
            self.assertEqual(after['fingerprint_migration']['mode'], 'historical-only')
            snapshot = read_json(migrated / 'dataset-snapshot.json')
            self.assertEqual(snapshot['prompt_version'], before['prompt_version'])
            self.assertEqual([example['input'] for example in snapshot['examples']],
                             [row['input'] for row in before['rows']])
            expected = read_json(DATASET / 'ground_truth/expected.json')['answers']
            self.assertEqual({example['task_id']: example['expected'] for example in snapshot['examples']}, expected)
            second_original = self.restore_baseline(root, index=1)
            second_migrated = migrate_baseline(second_original, root / 'migrated', historical_only=True)
            compared = read_json(write_comparison([migrated, second_migrated], root))
            self.assertEqual(compared['compatibility_mode'], 'contract-and-scoring')
            self.assertEqual(compared['contract_sha256'], manifest['contract_sha256'])
            fresh = run_experiment(DATASET, lambda _: {}, root / 'new', prompt_root=Path('/workspace'))
            with self.assertRaisesRegex(ValueError, 'matching dataset, prompt, evaluator'):
                write_comparison([migrated, fresh], root)
            with self.assertRaisesRegex(ValueError, 'already exists'):
                migrate_baseline(original, root / 'migrated', historical_only=True)

    def test_modified_report_cannot_claim_baseline_compatibility(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.restore_baseline(root)
            path = original / 'report.json'
            path.write_text(path.read_text() + '\n')
            for historical_only in (False, True):
                with self.subTest(historical_only=historical_only), self.assertRaisesRegex(ValueError, 'exact audited baseline'):
                    migrate_baseline(original, root / 'migrated', historical_only=historical_only)
            self.assertFalse((root / 'migrated').exists())

    def test_changed_source_or_sidecar_fails_before_writing_copy(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.restore_baseline(root)
            with self.assertRaisesRegex(ValueError, 'contract/scoring sources differ'):
                migrate_baseline(original, root / 'migrated')
            with patch('evals.experiments.fingerprints.source_manifest', return_value={}):
                with self.assertRaisesRegex(ValueError, 'sources differ'):
                    migrate_baseline(original, root / 'migrated')
            path = original / 'traces.json'
            path.write_text(path.read_text() + '\n')
            with self.assertRaisesRegex(ValueError, 'artifact differs'):
                migrate_baseline(original, root / 'migrated', historical_only=True)
            self.assertFalse((root / 'migrated').exists())

    def test_historical_mode_rejects_changed_scoring_sources_or_new_evaluator(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.restore_baseline(root)
            changed = source_manifest()
            changed['evals/evaluators/schema.py'] = '0' * 64
            with patch('evals.experiments.fingerprints.source_manifest', return_value=changed):
                with self.assertRaisesRegex(ValueError, 'scoring sources differ'):
                    migrate_baseline(original, root / 'migrated', historical_only=True)
            changed_hash = {**code_fingerprints(), 'scoring_sha256': '0' * 64}
            with patch('evals.experiments.fingerprints.code_fingerprints', return_value=changed_hash):
                with self.assertRaisesRegex(ValueError, 'scoring sources differ'):
                    migrate_baseline(original, root / 'migrated', historical_only=True)
            self.assertFalse((root / 'migrated').exists())

    def test_historical_mode_rejects_changed_reference_dataset(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.restore_baseline(root)
            dataset = root / 'dataset' / DATASET.name
            shutil.copytree(DATASET, dataset)
            references = dataset / 'ground_truth/expected.json'
            references.write_text(references.read_text() + '\n')
            with self.assertRaisesRegex(ValueError, 'dataset differs'):
                migrate_baseline(original, root / 'migrated', dataset=dataset, historical_only=True)
            self.assertFalse((root / 'migrated').exists())

    def test_committed_manifest_covers_exact_nine_archived_reports_and_reviewed_sources(self):
        manifest = read_json(ARTIFACTS / 'baseline-compatibility.json')
        self.assertEqual(len(manifest['runs']), 9)
        current_sources = source_manifest()
        self.assertEqual({name: manifest['reviewed_sources'][name] for name in SCORING_FILES},
                         {name: current_sources[name] for name in SCORING_FILES})
        self.assertEqual(manifest['scoring_sha256'], code_fingerprints()['scoring_sha256'])
        self.assertNotEqual(manifest['contract_sha256'], code_fingerprints()['contract_sha256'])
        self.assertEqual(hashlib.sha256((ARTIFACTS / 'runs.tar.gz').read_bytes()).hexdigest(), manifest['archive_sha256'])
        with tarfile.open(ARTIFACTS / 'runs.tar.gz') as archive:
            for entry in manifest['runs']:
                data = archive.extractfile('runs/' + entry['run_id'] + '/report.json').read()
                self.assertEqual(hashlib.sha256(data).hexdigest(), entry['report_sha256'])


if __name__ == '__main__':
    unittest.main()
