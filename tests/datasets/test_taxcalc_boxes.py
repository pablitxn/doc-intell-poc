"""Regressions for the visible-source label builder, including omitted XML zeros."""
from pathlib import Path
import importlib.util
import shutil
import tempfile
import unittest
from unittest.mock import patch
from tests.support.paths import ROOT

CORPUS = ROOT / "datasets/tax-document-dataset-v0.1/taxcalc/download"
HAS_AUDIT_DEPS = all(importlib.util.find_spec(name) for name in ("pdfplumber", "pypdf", "pypdfium2"))


@unittest.skipUnless(HAS_AUDIT_DEPS and CORPUS.is_dir(), "requires the source corpus and PDF audit dependencies")
class TaxCalcVisibleBoxesTests(unittest.TestCase):
    def extract(self, relative):
        from preparation.extractors.taxcalc import extract_document
        return {row["field"]: row for row in extract_document(CORPUS / relative)}

    def test_printed_zero_is_preserved_even_when_xml_omits_withholding(self):
        row = self.extract("ty25-ca-004/input/w2_1.pdf")["federal_income_tax_withheld"]
        self.assertEqual(row["value"], "0.00")
        self.assertEqual(row["box"], "2")
        self.assertEqual(row["kind"], "money")
        self.assertFalse(row["verification"]["xml_used"])

    def test_unprinted_w2_withholding_is_absent_instead_of_zero(self):
        fields = self.extract("ty25-il-003/input/w2_1.pdf")
        self.assertNotIn("federal_income_tax_withheld", fields)
        self.assertEqual(fields["wages"]["value"], "50000.00")

    def test_visually_reviewed_boxes_keep_their_semantics(self):
        checks = [
            ("ty25-ny-008/input/1099g_1.pdf", "unemployment_compensation", "1", "10200.00"),
            ("ty25-va-001/input/1098t_1.pdf", "qualified_tuition_payments", "1", "21000.00"),
            ("ty25-il-003/input/1099int_1.pdf", "federal_income_tax_withheld", "4", "20.00"),
            ("ty25-ca-004/input/1098e_1.pdf", "student_loan_interest", "1", "1800.00"),
            ("ty25-va-008/input/1098_1.pdf", "mortgage_insurance_premiums", "5", "2400.00"),
            ("ty25-ca-009/input/1099b_1.pdf", "cost_or_other_basis", "1e", "3884.00"),
            ("ty25-il-008/input/1099div_1.pdf", "ordinary_dividends", "1a", "472.00"),
            ("ty25-us-003/input/1099r_1.pdf", "taxable_amount", "2a", "7000.00"),
            ("ty25-il-003/input/1099misc_1_schedule-c-1-abc.pdf", "rents", "1", "6000.00"),
            ("ty25-ca-007/input/w2g_1.pdf", "federal_income_tax_withheld", "4", "60.00"),
            ("ty25-ca-009/input/1099sa_1.pdf", "earnings_on_excess_contributions", "2", "0.00"),
            ("ty25-il-003/input/1099k_1_schedule-c-1-abc.pdf", "gross_payment_transactions", "1a", "4000.00"),
            ("ty25-il-003/input/1099nec_1_schedule-c-1-abc.pdf", "federal_income_tax_withheld", "4", "15.00"),
        ]
        for path, name, box, amount in checks:
            with self.subTest(path=path):
                row = self.extract(path)[name]
                self.assertEqual((row["box"], row["value"]), (box, amount))
        self.assertNotIn("federal_income_tax_withheld", self.extract("ty25-ca-009/input/1099sa_1.pdf"))

    def test_reader_disagreement_aborts_label_generation(self):
        from preparation.extractors.taxcalc import extract_document
        with patch("preparation.extractors.taxcalc.pypdfium2.PdfDocument") as pdfium:
            pdfium.return_value.__enter__.return_value.__getitem__.return_value.get_textpage.return_value.get_text_bounded.return_value = "99999999"
            with self.assertRaisesRegex(ValueError, "Independent PDF readers disagree"):
                extract_document(CORPUS / "ty25-ca-001/input/w2_1.pdf")

    def test_wrong_form_name_fails_even_with_valid_pdf_bytes(self):
        from preparation.extractors.taxcalc import extract_document
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "1099g_1.pdf"
            shutil.copyfile(CORPUS / "ty25-ca-001/input/w2_1.pdf", target)
            with self.assertRaisesRegex(ValueError, "Printed form title"):
                extract_document(target)

    def test_numeric_normalization_rejects_precision_and_nonamounts(self):
        from preparation.extractors.taxcalc import _money
        self.assertEqual(_money("$ 1,800.00", "test"), "1800.00")
        self.assertEqual(_money("-1,800.5", "test"), "-1800.50")
        self.assertIsNone(_money("$", "test"))
        for raw in ("1.999", "1,23", "NaN", "inf", "2025-01-01", "N/A"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                _money(raw, "test")


if __name__ == "__main__":
    unittest.main()
