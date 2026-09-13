"""RunnerTests for the shared evaluation application."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from evals.datasets.loader import read_json
from evals.experiments.runner import run_experiment
from evals.experiments.prompt import PROMPT_VERSION
from tests.support.answers import empty_response, task_id_from_text
from tests.support.paths import ROOT

DATASET = ROOT / "datasets/tax-mini-poc"


class RunnerTests(unittest.TestCase):
    def test_unique_artifacts_and_fixed_denominator(self):
        with TemporaryDirectory() as tmp:
            first = run_experiment(DATASET, empty_response, Path(tmp))
            second = run_experiment(DATASET, empty_response, Path(tmp))
            self.assertNotEqual(first, second)
            report = read_json(first / "report.json")
            self.assertEqual(report["summary"]["fields_evaluated"], 54)
            self.assertEqual(report["summary"]["tasks_passed"], 0)
            self.assertIsNone(report["summary"]["total_service_cost_usd"])
            self.assertEqual(report["adapter"], f"{empty_response.__module__}:{empty_response.__qualname__}")
            self.assertNotIn("mode", report)
            self.assertNotIn("is_benchmark", report)
            self.assertEqual(len((first / "scores.csv").read_text().splitlines()), 7)

    def test_errors_do_not_drop_tasks_or_leak_messages(self):
        answers = read_json(DATASET / "ground_truth/expected.json")["answers"]

        def adapter(input_text):
            task_id = task_id_from_text(input_text)
            if task_id == "extract_doc_001":
                raise TimeoutError("private diagnostic")
            if task_id == "extract_doc_002":
                raise NotImplementedError("private diagnostic")
            if task_id == "extract_doc_003":
                raise RuntimeError("private diagnostic")
            return answers[task_id]

        with TemporaryDirectory() as tmp:
            path = run_experiment(DATASET, adapter, Path(tmp)) / "report.json"
            report = read_json(path)
            self.assertEqual(report["summary"]["fields_evaluated"], 54)
            self.assertEqual(report["summary"]["tasks_passed"], 3)
            self.assertEqual(report["summary"]["execution_status_counts"], {
                "timeout": 1, "unsupported": 1, "adapter_error": 1, "success": 3,
            })
            self.assertNotIn("private diagnostic", path.read_text())

    def test_select_one_task_and_record_adapter_name(self):
        answers = read_json(DATASET / "ground_truth/expected.json")["answers"]

        def adapter(input_text):
            return deepcopy(answers[task_id_from_text(input_text)])

        with TemporaryDirectory() as tmp:
            path = run_experiment(
                DATASET, adapter, Path(tmp),
                adapter_name="my-harness", task_id="reconcile_case",
            )
            report = read_json(path / "report.json")
            self.assertEqual(report["adapter"], "my-harness")
            summary = report["summary"]
            self.assertEqual(summary["fields_evaluated"], 6)
            self.assertEqual(summary["tasks_passed"], 1)
            with self.assertRaisesRegex(ValueError, "Unknown task"):
                run_experiment(DATASET, empty_response, Path(tmp), task_id="typo")

    def test_non_json_output_is_an_explicit_failure(self):
        with TemporaryDirectory() as tmp:
            path = run_experiment(DATASET, lambda task: {"bad": float("nan")}, Path(tmp))
            report = read_json(path / "report.json")
            self.assertEqual(report["summary"]["execution_status_counts"], {"invalid_response": 6})

    def test_harness_receives_only_text_and_report_preserves_it(self):
        received = []

        def adapter(input_text):
            self.assertIsInstance(input_text, str)
            received.append(input_text)
            return {"values": {}, "evidence": {}}

        with TemporaryDirectory() as tmp:
            path = run_experiment(DATASET, adapter, Path(tmp))
            report = read_json(path / "report.json")
            self.assertEqual(report["summary"]["fields_evaluated"], 54)
            self.assertEqual([row["input"] for row in report["rows"]], received)
            self.assertEqual(report["prompt_version"], PROMPT_VERSION)
            self.assertEqual(len(received), 6)
