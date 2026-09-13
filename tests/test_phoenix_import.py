"""Archive imports preserve historical scores and verify destination identities."""

from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import unquote

from evals.reporting.importer import import_report, _missing_spans, _hash, _span_time, SPAN_FINGERPRINT, _import_traces, _observable_attributes


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return deepcopy(self.body)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError(f"HTTP {self.status_code}")


class Phoenix:
    """The API persists before the network response, allowing lost-response tests."""
    base_url = "http://127.0.0.1:6006"

    def __init__(self):
        self.datasets = SimpleNamespace(get_dataset=self.get_dataset, create_dataset=self.create_dataset)
        self.experiments = SimpleNamespace(create=self.create, log_run=self.log_run, log_evaluation=self.log_evaluation)
        self.saved_datasets, self.saved_experiments, self.runs, self.scores = {}, [], [], {}
        self.spans = []
        self.lose = None

    def get_dataset(self, *, dataset):
        if dataset not in self.saved_datasets:
            raise ValueError(f"Dataset not found: {dataset}")
        return self.saved_datasets[dataset]

    def create_dataset(self, **kwargs):
        rows = deepcopy(kwargs['examples'])
        dataset_id = f"dataset-{len(self.saved_datasets)}"
        for index, row in enumerate(rows):
            row['node_id'] = f"{dataset_id}-example-{index}"
        result = SimpleNamespace(id=dataset_id, version_id=dataset_id + '-version', name=kwargs['name'], examples=rows)
        self.saved_datasets[result.name] = result
        self.lost('dataset')
        return result

    def lost(self, stage):
        if self.lose == stage:
            self.lose = None
            raise ConnectionError('response lost after commit')

    def create(self, **kwargs):
        result = {'id': f"experiment-{len(self.saved_experiments)}", 'dataset_id': kwargs['dataset_id'],
                  'dataset_version_id': kwargs['dataset_version_id'], 'name': kwargs['experiment_name'],
                  'metadata': deepcopy(kwargs['experiment_metadata']), 'repetitions': kwargs['repetitions']}
        self.saved_experiments.append(result)
        self.lost('experiment')
        return result

    def log_run(self, **kwargs):
        identity = tuple(kwargs[key] for key in ('experiment_id', 'dataset_example_id', 'repetition_number'))
        if any(tuple(run[key] for key in ('experiment_id', 'dataset_example_id', 'repetition_number')) == identity for run in self.runs):
            raise AssertionError('duplicate remote run was attempted')
        result = {'id': f"run-{len(self.runs)}", **deepcopy(kwargs)}
        for key in ('start_time', 'end_time'):
            result[key] = result[key].isoformat()
        self.runs.append(result)
        self.lost('run')
        return result

    def log_evaluation(self, **kwargs):
        self.scores[kwargs['experiment_run_id'], kwargs['name']] = deepcopy(kwargs)
        self.lost('score')

    def get(self, path, params=None):
        path = unquote(path)
        if path.endswith('/experiments'):
            dataset_id = path.split('/')[-2]
            return Response({'data': [item for item in self.saved_experiments if item['dataset_id'] == dataset_id]})
        if path.endswith('/runs'):
            experiment_id = path.split('/')[-2]
            return Response({'data': [item for item in self.runs if item['experiment_id'] == experiment_id]})
        if path.endswith('/json'):
            experiment_id = path.split('/')[-2]
            return Response([{'example_id': run['dataset_example_id'], 'repetition_number': run['repetition_number'],
                              'output': run['output'], 'trace_id': run.get('trace_id'),
                              'annotations': [score for (run_id, _), score in self.scores.items() if run_id == run['id']]}
                             for run in self.runs if run['experiment_id'] == experiment_id])
        if path.endswith('/spans'):
            return Response({'data': self.spans})
        raise AssertionError(path)


def fixture(root, *, snapshot=False, version='tax-mini-v1'):
    source = root / 'original'
    source.mkdir()
    report = {
        'complete': True, 'run_id': 'original-run', 'dataset': 'historical-mini', 'dataset_version': 'a' * 64,
        'prompt_version': 'tax-mini-text-v3', 'evaluator_version': version, 'grader_sha256': 'b' * 64,
        'eval_code_sha256': 'c' * 64, 'adapter': 'example', 'repetitions': 1,
        'summary': {'tasks_evaluated': 1}, 'harness_metadata': {'model': 'historical-model', 'thinking': 'medium'},
        'rows': [{'task_id': 'task1', 'case_id': 'case1', 'group': 'extraction', 'document_ids': ['doc1'],
                  'repetition': 1, 'input': 'Historical input, exactly as seen by the model.',
                  'output': {'values': {'amount': '7.00'}, 'evidence': {'amount': []}}, 'error': None,
                  'execution_status': 'success', 'start_time': '2026-09-13T13:00:00.100000+00:00',
                  'end_time': '2026-09-13T13:00:01.900000+00:00', 'elapsed_seconds': 1.8,
                  'usage': {'input_tokens': 123, 'output_tokens': 4}, 'telemetry': {'model': 'historical-model'},
                  'total_service_cost_usd': None, 'trace_id': '1' * 32,
                  'scores': {'schema_valid': True, 'task_pass': False, 'value_accuracy': 1.0,
                             'evidence_accuracy': 0.5, 'execution_status': 'success', 'schema_errors': []}}],
    }
    if snapshot:
        saved = {'dataset_version': report['dataset_version'], 'prompt_version': report['prompt_version'],
                 'examples': [{'task_id': 'task1', 'input': report['rows'][0]['input'],
                               'expected': {'values': {'amount': '7.00'}, 'evidence': {'amount': []}},
                               'field_types': {'amount': 'money'}}]}
        data = (json.dumps(saved, indent=2) + '\n').encode()
        (source / 'dataset-snapshot.json').write_bytes(data)
        report['dataset_snapshot_sha256'] = hashlib.sha256(data).hexdigest()
    spans = [{'trace_id': '1' * 32, 'span_id': '2' * 16, 'parent_span_id': None, 'name': 'task.execute',
              'kind': 'INTERNAL', 'start_time_unix_nano': 1789304400100000000,
              'end_time_unix_nano': 1789304401900000000, 'status': 'OK',
              'attributes': {'openinference.span.kind': 'CHAIN', 'input.value': report['rows'][0]['input']}}]
    (source / 'report.json').write_text(json.dumps(report))
    (source / 'traces.json').write_text(json.dumps(spans))
    (source / 'phoenix.json').write_text('{"complete":true,"experiment_id":"obsolete-id"}')
    (source / 'traces-upload.json').write_text('{"complete":true,"destination":"http://127.0.0.1:6006"}')
    return source, report, spans


class PhoenixImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.remote = Phoenix()
        self.source, self.report, self.spans = fixture(self.root)
        self.trace_patch = patch('evals.reporting.importer._import_traces')
        self.trace_patch.start()
        self.addCleanup(self.trace_patch.stop)

    def run_import(self, remote=None):
        client = remote or self.remote
        return import_report(client, client, self.source, self.root / 'receipts')

    def test_old_scores_and_versions_preserved_without_regrade_or_original_changes(self):
        original = {path.name: path.read_bytes() for path in self.source.iterdir()}
        result = self.run_import()
        self.assertTrue(result['complete'])
        self.assertEqual(result['reference_status'], 'unavailable')
        self.assertEqual(next(iter(self.remote.saved_datasets.values())).examples[0]['output'], {})
        metadata = self.remote.saved_experiments[0]['metadata']
        self.assertEqual(metadata['source_report']['evaluator_version'], 'tax-mini-v1')
        self.assertEqual(metadata['source_report']['harness_metadata'], self.report['harness_metadata'])
        evidence = self.remote.scores[('run-0', 'evidence_accuracy')]
        self.assertEqual(evidence['score'], 0.5)
        self.assertEqual(evidence['metadata']['version'], 'tax-mini-v1')
        self.assertEqual(evidence['metadata']['execution'], 'imported_saved_result')
        self.assertNotIn('phoenix_evaluator', str(metadata))
        self.assertEqual(self.remote.runs[0]['output']['source_measurements']['usage'], {'input_tokens': 123, 'output_tokens': 4})
        self.assertEqual(original, {path.name: path.read_bytes() for path in self.source.iterdir()})

    def test_repeat_requeries_remote_and_does_not_duplicate(self):
        first = self.run_import()
        second = self.run_import()
        self.assertEqual(first, second)
        self.assertEqual(len(self.remote.saved_experiments), 1)
        self.assertEqual(len(self.remote.runs), 1)
        self.assertEqual(len(self.remote.scores), 5)

    def test_same_url_after_server_reset_recreates_real_content_despite_complete_receipt(self):
        first = self.run_import()
        replacement = Phoenix()
        second = self.run_import(replacement)
        self.assertEqual(first['receipt'], second['receipt'])
        self.assertEqual(len(replacement.saved_experiments), 1)
        self.assertEqual(len(replacement.runs), 1)
        self.assertEqual(len(replacement.scores), 5)
        self.assertTrue(second['complete'])

    def test_lost_responses_recover_by_remote_identity_without_duplicates(self):
        for stage in ('dataset', 'experiment', 'run', 'score'):
            with self.subTest(stage=stage):
                remote = Phoenix()
                remote.lose = stage
                with self.assertRaises(ConnectionError):
                    self.run_import(remote)
                state = self.run_import(remote)
                self.assertTrue(state['complete'])
                self.assertEqual(len(remote.saved_datasets), 1)
                self.assertEqual(len(remote.saved_experiments), 1)
                self.assertEqual(len(remote.runs), 1)
                self.assertEqual(len(remote.scores), 5)

    def test_remote_score_corruption_is_rejected_before_overwriting(self):
        self.run_import()
        self.remote.scores['run-0', 'evidence_accuracy']['score'] = 0.75
        with self.assertRaisesRegex(ValueError, 'score differs'):
            self.run_import()
        self.assertEqual(self.remote.scores['run-0', 'evidence_accuracy']['score'], 0.75)

    def test_remote_run_corruption_is_rejected(self):
        self.run_import()
        self.remote.runs[0]['output']['answer'] = {'unexpected': True}
        with self.assertRaisesRegex(ValueError, 'output verification failed'):
            self.run_import()

    def test_remote_experiment_and_dataset_corruption_is_rejected(self):
        self.run_import()
        self.remote.saved_experiments[0]['metadata']['source_report']['evaluator_version'] = 'not-original'
        with self.assertRaisesRegex(ValueError, 'experiment differs'):
            self.run_import()
        self.remote.saved_experiments[0]['metadata']['source_report']['evaluator_version'] = 'tax-mini-v1'
        next(iter(self.remote.saved_datasets.values())).examples[0]['output'] = {'invented_reference': True}
        with self.assertRaisesRegex(ValueError, 'dataset content differs'):
            self.run_import()

    def test_invalid_report_rejected_before_remote_writes(self):
        for mutation in (lambda report: report.update(complete=False),
                         lambda report: report.update(repetitions=2),
                         lambda report: report['rows'].append(deepcopy(report['rows'][0])),
                         lambda report: report['rows'][0]['scores'].update(evidence_accuracy=1.01)):
            report = deepcopy(self.report)
            mutation(report)
            (self.source / 'report.json').write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                self.run_import()
        self.assertEqual(self.remote.saved_datasets, {})

    def test_missing_trace_artifact_is_not_silently_dropped(self):
        (self.source / 'traces.json').unlink()
        with self.assertRaisesRegex(ValueError, 'require the original traces'):
            self.run_import()
        self.assertEqual(self.remote.saved_datasets, {})

    def test_reference_snapshot_requires_original_digest_and_input(self):
        with TemporaryDirectory() as folder:
            source, report, _ = fixture(Path(folder), snapshot=True, version='tax-mini-v2')
            result = import_report(self.remote, self.remote, source, self.root / 'receipts')
            self.assertEqual(result['reference_status'], 'saved_snapshot')
            self.assertEqual(next(iter(self.remote.saved_datasets.values())).examples[0]['output']['values'], {'amount': '7.00'})
            snapshot = json.loads((source / 'dataset-snapshot.json').read_text())
            snapshot['examples'][0]['input'] = 'changed'
            (source / 'dataset-snapshot.json').write_text(json.dumps(snapshot))
            with self.assertRaisesRegex(ValueError, 'snapshot digest differs'):
                import_report(self.remote, self.remote, source, self.root / 'receipts')
            report['dataset_snapshot_sha256'] = hashlib.sha256((source / 'dataset-snapshot.json').read_bytes()).hexdigest()
            (source / 'report.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, 'snapshot input differs'):
                import_report(self.remote, self.remote, source, self.root / 'receipts')

    def test_output_directory_cannot_modify_original(self):
        with self.assertRaisesRegex(ValueError, 'outside the original'):
            import_report(self.remote, self.remote, self.source, self.source / 'import')

    def test_lost_trace_response_recovers_only_after_reading_persisted_span(self):
        original = self.spans[0]
        calls = []

        def post(*args, **kwargs):
            calls.append(kwargs)
            self.remote.spans = [{
                'context': {'trace_id': original['trace_id'], 'span_id': original['span_id']},
                'name': original['name'], 'parent_id': None, 'span_kind': 'CHAIN', 'status_code': 'OK',
                'start_time': _span_time(original['start_time_unix_nano']).isoformat(),
                'end_time': _span_time(original['end_time_unix_nano']).isoformat(),
                'attributes': _observable_attributes(original),
            }]
            raise ConnectionError('trace response lost after persistence')

        self.remote.post = post
        with patch('evals.reporting.importer.encode_otlp', return_value=b'encoded'):
            with self.assertRaises(ConnectionError):
                _import_traces(self.remote, self.spans, 'project')
            _import_traces(self.remote, self.spans, 'project')
        self.assertEqual(len(calls), 1)

    def test_metadata_normalization_and_changed_attribute_with_original_marker(self):
        original = deepcopy(self.spans[0])
        original['attributes']['metadata'] = json.dumps({'nested': {'model': 'old', 'empty': None, 'enabled': False},
                                                          'tags': ['one', 'two'], 'tools': [{'name': 'read'}]})
        expected = _observable_attributes(original)
        self.assertEqual(expected['metadata.nested.model'], 'old')
        self.assertNotIn('metadata.nested.empty', expected)
        self.assertEqual(expected['metadata.tags'], ['one', 'two'])
        self.assertEqual(expected['metadata.tools.0.name'], 'read')
        saved = {'context': {'trace_id': original['trace_id'], 'span_id': original['span_id']},
                 'name': original['name'], 'parent_id': None, 'span_kind': 'CHAIN', 'status_code': 'OK',
                 'start_time': _span_time(original['start_time_unix_nano']).isoformat(),
                 'end_time': _span_time(original['end_time_unix_nano']).isoformat(), 'attributes': expected}
        self.remote.spans = [saved]
        self.assertEqual(_missing_spans(self.remote, [original], 'project'), [])
        for key, value in (('input.value', 'tampered'), ('metadata.nested.model', 'tampered'), ('metadata.nested.enabled', 0)):
            changed = deepcopy(saved)
            changed['attributes'][key] = value
            self.remote.spans = [changed]
            self.assertEqual(changed['attributes'][SPAN_FINGERPRINT], _hash(original))
            with self.subTest(attribute=key), self.assertRaisesRegex(ValueError, 'span differs'):
                _missing_spans(self.remote, [original], 'project')

    def test_span_identity_verifies_content_digest_parent_timestamp_and_kind(self):
        original = self.spans[0]
        saved = {'context': {'trace_id': original['trace_id'], 'span_id': original['span_id']},
                 'parent_id': None, 'name': original['name'], 'span_kind': 'CHAIN', 'status_code': 'OK',
                 'start_time': _span_time(original['start_time_unix_nano']).isoformat(),
                 'end_time': _span_time(original['end_time_unix_nano']).isoformat(),
                 'attributes': _observable_attributes(original)}
        self.remote.spans = [deepcopy(saved)]
        self.assertEqual(_missing_spans(self.remote, self.spans, 'project'), [])
        rounded = deepcopy(saved)
        rounded['start_time'] = (_span_time(original['start_time_unix_nano']) + timedelta(microseconds=1)).isoformat()
        self.remote.spans = [rounded]
        self.assertEqual(_missing_spans(self.remote, self.spans, 'project'), [])
        for key, value in (('name', 'changed'), ('parent_id', '4' * 16), ('span_kind', 'LLM'), ('attributes', {}),
                           ('start_time', (_span_time(original['start_time_unix_nano']) + timedelta(microseconds=2)).isoformat())):
            self.remote.spans = [{**saved, key: value}]
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, 'span differs'):
                _missing_spans(self.remote, self.spans, 'project')
        self.remote.spans = []
        self.assertEqual(_missing_spans(self.remote, self.spans, 'project'), self.spans)


@unittest.skipUnless(os.environ.get('DOC_INTELL_PHOENIX_TESTS') == '1', 'Opt-in disposable real Phoenix import')
class PhoenixImportIntegrationTests(unittest.TestCase):
    def test_empty_phoenix_import_and_retry_verify_outputs_scores_and_spans(self):
        import httpx
        from phoenix.client import Client
        from tests.phoenix_fixture import temporary_phoenix
        with TemporaryDirectory() as folder, temporary_phoenix() as origin:
            root = Path(folder)
            source, report, spans = fixture(root)
            original = {path.name: path.read_bytes() for path in source.iterdir()}
            with httpx.Client(base_url=origin, timeout=30) as http:
                client = Client(http_client=http)
                first = import_report(client, http, source, root / 'receipts')
                second = import_report(client, http, source, root / 'receipts')
                self.assertEqual(first, second)
                self.assertTrue(first['complete'])
                dataset = client.datasets.get_dataset(dataset=first['dataset_name'])
                self.assertEqual(dataset.examples[0]['input']['text'], report['rows'][0]['input'])
                self.assertEqual(dataset.examples[0]['output'], {})
                runs = http.get(f"/v1/experiments/{first['experiment_id']}/json").json()
                self.assertEqual(len(runs), 1)
                self.assertEqual(runs[0]['output']['answer'], report['rows'][0]['output'])
                self.assertEqual(len(runs[0]['annotations']), 5)
                self.assertEqual(_missing_spans(http, spans, first['project_name']), [])
                self.assertEqual(original, {path.name: path.read_bytes() for path in source.iterdir()})
                self.assertEqual(len(client.experiments.list(dataset_id=dataset.id)), 1)
                registered = http.post('/graphql', json={'query': 'query { evaluators(first: 100) { edges { node { id } } } }'}).json()
                self.assertEqual(registered['data']['evaluators']['edges'], [])


if __name__ == '__main__':
    unittest.main()
