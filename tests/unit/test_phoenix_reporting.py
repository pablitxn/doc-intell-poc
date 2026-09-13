"""Publication contracts use an in-memory Phoenix client; no SDK or server required."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from evals.datasets.loader import load_examples, read_json
from evals.experiments.runner import run_experiment
from evals.reporting.phoenix import EVALUATOR_DEFINITIONS, prepare_dataset, publish_report, validate_current_report
from tests.support.paths import ROOT

DATASET = ROOT / "datasets/tax-mini-poc"


class FakeDatasets:
    def __init__(self):
        self.saved = {}
        self.creates = []

    def get_dataset(self, *, dataset):
        if dataset not in self.saved:
            raise ValueError(f"Dataset not found: {dataset}")
        return self.saved[dataset]

    def create_dataset(self, **kwargs):
        self.creates.append(deepcopy(kwargs))
        rows = deepcopy(kwargs["examples"])
        for index, row in enumerate(rows):
            row["node_id"] = f"example-{index}"
        dataset = SimpleNamespace(
            id=f"dataset-{len(self.creates)}", version_id=f"version-{len(self.creates)}",
            name=kwargs["name"], examples=rows,
        )
        self.saved[dataset.name] = dataset
        return dataset


class FakeExperiments:
    def __init__(self):
        self.creates = []
        self.runs = []
        self.evaluations = {}
        self.evaluation_calls = 0
        self.fail_evaluation_call = None

    def create(self, **kwargs):
        self.creates.append(deepcopy(kwargs))
        return {"id": f"experiment-{len(self.creates)}"}

    def log_run(self, **kwargs):
        self.runs.append(deepcopy(kwargs))
        return {"id": f"run-{len(self.runs)}"}

    def log_evaluation(self, **kwargs):
        self.evaluation_calls += 1
        if self.evaluation_calls == self.fail_evaluation_call:
            raise ConnectionError("simulated interrupted upload")
        # Phoenix replaces an existing annotation for the same run and name.
        key = kwargs["experiment_run_id"], kwargs["name"]
        self.evaluations[key] = deepcopy(kwargs)


class ConflictError(Exception):
    response = SimpleNamespace(status_code=409)


class LostResponseExperiments(FakeExperiments):
    """The server commits successfully, but its first response never arrives."""
    def __init__(self):
        super().__init__()
        self.persisted = {}

    def log_run(self, **kwargs):
        key = kwargs["experiment_id"], kwargs["dataset_example_id"], kwargs["repetition_number"]
        if key in self.persisted:
            raise ConflictError()
        result = super().log_run(**kwargs)
        self.persisted[key] = {
            **deepcopy(kwargs), **result,
            "start_time": kwargs["start_time"].isoformat(),
            "end_time": kwargs["end_time"].isoformat(),
        }
        raise ConnectionError("response lost after commit")

    def get_experiment(self, *, experiment_id):
        return {"task_runs": [deepcopy(run) for run in self.persisted.values()
                              if run["experiment_id"] == experiment_id]}


def fake_client():
    return SimpleNamespace(datasets=FakeDatasets(), experiments=FakeExperiments())


class PhoenixReportingTests(unittest.TestCase):
    def setUp(self):
        self.client = fake_client()
        self.examples, self.version = load_examples(DATASET)
        self.answers = {example.input.task_id: example.expected for example in self.examples}

    def answer(self, text):
        task_id = text.split("Task ID: ", 1)[1].splitlines()[0]
        return deepcopy(self.answers[task_id])

    def test_dataset_creation_and_reuse_preserve_all_six_reference_examples(self):
        dataset = prepare_dataset(self.client, DATASET)
        reused = prepare_dataset(self.client, DATASET)
        self.assertIs(reused, dataset)
        self.assertEqual(len(self.client.datasets.creates), 1)
        self.assertEqual(len(dataset.examples), 6)
        self.assertEqual(
            {row["metadata"]["task_id"]: row["output"] for row in dataset.examples},
            self.answers,
        )
        for row in dataset.examples:
            self.assertEqual(set(row["input"]), {"text"})
            self.assertEqual(row["metadata"]["dataset_version"], self.version)
            self.assertNotIn("ground_truth", row["input"]["text"])

    def test_partial_experiment_uses_full_dataset_and_only_selected_run(self):
        dataset = prepare_dataset(self.client, DATASET)
        with TemporaryDirectory() as tmp:
            run_dir = run_experiment(DATASET, self.answer, Path(tmp), task_id="reconcile_case")
            state = publish_report(self.client, dataset, run_dir)
        self.assertEqual(len(dataset.examples), 6)
        self.assertEqual(len(self.client.datasets.creates[0]["examples"]), 6)
        self.assertEqual(len(self.client.experiments.runs), 1)
        selected = next(row for row in dataset.examples if row["metadata"]["task_id"] == "reconcile_case")
        self.assertEqual(self.client.experiments.runs[0]["dataset_example_id"], selected["node_id"])
        self.assertEqual(len(self.client.experiments.evaluations), 5)
        self.assertEqual(set(state["run_ids"]), {"reconcile_case"})
        self.assertTrue(state["complete"])

    def test_edited_remote_ground_truth_is_rejected_without_creating_another_dataset(self):
        dataset = prepare_dataset(self.client, DATASET)
        dataset.examples[0]["output"]["values"]["wages"] = "1.00"
        with self.assertRaisesRegex(ValueError, "dataset content differs"):
            prepare_dataset(self.client, DATASET)
        self.assertEqual(len(self.client.datasets.creates), 1)
        self.assertEqual(self.client.experiments.creates, [])

    def test_incomplete_remote_dataset_is_rejected(self):
        dataset = prepare_dataset(self.client, DATASET)
        dataset.examples.pop()
        with self.assertRaisesRegex(ValueError, "dataset membership differs"):
            prepare_dataset(self.client, DATASET)
        self.assertEqual(len(self.client.datasets.creates), 1)

    def test_error_runs_are_published_with_all_five_scores(self):
        failures = {
            "extract_doc_001": TimeoutError,
            "extract_doc_002": NotImplementedError,
            "extract_doc_003": RuntimeError,
            "extract_doc_004": ValueError,
        }

        def adapter(text):
            task_id = text.split("Task ID: ", 1)[1].splitlines()[0]
            if task_id in failures:
                raise failures[task_id]("private diagnostic")
            return self.answer(text)

        dataset = prepare_dataset(self.client, DATASET)
        with TemporaryDirectory() as tmp:
            run_dir = run_experiment(DATASET, adapter, Path(tmp))
            report = read_json(run_dir / "report.json")
            state = publish_report(self.client, dataset, run_dir)
        self.assertEqual(len(self.client.experiments.runs), 6)
        self.assertEqual(len(self.client.experiments.evaluations), 30)
        for row in report["rows"]:
            run_id = state["run_ids"][row["task_id"]]
            evaluations = {
                name: evaluation for (evaluation_run_id, name), evaluation
                in self.client.experiments.evaluations.items() if evaluation_run_id == run_id
            }
            self.assertEqual(set(evaluations), set(EVALUATOR_DEFINITIONS))
            status = row["scores"]["execution_status"]
            self.assertEqual(evaluations["execution_status"]["label"], status)
            self.assertEqual(evaluations["execution_status"]["score"], float(status == "success"))
            if row["task_id"] in failures:
                self.assertTrue(all(evaluation["score"] == 0 for evaluation in evaluations.values()))
        self.assertNotIn("private diagnostic", str(self.client.experiments.runs))

    def test_upload_retry_reuses_checkpointed_experiment_and_runs(self):
        dataset = prepare_dataset(self.client, DATASET)
        # Fail after the second run exists and two of its annotations were accepted.
        self.client.experiments.fail_evaluation_call = 8
        with TemporaryDirectory() as tmp:
            run_dir = run_experiment(DATASET, self.answer, Path(tmp))
            with self.assertRaisesRegex(ConnectionError, "interrupted upload"):
                publish_report(self.client, dataset, run_dir)
            checkpoint = read_json(run_dir / "phoenix.json")
            self.assertFalse(checkpoint["complete"])
            self.assertEqual(len(checkpoint["run_ids"]), 2)
            self.assertEqual(len(self.client.experiments.runs), 2)
            state = publish_report(self.client, dataset, run_dir)
            self.assertEqual(state, read_json(run_dir / "phoenix.json"))
        self.assertTrue(state["complete"])
        self.assertEqual(len(self.client.experiments.creates), 1)
        self.assertEqual(len(self.client.experiments.runs), 6)
        self.assertEqual(len({run["dataset_example_id"] for run in self.client.experiments.runs}), 6)
        self.assertEqual(len(self.client.experiments.evaluations), 30)
        for task_id, run_id in checkpoint["run_ids"].items():
            self.assertEqual(state["run_ids"][task_id], run_id)

    def test_invalid_schema_preserves_partial_value_credit_in_published_code(self):
        from evals.evaluators.definitions import code_definitions

        def adapter(text):
            answer = self.answer(text)
            answer["values"]["wages"] = 240000
            return answer

        dataset = prepare_dataset(self.client, DATASET)
        with TemporaryDirectory() as tmp:
            run_dir = run_experiment(DATASET, adapter, Path(tmp), task_id="extract_doc_001")
            state = publish_report(self.client, dataset, run_dir)
        run = self.client.experiments.runs[0]
        self.assertEqual(run["error"], "invalid_response")
        self.assertEqual(run["output"]["execution_status"], "success")
        namespace = {}
        definition = next(item for item in code_definitions() if item["name"] == "value_accuracy")
        exec(definition["source_code"], namespace)
        example = dataset.examples[0]
        exported = namespace["evaluate"](run["output"], example["output"], example["metadata"])
        annotation = self.client.experiments.evaluations[(state["run_ids"]["extract_doc_001"], "value_accuracy")]
        self.assertEqual(exported["score"], annotation["score"])
        self.assertEqual(exported["score"], 1)

    def test_report_mismatch_is_rejected_before_any_experiment_mutation(self):
        dataset = prepare_dataset(self.client, DATASET)
        with TemporaryDirectory() as tmp:
            run_dir = run_experiment(DATASET, self.answer, Path(tmp))
            original = read_json(run_dir / "report.json")
            for field in ("task_id", "input", "dataset_version", "prompt_version"):
                with self.subTest(field=field):
                    report = deepcopy(original)
                    if field in ("task_id", "input"):
                        report["rows"][-1][field] = "does-not-match"
                    else:
                        report[field] = "does-not-match"
                    (run_dir / "report.json").write_text(json.dumps(report))
                    with self.assertRaisesRegex(ValueError, "Report does not match"):
                        publish_report(self.client, dataset, run_dir)
                    self.assertFalse((run_dir / "phoenix.json").exists())
        self.assertEqual(self.client.experiments.creates, [])
        self.assertEqual(self.client.experiments.runs, [])
        self.assertEqual(self.client.experiments.evaluations, {})

    def test_checkpoint_for_another_dataset_version_is_rejected(self):
        dataset = prepare_dataset(self.client, DATASET)
        with TemporaryDirectory() as tmp:
            run_dir = run_experiment(DATASET, self.answer, Path(tmp))
            (run_dir / "phoenix.json").write_text(json.dumps({
                "dataset_id": dataset.id, "dataset_version_id": "other-version",
            }))
            with self.assertRaisesRegex(ValueError, "different Phoenix dataset version"):
                publish_report(self.client, dataset, run_dir)
        self.assertEqual(self.client.experiments.creates, [])
        self.assertEqual(self.client.experiments.runs, [])

    def test_repetitions_and_trace_links_survive_upload_retry(self):
        dataset = prepare_dataset(self.client, DATASET)
        self.client.experiments.fail_evaluation_call = 8
        with TemporaryDirectory() as tmp:
            run_dir = run_experiment(DATASET, self.answer, Path(tmp),
                                     task_id="reconcile_case", repetitions=3)
            report = read_json(run_dir / "report.json")
            with self.assertRaises(ConnectionError):
                publish_report(self.client, dataset, run_dir)
            state = publish_report(self.client, dataset, run_dir)
        self.assertEqual(self.client.experiments.creates[0]["repetitions"], 3)
        self.assertEqual(len(self.client.experiments.runs), 3)
        self.assertEqual(set(state["run_ids"]), {
            "reconcile_case", "reconcile_case::2", "reconcile_case::3",
        })
        self.assertEqual([run["repetition_number"] for run in self.client.experiments.runs], [1, 2, 3])
        self.assertEqual([run["trace_id"] for run in self.client.experiments.runs],
                         [row["trace_id"] for row in report["rows"]])
        self.assertEqual(len(self.client.experiments.evaluations), 15)

    def test_duplicate_task_repetition_is_rejected_before_mutations(self):
        dataset = prepare_dataset(self.client, DATASET)
        with TemporaryDirectory() as tmp:
            run_dir = run_experiment(DATASET, self.answer, Path(tmp), task_id="reconcile_case")
            report = read_json(run_dir / "report.json")
            report["rows"].append(deepcopy(report["rows"][0]))
            (run_dir / "report.json").write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "duplicate task and repetition"):
                publish_report(self.client, dataset, run_dir)
            self.assertFalse((run_dir / "phoenix.json").exists())
        self.assertEqual(self.client.experiments.creates, [])
        self.assertEqual(self.client.experiments.runs, [])

    def test_incomplete_or_unknown_completion_is_rejected_before_mutations(self):
        dataset = prepare_dataset(self.client, DATASET)
        with TemporaryDirectory() as tmp:
            run_dir = run_experiment(DATASET, self.answer, Path(tmp), task_id="reconcile_case")
            report = read_json(run_dir / "report.json")
            report["complete"] = False
            (run_dir / "report.json").write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "incomplete evaluation report"):
                publish_report(self.client, dataset, run_dir)
            self.assertFalse((run_dir / "phoenix.json").exists())
            self.assertEqual(self.client.experiments.creates, [])
            self.assertEqual(self.client.experiments.runs, [])
            self.assertEqual(self.client.experiments.evaluations, {})
            del report["complete"]
            (run_dir / "report.json").write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "complete must be explicitly true"):
                publish_report(self.client, dataset, run_dir)
            self.assertEqual(self.client.experiments.creates, [])
            self.assertFalse((run_dir / "phoenix.json").exists())

    def test_historical_or_changed_scoring_sources_cannot_use_current_registry(self):
        dataset = prepare_dataset(self.client, DATASET)
        with TemporaryDirectory() as tmp:
            run_dir = run_experiment(DATASET, self.answer, Path(tmp), task_id="reconcile_case")
            original = read_json(run_dir / "report.json")
            for key in ("scoring_sha256", "grader_sha256", "contract_sha256"):
                with self.subTest(key=key):
                    report = deepcopy(original)
                    report[key] = "0" * 64
                    (run_dir / "report.json").write_text(json.dumps(report))
                    with self.assertRaisesRegex(ValueError, "--import-run"):
                        publish_report(self.client, dataset, run_dir,
                            evaluator_registry={"task_pass": {"id": "current-definition"}})
                    self.assertFalse((run_dir / "phoenix.json").exists())
            for key in ("fingerprint_version", "contract_sha256", "scoring_sha256", "runtime_code_sha256"):
                original.pop(key)
            (run_dir / "report.json").write_text(json.dumps(original))
            with self.assertRaisesRegex(ValueError, "--import-run or explicit baseline migration"):
                publish_report(self.client, dataset, run_dir)
        self.assertEqual(self.client.experiments.creates, [])
        self.assertEqual(self.client.experiments.runs, [])
        self.assertEqual(self.client.experiments.evaluations, {})

    def test_partial_or_unsupported_fingerprints_are_rejected(self):
        with TemporaryDirectory() as tmp:
            run_dir = run_experiment(DATASET, self.answer, Path(tmp), task_id="reconcile_case")
            original = read_json(run_dir / "report.json")
            for change in (
                lambda report: report.pop("scoring_sha256"),
                lambda report: report.update(fingerprint_version="future-unknown"),
                lambda report: report.update(runtime_code_sha256=""),
                lambda report: report.update(eval_code_sha256=None),
                lambda report: report.update(evaluator_version="another-policy"),
                lambda report: report.update(complete=1),
            ):
                report = deepcopy(original)
                change(report)
                with self.assertRaises(ValueError):
                    validate_current_report(report)

    def test_complete_flag_cannot_hide_missing_rows_or_wrong_summary_count(self):
        dataset = prepare_dataset(self.client, DATASET)
        with TemporaryDirectory() as tmp:
            run_dir = run_experiment(DATASET, self.answer, Path(tmp), task_id="reconcile_case", repetitions=2)
            original = read_json(run_dir / "report.json")
            for change, message in (
                (lambda report: report["rows"].pop(), "missing task repetitions"),
                (lambda report: report.update(rows=[]), "nonempty task rows"),
                (lambda report: report["summary"].update(tasks_evaluated=1), "summary task count"),
                (lambda report: report["rows"][0].update(repetition=0), "outside the experiment range"),
            ):
                with self.subTest(message=message):
                    report = deepcopy(original)
                    change(report)
                    (run_dir / "report.json").write_text(json.dumps(report))
                    with self.assertRaisesRegex(ValueError, message):
                        publish_report(self.client, dataset, run_dir)
                    self.assertFalse((run_dir / "phoenix.json").exists())
        self.assertEqual(self.client.experiments.creates, [])
        self.assertEqual(self.client.experiments.runs, [])
        self.assertEqual(self.client.experiments.evaluations, {})

    def test_runtime_changes_are_allowed_and_full_source_provenance_is_published(self):
        dataset = prepare_dataset(self.client, DATASET)
        with TemporaryDirectory() as tmp:
            run_dir = run_experiment(DATASET, self.answer, Path(tmp), task_id="reconcile_case")
            report = read_json(run_dir / "report.json")
            report.update(runtime_code_sha256="a" * 64, eval_code_sha256="b" * 64,
                          runtime_fingerprint_basis="legacy-whole-evals",
                          fingerprint_migration={"original_report_sha256": "c" * 64})
            (run_dir / "report.json").write_text(json.dumps(report))
            state = publish_report(self.client, dataset, run_dir)
            self.assertTrue(state["complete"])
        metadata = self.client.experiments.creates[0]["experiment_metadata"]
        for key in ("eval_code_sha256", "runtime_code_sha256", "runtime_fingerprint_basis", "fingerprint_migration"):
            self.assertEqual(metadata[key], report[key])
        self.assertEqual(metadata["evaluators"]["task_pass"]["source_sha256"], report["scoring_sha256"])

    def test_stable_document_root_matches_dataset_and_run(self):
        prompt_root = Path("/workspace/dataset")
        dataset = prepare_dataset(self.client, DATASET, prompt_root=prompt_root)
        with TemporaryDirectory() as tmp:
            run_dir = run_experiment(DATASET, self.answer, Path(tmp),
                                     task_id="reconcile_case", prompt_root=prompt_root)
            state = publish_report(self.client, dataset, run_dir)
        self.assertTrue(state["complete"])
        self.assertIn("/workspace/dataset/inputs/01_w2.pdf", dataset.examples[0]["input"]["text"])
        self.assertNotIn(str(DATASET), dataset.examples[0]["input"]["text"])

    def test_lost_successful_run_response_is_recovered_without_another_run(self):
        self.client.experiments = LostResponseExperiments()
        dataset = prepare_dataset(self.client, DATASET)
        with TemporaryDirectory() as tmp:
            run_dir = run_experiment(DATASET, self.answer, Path(tmp), task_id="reconcile_case")
            with self.assertRaises(ConnectionError):
                publish_report(self.client, dataset, run_dir)
            self.assertEqual(read_json(run_dir / "phoenix.json")["run_ids"], {})
            state = publish_report(self.client, dataset, run_dir)
        self.assertTrue(state["complete"])
        self.assertEqual(state["run_ids"], {"reconcile_case": "run-1"})
        self.assertEqual(len(self.client.experiments.creates), 1)
        self.assertEqual(len(self.client.experiments.runs), 1)
        self.assertEqual(len(self.client.experiments.evaluations), 5)

    def test_conflicting_foreign_run_is_not_adopted_or_annotated(self):
        self.client.experiments = LostResponseExperiments()
        dataset = prepare_dataset(self.client, DATASET)
        with TemporaryDirectory() as tmp:
            run_dir = run_experiment(DATASET, self.answer, Path(tmp), task_id="reconcile_case")
            with self.assertRaises(ConnectionError):
                publish_report(self.client, dataset, run_dir)
            remote = next(iter(self.client.experiments.persisted.values()))
            remote["trace_id"] = "f" * 32
            with self.assertRaisesRegex(ValueError, "differs from the local attempt"):
                publish_report(self.client, dataset, run_dir)
            self.assertEqual(read_json(run_dir / "phoenix.json")["run_ids"], {})
        self.assertEqual(len(self.client.experiments.runs), 1)
        self.assertEqual(self.client.experiments.evaluations, {})

    def test_conflict_recovery_follows_http_pagination(self):
        self.client.experiments = LostResponseExperiments()
        dataset = prepare_dataset(self.client, DATASET)
        requests = []
        def get(url, *, params):
            requests.append((url, params))
            remote = deepcopy(next(iter(self.client.experiments.persisted.values())))
            if "cursor" not in params:
                remote["dataset_example_id"] = "another-example"
                data = {"data": [remote], "next_cursor": "page-2"}
            else:
                data = {"data": [remote], "next_cursor": None}
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: data)
        with TemporaryDirectory() as tmp:
            run_dir = run_experiment(DATASET, self.answer, Path(tmp), task_id="reconcile_case")
            with self.assertRaises(ConnectionError):
                publish_report(self.client, dataset, run_dir)
            state = publish_report(self.client, dataset, run_dir, http=SimpleNamespace(get=get))
        self.assertTrue(state["complete"])
        self.assertEqual(requests, [
            ("/v1/experiments/experiment-1/runs", {"limit": 50}),
            ("/v1/experiments/experiment-1/runs", {"limit": 50, "cursor": "page-2"}),
        ])


if __name__ == "__main__":
    unittest.main()
