"""Read selected visible 2024 1040 fields; empty AcroForms are not the oracle."""

from decimal import Decimal
from pathlib import Path
import re

import pdfplumber
import pypdfium2

VERSION = 'prior-1040-visible-v1'
BOXES = (
    ('form_year', 'tax_year', 1, (295, 35, 353, 61), 'string',
     'The tax year printed in the Form 1040 heading; cite box tax_year on page 1.'),
    ('prior_adjusted_gross_income', '11', 1, (500, 665, 577, 680), 'money',
     'Adjusted gross income printed on line 11 of the 2024 return, page 1.'),
    ('prior_overpayment_elected_for_2025', '36', 2, (410, 347, 487, 362), 'money',
     'The amount elected on line 36 of the 2024 return for 2025 estimated tax, page 2. '
     'This is the election printed on the return, not evidence of a bank transaction.'),
)


def _normalize(text, kind):
    value = re.sub(r'\s+', '', text)
    if not value:
        return None
    if kind == 'string':
        if value != '2024':
            raise ValueError('Unexpected prior-return heading year')
        return value
    if not re.fullmatch(r'-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?', value):
        raise ValueError('Unexpected printed 1040 money field')
    return format(Decimal(value.replace(',', '')).quantize(Decimal('0.01')), '.2f')


def extract_document(path):
    path = Path(path)
    result = []
    with pdfplumber.open(path) as pdf, pypdfium2.PdfDocument(path) as independent:
        if len(pdf.pages) != 2 or len(independent) != 2:
            raise ValueError('Expected the audited two-page 2024 Form 1040')
        if 'adjusted gross income' not in pdf.pages[0].extract_text().lower():
            raise ValueError('Missing Form 1040 line 11 label')
        if 'your 2025 estimated tax' not in pdf.pages[1].extract_text():
            raise ValueError('Missing Form 1040 line 36 label')
        for field, box, page, bounds, kind, definition in BOXES:
            view = pdf.pages[page - 1]
            if (view.width, view.height) != (612, 792):
                raise ValueError('Unexpected 1040 page geometry')
            value = _normalize(view.crop(bounds).extract_text(), kind)
            other = independent[page - 1]
            text = other.get_textpage()
            try:
                x0, y0, x1, y1 = bounds
                corroborated = _normalize(text.get_text_bounded(x0, 792-y1, x1, 792-y0), kind)
            finally:
                text.close()
                other.close()
            if value != corroborated:
                raise ValueError(f'Independent readers disagree for {path.name} line {box}')
            if value is not None:
                result.append({'field': field, 'box': box, 'page': page, 'value': value,
                               'kind': kind, 'definition': definition, 'bbox': list(bounds),
                               'verification': {'method': 'pdfplumber-and-pdfium-visible-text',
                                                'review_version': VERSION}})
    if not result or result[0]['field'] != 'form_year':
        raise ValueError('Prior return has no readable heading')
    return result
