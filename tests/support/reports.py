"""Historical report files shared by import unit and integration tests."""

import hashlib
import json


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
