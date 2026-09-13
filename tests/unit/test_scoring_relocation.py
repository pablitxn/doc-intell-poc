"""The relocated scorer must preserve audited decisions and exported evaluator code."""

import ast
from copy import deepcopy
from decimal import Decimal
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest

from evals.datasets.loader import load_examples, read_json
from evals.evaluators.definitions import code_definitions
from evals.evaluators.scoring import GRADER_PATH, score_answer
from evals.experiments.fingerprints import (
    REPO_ROOT, _historical_score_answer, _historical_scoring_sources,
)


MANIFEST = REPO_ROOT / 'artifacts/2026-09-13/baseline-compatibility.json'


def frozen_definitions(manifest):
    """Execute the hash-verified former exporter with its original function text."""
    sources = _historical_scoring_sources(manifest)
    frozen_score = _historical_score_answer(manifest)
    function_text = {}
    for source in sources.values():
        for node in ast.parse(source).body:
            if isinstance(node, ast.FunctionDef):
                function_text[node.name] = ast.get_source_segment(source, node) + '\n'
    tree = ast.parse(sources['evals/evaluators/definitions.py'])
    descriptions = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                        and any(isinstance(target, ast.Name) and target.id == 'EVALUATOR_DEFINITIONS'
                                for target in node.targets))
    exporter = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == 'code_definitions')
    namespace = {
        **frozen_score.__globals__,
        'ast': ast,
        'inspect': SimpleNamespace(getsource=lambda function: function_text[function.__name__]),
        'GRADER_PATH': SimpleNamespace(read_text=lambda: sources['datasets/tax-mini-poc/grade.py']),
        'EVALUATOR_VERSION': manifest['evaluator_version'],
        'EVALUATOR_DEFINITIONS': ast.literal_eval(descriptions),
    }
    exec(compile(ast.Module(body=[exporter], type_ignores=[]), '<verified historical exporter>', 'exec'), namespace)
    return namespace['code_definitions']()


class ScoringRelocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = read_json(MANIFEST)
        cls.frozen_score = staticmethod(_historical_score_answer(cls.manifest))
        cls.examples = []
        for name in ('tax-mini-poc', 'tax-document-eval-v1'):
            examples, _ = load_examples(REPO_ROOT / 'datasets' / name)
            cls.examples.extend(examples)

    def assert_equivalent(self, output, example, status='success'):
        fields, expected = example.input.fields, example.expected
        self.assertEqual(score_answer(output, expected, fields, status),
                         self.frozen_score(output, expected, fields, status))

    def test_all_selected_reference_answers_and_execution_failures_preserve_scores(self):
        self.assertEqual(len(self.examples), 372)
        for example in self.examples:
            for status in ('success', 'timeout', 'unsupported', 'adapter_error', 'invalid_response'):
                with self.subTest(task=example.input.task_id, status=status):
                    self.assert_equivalent(example.expected, example, status)

    def test_every_selected_value_and_reference_mutation_preserves_decisions(self):
        for example in self.examples:
            for field, kind in example.input.fields.items():
                for mutation in ('missing', 'wrong_value', 'wrong_document', 'wrong_page', 'wrong_box', 'extra_reference'):
                    with self.subTest(task=example.input.task_id, field=field, mutation=mutation):
                        output = deepcopy(example.expected)
                        if mutation == 'missing':
                            output['values'].pop(field)
                        elif mutation == 'wrong_value':
                            value = output['values'][field]
                            output['values'][field] = (str(Decimal(value) + 1) if kind in ('money', 'percent')
                                                       else not value if kind == 'boolean' else str(value) + '_wrong')
                        elif mutation == 'extra_reference':
                            output['evidence'][field].append({'document_id': 'unknown', 'page': 1, 'box': 'wrong'})
                        else:
                            reference = output['evidence'][field][0]
                            key = {'wrong_document': 'document_id', 'wrong_page': 'page', 'wrong_box': 'box'}[mutation]
                            reference[key] = reference[key] + 1 if key == 'page' else reference[key] + '_wrong'
                        self.assert_equivalent(output, example)
                        self.assertFalse(score_answer(output, example.expected, example.input.fields)['task_pass'])

    def test_malformed_answers_preserve_schema_and_failure_classification(self):
        for example in self.examples:
            invalid = [None, [], False, 'invalid', {}, {'values': [], 'evidence': {}},
                       {'values': {}, 'evidence': []}, {**example.expected, 'unexpected': True}]
            for output in invalid:
                with self.subTest(task=example.input.task_id, output_type=type(output).__name__):
                    self.assert_equivalent(output, example)
                    self.assertFalse(score_answer(output, example.expected, example.input.fields)['task_pass'])

    def test_all_five_exported_evaluators_are_byte_identical(self):
        self.assertEqual(code_definitions(), frozen_definitions(self.manifest))

    def test_active_grader_is_generic_and_original_dataset_grader_is_intact(self):
        self.assertEqual(GRADER_PATH, REPO_ROOT / 'evals/evaluators/grading.py')
        original = REPO_ROOT / 'datasets/tax-mini-poc/grade.py'
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), self.manifest['grader_sha256'])
        self.assertNotEqual(hashlib.sha256(GRADER_PATH.read_bytes()).hexdigest(), self.manifest['grader_sha256'])


if __name__ == '__main__':
    unittest.main()
