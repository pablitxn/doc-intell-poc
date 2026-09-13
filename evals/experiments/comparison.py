"""A small side-by-side summary backed by the original per-harness reports."""

import csv
import json
from pathlib import Path
from uuid import uuid4

from ..datasets.loader import read_json
from .fingerprints import FINGERPRINT_FIELDS, FINGERPRINT_VERSION


def write_comparison(run_dirs: list[Path], output_dir: Path) -> Path:
    if len(run_dirs) < 2:
        raise ValueError('Comparison requires at least two experiments')
    reports = [read_json(path / 'report.json') for path in run_dirs]
    if any(report.get('complete') is not True for report in reports):
        raise ValueError('Comparison requires complete reports')
    required = ('dataset_version', 'prompt_version', 'evaluator_version', 'grader_sha256',
                'eval_code_sha256', 'document_access', 'repetitions')
    for report in reports:
        if any(not isinstance(report.get(key), str) or not report[key].strip() for key in required[:-1]):
            raise ValueError('Comparison requires nonempty dataset, prompt, evaluator, scenario and code metadata')
        if type(report.get('repetitions')) is not int or report['repetitions'] < 1:
            raise ValueError('Comparison requires positive integer repetitions')
    modern = [any(key in report for key in FINGERPRINT_FIELDS) for report in reports]
    if any(modern):
        if not all(modern) or any(
            any(not isinstance(report.get(key), str) or not report[key].strip()
                for key in FINGERPRINT_FIELDS) for report in reports
        ):
            raise ValueError('Comparison requires complete fingerprint metadata; migrate legacy baselines explicitly')
        if any(report['fingerprint_version'] != FINGERPRINT_VERSION for report in reports):
            raise ValueError('Comparison requires a supported fingerprint metadata version')
        fields = ('dataset_version', 'prompt_version', 'evaluator_version', 'grader_sha256',
                  'fingerprint_version', 'contract_sha256', 'scoring_sha256',
                  'document_access', 'repetitions')
        compatibility_mode = 'contract-and-scoring'
    else:
        # Legacy reports remain comparable only under their original strict rule.
        fields = required
        compatibility_mode = 'legacy-full-source'
    if any(any(report.get(key) != reports[0].get(key) for key in fields) for report in reports[1:]):
        raise ValueError('Comparison requires matching dataset, prompt, evaluator, scenario and repetitions')
    for report in reports:
        rows = report.get('rows')
        if not isinstance(rows, list) or not rows:
            raise ValueError('Comparison requires nonempty task membership')
        for row in rows:
            if (not isinstance(row, dict) or not isinstance(row.get('task_id'), str)
                    or not row['task_id'].strip() or type(row.get('repetition', 1)) is not int
                    or not 1 <= row.get('repetition', 1) <= report['repetitions']):
                raise ValueError('Comparison requires valid task/repetition membership')
    membership = [{(row['task_id'], row.get('repetition', 1)) for row in report['rows']} for report in reports]
    if any(len(items) != len(report['rows']) for items, report in zip(membership, reports)):
        raise ValueError('Comparison cannot contain duplicate task/repetition rows')
    for report, items in zip(reports, membership):
        tasks = {task for task, _ in items}
        if items != {(task, repetition) for task in tasks for repetition in range(1, report['repetitions'] + 1)}:
            raise ValueError('Comparison requires complete task/repetition membership')
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
            'eval_code_sha256': report['eval_code_sha256'],
            'runtime_code_sha256': report.get('runtime_code_sha256'),
            'runtime_fingerprint_basis': report.get('runtime_fingerprint_basis', 'partitioned-evals' if all(modern) else 'legacy-whole-evals'),
        })
    path = output_dir / f'comparison-{uuid4().hex[:12]}.json'
    payload = {**{key: reports[0].get(key) for key in fields}, 'harnesses': records,
               'compatibility_mode': compatibility_mode,
               'same_model_configuration': all(row['model'] and row['provider'] for row in records) and len({(row['model'], row['provider'], row['thinking']) for row in records}) == 1,
               'latency_scope': 'Full isolated invocation including container setup and cleanup'}
    path.write_text(json.dumps(payload, indent=2) + '\n')
    with path.with_suffix('.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    return path


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Compare saved complete reports without running a harness')
    parser.add_argument('run_dirs', nargs='+', type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        print(write_comparison(args.run_dirs, args.output_dir))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f'Comparison failed: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
