"""Reference answers are used here to test the evaluator, never as model results."""

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from evals.adapters.offline import empty_response, replay
from evals.datasets.loader import load_examples, read_json
from evals.evaluators.tax_mini import evaluate
from evals.experiments.runner import run_experiment

DATASET = Path(__file__).resolve().parents[1] / "datasets/tax-mini-poc"


class EvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.examples, self.version = load_examples(DATASET)

    def test_reference_answers_pass_all_54_fields(self):
        self.assertEqual(len(self.examples), 6)
        scores = [evaluate(example.expected, example) for example in self.examples]
        self.assertTrue(all(score["task_pass"] for score in scores))
        self.assertEqual(sum(len(score["fields"]) for score in scores), 54)

    def test_wrong_amount_fails_values_only(self):
        example = self.examples[0]
        output = deepcopy(example.expected)
        output["values"]["wages"] = "1.00"
        score = evaluate(output, example)
        self.assertTrue(score["schema_valid"])
        self.assertFalse(score["task_pass"])
        self.assertLess(score["value_accuracy"], 1)
        self.assertEqual(score["evidence_accuracy"], 1)

    def test_tax_liability_citation_is_not_withholding(self):
        example = self.examples[-1]
        output = deepcopy(example.expected)
        output["evidence"]["additional_medicare_withheld"][0]["box"] = "18"
        score = evaluate(output, example)
        self.assertEqual(score["value_accuracy"], 1)
        self.assertLess(score["evidence_accuracy"], 1)
        self.assertFalse(score["task_pass"])

    def test_double_counted_sdi_fails(self):
        example = self.examples[-1]
        output = deepcopy(example.expected)
        output["values"]["unique_employee_sdi_withheld"] = "6000.00"
        self.assertFalse(evaluate(output, example)["task_pass"])

    def test_extra_wrong_citation_fails(self):
        example = self.examples[0]
        output = deepcopy(example.expected)
        output["evidence"]["wages"].append({"document_id": "DOC-999", "page": 1, "box": "1"})
        self.assertFalse(evaluate(output, example)["task_pass"])

    def test_missing_is_not_zero(self):
        example = self.examples[1]
        output = deepcopy(example.expected)
        output["values"]["early_withdrawal_penalty"] = None
        score = evaluate(output, example)
        self.assertLess(score["value_accuracy"], 1)
        self.assertFalse(score["schema_valid"])

    def test_correct_number_still_requires_decimal_string(self):
        example = self.examples[0]
        output = deepcopy(example.expected)
        output["values"]["wages"] = 240000
        score = evaluate(output, example)
        self.assertEqual(score["value_accuracy"], 1)
        self.assertFalse(score["task_pass"])
        self.assertEqual(score["execution_status"], "invalid_response")

    def test_malformed_outputs_are_scored_without_crashing(self):
        for output in (None, [], "not JSON", {"values": [], "evidence": {}}, {"values": {}, "evidence": {}}):
            with self.subTest(output=output):
                score = evaluate(output, self.examples[0])
                self.assertFalse(score["task_pass"])
                self.assertEqual(len(score["fields"]), 12)

    def test_failure_cannot_pass_with_reference_output(self):
        example = self.examples[0]
        score = evaluate(example.expected, example, "timeout")
        self.assertEqual(score["value_accuracy"], 0)
        self.assertEqual(score["evidence_accuracy"], 0)
        self.assertFalse(score["task_pass"])

    def test_task_inputs_contain_no_reference_labels(self):
        for example in self.examples:
            payload = asdict(example.input)
            self.assertNotIn("expected", payload)
            self.assertNotIn("ground_truth", json.dumps(payload))
            for doc in payload["documents"]:
                self.assertEqual(set(doc), {"document_id", "path", "sha256", "page_count"})


class RunnerTests(unittest.TestCase):
    def test_unique_artifacts_and_fixed_denominator(self):
        with TemporaryDirectory() as tmp:
            first = run_experiment(DATASET, empty_response, Path(tmp), mode="smoke")
            second = run_experiment(DATASET, empty_response, Path(tmp), mode="smoke")
            self.assertNotEqual(first, second)
            report = read_json(first / "report.json")
            self.assertEqual(report["summary"]["fields_evaluated"], 54)
            self.assertEqual(report["summary"]["tasks_passed"], 0)
            self.assertIsNone(report["summary"]["total_service_cost_usd"])
            self.assertFalse(report["is_benchmark"])
            self.assertEqual(len((first / "scores.csv").read_text().splitlines()), 7)

    def test_errors_do_not_drop_tasks_or_leak_messages(self):
        answers = read_json(DATASET / "ground_truth/expected.json")["answers"]

        def adapter(task):
            if task.task_id == "extract_doc_001":
                raise TimeoutError("private diagnostic")
            if task.task_id == "extract_doc_002":
                raise NotImplementedError("private diagnostic")
            if task.task_id == "extract_doc_003":
                raise RuntimeError("private diagnostic")
            return answers[task.task_id]

        with TemporaryDirectory() as tmp:
            path = run_experiment(DATASET, adapter, Path(tmp), mode="test") / "report.json"
            report = read_json(path)
            self.assertEqual(report["summary"]["fields_evaluated"], 54)
            self.assertEqual(report["summary"]["tasks_passed"], 3)
            self.assertEqual(report["summary"]["execution_status_counts"], {
                "timeout": 1, "unsupported": 1, "adapter_error": 1, "success": 3,
            })
            self.assertNotIn("private diagnostic", path.read_text())

    def test_replay_one_task_and_reject_unknown_task(self):
        answers = read_json(DATASET / "ground_truth/expected.json")["answers"]
        with TemporaryDirectory() as tmp:
            path = run_experiment(DATASET, replay(answers), Path(tmp), mode="test", task_id="reconcile_case")
            summary = read_json(path / "report.json")["summary"]
            self.assertEqual(summary["fields_evaluated"], 6)
            self.assertEqual(summary["tasks_passed"], 1)
            with self.assertRaisesRegex(ValueError, "Unknown task"):
                run_experiment(DATASET, empty_response, Path(tmp), mode="test", task_id="typo")

    def test_non_json_output_is_an_explicit_failure(self):
        with TemporaryDirectory() as tmp:
            path = run_experiment(DATASET, lambda task: {"bad": float("nan")}, Path(tmp), mode="test")
            report = read_json(path / "report.json")
            self.assertEqual(report["summary"]["execution_status_counts"], {"invalid_response": 6})

    def test_adapter_cannot_mutate_evaluator_inputs(self):
        def adapter(task):
            task.fields.clear()
            return {"values": {}, "evidence": {}}

        with TemporaryDirectory() as tmp:
            path = run_experiment(DATASET, adapter, Path(tmp), mode="test")
            self.assertEqual(read_json(path / "report.json")["summary"]["fields_evaluated"], 54)


if __name__ == "__main__":
    unittest.main()
