"""Read back this saved smoke from its Phoenix; never call models or regrade.

Run from the repository root with tests/requirements.txt dependencies installed.
The original Phoenix is the default. A restored destination must use its own
import receipts; the saved checkpoints identify the original instance only.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote

import httpx
from phoenix.client import Client

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from evals.datasets.loader import load_examples
from evals.experiments.prompt import build_prompt
from evals.reporting.importer import _pages


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phoenix-url', default='http://127.0.0.1:6006')
    parser.add_argument('--output', type=Path, default=HERE / 'live-validation.json')
    args = parser.parse_args()
    from evals.adapters.network import trace_endpoint
    trace_endpoint(args.phoenix_url)
    smoke = json.loads((HERE / 'live-smoke.json').read_text())
    assert smoke['complete'] and len(smoke['tasks']) == 4
    dataset_root = ROOT / 'datasets/tax-document-eval-v1'
    examples, version = load_examples(dataset_root)
    by_task = {example.input.task_id: example for example in examples}
    headers = {'Authorization': f'Bearer {os.environ["PHOENIX_API_KEY"]}'} if os.environ.get('PHOENIX_API_KEY') else {}
    checked, datasets = [], set()
    with httpx.Client(base_url=args.phoenix_url, headers=headers, timeout=30, trust_env=False) as http:
        client = Client(http_client=http)
        for batch in smoke['tasks']:
            assert len(batch['run_ids']) == 3 and batch['exit_code'] == 0
            for run_id in batch['run_ids']:
                directory = ROOT / 'runs' / run_id
                report = json.loads((directory / 'report.json').read_text())
                publication = json.loads((directory / 'phoenix.json').read_text())
                spans = json.loads((directory / 'traces.json').read_text())
                assert report['complete'] and publication['complete']
                assert report['dataset_version'] == version and report['summary']['tasks_passed'] == 1
                assert report['summary']['value_accuracy'] == report['summary']['evidence_accuracy'] == 1.0
                row, = report['rows']
                assert row['task_id'] == batch['task_id']
                if publication['dataset_name'] not in datasets:
                    dataset = client.datasets.get_dataset(dataset=publication['dataset_name'])
                    actual = {example['metadata']['task_id']: example for example in dataset.examples}
                    assert len(dataset.examples) == len(actual) == 366 and set(actual) == set(by_task)
                    assert len({example['metadata']['case_id'] for example in actual.values()}) == 55
                    for task_id, example in by_task.items():
                        assert actual[task_id]['output'] == example.expected
                        assert actual[task_id]['input']['text'] == build_prompt(example.input, dataset_root, document_root=Path('/workspace'))
                    datasets.add(publication['dataset_name'])
                response = http.get(f'/v1/experiments/{quote(publication["experiment_id"], safe="")}/json')
                response.raise_for_status()
                remote, = response.json()
                assert remote['trace_id'] == row['trace_id'] and remote['output']['answer'] == row['output']
                assert {item['name'] for item in remote['annotations']} == {
                    'schema_valid', 'value_accuracy', 'evidence_accuracy', 'task_pass', 'execution_status'}
                assert len(remote['annotations']) == 5 and all(item['score'] == 1.0 for item in remote['annotations'])
                observed = _pages(http, '/v1/projects/doc-intell-poc/spans', params={'trace_id': [row['trace_id']]})
                indexed = {span['context']['span_id']: span for span in observed}
                assert len(indexed) == len(observed) == len(spans)
                assert set(indexed) == {span['span_id'] for span in spans}
                for span in spans:
                    saved = indexed[span['span_id']]
                    assert saved['context']['trace_id'] == span['trace_id']
                    assert saved['name'] == span['name'] and saved['parent_id'] == span['parent_span_id']
                    assert saved['status_code'] == span['status']
                checked.append({'run_id': run_id, 'task_id': row['task_id'], 'harness': report['adapter'],
                                'model': report['harness_metadata']['model'], 'thinking': report['harness_metadata']['thinking'],
                                'fields': report['summary']['fields_evaluated'], 'task_pass': True,
                                'elapsed_seconds': row['elapsed_seconds'], 'trace_id': row['trace_id'],
                                'spans': len(spans), 'scores_verified': 5, 'image_id': report['harness_metadata']['image_id']})
    result = {'verified_at': datetime.now(timezone.utc).isoformat(), 'dataset_version': version,
              'dataset_tasks_verified': 366, 'dataset_cases_verified': 55,
              'model_calls_in_smoke': 12, 'model_calls_in_verification': 0,
              'requested_model': smoke['model'], 'reasoning': smoke['thinking'],
              'tasks_passed': len(checked), 'tasks_executed': len(checked),
              'fields_evaluated': sum(run['fields'] for run in checked),
              'scores_verified': sum(run['scores_verified'] for run in checked),
              'spans_verified': sum(run['spans'] for run in checked),
              'complete_matrix_executed': False, 'runs': checked}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'runs'}, indent=2))


if __name__ == '__main__':
    main()
