"""Publish versioned datasets, task runs and deterministic scores to Phoenix."""

from datetime import datetime
import hashlib
import json
from pathlib import Path

from ..datasets.loader import load_examples, read_json
from ..evaluators.tax_mini import EVALUATOR_VERSION
from ..evaluators.definitions import EVALUATOR_DEFINITIONS
from ..experiments.prompt import PROMPT_VERSION, build_prompt

def prepare_dataset(client, root: Path):
    """Always publish all tasks, even when the experiment selects only one."""
    examples, version = load_examples(root)
    rows = [
        {
            "input": {"text": build_prompt(example.input, root)},
            "output": example.expected,
            "metadata": {
                "task_id": example.input.task_id,
                "case_id": example.input.case_id,
                "group": example.group,
                "field_types": example.input.fields,
                "document_ids": [doc["document_id"] for doc in example.input.documents],
                "dataset_version": version,
                "prompt_version": PROMPT_VERSION,
            },
        }
        for example in examples
    ]
    fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    name = f"{root.name}-{fingerprint[:16]}"
    try:
        dataset = client.datasets.get_dataset(dataset=name)
    except ValueError as exc:
        if str(exc) != f"Dataset not found: {name}":
            raise
        dataset = client.datasets.create_dataset(
            name=name,
            examples=rows,
            dataset_description=f"Synthetic fiscal document tasks; one case. Content SHA256: {fingerprint}",
        )
    # Never silently reuse edited reference answers or a partial dataset.
    actual = {row["metadata"]["task_id"]: row for row in dataset.examples}
    if len(dataset.examples) != len(rows) or set(actual) != {row["metadata"]["task_id"] for row in rows}:
        raise ValueError("Phoenix dataset membership differs from the local dataset")
    for row in rows:
        remote = actual[row["metadata"]["task_id"]]
        if any(remote[key] != row[key] for key in ("input", "output", "metadata")):
            raise ValueError("Phoenix dataset content differs from the local dataset")
    return dataset


def publish_report(client, dataset, run_dir: Path, evaluator_registry: dict | None = None) -> dict:
    """Checkpoint upload progress; rerunning uploads never invokes the harness."""
    report = read_json(run_dir / "report.json")
    if report["evaluator_version"] != EVALUATOR_VERSION:
        raise ValueError("Report evaluator version differs from the loaded evaluator definitions")
    examples = {row["metadata"]["task_id"]: row for row in dataset.examples}
    for row in report["rows"]:
        example = examples.get(row["task_id"])
        if (example is None or example["input"]["text"] != row["input"]
                or example["metadata"]["dataset_version"] != report["dataset_version"]
                or example["metadata"]["prompt_version"] != report["prompt_version"]):
            raise ValueError("Report does not match the Phoenix dataset version")

    state_path = run_dir / "phoenix.json"
    state = read_json(state_path) if state_path.exists() else {
        "dataset_id": dataset.id,
        "dataset_version_id": dataset.version_id,
        "dataset_name": dataset.name,
        "experiment_id": None,
        "run_ids": {},
        "complete": False,
    }
    if state["dataset_id"] != dataset.id or state["dataset_version_id"] != dataset.version_id:
        raise ValueError("Upload checkpoint belongs to a different Phoenix dataset version")

    def checkpoint():
        temporary = state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2) + "\n")
        temporary.replace(state_path)

    definitions = {
        name: {"description": description, "version": EVALUATOR_VERSION,
               "source_sha256": report["eval_code_sha256"], "execution": "local"}
        for name, description in EVALUATOR_DEFINITIONS.items()
    }
    for name, registration in (evaluator_registry or {}).items():
        definitions[name]["phoenix_evaluator"] = registration
    if state["experiment_id"] is None:
        experiment = client.experiments.create(
            dataset_id=dataset.id,
            dataset_version_id=dataset.version_id,
            experiment_name=f"{report['dataset']}-{Path(report['adapter']).name}-{report['run_id']}",
            experiment_metadata={
                "run_id": report["run_id"],
                "harness": report["adapter"],
                "dataset_version": report["dataset_version"],
                "prompt_version": report["prompt_version"],
                "evaluator_version": report["evaluator_version"],
                "grader_sha256": report["grader_sha256"],
                "summary": report["summary"],
                "evaluators": definitions,
            },
            repetitions=1,
        )
        state["experiment_id"] = experiment["id"]
        checkpoint()

    for row in report["rows"]:
        task_id = row["task_id"]
        scores = row["scores"]
        if task_id not in state["run_ids"]:
            run = client.experiments.log_run(
                experiment_id=state["experiment_id"],
                dataset_example_id=examples[task_id]["node_id"],
                output={
                    "answer": row["output"],
                    # Preserve the execution outcome before schema validation:
                    # valid JSON with wrong types may still have correct values.
                    "execution_status": row.get("execution_status", "success" if row["error"] is None else scores["execution_status"]),
                },
                start_time=datetime.fromisoformat(row["start_time"]),
                end_time=datetime.fromisoformat(row["end_time"]),
                error=None if scores["execution_status"] == "success" else scores["execution_status"],
            )
            state["run_ids"][task_id] = run["id"]
            checkpoint()
        for name, definition in definitions.items():
            value = scores[name]
            score = float(value == "success") if name == "execution_status" else float(value)
            explanation = definition["description"]
            if name == "schema_valid" and scores["schema_errors"]:
                explanation += " " + "; ".join(scores["schema_errors"])
            client.experiments.log_evaluation(
                experiment_run_id=state["run_ids"][task_id],
                name=name,
                annotator_kind="CODE",
                score=score,
                label=value if name == "execution_status" else None,
                explanation=explanation,
                metadata=definition,
            )
    state["complete"] = True
    checkpoint()
    return state
