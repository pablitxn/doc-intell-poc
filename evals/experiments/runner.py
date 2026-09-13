"""Sequential real harness execution, deterministic scoring and local evidence."""

from collections import Counter
from datetime import datetime, timezone
import csv
import hashlib
import json
import platform
from pathlib import Path
from statistics import median
from time import perf_counter, time_ns
from uuid import uuid4

from ..contracts import HarnessAdapter, HarnessInvocation, HarnessResult
from ..datasets.loader import load_examples
from ..evaluators.tax_mini import EVALUATOR_VERSION, GRADER_PATH, evaluate
from ..reporting.tracing import build_task_trace
from .prompt import PROMPT_VERSION, build_prompt
from .fingerprints import code_fingerprints, legacy_code_sha256


def _summary(rows: list[dict]) -> dict:
    fields = [field for row in rows for field in row['scores']['fields']]
    durations = [row['elapsed_seconds'] for row in rows]
    costs = [row['total_service_cost_usd'] for row in rows]
    return {
        'tasks_evaluated': len(rows),
        'tasks_passed': sum(row['scores']['task_pass'] for row in rows),
        'fields_evaluated': len(fields),
        'value_accuracy': sum(field['value_correct'] for field in fields) / len(fields),
        'evidence_accuracy': sum(field['evidence_correct'] for field in fields) / len(fields),
        'execution_status_counts': dict(Counter(row['scores']['execution_status'] for row in rows)),
        'elapsed_seconds': {'total': sum(durations), 'min': min(durations),
                            'median': median(durations), 'max': max(durations)},
        'coordinator_cost_usd': None, 'extractor_cost_usd': None, 'di_cost_usd': None,
        'total_service_cost_usd': sum(costs) if all(value is not None for value in costs) else None,
    }


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)



def build_dataset_snapshot(examples, dataset: Path, prompt_root: Path | None) -> dict:
    """Private report artifact for publication on a new machine; never an input mount."""
    return {'examples': [
        {'task_id': example.input.task_id, 'case_id': example.input.case_id,
         'group': example.group, 'field_types': example.input.fields,
         'document_ids': [doc['document_id'] for doc in example.input.documents],
         'input': build_prompt(example.input, dataset, document_root=prompt_root),
         'expected': example.expected}
        for example in examples
    ]}


def run_experiment(
    dataset: Path, adapter: HarnessAdapter, output_dir: Path, *,
    adapter_name: str | None = None, task_id: str | None = None,
    repetitions: int = 1, prompt_root: Path | None = None,
    harness_metadata: dict | None = None,
) -> Path:
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions < 1:
        raise ValueError('Repetitions must be a positive integer')
    dataset = dataset.resolve()
    examples, version = load_examples(dataset)
    snapshot = {**build_dataset_snapshot(examples, dataset, prompt_root),
                'dataset_version': version, 'prompt_version': PROMPT_VERSION}
    if task_id:
        examples = [example for example in examples if example.input.task_id == task_id]
        if not examples:
            raise ValueError(f'Unknown task: {task_id}')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:12]
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    snapshot_path = run_dir / 'dataset-snapshot.json'
    _write_json(snapshot_path, snapshot)
    adapter_label = adapter_name or (
        f"{getattr(adapter, '__module__', type(adapter).__module__)}:"
        f"{getattr(adapter, '__qualname__', type(adapter).__qualname__)}"
    )
    metadata = dict(harness_metadata or {})
    fingerprints = code_fingerprints()
    report = {
        'run_id': run_id, 'adapter': adapter_label, 'harness_metadata': metadata,
        'dataset': dataset.name, 'dataset_version': version, 'prompt_version': PROMPT_VERSION,
        'prompt_root': str(prompt_root) if prompt_root else None,
        'evaluator_version': EVALUATOR_VERSION, 'repetitions': repetitions,
        'document_access': 'native', 'complete': False,
        'environment': {'os': platform.system(), 'architecture': platform.machine(),
                        'python': platform.python_version()},
        'grader_sha256': hashlib.sha256(GRADER_PATH.read_bytes()).hexdigest(),
        'eval_code_sha256': legacy_code_sha256(),
        **fingerprints,
        'dataset_snapshot_sha256': hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
        'rows': [],
    }
    rows = report['rows']
    traces = []
    for repetition in range(1, repetitions + 1):
        for example in examples:
            input_text = build_prompt(example.input, dataset, document_root=prompt_root)
            trace_id, root_span_id, harness_span_id = uuid4().hex, uuid4().hex[:16], uuid4().hex[:16]
            invocation_dir = run_dir / 'tasks' / f'{example.input.task_id}-{repetition}'
            invocation_dir.mkdir(parents=True)
            invocation = HarnessInvocation(
                input_text=input_text, task_id=example.input.task_id, repetition=repetition,
                dataset=dataset, documents=example.input.documents, artifact_dir=invocation_dir,
                trace_id=trace_id, parent_span_id=harness_span_id, run_id=run_id,
            )
            result = HarnessResult()
            start_time = datetime.now(timezone.utc)
            harness_start_ns = time_ns()
            started = perf_counter()
            try:
                if hasattr(adapter, 'invoke'):
                    result = adapter.invoke(invocation)
                    if not isinstance(result, HarnessResult):
                        raise TypeError('Native adapter must return HarnessResult')
                else:
                    returned = adapter(input_text)
                    result = returned if isinstance(returned, HarnessResult) else HarnessResult(output=returned)
                # Preserve values exactly: validation must not repair an answer.
                result.output = json.loads(json.dumps(result.output, allow_nan=False))
            except TimeoutError:
                result.status, result.error = 'timeout', 'TimeoutError'
            except NotImplementedError:
                result.status, result.error = 'unsupported', 'NotImplementedError'
            except (TypeError, ValueError):
                result.status, result.error, result.output = 'invalid_response', 'InvalidJSONOutput', None
            except Exception as exc:
                result.status, result.error = 'adapter_error', type(exc).__name__
            elapsed = perf_counter() - started
            harness_end_ns = time_ns()
            end_time = datetime.now(timezone.utc)
            scores = evaluate(result.output, example, result.status)
            row = {
                'task_id': example.input.task_id, 'case_id': example.input.case_id,
                'group': example.group,
                'document_ids': [doc['document_id'] for doc in example.input.documents],
                'repetition': repetition, 'input': input_text, 'output': result.output,
                'elapsed_seconds': elapsed, 'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat(), 'error': result.error,
                'execution_status': result.status, 'scores': scores,
                'usage': result.usage, 'telemetry': result.metadata,
                'total_service_cost_usd': result.usage.get('cost_usd'),
                'trace_id': trace_id,
            }
            rows.append(row)
            spans = build_task_trace(
                row, trace_id=trace_id, root_span_id=root_span_id, harness_span_id=harness_span_id,
                harness_start_ns=harness_start_ns, harness_end_ns=harness_end_ns,
                task_end_ns=time_ns(), events=result.events,
                metadata={**metadata, 'run_id': run_id, 'harness': adapter_label,
                          'dataset_version': version, 'prompt_version': PROMPT_VERSION,
                          'evaluator_version': EVALUATOR_VERSION, 'document_access': 'native',
                          **fingerprints},
            )
            traces.extend(spans)
            _write_json(invocation_dir / 'events.json', result.events)
            report['summary'] = _summary(rows)
            report['summary']['groups'] = {
                group: _summary([row for row in rows if row['group'] == group])
                for group in sorted({row['group'] for row in rows})
            }
            # Flush each completed task; a publication retry never repeats paid work.
            _write_json(run_dir / 'traces.json', traces)
            _write_json(run_dir / 'report.json', report)
    report['complete'] = True
    _write_json(run_dir / 'report.json', report)
    with (run_dir / 'scores.csv').open('w', newline='') as handle:
        columns = ['task_id', 'repetition', 'group', 'schema_valid', 'value_accuracy',
                   'evidence_accuracy', 'task_pass', 'execution_status', 'elapsed_seconds', 'trace_id']
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] if key in row else row['scores'][key] for key in columns})
    return run_dir
