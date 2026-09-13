"""Contract and arithmetic checks for the prepared full source projection.

Scoring the expected answer only tests compatibility. Source correctness is
established separately by the recorded visual/PDF audit; reconciliation below
is recomputed from extraction observations without importing the builder.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import unittest

from evals.datasets.loader import load_examples, read_json
from evals.evaluators.scoring import evaluate
from evals.experiments.prompt import build_prompt
from tests.support.paths import ROOT


DATASET = ROOT / "datasets/tax-document-eval-v1"
SOURCE = ROOT / "datasets/tax-document-dataset-v0.1"


def references(items):
    return {(item["document_id"], item["page"], item["box"]) for item in items}


class FullDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.examples, cls.version = load_examples(DATASET)
        cls.tasks = read_json(DATASET / "tasks.json")["tasks"]
        cls.manifest = read_json(DATASET / "manifest.json")
        cls.answers = read_json(DATASET / "ground_truth/expected.json")["answers"]
        cls.types = read_json(DATASET / "ground_truth/field_types.json")
        cls.provenance = read_json(DATASET / "ground_truth/provenance.json")
        cls.by_document = {doc["document_id"]: doc for doc in cls.manifest}
        cls.by_task = {example.input.task_id: example for example in cls.examples}
        cls.extractions = {
            example.input.documents[0]["document_id"]: example
            for example in cls.examples if example.group == "extraction"
        }

    def test_complete_document_task_and_reference_membership(self):
        self.assertEqual(len(self.manifest), 319)
        self.assertEqual(len(self.examples), 366)
        self.assertEqual(Counter(example.group for example in self.examples),
                         {"extraction": 319, "reconciliation": 47})
        self.assertEqual(Counter(Path(doc["path"]).suffix for doc in self.manifest),
                         {".pdf": 264, ".json": 50, ".jpg": 5})
        case_ids = {example.input.case_id for example in self.examples}
        self.assertEqual(len(case_ids), 55)
        self.assertEqual(sum(case.startswith("ty25-") for case in case_ids), 50)
        self.assertEqual(sum(case.startswith("fake-w2-") for case in case_ids), 5)
        task_ids = {task["task_id"] for task in self.tasks}
        self.assertEqual(task_ids, set(self.answers))
        self.assertEqual(task_ids, set(self.types))
        self.assertEqual(task_ids, set(self.provenance))
        self.assertEqual(set(self.extractions), set(self.by_document))
        self.assertEqual(len(task_ids), len(self.tasks))
        self.assertEqual(len(self.by_document), len(self.manifest))
        self.assertEqual(sum(len(task.input.fields) for task in self.examples), 1465)
        self.assertEqual(Counter(kind for task in self.examples for kind in task.input.fields.values()),
                         {"money": 1253, "boolean": 162, "string": 50})

    def test_preparation_provenance_covers_current_package_and_entry_point(self):
        audit = read_json(DATASET / "audit.json")
        expected_files = {"scripts/prepare_full_dataset.py"} | {
            path.relative_to(ROOT).as_posix() for path in (ROOT / "preparation").rglob("*.py")
        }
        self.assertEqual(set(audit["preparation_source_sha256"]), expected_files)
        for name, digest in audit["preparation_source_sha256"].items():
            with self.subTest(source=name):
                self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)

    def test_source_bytes_and_derived_inputs_have_exact_membership(self):
        actual = {path.relative_to(DATASET).as_posix()
                  for path in (DATASET / "inputs").rglob("*") if path.is_file()}
        self.assertEqual(actual, {doc["path"] for doc in self.manifest})
        for doc in self.manifest:
            with self.subTest(document=doc["document_id"]):
                digest = hashlib.sha256((DATASET / doc["path"]).read_bytes()).hexdigest()
                self.assertEqual(digest, doc["sha256"])
                self.assertEqual(digest, hashlib.sha256((SOURCE / doc["source_path"]).read_bytes()).hexdigest())
                self.assertNotIn("/output/", doc["source_path"])
                self.assertFalse(doc["source_path"].startswith(("official/", "extractbench/")))

    def test_case_and_year_context_matches_every_assigned_document(self):
        years_by_case = defaultdict(set)
        for example in self.examples:
            task = example.input
            years_by_case[task.case_id].add(task.tax_year)
            documents = [self.by_document[doc["document_id"]] for doc in task.documents]
            with self.subTest(task=task.task_id):
                self.assertTrue(all(doc["case_id"] == task.case_id for doc in documents))
                if example.group == "reconciliation":
                    self.assertEqual(task.tax_year, 2025)
                else:
                    doc = documents[0]
                    year = 2010 if doc["family"] == "fake_w2" else 2024 if doc["family"] == "1040" else 2025
                    self.assertEqual(task.tax_year, year)
                    self.assertEqual(doc["tax_year"], year)
                prompt = build_prompt(task, DATASET, document_root=Path("/workspace"))
                self.assertIn(f"Case: {task.case_id}\nTax year: {task.tax_year}\n", prompt)
        for case, years in years_by_case.items():
            self.assertEqual(years, {2010} if case.startswith("fake-w2-") else {2024, 2025})

    def test_references_are_assigned_and_qualifiers_are_public(self):
        saw_rows = saw_json = saw_boolean = False
        for example in self.examples:
            task = example.input
            assigned = {doc["document_id"]: doc for doc in task.documents}
            for field, refs in example.expected["evidence"].items():
                with self.subTest(task=task.task_id, field=field):
                    self.assertTrue(refs)
                    self.assertEqual(len(references(refs)), len(refs))
                    for ref in refs:
                        self.assertIn(ref["document_id"], assigned)
                        self.assertGreaterEqual(ref["page"], 1)
                        self.assertLessEqual(ref["page"], assigned[ref["document_id"]]["page_count"])
                        if example.group == "extraction":
                            self.assertIn(f'Use evidence.box={json.dumps(ref["box"])} on page {ref["page"]}.',
                                          task.instruction)
                        if ":first" in ref["box"] or ":second" in ref["box"]:
                            saw_rows = True
                            self.assertIn("first and second printed state/local", task.instruction)
                        if ref["box"].startswith("/"):
                            saw_json = True
                            self.assertEqual(ref["page"], 1)
                            self.assertIn("JSON pointer", task.instruction)
                        if ref["box"].startswith("13:"):
                            saw_boolean = True
                            self.assertIn("checkbox", task.instruction)
        self.assertTrue(saw_rows and saw_json and saw_boolean)

    def test_prompts_and_public_document_metadata_do_not_include_grading_files(self):
        for example in self.examples:
            task = example.input
            prompt = build_prompt(task, DATASET, document_root=Path("/workspace"))
            with self.subTest(task=task.task_id):
                self.assertIn("exactly two fractional digits", prompt)
                self.assertIn("including row qualifiers or JSON pointers", prompt)
                for marker in ("ground_truth", "expected.json", "field_types.json", "provenance.json",
                               "preparation/", "fake_w2.py", "taxcalc.py", "grade.py"):
                    self.assertNotIn(marker, prompt)
                for doc in task.documents:
                    self.assertEqual(set(doc), {"document_id", "path", "sha256", "page_count"})
                lines = prompt.split("Documents for this task:\n", 1)[1].split("\n\n", 1)[0].splitlines()
                expected = [f'- {doc["document_id"]}: /workspace/{doc["path"]}' for doc in task.documents]
                self.assertEqual(lines, expected)

    def test_expected_answers_are_compatible_with_the_contract_not_a_source_oracle(self):
        for example in self.examples:
            with self.subTest(task=example.input.task_id):
                score = evaluate(example.expected, example)
                self.assertTrue(score["schema_valid"])
                self.assertTrue(score["task_pass"])
                self.assertEqual(score["value_accuracy"], 1.0)
                self.assertEqual(score["evidence_accuracy"], 1.0)

    def test_each_task_rejects_an_incorrect_value_none_and_wrong_box(self):
        for example in self.examples:
            field, kind = next(iter(example.input.fields.items()))
            value = example.expected["values"][field]
            wrong = (format(Decimal(value) + Decimal("0.01"), ".2f")
                     if kind in {"money", "percent"} else not value
                     if kind == "boolean" else value + "-incorrect")
            for mutation in ("wrong_value", "none", "wrong_box", "unsupported_reference", "extra_field"):
                with self.subTest(task=example.input.task_id, mutation=mutation):
                    answer = deepcopy(example.expected)
                    if mutation == "wrong_value":
                        answer["values"][field] = wrong
                    elif mutation == "none":
                        answer["values"][field] = None
                    elif mutation == "wrong_box":
                        answer["evidence"][field][0]["box"] += ":wrong"
                    elif mutation == "unsupported_reference":
                        answer["evidence"][field].append({"document_id": "not-an-assigned-document", "page": 1, "box": "1"})
                    else:
                        answer["values"]["unrequested"] = "0.00"
                    self.assertFalse(evaluate(answer, example)["task_pass"])

    def test_each_money_task_rejects_json_float_even_when_numerically_equal(self):
        covered = set()
        for example in self.examples:
            field = next((key for key, kind in example.input.fields.items() if kind == "money"), None)
            if field is None:
                continue
            covered.add(example.group)
            with self.subTest(task=example.input.task_id):
                answer = deepcopy(example.expected)
                answer["values"][field] = float(answer["values"][field])
                result = evaluate(answer, example)
                self.assertFalse(result["schema_valid"])
                self.assertFalse(result["task_pass"])
        self.assertEqual(covered, {"extraction", "reconciliation"})

    def test_same_amount_in_a_different_printed_box_is_not_interchangeable(self):
        for document in (doc for doc in self.manifest if doc["family"] == "fake_w2"):
            example = self.extractions[document["document_id"]]
            # These synthetic sources repeat the same amount in distinct boxes.
            # Their explicitly named observations remain different fields.
            self.assertEqual(example.expected["values"]["box_3_social_security_wages"],
                             example.expected["values"]["box_7_social_security_tips"])
            answer = deepcopy(example.expected)
            answer["evidence"]["box_3_social_security_wages"] = deepcopy(
                answer["evidence"]["box_7_social_security_tips"])
            score = evaluate(answer, example)
            self.assertEqual(score["value_accuracy"], 1.0)
            self.assertFalse(score["task_pass"])
            row_field = "box_17_first_state_income_tax"
            for wrong_box in ("17", "17:second"):
                with self.subTest(document=document["document_id"], box=wrong_box):
                    answer = deepcopy(example.expected)
                    answer["evidence"][row_field][0]["box"] = wrong_box
                    self.assertFalse(evaluate(answer, example)["task_pass"])

    def test_audited_blank_prior_return_has_no_invented_zero_amount(self):
        example = self.by_task["extract_taxcalc_ty25_us_001_1040_2024"]
        self.assertEqual(example.input.tax_year, 2024)
        self.assertEqual(example.input.fields, {"form_year": "string"})
        self.assertEqual(example.expected["values"], {"form_year": "2024"})

    def test_all_50_cases_independently_define_only_supported_reconciliations(self):
        withholding_families = {"w2", "w2g", "1099b", "1099div", "1099g", "1099int",
                                "1099k", "1099misc", "1099nec", "1099r"}
        reconciliations = {example.input.case_id: example for example in self.examples
                           if example.group == "reconciliation"}
        documents_by_case = defaultdict(list)
        for document in self.manifest:
            if document["case_id"].startswith("ty25-"):
                documents_by_case[document["case_id"]].append(document)
        missing_totals = 0
        missing_cases = set()
        self.assertEqual(len(documents_by_case), 50)
        self.assertEqual(len(reconciliations), 47)
        for case_id, documents in documents_by_case.items():
            contributors = {key: [] for key in ("w2_wages_total", "w2_federal_withholding_total",
                                                 "documented_federal_withholding_total")}
            for document in documents:
                source = self.extractions[document["document_id"]]
                values = source.expected["values"]
                if document["family"] == "w2" and "wages" in values:
                    contributors["w2_wages_total"].append((source, "wages"))
                if document["family"] == "w2" and "federal_income_tax_withheld" in values:
                    contributors["w2_federal_withholding_total"].append((source, "federal_income_tax_withheld"))
                if document["family"] in withholding_families and "federal_income_tax_withheld" in values:
                    contributors["documented_federal_withholding_total"].append((source, "federal_income_tax_withheld"))
            with self.subTest(case=case_id):
                populated = {key for key, rows in contributors.items() if rows}
                if not populated:
                    missing_cases.add(case_id)
                    self.assertNotIn(case_id, reconciliations)
                    continue
                self.assertIn(case_id, reconciliations)
                example = reconciliations[case_id]
                self.assertEqual(set(example.input.fields), populated)
                for total_field, rows in contributors.items():
                    if not rows:
                        missing_totals += 1
                        self.assertNotIn(total_field, example.expected["values"])
                        self.assertNotIn(total_field, example.expected["evidence"])
                        continue
                    # Integer cents, independently from the builder's Decimal sum.
                    cents = sum(int(Decimal(source.expected["values"][field]) * 100) for source, field in rows)
                    self.assertEqual(Decimal(example.expected["values"][total_field]) * 100, cents)
                    expected_refs = {ref for source, field in rows
                                     for ref in references(source.expected["evidence"][field])}
                    self.assertEqual(references(example.expected["evidence"][total_field]), expected_refs)
                    self.assertTrue(all(self.by_document[doc_id]["family"] in withholding_families
                                        for doc_id, _, _ in expected_refs))
        self.assertEqual(len(missing_cases), 3)
        self.assertGreater(missing_totals, 0, "Blank contributions must not create invented zero totals")

    def test_fake_w2_values_match_reviewed_source_metadata_without_personal_identifiers(self):
        cases = [doc for doc in self.manifest if doc["family"] == "fake_w2"]
        self.assertEqual(len(cases), 5)
        kinds = Counter()
        for document in cases:
            example = self.extractions[document["document_id"]]
            original = read_json((SOURCE / document["source_path"]).with_suffix(".json"))["gt_parse"]
            self.assertEqual(len(example.input.fields), 25)
            for field, kind in example.input.fields.items():
                kinds[kind] += 1
                source_field = field.replace("_first_", "_1_").replace("_second_", "_2_")
                source_field = {
                    "box_6_medicare_tax_withheld": "box_6_medicare_wages_tax_withheld",
                    "box_13_statutory_employee": "box_13_statutary_employee",
                    "box_13_third_party_sick_pay": "box_13_third_part_sick_pay",
                }.get(source_field, source_field)
                observed = original[source_field]
                value = format(Decimal(str(observed)), ".2f") if kind == "money" else observed == "x"
                with self.subTest(document=document["document_id"], field=field):
                    self.assertEqual(example.expected["values"][field], value)
                    self.assertIs(type(example.expected["values"][field]), type(value))
                    evidence = self.provenance[example.input.task_id][field]
                    self.assertEqual(evidence["source_sha256"], document["sha256"])
                    self.assertEqual(evidence["review_version"], "fake-w2-visual-v1")
                    self.assertNotIn("id", field)
                    self.assertNotIn("name", field)
                    if kind == "money":
                        self.assertNotEqual(observed, "None")
        self.assertEqual(kinds, {"money": 110, "boolean": 15})

    def test_identical_source_documents_cannot_be_assigned_different_split_groups(self):
        groups = defaultdict(set)
        for document in self.manifest:
            groups[document["sha256"]].add(document["source_group_id"])
        self.assertTrue(all(len(group) == 1 for group in groups.values()))
        for task in self.tasks:
            self.assertEqual(task["split"], "development")


if __name__ == "__main__":
    unittest.main()
