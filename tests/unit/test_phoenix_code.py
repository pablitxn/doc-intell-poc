"""Published evaluator code must compute the same scores as local execution."""

from copy import deepcopy
import unittest

from evals.datasets.loader import load_examples
from evals.evaluators.definitions import code_definitions
from evals.evaluators.scoring import evaluate
from tests.support.paths import ROOT


class PublishedCodeTests(unittest.TestCase):
    def test_exported_code_matches_local_success_and_failure_scores(self):
        examples, _ = load_examples(ROOT / "datasets/tax-mini-poc")
        functions = {}
        for definition in code_definitions():
            namespace = {}
            exec(definition["source_code"], namespace)
            functions[definition["name"]] = namespace["evaluate"]
        for example in examples:
            wrong = deepcopy(example.expected)
            wrong["values"][next(iter(wrong["values"]))] = "999.00"
            wrong_type = deepcopy(example.expected)
            for key, kind in example.input.fields.items():
                if kind == "money":
                    wrong_type["values"][key] = float(wrong_type["values"][key])
                    break
            for answer, status in ((example.expected, "success"), (wrong, "success"),
                                   (wrong_type, "success"), (None, "timeout"), ({}, "invalid_response")):
                local = evaluate(answer, example, status)
                for name, function in functions.items():
                    with self.subTest(task=example.input.task_id, status=status, evaluator=name):
                        result = function({"answer": answer, "execution_status": status}, example.expected,
                                          {"field_types": example.input.fields})
                        expected = float(local[name] == "success") if name == "execution_status" else float(local[name])
                        self.assertEqual(result["score"], expected)


if __name__ == "__main__":
    unittest.main()
