"""Publish versioned datasets, task runs and deterministic scores to Phoenix."""

from datetime import datetime
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from ..datasets.loader import load_examples, read_json
from ..evaluators.tax_mini import EVALUATOR_VERSION
from ..evaluators.definitions import EVALUATOR_DEFINITIONS
from ..experiments.prompt import PROMPT_VERSION, build_prompt

def prepare_dataset(client, root: Path, *, prompt_root: Path | None = None):
    """Always publish all tasks, even when the experiment selects only one."""
    examples, version = load_examples(root)
    rows = [
        {
            "input": {"text": build_prompt(example.input, root, document_root=prompt_root)
                      if prompt_root is not None else build_prompt(example.input, root)},
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


def _recover_run(client, request: dict, http=None) -> dict:
    """Resolve a 409 only when the persisted run matches this exact local attempt.

    The pinned Phoenix 3.5 client uses this REST pagination contract internally.
    An explicit HTTP client avoids its public get_experiment single-page limit.
    """
    if http is None:
        runs = client.experiments.get_experiment(
            experiment_id=request["experiment_id"],
        )["task_runs"]
    else:
        runs, cursor, seen_cursors = [], None, set()
        while True:
            params = {"limit": 50}
            if cursor:
                params["cursor"] = cursor
            response = http.get(
                f"/v1/experiments/{quote(request['experiment_id'], safe='')}/runs", params=params,
            )
            response.raise_for_status()
            body = response.json()
            runs.extend(body["data"])
            cursor = body.get("next_cursor")
            if not cursor:
                break
            if cursor in seen_cursors:
                raise ValueError("Phoenix run pagination repeated a cursor")
            seen_cursors.add(cursor)
    candidates = [run for run in runs if all(
        run.get(key) == request[key]
        for key in ("experiment_id", "dataset_example_id", "repetition_number")
    )]
    if len(candidates) != 1:
        raise ValueError("Conflicting Phoenix run could not be uniquely recovered")
    run = candidates[0]
    matches = (run.get("output") == request["output"]
               and run.get("trace_id") == request.get("trace_id")
               and (run.get("error") or None) == (request.get("error") or None))
    try:
        matches = matches and all(
            datetime.fromisoformat(run[key]) == request[key] for key in ("start_time", "end_time")
        )
    except (KeyError, TypeError, ValueError):
        matches = False
    if not matches or not isinstance(run.get("id"), str) or not run["id"]:
        raise ValueError("Existing Phoenix run differs from the local attempt; refusing to overwrite")
    return run


def publish_report(client, dataset, run_dir: Path, evaluator_registry: dict | None = None, *, http=None) -> dict:
    """Checkpoint upload progress; rerunning uploads never invokes the harness."""
    report = read_json(run_dir / "report.json")
    if report.get("complete") is False:
        raise ValueError("Cannot publish an incomplete evaluation report")
    if report["evaluator_version"] != EVALUATOR_VERSION:
        raise ValueError("Report evaluator version differs from the loaded evaluator definitions")
    repetitions = report.get("repetitions", 1)
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("Report repetitions must be a positive integer")
    examples = {row["metadata"]["task_id"]: row for row in dataset.examples}
    identities = set()
    for row in report["rows"]:
        repetition = row.get("repetition", 1)
        if type(repetition) is not int or not 1 <= repetition <= repetitions:
            raise ValueError("Report row repetition is outside the experiment range")
        identity = row["task_id"], repetition
        if identity in identities:
            raise ValueError("Report contains duplicate task and repetition")
        identities.add(identity)
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
                "harness_metadata": report.get("harness_metadata", {}),
            },
            repetitions=repetitions,
        )
        state["experiment_id"] = experiment["id"]
        checkpoint()

    for row in report["rows"]:
        task_id = row["task_id"]
        repetition = row.get("repetition", 1)
        run_key = task_id if repetition == 1 else f"{task_id}::{repetition}"
        scores = row["scores"]
        if run_key not in state["run_ids"]:
            request = dict(
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
                repetition_number=repetition,
                trace_id=row.get("trace_id"),
                error=None if scores["execution_status"] == "success" else scores["execution_status"],
            )
            try:
                run = client.experiments.log_run(**request)
            except Exception as exc:
                if getattr(getattr(exc, "response", None), "status_code", None) != 409:
                    raise
                run = _recover_run(client, request, http=http)
            state["run_ids"][run_key] = run["id"]
            checkpoint()
        for name, definition in definitions.items():
            value = scores[name]
            score = float(value == "success") if name == "execution_status" else float(value)
            explanation = definition["description"]
            if name == "schema_valid" and scores["schema_errors"]:
                explanation += " " + "; ".join(scores["schema_errors"])
            client.experiments.log_evaluation(
                experiment_run_id=state["run_ids"][run_key],
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
