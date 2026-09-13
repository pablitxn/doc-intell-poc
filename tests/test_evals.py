"""Reference answers are used here to test the evaluator, never as model results."""

from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from evals.__main__ import main
from evals.datasets.loader import load_examples, read_json
from evals.evaluators.tax_mini import evaluate
from evals.experiments.runner import run_experiment
from evals.experiments.prompt import PROMPT_VERSION, build_prompt

DATASET = Path(__file__).resolve().parents[1] / "datasets/tax-mini-poc"


def empty_response(input_text):
    """A local test double; production runs always invoke the injected harness."""
    assert isinstance(input_text, str)
    return {"values": {}, "evidence": {}}


def task_id_from_text(input_text):
    return input_text.split("Task ID: ", 1)[1].splitlines()[0]


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

    def test_equal_amount_in_an_intermediate_box_is_not_the_requested_total(self):
        example = self.examples[-1]
        self.assertIn('use and cite the total on line 24', example.input.instruction)
        output = deepcopy(example.expected)
        output['evidence']['additional_medicare_withheld'][0]['box'] = '22'
        score = evaluate(output, example)
        self.assertEqual(score['value_accuracy'], 1)
        self.assertLess(score['evidence_accuracy'], 1)
        self.assertFalse(score['task_pass'])

    def test_unrequested_top_level_answer_content_fails_schema(self):
        example = self.examples[0]
        output = deepcopy(example.expected)
        output['unrequested'] = 'extra answer'
        self.assertFalse(evaluate(output, example)['schema_valid'])
        self.assertFalse(evaluate(output, example)['task_pass'])

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


class PromptTests(unittest.TestCase):
    def test_format_contract_is_explicit_for_reconciliation_too(self):
        examples, _ = load_examples(DATASET)
        for example in examples:
            text = build_prompt(example.input, DATASET, document_root=Path('/workspace'))
            self.assertIn('no currency/percent symbols', text)
            self.assertIn('no thousands separators', text)
            self.assertIn('evidence.box', text)
            self.assertNotIn('ground_truth', text)

    def test_prompt_contains_dataset_reference_and_only_requested_documents(self):
        examples, _ = load_examples(DATASET)
        task = examples[0].input
        text = build_prompt(task, DATASET)
        self.assertIn(str(DATASET / "inputs"), text)
        self.assertIn(str(DATASET / "inputs/01_w2.pdf"), text)
        self.assertNotIn("02_1099_int.pdf", text)
        self.assertIn(task.instruction, text)
        self.assertIn("wages: money", text)
        self.assertIn("DOC-001", text)
        self.assertNotIn("ground_truth", text)
        self.assertNotIn("240000.00", text)
        self.assertNotIn("grade.py", text)
        self.assertEqual(task_id_from_text(text), task.task_id)


class CLITests(unittest.TestCase):
    def test_harness_command_is_required(self):
        with patch("sys.argv", ["evals"]), redirect_stderr(StringIO()):
            with patch("evals.__main__.command_harness") as factory, patch("evals.__main__.run_experiment") as runner:
                with self.assertRaises(SystemExit) as error:
                    main()
                self.assertEqual(error.exception.code, 2)
                factory.assert_not_called()
                runner.assert_not_called()

    def test_missing_executable_does_not_start_an_experiment(self):
        with patch("sys.argv", ["evals", "--harness-command", "missing"]), redirect_stderr(StringIO()):
            with patch("evals.__main__.command_harness", side_effect=ValueError("Executable not found")):
                with patch("evals.__main__.run_experiment") as runner:
                    with self.assertRaises(SystemExit) as error:
                        main()
                    self.assertEqual(error.exception.code, 2)
                    runner.assert_not_called()

    def test_cli_passes_command_as_arguments_and_run_options(self):
        argv = ["evals", "--harness-command", 'my-harness run --label "two words"',
                "--dataset", "custom-dataset", "--task", "reconcile_case",
                "--output-dir", "custom-runs", "--timeout", "30"]
        summary = {"tasks_passed": 1, "tasks_evaluated": 1, "fields_evaluated": 6}
        with patch("sys.argv", argv), redirect_stdout(StringIO()):
            with patch("evals.__main__.command_harness", return_value=empty_response) as factory:
                with patch("evals.__main__.run_experiment", return_value=Path("custom-runs/run-id")) as runner:
                    with patch("evals.__main__.read_json", return_value={"summary": summary}):
                        main()
            factory.assert_called_once_with(["my-harness", "run", "--label", "two words"], timeout_seconds=30.0)
            runner.assert_called_once_with(
                Path("custom-dataset"), empty_response, Path("custom-runs"),
                adapter_name="my-harness", task_id="reconcile_case",
            )


if __name__ == "__main__":
    unittest.main()
