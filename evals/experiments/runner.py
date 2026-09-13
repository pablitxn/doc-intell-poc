"""Sequential task execution, deterministic evaluation and local artifacts."""

from collections import Counter
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from ..contracts import HarnessAdapter
from ..datasets.loader import load_examples
from ..evaluators.tax_mini import EVALUATOR_VERSION, GRADER_PATH, evaluate
from .prompt import PROMPT_VERSION, build_prompt


def run_experiment(
    dataset: Path,
    adapter: HarnessAdapter,
    output_dir: Path,
    *,
    adapter_name: str | None = None,
    task_id: str | None = None,
) -> Path:
    examples, version = load_examples(dataset)
    if task_id:
        examples = [example for example in examples if example.input.task_id == task_id]
        if not examples:
            raise ValueError(f"Unknown task: {task_id}")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    rows = []
    for example in examples:
        input_text = build_prompt(example.input, dataset)
        output, error, status = None, None, "success"
        start_time = datetime.now(timezone.utc)
        started = perf_counter()
        try:
            output = adapter(input_text)
            # Roundtrip enforces JSON output and rejects nonfinite numbers.
            output = json.loads(json.dumps(output, allow_nan=False))
        except TimeoutError:
            status, error = "timeout", "TimeoutError"
        except NotImplementedError:
            status, error = "unsupported", "NotImplementedError"
        except (TypeError, ValueError):
            status, error = "invalid_response", "InvalidJSONOutput"
            output = None
        except Exception as exc:
            # Avoid persisting arbitrary exception messages containing credentials.
            status, error = "adapter_error", type(exc).__name__
        elapsed = perf_counter() - started
        end_time = datetime.now(timezone.utc)
        scores = evaluate(output, example, status)
        rows.append({
            "task_id": example.input.task_id,
            "case_id": example.input.case_id,
            "group": example.group,
            "document_ids": [doc["document_id"] for doc in example.input.documents],
            "repetition": 1,
            "input": input_text,
            "output": output,
            "elapsed_seconds": elapsed,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "error": error,
            "execution_status": status,
            "scores": scores,
            "total_service_cost_usd": None,
        })

    fields = [field for row in rows for field in row["scores"]["fields"]]
    summary = {
        "tasks_evaluated": len(rows),
        "tasks_passed": sum(row["scores"]["task_pass"] for row in rows),
        "fields_evaluated": len(fields),
        "value_accuracy": sum(field["value_correct"] for field in fields) / len(fields),
        "evidence_accuracy": sum(field["evidence_correct"] for field in fields) / len(fields),
        "execution_status_counts": dict(Counter(row["scores"]["execution_status"] for row in rows)),
        "coordinator_cost_usd": None,
        "extractor_cost_usd": None,
        "di_cost_usd": None,
        "total_service_cost_usd": None,
    }
    code_root = Path(__file__).resolve().parents[1]
    report = {
        "run_id": run_id,
        "adapter": adapter_name or (
            f"{getattr(adapter, '__module__', type(adapter).__module__)}:"
            f"{getattr(adapter, '__qualname__', type(adapter).__qualname__)}"
        ),
        "dataset": dataset.name,
        "dataset_version": version,
        "prompt_version": PROMPT_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "grader_sha256": hashlib.sha256(GRADER_PATH.read_bytes()).hexdigest(),
        "eval_code_sha256": hashlib.sha256(b"".join(
            path.relative_to(code_root).as_posix().encode() + b"\0" + path.read_bytes()
            for path in sorted(code_root.rglob("*.py"))
        )).hexdigest(),
        "summary": summary,
        "rows": rows,
    }
    (run_dir / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    with (run_dir / "scores.csv").open("w", newline="") as handle:
        columns = ["task_id", "group", "schema_valid", "value_accuracy", "evidence_accuracy", "task_pass", "execution_status"]
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] if key in row else row["scores"][key] for key in columns})
    return run_dir
