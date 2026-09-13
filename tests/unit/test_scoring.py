"""EvaluatorTests for the shared evaluation application."""

from copy import deepcopy
from dataclasses import asdict
import json
import unittest
from evals.datasets.loader import load_examples
from evals.evaluators.scoring import evaluate
from tests.support.paths import ROOT

DATASET = ROOT / "datasets/tax-mini-poc"


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
