"""A small side-by-side summary backed by the original per-harness reports."""

import csv
import json
from pathlib import Path
from uuid import uuid4


def write_comparison(run_dirs: list[Path], output_dir: Path) -> Path:
    if len(run_dirs) < 2:
        raise ValueError('Comparison requires at least two experiments')
    reports = [json.loads((path / 'report.json').read_text()) for path in run_dirs]
    if any(report.get('complete') is not True for report in reports):
        raise ValueError('Comparison requires complete reports')
    fields = ('dataset_version', 'prompt_version', 'evaluator_version', 'grader_sha256',
              'eval_code_sha256', 'document_access', 'repetitions')
    for report in reports:
        if any(not isinstance(report.get(key), str) or not report[key].strip() for key in fields[:-1]):
            raise ValueError('Comparison requires nonempty dataset, prompt, evaluator, scenario and code metadata')
        if type(report.get('repetitions')) is not int or report['repetitions'] < 1:
            raise ValueError('Comparison requires positive integer repetitions')
    if any(any(report.get(key) != reports[0].get(key) for key in fields) for report in reports[1:]):
        raise ValueError('Comparison requires matching dataset, prompt, evaluator, scenario and repetitions')
    membership = [{(row['task_id'], row.get('repetition', 1)) for row in report['rows']} for report in reports]
    if any(len(items) != len(report['rows']) for items, report in zip(membership, reports)):
        raise ValueError('Comparison cannot contain duplicate task/repetition rows')
    if any(items != membership[0] for items in membership[1:]):
        raise ValueError('Comparison requires the same task/repetition membership')
    records = []
    for path, report in zip(run_dirs, reports):
        metadata, summary = report.get('harness_metadata', {}), report['summary']
        usage = {}
        for name in ('input_tokens', 'output_tokens', 'cache_read_tokens', 'reasoning_tokens'):
            counts = [row.get('usage', {}).get(name) for row in report['rows']]
            usage[name] = sum(counts) if counts and all(value is not None for value in counts) else None
        records.append({
            'harness': report['adapter'], 'model': metadata.get('model'),
            'provider': metadata.get('provider'), 'thinking': metadata.get('thinking'),
            'version': metadata.get('version'), 'tasks_passed': summary['tasks_passed'],
            'tasks_evaluated': summary['tasks_evaluated'],
            'value_accuracy': summary['value_accuracy'], 'evidence_accuracy': summary['evidence_accuracy'],
            'total_seconds': summary['elapsed_seconds']['total'],
            'median_seconds': summary['elapsed_seconds']['median'],
            'cost_usd': summary['total_service_cost_usd'], **usage,
            'report': str(path.resolve() / 'report.json'),
        })
    path = output_dir / f'comparison-{uuid4().hex[:12]}.json'
    payload = {**{key: reports[0].get(key) for key in fields}, 'harnesses': records,
               'same_model_configuration': all(row['model'] and row['provider'] for row in records) and len({(row['model'], row['provider'], row['thinking']) for row in records}) == 1,
               'latency_scope': 'Full isolated invocation including container setup and cleanup'}
    path.write_text(json.dumps(payload, indent=2) + '\n')
    with path.with_suffix('.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    return path
