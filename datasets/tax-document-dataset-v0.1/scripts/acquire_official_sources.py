"""Acquire public IRS source templates. Blank forms are NOT labeled eval cases.

Run with Python 3 + pypdf. Saves original bytes, hashes and inspection metadata.
Failed annual URLs are retained as failures, never relabeled as another year.
"""
import concurrent.futures
import datetime
import hashlib
import io
import json
import pathlib
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEST = ROOT / 'official'
FORMS = {
    'W2': 'fw2', '1099INT': 'f1099int', '1099DIV': 'f1099div',
    '1099B': 'f1099b', '1099R': 'f1099r', '1099NEC': 'f1099nec',
    '1099MISC': 'f1099msc', '1099G': 'f1099g',
    'K1_1065': 'f1065sk1', 'K1_1120S': 'f1120ssk',
    'K1_1041': 'f1041sk1', '8959': 'f8959', '1040': 'f1040',
    'ScheduleA': 'f1040sa', 'Schedule1': 'f1040s1',
    'Schedule2': 'f1040s2', 'Schedule3': 'f1040s3',
    '6251_AMT': 'f6251', '1116_FTC': 'f1116',
    '1040ES': 'f1040es', '4868_extension': 'f4868',
}
SOURCES = [dict(source_id=f'irs_{name}_2025', form_family=name, requested_year=2025,
    role='blank_template', url=f'https://www.irs.gov/pub/irs-prior/{stem}--2025.pdf')
    for name, stem in FORMS.items()]
SOURCES += [dict(source_id=f'irs_{name}_2024', form_family=name, requested_year=2024,
    role='blank_template', url=f'https://www.irs.gov/pub/irs-prior/{FORMS[name]}--2024.pdf')
    for name in ('W2','1040','ScheduleA','6251_AMT','1116_FTC','8959','1099G')]
SOURCES += [
    dict(source_id='irs_W2c_current_revision', form_family='W2c', requested_year=None,
         role='blank_template_continuous_use', url='https://www.irs.gov/pub/irs-pdf/fw2c.pdf'),
    dict(source_id='irs_VITA_6744_current', form_family='educational_casebook', requested_year=None,
         role='educational_examples_not_machine_labeled', url='https://www.irs.gov/pub/irs-pdf/f6744.pdf'),
]

def acquire(source):
    from pypdf import PdfReader
    rec = dict(source, accessed_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    try:
        request = urllib.request.Request(source['url'], headers={'User-Agent': 'TaxDatasetResearch/0.1'})
        with urllib.request.urlopen(request, timeout=35) as response:
            data = response.read()
            rec.update(http_status=response.status, resolved_url=response.url)
        if not data.startswith(b'%PDF-'):
            raise ValueError('Response is not a PDF')
        file = DEST / (source['source_id'] + '.pdf')
        file.write_bytes(data)
        reader = PdfReader(io.BytesIO(data))
        fields = reader.get_fields() or {}
        rec.update(status='downloaded_and_parsed', file=str(file.relative_to(ROOT)),
            bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
            pages=len(reader.pages), acroform_field_count=len(fields),
            first_page_excerpt=(reader.pages[0].extract_text() or '')[:650],
            ground_truth_status='none', source_year_requires_content_check=True)
        if fields:
            fieldfile = DEST / (source['source_id'] + '.fields.json')
            fieldfile.write_text(json.dumps({str(k): {'type': str(v.get('/FT','')),
                'label': str(v.get('/TU','')), 'value': str(v.get('/V',''))}
                for k,v in fields.items()}, indent=2))
    except Exception as exc:
        rec.update(status='unavailable_or_parse_failed', error=f'{type(exc).__name__}: {exc}')
    return rec

def main():
    DEST.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(acquire, SOURCES))
    (DEST / 'inventory.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(json.dumps({'requested': len(rows), 'downloaded': sum(r['status']=='downloaded_and_parsed' for r in rows),
        'failures': [{'id':r['source_id'],'error':r.get('error')} for r in rows if r['status']!='downloaded_and_parsed']}, indent=2))

if __name__ == '__main__':
    main()
