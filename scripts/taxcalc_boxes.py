"""Read audited money boxes from TaxCalc TY25 one-page PDF input forms.

This is a label-building utility for the fixed corpus, never an agent tool. It
reads the visible PDF text in independently checked boxes using pdfplumber and
PDFium. It does not use output.xml, compute tax, infer tax years, or turn blank
boxes into zero. Template, label, precision, and extraction disagreements fail
closed instead of silently producing a label.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import re

import pdfplumber
from pypdf import PdfReader
import pypdfium2

VERSION = "taxcalc-visible-boxes-v1"

# field, printed box, number bounds, label bounds, expected printed label.
# Coordinates are PDF points measured from the top left, page 1.
BOXES = {
    "w2": [
        ("wages", "1", (330, 72, 450, 84), (330, 61, 451, 71), "1 Wages tips other compensation"),
        ("federal_income_tax_withheld", "2", (450, 72, 577, 84), (450, 61, 577, 71), "2 Federal income tax withheld"),
        ("social_security_wages", "3", (330, 96, 450, 108), (330, 85, 451, 95), "3 Social security wages"),
        ("social_security_tax_withheld", "4", (450, 96, 577, 108), (450, 85, 577, 95), "4 Social security tax withheld"),
        ("medicare_wages_and_tips", "5", (330, 120, 450, 132), (330, 109, 451, 119), "5 Medicare wages and tips"),
        ("medicare_tax_withheld", "6", (450, 120, 577, 132), (450, 109, 577, 119), "6 Medicare tax withheld"),
    ],
    "1099g": [
        ("unemployment_compensation", "1", (294, 58, 393, 72), (294, 37, 393, 55), "1 Unemployment compensation"),
        ("state_local_income_tax_refunds", "2", (294, 94, 393, 108), (294, 73, 393, 92), "2 State or local income tax refunds credits or offsets"),
        ("federal_income_tax_withheld", "4", (394, 118, 495, 132), (394, 109, 495, 119), "4 Federal income tax withheld"),
    ],
    "1098t": [
        ("qualified_tuition_payments", "1", (294, 60, 393, 72), (294, 36, 393, 59), "1 Payments received for qualified tuition and related expenses"),
        ("scholarships_or_grants", "5", (394, 156, 495, 168), (394, 132, 495, 145), "5 Scholarships or grants"),
    ],
    "1099int": [
        ("interest_income", "1", (294, 94, 402, 108), (294, 73, 402, 87), "1 Interest income"),
        ("us_savings_treasury_interest", "3", (294, 166, 495, 180), (294, 145, 495, 159), "3 Interest on U S Savings Bonds and Treasury obligations"),
        ("federal_income_tax_withheld", "4", (294, 190, 393, 204), (294, 181, 393, 191), "4 Federal income tax withheld"),
        ("tax_exempt_interest", "8", (294, 250, 393, 264), (294, 229, 393, 243), "8 Tax exempt interest"),
    ],
    "1098e": [
        ("student_loan_interest", "1", (294, 120, 495, 134), (294, 109, 495, 120), "1 Student loan interest received by lender"),
    ],
    "1098": [
        ("mortgage_interest_received", "1", (294, 120, 495, 134), (294, 109, 495, 120), "1 Mortgage interest received from payer s borrower s"),
        ("outstanding_mortgage_principal", "2", (294, 150, 393, 164), (294, 133, 393, 150), "2 Outstanding mortgage principal"),
        ("mortgage_insurance_premiums", "5", (394, 180, 495, 194), (394, 163, 495, 181), "5 Mortgage insurance premiums"),
    ],
    "1099b": [
        ("proceeds", "1d", (294, 144, 393, 158), (294, 133, 393, 145), "1d Proceeds"),
        ("cost_or_other_basis", "1e", (394, 144, 495, 158), (394, 133, 495, 145), "1e Cost or other basis"),
        ("federal_income_tax_withheld", "4", (294, 228, 393, 242), (294, 217, 393, 229), "4 Federal income tax withheld"),
    ],
    "1099div": [
        ("ordinary_dividends", "1a", (294, 60, 393, 74), (294, 37, 393, 52), "1a Total ordinary dividends"),
        ("qualified_dividends", "1b", (294, 96, 393, 110), (294, 73, 393, 87), "1b Qualified dividends"),
        ("capital_gain_distributions", "2a", (294, 120, 393, 134), (294, 109, 393, 120), "2a Total capital gain distr"),
        ("federal_income_tax_withheld", "4", (394, 192, 495, 206), (394, 181, 495, 192), "4 Federal income tax withheld"),
    ],
    "1099r": [
        ("gross_distribution", "1", (294, 58, 393, 72), (294, 37, 393, 52), "1 Gross distribution"),
        ("taxable_amount", "2a", (294, 94, 393, 108), (294, 73, 393, 87), "2a Taxable amount"),
        ("federal_income_tax_withheld", "4", (394, 166, 495, 180), (394, 133, 495, 155), "4 Federal income tax withheld"),
    ],
    "1099misc": [
        ("rents", "1", (294, 60, 393, 74), (294, 37, 393, 52), "1 Rents"),
        ("royalties", "2", (294, 96, 393, 110), (294, 73, 393, 87), "2 Royalties"),
        ("other_income", "3", (294, 120, 393, 134), (294, 109, 393, 120), "3 Other income"),
        ("federal_income_tax_withheld", "4", (394, 120, 495, 134), (394, 109, 495, 120), "4 Federal income tax withheld"),
    ],
    "w2g": [
        ("reportable_winnings", "1", (294, 60, 393, 74), (294, 37, 393, 51), "1 Reportable winnings"),
        ("federal_income_tax_withheld", "4", (394, 84, 495, 98), (394, 73, 495, 84), "4 Federal income tax withheld"),
    ],
    "1099sa": [
        ("gross_distribution", "1", (294, 120, 393, 134), (294, 109, 393, 120), "1 Gross distribution"),
        ("earnings_on_excess_contributions", "2", (394, 120, 495, 134), (394, 109, 495, 120), "2 Earnings on excess cont"),
    ],
    "1099k": [
        ("gross_payment_transactions", "1a", (294, 108, 393, 122), (294, 85, 393, 108), "1a Gross amount of payment card third party network transactions"),
        ("federal_income_tax_withheld", "4", (394, 168, 495, 182), (394, 151, 495, 168), "4 Federal income tax withheld"),
    ],
    "1099nec": [
        ("nonemployee_compensation", "1", (294, 120, 495, 134), (294, 109, 495, 120), "1 Nonemployee compensation"),
        ("federal_income_tax_withheld", "4", (294, 192, 495, 206), (294, 181, 495, 192), "4 Federal income tax withheld"),
    ],
}
FORM_NAMES = {family: family.upper().replace("1099", "1099-").replace("1098", "1098-").replace("W2", "W-2") for family in BOXES}
FORM_NAMES["1098"] = "1098"


def _normal_label(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _money(text: str, context: str) -> str | None:
    value = re.sub(r"\s+", "", text).replace("$", "")
    if not value:
        return None
    if not re.fullmatch(r"-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?", value):
        raise ValueError(f"Unexpected numeric text in {context}")
    return format(Decimal(value.replace(",", "")).quantize(Decimal("0.01")), ".2f")


def extract_document(path: str | Path) -> list[dict]:
    """Return only explicitly printed amounts in the audited boxes.

    Both readers must agree even for omitted blank boxes. This utility is bound
    to these observed TaxCalc templates; changed labels/layout fail validation.
    It intentionally does not infer the document's tax year or other money boxes.
    """
    path = Path(path)
    family = path.stem.split("_")[0]
    if family not in BOXES:
        raise ValueError(f"Unsupported one-page TaxCalc form family: {family}")
    reader = PdfReader(path)
    if len(reader.pages) != 1 or reader.is_encrypted:
        raise ValueError("Expected one unencrypted TaxCalc PDF page")
    page = reader.pages[0]
    if abs(float(page.mediabox.width) - 612) > 0.05 or abs(float(page.mediabox.height) - 792) > 0.05 or page.rotation:
        raise ValueError("Unexpected TaxCalc PDF page dimensions or rotation")
    full_text = page.extract_text()
    if _normal_label(FORM_NAMES[family]) not in _normal_label(full_text):
        raise ValueError(f"Printed form title does not match {family}")
    result = []
    with pdfplumber.open(path) as pdf, pypdfium2.PdfDocument(path) as pdfium:
        visible = pdf.pages[0]
        pdfium_page = pdfium[0]
        pdfium_text = pdfium_page.get_textpage()
        for field, box, bbox, label_bbox, expected_label in BOXES[family]:
            context = f"{path.name} box {box}"
            label_text = visible.crop(label_bbox).extract_text() or ""
            if _normal_label(expected_label) not in _normal_label(label_text):
                raise ValueError(f"Printed box label mismatch in {context}")
            plumber_value = _money(visible.crop(bbox).extract_text() or "", context)
            x0, top, x1, bottom = bbox
            page_height = float(page.mediabox.height)
            pdfium_raw = pdfium_text.get_text_bounded(x0, page_height - bottom, x1, page_height - top)
            pdfium_value = _money(pdfium_raw, context)
            if plumber_value != pdfium_value:
                raise ValueError(f"Independent PDF readers disagree in {context}")
            if plumber_value is None:
                continue
            result.append({
                "field": field, "box": box, "page": 1, "value": plumber_value,
                "kind": "money", "bbox": list(bbox),
                "verification": {
                    "method": VERSION,
                    "numeric_readers": ["pdfplumber_box", "pdfium_bounded_text"],
                    "printed_label": expected_label,
                    "label_bbox": list(label_bbox),
                    "blank_policy": "omit_unprinted_box; explicit_zero_preserved",
                    "xml_used": False,
                },
            })
    if not result:
        raise ValueError(f"No explicit amount found in selected boxes of {path.name}")
    return result
