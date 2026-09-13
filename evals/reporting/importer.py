"""Import immutable saved results into Phoenix; never execute or regrade a task."""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import quote, urlsplit, urlunsplit

from ..json_io import strict_json_loads
from .tracing import _validate_spans, _rejected_spans, encode_otlp


SCORES = ("schema_valid", "value_accuracy", "evidence_accuracy", "task_pass", "execution_status")
IMPORT_VERSION = "phoenix-archive-v1"
SPAN_FINGERPRINT = "benchmark.import.span_sha256"


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _artifact(path):
    data = path.read_bytes()
    return strict_json_loads(data.decode()), hashlib.sha256(data).hexdigest()


def _pages(http, path, *, params=None, missing_ok=False):
    result, cursor, seen = [], None, set()
    while True:
        query = {"limit": 100, **(params or {})}
        if cursor:
            query["cursor"] = cursor
        response = http.get(path, params=query)
        if missing_ok and response.status_code == 404:
            return []
        response.raise_for_status()
        body = response.json()
        result.extend(body["data"])
        cursor = body.get("next_cursor")
        if not cursor:
            return result
        if cursor in seen:
            raise ValueError("Phoenix import pagination repeated a cursor")
        seen.add(cursor)


def _load_source(source_dir):
    report, report_hash = _artifact(source_dir / "report.json")
    if report.get("complete") is not True:
        raise ValueError("Only explicitly complete reports can be imported")
    for key in ("run_id", "dataset", "dataset_version", "prompt_version", "evaluator_version", "grader_sha256", "eval_code_sha256"):
        if not isinstance(report.get(key), str) or not report[key]:
            raise ValueError(f"Import report is missing {key}")
    repetitions = report.get("repetitions", 1)
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("Import repetitions must be a positive integer")
    rows = report.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Import requires saved task rows")
    identities, tasks, trace_ids = set(), {}, set()
    for row in rows:
        task, repetition = row.get("task_id"), row.get("repetition", 1)
        if not isinstance(task, str) or not task or type(repetition) is not int or not 1 <= repetition <= repetitions:
            raise ValueError("Invalid imported task identity")
        if (task, repetition) in identities:
            raise ValueError("Duplicate imported task and repetition")
        identities.add((task, repetition))
        if not isinstance(row.get("input"), str) or "output" not in row:
            raise ValueError("Import requires original task input and output")
        if task in tasks and tasks[task]["input"] != row["input"]:
            raise ValueError("Imported repetitions have different inputs")
        tasks[task] = row
        start, end = (datetime.fromisoformat(row[key]) for key in ("start_time", "end_time"))
        if start.tzinfo is None or end.tzinfo is None or start > end:
            raise ValueError("Invalid imported task timestamps")
        scores = row.get("scores", {})
        for name in SCORES:
            value = scores.get(name)
            if name == "execution_status":
                valid = isinstance(value, str) and bool(value)
            elif name in ("schema_valid", "task_pass"):
                valid = type(value) is bool
            else:
                valid = type(value) in (float, int) and 0 <= value <= 1
            if not valid:
                raise ValueError("Missing or invalid saved evaluation score")
        if row.get("trace_id"):
            if row["trace_id"] in trace_ids:
                raise ValueError("Imported tasks must have distinct trace IDs")
            trace_ids.add(row["trace_id"])
    if len(rows) != len(tasks) * repetitions or report.get("summary", {}).get("tasks_evaluated") != len(rows):
        raise ValueError("Import report is missing tasks or repetitions")
    spans, traces_hash = ([], None)
    if (source_dir / "traces.json").exists():
        spans, traces_hash = _artifact(source_dir / "traces.json")
        if not isinstance(spans, list):
            raise ValueError("Trace artifact must contain a list of spans")
        _validate_spans(spans)
        if {span["trace_id"] for span in spans} != trace_ids:
            raise ValueError("Imported trace membership differs from task rows")
    elif trace_ids:
        raise ValueError("Saved task trace IDs require the original traces.json")

    snapshot, snapshot_hash = None, None
    if (source_dir / "dataset-snapshot.json").exists():
        snapshot, snapshot_hash = _artifact(source_dir / "dataset-snapshot.json")
        if report.get("dataset_snapshot_sha256") != snapshot_hash:
            raise ValueError("Dataset snapshot digest differs from the saved report")
        if any(snapshot.get(key) != report[key] for key in ("dataset_version", "prompt_version")):
            raise ValueError("Dataset snapshot version differs from the saved report")
        entries = snapshot.get("examples", [])
        if (not isinstance(entries, list) or not entries
                or any(not isinstance(entry, dict) for entry in entries)):
            raise ValueError("Dataset snapshot has no valid examples")
        indexed = {entry.get("task_id"): entry for entry in entries}
        if (len(indexed) != len(entries) or any(not isinstance(key, str) or not key for key in indexed)
                or any(not isinstance(entry.get("input"), str) or not isinstance(entry.get("expected"), dict)
                       or not isinstance(entry.get("field_types"), dict) for entry in entries)):
            raise ValueError("Dataset snapshot contains invalid or duplicate task entries")
        if any(task not in indexed or indexed[task]["input"] != row["input"] for task, row in tasks.items()):
            raise ValueError("Dataset snapshot input differs from the saved task")
    elif report.get("dataset_snapshot_sha256"):
        raise ValueError("The report's dataset snapshot is missing")
    return report, spans, snapshot, {"report_sha256": report_hash, "traces_sha256": traces_hash,
                                     "dataset_snapshot_sha256": snapshot_hash}


def _dataset_rows(report, snapshot):
    if snapshot is None:
        entries = {row["task_id"]: row for row in report["rows"]}.values()
    else:
        entries = snapshot["examples"]
    return [{
        "input": {"text": entry["input"]},
        "output": entry["expected"] if snapshot is not None else {},
        "metadata": {
            "task_id": entry["task_id"], "dataset_version": report["dataset_version"],
            "prompt_version": report["prompt_version"], "source_dataset": report["dataset"],
            "reference_status": "saved_snapshot" if snapshot is not None else "unavailable",
            **{key: entry[key] for key in ("case_id", "group", "document_ids", "field_types") if key in entry},
        },
    } for entry in sorted(entries, key=lambda entry: entry["task_id"])]


def _prepare_dataset(client, rows):
    fingerprint = _hash(rows)
    name = f"archive-{fingerprint[:24]}"
    try:
        dataset = client.datasets.get_dataset(dataset=name)
    except ValueError as exc:
        if str(exc) != f"Dataset not found: {name}":
            raise
        dataset = client.datasets.create_dataset(
            name=name, examples=rows,
            dataset_description=f"Imported historical task inputs; reference availability is explicit in metadata. Content SHA256: {fingerprint}",
        )
    remote = {row["metadata"].get("task_id"): row for row in dataset.examples}
    if len(remote) != len(rows) or len(dataset.examples) != len(rows):
        raise ValueError("Imported Phoenix dataset membership differs from saved artifacts")
    for row in rows:
        actual = remote.get(row["metadata"]["task_id"])
        if actual is None or any(actual[key] != row[key] for key in ("input", "output", "metadata")):
            raise ValueError("Imported Phoenix dataset content differs from saved artifacts")
    return dataset


def _output(row):
    return {
        "answer": row["output"],
        "execution_status": row.get("execution_status", "success" if row.get("error") is None else row["scores"]["execution_status"]),
        "source_measurements": {key: row[key] for key in (
            "elapsed_seconds", "usage", "telemetry", "total_service_cost_usd",
        ) if key in row},
        "source_error": row.get("error"),
        "source_scores": row["scores"],
    }


def _request(report, row, experiment_id, example_id):
    return dict(
        experiment_id=experiment_id, dataset_example_id=example_id, output=_output(row),
        start_time=datetime.fromisoformat(row["start_time"]), end_time=datetime.fromisoformat(row["end_time"]),
        repetition_number=row.get("repetition", 1), trace_id=row.get("trace_id"),
        error=None if row["scores"]["execution_status"] == "success" else row["scores"]["execution_status"],
    )


def _assert_run(remote, request):
    keys = ("experiment_id", "dataset_example_id", "repetition_number", "output", "trace_id")
    if (any(remote.get(key) != request.get(key) for key in keys)
            or (remote.get("error") or None) != request["error"]
            or any(datetime.fromisoformat(remote[key]) != request[key] for key in ("start_time", "end_time"))
            or not remote.get("id")):
        raise ValueError("Existing Phoenix import run differs from the saved attempt")


def _score_metadata(report, digests, name):
    return {
        "execution": "imported_saved_result", "version": report["evaluator_version"],
        "source_sha256": report.get("scoring_sha256", report["eval_code_sha256"]),
        "grader_sha256": report["grader_sha256"], "report_sha256": digests["report_sha256"],
        "metric": name,
    }


def _span_time(nanoseconds):
    # Phoenix stores microseconds and its conversion may round by one microsecond.
    # Export still sends the exact original nanoseconds; the content digest binds them.
    return datetime.fromtimestamp(nanoseconds // 1_000_000_000, timezone.utc) + timedelta(microseconds=(nanoseconds % 1_000_000_000) // 1000)


def _observable_attributes(span):
    """Match Phoenix 20.11 REST flattening for the attributes our exporter sends.

    Phoenix parses JSON metadata/tool parameters, flattens mappings and lists of
    mappings, drops nulls, and exposes the OpenInference kind separately.
    """
    result = {}

    def flatten(key, value):
        if isinstance(value, dict):
            for child, item in value.items():
                flatten(f"{key}.{child}", item)
        elif isinstance(value, list) and any(isinstance(item, dict) for item in value):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    flatten(f"{key}.{index}", item)
        elif value is not None:
            result[key] = value

    for key, value in span["attributes"].items():
        if key == "openinference.span.kind" or value is None:
            continue
        encoded = value if isinstance(value, (bool, int, float, str)) else json.dumps(value, sort_keys=True, allow_nan=False)
        if key.endswith(("metadata", "tool.parameters", "llm.prompt_template.variables")) and isinstance(encoded, str):
            try:
                encoded = strict_json_loads(encoded)
            except ValueError:
                pass
        if key in ("llm.token_count.prompt", "llm.token_count.completion", "llm.token_count.total"):
            try:
                encoded = int(encoded)
            except (ValueError, TypeError):
                pass
        flatten(key, encoded)
    result[SPAN_FINGERPRINT] = _hash(span)
    return result


def _missing_spans(http, spans, project_name):
    if not spans:
        return []
    existing = _pages(http, f"/v1/projects/{quote(project_name, safe='')}/spans", missing_ok=True,
                      params={"trace_id": sorted({span["trace_id"] for span in spans})})
    indexed = {}
    for span in existing:
        key = span["context"]["trace_id"], span["context"]["span_id"]
        if key in indexed:
            raise ValueError("Phoenix has duplicate imported span identities")
        indexed[key] = span
    missing = []
    for span in spans:
        remote = indexed.get((span["trace_id"], span["span_id"]))
        if remote is None:
            missing.append(span)
            continue
        if (_hash(remote["attributes"]) != _hash(_observable_attributes(span))
                or remote["name"] != span["name"] or remote.get("parent_id") != span["parent_span_id"]
                or remote["status_code"] != span["status"]
                or remote["span_kind"] != span["attributes"].get("openinference.span.kind", "UNKNOWN")
                or any(abs(datetime.fromisoformat(remote[key]) - _span_time(span[key + "_unix_nano"])) > timedelta(microseconds=1)
                       for key in ("start_time", "end_time"))):
            raise ValueError("Existing Phoenix import span differs from the saved span")
    return missing


def _import_traces(http, spans, project_name):
    missing = _missing_spans(http, spans, project_name)
    if missing:
        exported = [dict(span, attributes={**span["attributes"], SPAN_FINGERPRINT: _hash(span)}) for span in missing]
        response = http.post("/v1/traces", content=encode_otlp(exported, project_name=project_name),
                             headers={"Content-Type": "application/x-protobuf"})
        response.raise_for_status()
        if _rejected_spans(response.content):
            raise RuntimeError("Phoenix rejected imported spans")
    # OTLP acceptance precedes asynchronous persistence; verify before completion.
    for attempt in range(21):
        if not _missing_spans(http, spans, project_name):
            return
        if attempt < 20:
            time.sleep(0.25)
    raise RuntimeError("Imported spans were accepted but are not yet readable; retry the import")


def _verify_scores(http, report, experiment_id, examples, digests, *, allow_partial=False):
    response = http.get(f"/v1/experiments/{quote(experiment_id, safe='')}/json")
    response.raise_for_status()
    exported = response.json()
    indexed = {(row["example_id"], row["repetition_number"]): row for row in exported}
    expected_identities = {(examples[row["task_id"]]["node_id"], row.get("repetition", 1)) for row in report["rows"]}
    if (not set(indexed) <= expected_identities or len(exported) != len(indexed)
            or (not allow_partial and len(indexed) != len(report["rows"]))):
        raise ValueError("Phoenix import task membership is incomplete or duplicated")
    for row in report["rows"]:
        item = indexed.get((examples[row["task_id"]]["node_id"], row.get("repetition", 1)))
        if item is None and allow_partial:
            continue
        if item is None or item["output"] != _output(row) or item.get("trace_id") != row.get("trace_id"):
            raise ValueError("Phoenix import output verification failed")
        annotations = {annotation["name"]: annotation for annotation in item["annotations"]}
        if (not set(annotations) <= set(SCORES) or len(item["annotations"]) != len(annotations)
                or (not allow_partial and set(annotations) != set(SCORES))):
            raise ValueError("Phoenix import score membership differs from saved results")
        for name in annotations:
            value = row["scores"][name]
            expected = float(value == "success") if name == "execution_status" else float(value)
            annotation = annotations[name]
            if (annotation["score"] != expected or annotation.get("label") != (value if name == "execution_status" else None)
                    or annotation.get("metadata") != _score_metadata(report, digests, name)):
                raise ValueError("Phoenix import score differs from the saved result")


def import_report(client, http, source_dir: Path, output_dir: Path, *, project_name="doc-intell-poc-imported") -> dict:
    """Import a complete report into an explicitly selected destination.

    Originals, upload checkpoints and evaluator registrations are never changed.
    Every retry re-reads remote content; local IDs alone are never trusted, even
    when a new Phoenix instance has the same URL and reuses numerical IDs.
    Historical reports without a reference snapshot have empty reference outputs
    and reference_status=unavailable; their saved scores are copied, not rerun.
    """
    source_dir, output_dir = Path(source_dir).resolve(), Path(output_dir).resolve()
    if output_dir == source_dir or source_dir in output_dir.parents:
        raise ValueError("Import output directory must be outside the original run")
    report, spans, snapshot, digests = _load_source(source_dir)
    destination = urlsplit(str(http.base_url))
    if destination.username or destination.password or destination.query or destination.fragment:
        raise ValueError("Phoenix import URL must not contain credentials, query or fragment")
    destination_url = urlunsplit(destination)
    identity = _hash({**digests, "version": IMPORT_VERSION, "project_name": project_name})
    receipt_dir = output_dir / f"import-{identity[:20]}-{hashlib.sha256(destination_url.encode()).hexdigest()[:12]}"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    state_path = receipt_dir / "phoenix-import.json"
    state = {"import_version": IMPORT_VERSION, "import_id": identity, "source_run_id": report["run_id"],
             **digests, "destination": destination_url, "project_name": project_name,
             "reference_status": "saved_snapshot" if snapshot is not None else "unavailable",
             "complete": False, "run_ids": {}, "spans": len(spans)}

    def checkpoint():
        temporary = state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2, allow_nan=False) + "\n")
        temporary.replace(state_path)

    checkpoint()
    dataset = _prepare_dataset(client, _dataset_rows(report, snapshot))
    state.update(dataset_id=dataset.id, dataset_version_id=dataset.version_id, dataset_name=dataset.name)
    metadata = {"import_version": IMPORT_VERSION, "import_id": identity, **digests,
                "reference_status": state["reference_status"], "project_name": project_name,
                "source_report": {key: value for key, value in report.items() if key != "rows"}}
    name = f"import-{report['run_id']}-{identity[:12]}"
    experiments = _pages(http, f"/v1/datasets/{quote(dataset.id, safe='')}/experiments")
    found = [item for item in experiments if item.get("name") == name or item.get("metadata", {}).get("import_id") == identity]
    if len(found) > 1:
        raise ValueError("Phoenix import experiment is not unique")
    if found:
        experiment = found[0]
        if (experiment.get("metadata") != metadata or experiment.get("dataset_version_id") != dataset.version_id
                or experiment.get("repetitions") != report.get("repetitions", 1)):
            raise ValueError("Existing Phoenix import experiment differs from saved artifacts")
    else:
        experiment = client.experiments.create(dataset_id=dataset.id, dataset_version_id=dataset.version_id,
            experiment_name=name, experiment_metadata=metadata, repetitions=report.get("repetitions", 1))
    experiment_id = state["experiment_id"] = experiment["id"]
    checkpoint()
    examples = {row["metadata"]["task_id"]: row for row in dataset.examples}
    remote_runs = _pages(http, f"/v1/experiments/{quote(experiment_id, safe='')}/runs")
    indexed = {(row["dataset_example_id"], row["repetition_number"]): row for row in remote_runs}
    expected_identities = {(examples[row["task_id"]]["node_id"], row.get("repetition", 1)) for row in report["rows"]}
    if len(indexed) != len(remote_runs) or not set(indexed) <= expected_identities:
        raise ValueError("Existing Phoenix import has unexpected or duplicate task runs")
    if remote_runs:
        _verify_scores(http, report, experiment_id, examples, digests, allow_partial=True)
    for row in report["rows"]:
        request = _request(report, row, experiment_id, examples[row["task_id"]]["node_id"])
        run = indexed.get((request["dataset_example_id"], request["repetition_number"]))
        if run is None:
            run = client.experiments.log_run(**request)
        else:
            _assert_run(run, request)
        run_key = f"{row['task_id']}::{row.get('repetition', 1)}"
        state["run_ids"][run_key] = run["id"]
        checkpoint()
        for metric in SCORES:
            value = row["scores"][metric]
            client.experiments.log_evaluation(experiment_run_id=run["id"], name=metric, annotator_kind="CODE",
                score=float(value == "success") if metric == "execution_status" else float(value),
                label=value if metric == "execution_status" else None,
                explanation="Saved historical score imported without recomputation or evaluator registration.",
                metadata=_score_metadata(report, digests, metric))
    _import_traces(http, spans, project_name)
    _verify_scores(http, report, experiment_id, examples, digests)
    state["complete"] = True
    checkpoint()
    return {**state, "receipt": str(state_path)}
