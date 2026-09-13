"""PromptTests for the shared evaluation application."""

from pathlib import Path
import unittest
from evals.datasets.loader import load_examples
from evals.experiments.prompt import build_prompt
from tests.support.answers import task_id_from_text
from tests.support.paths import ROOT

DATASET = ROOT / "datasets/tax-mini-poc"


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
