"""Independent PDF transcription is an oracle, not a call back into the grader.

The five PDFs were visually inspected and their 48 printed fields transcribed.
Hashes bind that review to the exact immutable source files. Six reconciliation
values are recomputed below with Decimal instead of using grader output.
"""

from decimal import Decimal as D
import hashlib
import json
import unittest
from tests.support.paths import ROOT

DATASET = ROOT / 'datasets/tax-mini-poc'
AUDIT = json.loads((ROOT / 'tests/fixtures/tax_mini_pdf_audit.json').read_text())


class DatasetSourceAuditTests(unittest.TestCase):
    def test_all_sources_match_the_visually_reviewed_pdf_bytes(self):
        self.assertEqual(len(AUDIT['sources']), 5)
        for filename, source in AUDIT['sources'].items():
            with self.subTest(source=filename):
                self.assertEqual(hashlib.sha256((DATASET/'inputs'/filename).read_bytes()).hexdigest(), source['sha256'])

    def test_all_54_ground_truth_values_and_citations_match_independent_transcription(self):
        expected = json.loads((DATASET/'ground_truth/expected.json').read_text())['answers']
        self.assertEqual(set(AUDIT['tasks']), set(expected))
        self.assertEqual(sum(len(fields) for fields in AUDIT['tasks'].values()), 54)
        for task, fields in AUDIT['tasks'].items():
            self.assertEqual(set(fields), set(expected[task]['values']))
            self.assertEqual(set(fields), set(expected[task]['evidence']))
            for field, observed in fields.items():
                with self.subTest(task=task, field=field):
                    self.assertEqual(observed['value'], expected[task]['values'][field])
                    self.assertEqual(type(observed['value']), type(expected[task]['values'][field]))
                    references = lambda refs: {(ref['document_id'],ref['page'],ref['box']) for ref in refs}
                    self.assertEqual(references(observed['evidence']), references(expected[task]['evidence'][field]))

    def test_reconciliation_and_payroll_arithmetic_recompute_from_printed_inputs(self):
        def values(task):
            return {field:item['value'] for field,item in AUDIT['tasks'][task].items()}
        w2, interest, form, payroll = [values(task) for task in
            ('extract_doc_001','extract_doc_002','extract_doc_004','extract_doc_005')]
        number = lambda data, key: D(data[key])
        self.assertEqual(number(w2,'wages') + number(w2,'retirement_deferral_D'), number(w2,'medicare_wages'))
        self.assertEqual(number(w2,'social_security_wages') * D('0.062'), number(w2,'social_security_tax_withheld'))
        regular = number(w2,'medicare_wages') * D('0.0145')
        additional = max(number(w2,'medicare_wages') - number(form,'line_5'), D(0)) * D('0.009')
        self.assertEqual(regular + additional, number(w2,'medicare_tax_withheld'))
        self.assertEqual(regular, number(form,'line_21'))
        self.assertEqual(number(form,'line_19') - number(form,'line_21'), number(form,'line_22'))
        # The PDF explicitly excludes RRTA; total line24 therefore equals line22.
        self.assertEqual(number(form,'line_22'), number(form,'line_24'))
        self.assertEqual(number(payroll,'sdi_taxable_wages') * number(payroll,'employee_sdi_rate') / D(100),
                         number(payroll,'employee_sdi_withheld'))
        self.assertEqual(number(payroll,'employee_sdi_withheld'), number(w2,'employee_sdi_withheld'))
        self.assertEqual(number(interest,'interest_income') * D('0.24'), number(interest,'federal_income_tax_withheld'))
        derived = {
            'w2_federal_withheld': number(w2,'federal_income_tax_withheld'),
            'form1099_federal_withheld': number(interest,'federal_income_tax_withheld'),
            'additional_medicare_withheld': number(form,'line_24'),
            'combined_federal_withholding_credit': number(w2,'federal_income_tax_withheld') + number(interest,'federal_income_tax_withheld') + number(form,'line_24'),
            'ca_income_tax_withheld': number(w2,'state_income_tax_withheld'),
            'unique_employee_sdi_withheld': number(w2,'employee_sdi_withheld'),
        }
        expected = json.loads((DATASET/'ground_truth/expected.json').read_text())['answers']['reconcile_case']['values']
        self.assertEqual({key:format(value, '.2f') for key,value in derived.items()}, expected)

    def test_dataset_checksum_receipt_has_no_stale_or_missing_files(self):
        recorded = {}
        for line in (DATASET/'SHA256SUMS').read_text().splitlines():
            digest, filename = line.split('  ',1)
            self.assertNotIn(filename, recorded)
            recorded[filename] = digest
            self.assertEqual(hashlib.sha256((DATASET/filename).read_bytes()).hexdigest(), digest, filename)
        actual = {p.relative_to(DATASET).as_posix() for p in DATASET.rglob('*')
                  if p.is_file() and p.name != 'SHA256SUMS' and '__pycache__' not in p.parts}
        self.assertEqual(set(recorded), actual)
