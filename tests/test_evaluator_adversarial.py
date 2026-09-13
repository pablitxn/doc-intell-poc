"""Adversarial contract mutations; these are evaluator fixtures, not model results."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from evals.contracts import HarnessResult
from evals.datasets.loader import load_examples, read_json
from evals.evaluators.definitions import code_definitions
from evals.evaluators.tax_mini import evaluate
from evals.experiments.prompt import build_prompt
from evals.experiments.runner import run_experiment


DATASET = Path(__file__).resolve().parents[1] / "datasets/tax-mini-poc"


def mutated_answer(example, section, field, value):
    answer = deepcopy(example.expected)
    answer[section][field] = value
    return answer


class AdversarialScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.examples, _ = load_examples(DATASET)
        cls.remote = {}
        for definition in code_definitions():
            namespace = {}
            exec(definition["source_code"], namespace)
            cls.remote[definition["name"]] = namespace["evaluate"]

    def assert_scores_match_export(self, answer, example, status="success"):
        local = evaluate(answer, example, status)
        for name, function in self.remote.items():
            result = function({"answer": answer, "execution_status": status}, example.expected,
                              {"field_types": example.input.fields})
            expected = float(local[name] == "success") if name == "execution_status" else float(local[name])
            self.assertEqual(result["score"], expected, name)
            if name == "execution_status":
                self.assertEqual(result["label"], local[name])
        return local

    def test_money_mutations_reject_false_task_pass_and_match_phoenix(self):
        example = self.examples[0]
        for value in (None, True, False, float("nan"), float("inf"), -float("inf"),
                      "NaN", "Infinity", "$240,000.00", "240000", "240000.000",
                      "2.4e5", 240000, "240000.01", [], {}):
            with self.subTest(value=repr(value)):
                answer = mutated_answer(example, "values", "wages", value)
                score = self.assert_scores_match_export(answer, example)
                self.assertFalse(score["task_pass"])
                self.assertEqual(len(score["fields"]), len(example.input.fields))

    def test_boolean_is_not_an_integer_and_dates_must_exist(self):
        for value in (1, 0, "true", "false", None):
            with self.subTest(boolean=value):
                score = self.assert_scores_match_export(
                    mutated_answer(self.examples[0], "values", "retirement_plan", value), self.examples[0])
                field = next(field for field in score["fields"] if field["field"] == "retirement_plan")
                self.assertFalse(field["value_correct"])
                self.assertFalse(score["task_pass"])
        for value in ("2025-02-29", "2025-13-01", "2025-01-32", "2025-1-1", 20250101):
            with self.subTest(date=value):
                score = self.assert_scores_match_export(
                    mutated_answer(self.examples[4], "values", "coverage_start", value), self.examples[4])
                self.assertFalse(score["schema_valid"])

    def test_missing_zero_and_false_stay_wrong(self):
        example = self.examples[1]
        for field in ("early_withdrawal_penalty", "corrected"):
            for missing in (True, False):
                with self.subTest(field=field, missing=missing):
                    answer = deepcopy(example.expected)
                    if missing:
                        del answer["values"][field]
                    else:
                        answer["values"][field] = None
                    score = self.assert_scores_match_export(answer, example)
                    self.assertFalse(next(item for item in score["fields"] if item["field"] == field)["value_correct"])

    def test_extra_or_unrequested_fields_do_not_pass_schema(self):
        for section in ("values", "evidence"):
            answer = deepcopy(self.examples[0].expected)
            answer[section]["unrequested"] = "1.00" if section == "values" else []
            score = self.assert_scores_match_export(answer, self.examples[0])
            self.assertFalse(score["schema_valid"])
            self.assertFalse(score["task_pass"])
        answer = deepcopy(self.examples[0].expected)
        answer["unrequested"] = {"values": {"wages": "240000.00"}}
        score = self.assert_scores_match_export(answer, self.examples[0])
        self.assertFalse(score["schema_valid"])
        self.assertFalse(score["task_pass"])

    def test_citations_are_exact_sets_with_no_coercion_or_extra_support(self):
        example = self.examples[0]
        original = example.expected["evidence"]["wages"][0]
        mutations = [[], None, [None], [{}]]
        for key, values in (
            ("document_id", ("DOC-002", "DOC-999", "doc-001", " DOC-001", None, 1)),
            ("page", (True, False, 0, -1, 2, 1.0, "1", None)),
            ("box", ("2", "box 1", "W-2 box 1", " 1", "1 ", "01", 1, None)),
        ):
            for value in values:
                ref = deepcopy(original)
                ref[key] = value
                mutations.append([ref])
        mutations.append([original, {"document_id": "DOC-999", "page": 1, "box": "1"}])
        for refs in mutations:
            with self.subTest(refs=refs):
                score = self.assert_scores_match_export(mutated_answer(example, "evidence", "wages", refs), example)
                self.assertFalse(score["task_pass"])
                field = next(item for item in score["fields"] if item["field"] == "wages")
                # Numeric box 1 matches reference_key's stringification but is
                # independently rejected by schema; preserve existing policy.
                if refs != [{**original, "box": 1}]:
                    self.assertFalse(field["evidence_correct"])

    def test_documented_set_semantics_and_independent_accuracy_are_preserved(self):
        example = self.examples[0]
        answer = deepcopy(example.expected)
        answer["evidence"]["wages"] *= 2
        self.assertTrue(self.assert_scores_match_export(answer, example)["task_pass"])
        numeric = mutated_answer(example, "values", "wages", 240000)
        score = self.assert_scores_match_export(numeric, example)
        self.assertEqual(score["value_accuracy"], 1.0)
        self.assertFalse(score["schema_valid"])
        self.assertFalse(score["task_pass"])

    def test_each_failure_status_keeps_every_field_in_denominator_and_zeroes_credit(self):
        for example in self.examples:
            for status in ("timeout", "unsupported", "invalid_response", "adapter_error"):
                with self.subTest(task=example.input.task_id, status=status):
                    score = self.assert_scores_match_export(example.expected, example, status)
                    self.assertFalse(score["task_pass"])
                    self.assertEqual(score["value_accuracy"], 0)
                    self.assertEqual(score["evidence_accuracy"], 0)
                    self.assertEqual(len(score["fields"]), len(example.input.fields))

    def test_runner_repetitions_do_not_drop_failed_tasks(self):
        statuses = ["success", "timeout", "unsupported", "invalid_response", "adapter_error", "success"]
        position = 0

        def adapter(_prompt):
            nonlocal position
            example = self.examples[position % len(self.examples)]
            status = statuses[position % len(statuses)]
            position += 1
            return HarnessResult(output=deepcopy(example.expected), status=status)

        with TemporaryDirectory() as directory:
            path = run_experiment(DATASET, adapter, Path(directory), repetitions=2)
            report = read_json(path / "report.json")
        self.assertEqual(report["summary"]["fields_evaluated"], 108)
        self.assertEqual(report["summary"]["tasks_evaluated"], 12)
        self.assertEqual(report["summary"]["tasks_passed"], 4)
        self.assertEqual(len(report["rows"]), 12)

    def test_prompts_include_only_assigned_documents_and_shared_format_contract(self):
        manifest = read_json(DATASET / "manifest.json")
        for example in self.examples:
            prompt = build_prompt(example.input, DATASET, document_root=Path("/workspace"))
            paths = {document["path"] for document in example.input.documents}
            for document in manifest:
                self.assertEqual(document["path"] in prompt, document["path"] in paths)
            self.assertIn("no currency/percent symbols", prompt)
            for excluded in ("ground_truth", "expected.json", "field_types.json", "grade.py"):
                self.assertNotIn(excluded, prompt)


class AdversarialDatasetContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "dataset"
        shutil.copytree(DATASET, self.root)

    def edit(self, name, mutate):
        path = self.root / name
        value = read_json(path)
        mutate(value)
        path.write_text(json.dumps(value, indent=2))

    def assert_rejected(self):
        with self.assertRaises(ValueError):
            load_examples(self.root)

    def test_added_requested_field_without_expected_cannot_silently_pass(self):
        self.edit("tasks.json", lambda value: value["tasks"][0]["fields"].update(ungraded="money"))
        self.edit("ground_truth/field_types.json", lambda value: value["extract_doc_001"].update(ungraded="money"))
        self.assert_rejected()

    def test_missing_reference_field_or_extra_reference_field_is_rejected(self):
        for extra in (False, True):
            with self.subTest(extra=extra):
                original = read_json(DATASET / "ground_truth/expected.json")
                values = original["answers"]["extract_doc_001"]["values"]
                if extra:
                    values["unrequested"] = "0.00"
                else:
                    del values["wages"]
                (self.root / "ground_truth/expected.json").write_text(json.dumps(original))
                self.assert_rejected()

    def test_empty_tasks_fields_documents_and_extra_reference_task_are_rejected(self):
        mutations = [lambda value: value.update(tasks=[]),
                     lambda value: value["tasks"][0].update(fields={}),
                     lambda value: value["tasks"][0].update(documents=[]),
                     lambda value: value["tasks"].append(deepcopy(value["tasks"][0])),
                     lambda value: value["tasks"][0].update(task_id="../escape"),
                     lambda value: value["tasks"][0]["fields"].update(wages="unknown")]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                shutil.copyfile(DATASET / "tasks.json", self.root / "tasks.json")
                self.edit("tasks.json", mutate)
                self.assert_rejected()

    def test_reference_types_docs_and_pages_are_validated(self):
        mutations = [lambda answer: answer["values"].update(wages=240000),
                     lambda answer: answer["evidence"]["wages"][0].update(document_id="DOC-002"),
                     lambda answer: answer["evidence"]["wages"][0].update(page=2),
                     lambda answer: answer["evidence"]["wages"][0].update(page=True),
                     lambda answer: answer["evidence"]["wages"][0].update(box=" ")]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                shutil.copyfile(DATASET / "ground_truth/expected.json", self.root / "ground_truth/expected.json")
                self.edit("ground_truth/expected.json", lambda value: mutate(value["answers"]["extract_doc_001"]))
                self.assert_rejected()

    def test_field_types_cannot_diverge_from_tasks_without_detection(self):
        self.edit("ground_truth/field_types.json", lambda value: value["extract_doc_001"].update(wages="string"))
        self.assert_rejected()

    def test_manifest_duplicate_ids_paths_and_invalid_pages_are_rejected(self):
        mutations = [lambda value: value[1].update(document_id=value[0]["document_id"]),
                     lambda value: value.append(deepcopy(value[0])),
                     lambda value: value[0].update(page_count=True),
                     lambda value: value[0].update(page_count=0),
                     lambda value: value[0].update(path="inputs/../grade.py"),
                     lambda value: value[0].update(path=".")]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                shutil.copyfile(DATASET / "manifest.json", self.root / "manifest.json")
                self.edit("manifest.json", mutate)
                self.assert_rejected()

    def test_reference_and_type_task_membership_must_match(self):
        for filename, extra in (("ground_truth/expected.json", "answers"),
                                ("ground_truth/field_types.json", None)):
            with self.subTest(filename=filename):
                target = self.root / filename
                original = target.read_text()
                self.edit(filename, lambda value: (value[extra] if extra else value).update(unrequested={}))
                self.assert_rejected()
                target.write_text(original)

    def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected_at_read(self):
        path = self.root / "mutation.json"
        for text in ('{"x":1,"x":2}', '{"nested":{"x":1,"x":2}}',
                     '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{"x":1e999}'):
            with self.subTest(text=text):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    read_json(path)

    def test_type_file_participates_in_dataset_fingerprint(self):
        _, before = load_examples(self.root)
        path = self.root / "ground_truth/field_types.json"
        path.write_text(path.read_text() + "\n")
        _, after = load_examples(self.root)
        self.assertNotEqual(before, after)


class StandaloneGraderContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.checkout = Path(self.temp.name) / "checkout"
        self.root = self.checkout / "datasets/tax-mini-poc"
        shutil.copytree(DATASET, self.root)
        shutil.copytree(DATASET.parents[1] / "evals", self.checkout / "evals",
                        ignore=shutil.ignore_patterns("__pycache__"))
        self.examples, _ = load_examples(self.root)

    def run_cli(self, predictions, task=None):
        path = self.checkout / "predictions.json"
        path.write_text(json.dumps(predictions))
        argv = [sys.executable, str(self.root / "grade.py"), "--predictions", str(path)]
        if task:
            argv.extend(["--task", task])
        # An unrelated cwd verifies that the complete checkout is found by the
        # script path, without relying on the invoking shell's import path.
        return subprocess.run(argv, cwd=self.temp.name, capture_output=True, text=True)

    def test_cli_task_pass_schema_and_partial_accuracy_match_runner(self):
        example = self.examples[0]
        variants = [deepcopy(example.expected)]
        for value in (240000, "$240,000.00", "240000", "240000.01"):
            variants.append(mutated_answer(example, "values", "wages", value))
        extra = deepcopy(example.expected)
        extra["unrequested"] = "content"
        variants.append(extra)
        for answer in variants:
            with self.subTest(answer=answer["values"]["wages"], extra="unrequested" in answer):
                result = self.run_cli({"answers": {example.input.task_id: answer}}, example.input.task_id)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                local = evaluate(answer, example)
                self.assertEqual(report["tasks_evaluated"], 1)
                self.assertEqual(report["tasks_passed"], int(local["task_pass"]))
                self.assertEqual(report["value_accuracy"], local["value_accuracy"])
                self.assertEqual(report["evidence_accuracy"], local["evidence_accuracy"])
                row = report["per_task"][0]
                for metric in ("schema_valid", "schema_errors", "execution_status", "fields"):
                    self.assertEqual(row[metric], local[metric], metric)
                self.assertEqual(row["passed"], local["task_pass"])

    def test_cli_all_tasks_preserve_denominator_with_missing_predictions(self):
        result = self.run_cli({"answers": {self.examples[0].input.task_id: self.examples[0].expected}})
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["tasks_evaluated"], 6)
        self.assertEqual(report["tasks_passed"], 1)
        self.assertEqual(report["fields_evaluated"], 54)

    def test_cli_rejects_invalid_ground_truth_before_producing_a_report(self):
        path = self.root / "ground_truth/expected.json"
        expected = read_json(path)
        del expected["answers"]["extract_doc_001"]["values"]["wages"]
        path.write_text(json.dumps(expected))
        result = self.run_cli({"answers": {example.input.task_id: example.expected for example in self.examples}})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("Reference answer", result.stderr)


if __name__ == "__main__":
    unittest.main()
