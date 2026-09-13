#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pypdf==6.10.0", "pdfplumber==0.11.9", "pypdfium2==5.13.0", "Pillow==12.3.0"]
# ///
"""Build or verify a deterministic runnable projection of the acquired sources.

This process belongs to the evaluator. It never calls a harness or model, never
modifies the acquisition kit, and never mounts its labels in a worker.
"""

from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from evals.datasets.loader import load_examples, read_json
from scripts.taxcalc_boxes import extract_document as taxcalc_fields
from scripts.prior_1040_labels import extract_document as prior_fields
from scripts.fake_w2_labels import extract_document as fake_fields

SOURCE = REPO / 'datasets/tax-document-dataset-v0.1'
DESTINATION = REPO / 'datasets/tax-document-eval-v1'
VERSION = 'tax-document-projection-v1'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def verify_source(source):
    """Verify the release and its exact file membership before deriving labels."""
    source = source.resolve()
    names = set()
    for line in (source / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        relative = PurePosixPath(name)
        if (relative.is_absolute() or '..' in relative.parts or '\\' in name
                or name in names or not re.fullmatch(r'[a-f0-9]{64}', digest)):
            raise ValueError('Invalid or duplicated source checksum entry')
        path = (source / name).resolve()
        if not path.is_relative_to(source) or not path.is_file() or sha(path) != digest:
            raise ValueError(f'Source checksum mismatch: {name}')
        names.add(name)
    actual = {p.relative_to(source).as_posix() for p in source.rglob('*')
              if p.is_file() and p.name != '.DS_Store' and '__pycache__' not in p.parts}
    if actual != names | {'SHA256SUMS'}:
        raise ValueError('Source release has missing or unmanifested files')
    return {'release_files_verified': len(names), 'sha256sums_sha256': sha(source / 'SHA256SUMS')}


def structured_fields(path):
    """Only declared payment amounts/flags, with literal JSON-pointer evidence.

    These observations are not a claim that a payment settled or a return was
    filed. Missing nodes remain absent; contradictory flags are preserved.
    """
    document = read_json(path)
    roots = {
        'federal': ('input', 'return_data', 'irs1040'),
        'federal_schedule3': ('input', 'return_data', 'irs1040_schedule3'),
        'ca': ('input', 'ca_tax_return', 'ca_return_data', 'ca_form540', 'ca_payments'),
        'il': ('input', 'il_tax_return', 'il_return_data', 'il_formIL1040'),
        'ny': ('input', 'ny_tax_return', 'ny_return_data', 'ny_process_bo', 'ny_composition',
               'ny_composition_forms', 'form_IT201'),
        'va': ('input', 'va_tax_return', 'va_return_data', 'va_form760_cg'),
    }
    money = {'estimated_tax_payment_1', 'estimated_tax_payment_2', 'estimated_tax_payment_3',
             'estimated_tax_payment_4', 'estimated_payment_1', 'estimated_payment_2',
             'estimated_payment_3', 'estimated_payment_4', 'estimated_payment_q1',
             'estimated_payment_q2', 'estimated_payment_q3', 'estimated_payment_q4',
             'extension_payment', 'applied_from_prior_year'}
    flags = {'paid_estimated_tax_pmts', 'requested_extension', 'paid_extension',
             'state_extension_requested', 'applied_py_refund', 'applied_refund_from_prior_year'}
    result = []
    for jurisdiction, keys in roots.items():
        node = document
        for key in keys:
            node = node.get(key, {}) if isinstance(node, dict) else {}
        if not isinstance(node, dict):
            raise ValueError('Unexpected structured payment section')
        for key in sorted(set(node) & (money | flags)):
            observed = node[key]
            if not isinstance(observed, dict) or 'value' not in observed or 'label' not in observed:
                raise ValueError('Structured payment requires explicit value and label')
            value = observed['value']
            if value is None:
                continue
            kind = 'boolean' if key in flags else 'money'
            if kind == 'boolean':
                if type(value) is not bool:
                    raise ValueError('Payment flag is not a JSON boolean')
            else:
                if type(value) not in (int, float, str) or isinstance(value, str) and not value.strip():
                    raise ValueError('Payment amount is not a decimal')
                amount = Decimal(str(value))
                if not amount.is_finite() or amount != amount.quantize(Decimal('0.01')):
                    raise ValueError('Payment amount cannot be represented exactly in cents')
                value = format(amount, '.2f')
            pointer = '/' + '/'.join((*keys, key, 'value'))
            result.append({'field': f'{jurisdiction}_{key}', 'box': pointer, 'page': 1,
                           'kind': kind, 'value': value,
                           'definition': f'Read the declared {jurisdiction} value at JSON pointer {pointer}. '
                                         f'Source label: {observed["label"]}.',
                           'verification': {'method': 'literal-json-pointer', 'pointer': pointer}})
    if not result:
        raise ValueError(f'No selected declared payment data in {path.parent.parent.name}')
    return result


def source_groups(documents):
    """Connected case groups share identical source bytes; never split them later."""
    cases = sorted({d['case_id'] for d in documents})
    parent = {case: case for case in cases}
    def find(case):
        while parent[case] != case:
            case = parent[case]
        return case
    by_hash = defaultdict(list)
    for doc in documents:
        by_hash[doc['sha256']].append(doc)
    for group in by_hash.values():
        for doc in group[1:]:
            a, b = sorted((find(group[0]['case_id']), find(doc['case_id'])))
            parent[b] = a
    return {case: f'source-group-{find(case)}' for case in cases}, [
        {'sha256': digest, 'document_ids': [d['document_id'] for d in group]}
        for digest, group in sorted(by_hash.items()) if len(group) > 1]


def build(source, destination):
    verification = verify_source(source)
    if destination.exists():
        raise ValueError('Destination already exists; use --check or a separate --output')
    destination.mkdir(parents=True)
    manifest, tasks, answers, types, provenance = [], [], {}, {}, {}
    absent_aggregates = []
    case_documents = defaultdict(list)
    extracted = {}

    def add_document(path, case, year, family, relative, fields, pages):
        doc_id = re.sub('[^a-zA-Z0-9_]+', '_', relative.rsplit('.', 1)[0])
        local = f'inputs/{relative}'
        target = destination / local
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        metadata = {'document_id': doc_id, 'path': local, 'sha256': sha(path), 'page_count': pages,
                    'case_id': case, 'tax_year': year, 'family': family,
                    'source_path': path.relative_to(source).as_posix()}
        manifest.append(metadata)
        case_documents[case].append(metadata)
        extracted[doc_id] = fields
        tid = 'extract_' + doc_id
        descriptions = '\n'.join(f'- {f["field"]}: {f.get("definition", f["field"].replace("_", " "))} '
                                  f'Use evidence.box={json.dumps(f["box"])} on page {f["page"]}.' for f in fields)
        instruction = ('Extract exactly the requested observations from this document. '
                       'The following canonical evidence identifiers are part of this task. '
                       'Use the printed amount without recalculating tax. A printed zero is zero; '
                       'a blank is not zero. Do not repair inconsistent source facts.\n' + descriptions)
        if family == 'declared_payments':
            instruction += ('\nThis JSON file is page 1 for citation purposes; evidence.box is the exact '
                            'JSON pointer listed above. Extract declared amounts and flags separately. '
                            'They do not establish payment settlement, bank processing or tax eligibility.')
        elif family == 'fake_w2':
            instruction += ('\nThe image shows Copy B and Copy C of the same 2010 W-2. Read the upper '
                            'Copy B once. :first and :second mean the first and second printed state/local '
                            'rows within that copy, not the second copy. :a/:b/:c/:d identify rows of box 12.')
        elif family != '1040':
            instruction += ('\nThe explicit case context assigns these inputs to tax year 2025; '
                            'do not infer a calendar year from a template revision date.')
        tasks.append({'task_id': tid, 'case_id': case, 'tax_year': year,
                      'documents': [local], 'instruction': instruction,
                      'fields': {f['field']: f['kind'] for f in fields}})
        types[tid] = tasks[-1]['fields']
        answers[tid] = {'values': {f['field']: f['value'] for f in fields}, 'evidence': {
            f['field']: [{'document_id': doc_id, 'page': f['page'], 'box': f['box']}] for f in fields}}
        provenance[tid] = {f['field']: {**f['verification'], 'source_path': metadata['source_path'],
                                      'source_sha256': metadata['sha256'], 'page': f['page'],
                                      'box': f['box'], **({'bbox_points_top_left': f['bbox']} if 'bbox' in f else {})}
                           for f in fields}

    upstream = source / 'taxcalc/download'
    for case_dir in sorted(upstream.iterdir()):
        if not case_dir.is_dir():
            continue
        for path in sorted((case_dir / 'input').iterdir()):
            family = path.stem.split('_')[0]
            if path.suffix == '.pdf':
                fields = prior_fields(path) if family == '1040' else taxcalc_fields(path)
                add_document(path, case_dir.name, 2024 if family == '1040' else 2025, family,
                             f'taxcalc/{case_dir.name}/{path.name}', fields, 2 if family == '1040' else 1)
            elif path.name == 'remaining_data.json':
                add_document(path, case_dir.name, 2025, 'declared_payments',
                             f'taxcalc/{case_dir.name}/{path.name}', structured_fields(path), 1)
            else:
                raise ValueError(f'Unclassified TaxCalc input: {path.name}')
    for path in sorted((source / 'fake_w2').glob('*.jpg')):
        add_document(path, 'fake-w2-' + path.stem, 2010, 'fake_w2',
                     f'fake_w2/{path.name}', fake_fields(path), 1)

    for case, documents in sorted(case_documents.items()):
        if not case.startswith('ty25-'):
            continue
        fields = {}
        for name, accepted in (
            ('w2_wages_total', lambda d, f: d['family'] == 'w2' and f['field'] == 'wages'),
            ('w2_federal_withholding_total', lambda d, f: d['family'] == 'w2' and f['field'] == 'federal_income_tax_withheld'),
            ('documented_federal_withholding_total', lambda d, f: d['family'] != 'fake_w2' and f['field'] == 'federal_income_tax_withheld'),
        ):
            contributors = [(d, f) for d in documents for f in extracted[d['document_id']] if accepted(d, f)]
            if not contributors:
                absent_aggregates.append({'case_id': case, 'field': name,
                                          'reason': 'No explicitly printed contributing amount; not inferred as zero'})
                continue
            value = sum((Decimal(f['value']) for _, f in contributors), Decimal(0))
            # Independent integer-cents arithmetic catches aggregation mistakes.
            cents = sum(int(f['value'].replace('.', '')) for _, f in contributors)
            if value * 100 != cents:
                raise ValueError('Independent reconciliation arithmetic disagrees')
            fields[name] = (format(value, '.2f'), contributors)
        tid = 'reconcile_' + case.replace('-', '_')
        if not fields:
            continue
        instruction = (
            'Reconcile the explicitly printed income-tax withholding in this 2025 case. '
            'Report only the totals listed in Requested fields; a total with no explicitly printed '
            'contribution is outside this task and must not be added as zero. '
            'w2_wages_total is the sum of W-2 box 1; w2_federal_withholding_total is the sum of W-2 box 2. '
            'documented_federal_withholding_total adds W-2 box 2 and federal income tax withholding in '
            'W-2G and Forms 1099-B/DIV/G/INT/K/MISC/NEC/R box 4. Count each listed document once. '
            'Include printed zero amounts and cite every contributing populated box, including zeros. '
            'Do not include a blank box in the evidence set; this is a sum of observed amounts only, '
            'not a claim that an unreported amount is zero. Cite only the applicable document, page and box. '
            'Exclude Social Security/Medicare tax, 1099-SA box 4 (fair market value), all 1098 forms, '
            'the 2024 Form 1040, and amounts or flags from remaining_data.json. '
            'Do not calculate tax liability, Additional Medicare Tax or total tax payments. '
            'The 2024 return and JSON are context/distractors, not new withholding contributions.')
        tasks.append({'task_id': tid, 'case_id': case, 'tax_year': 2025, 'instruction': instruction,
                      'documents': [d['path'] for d in documents], 'fields': {key: 'money' for key in fields}})
        types[tid] = tasks[-1]['fields']
        answers[tid] = {'values': {key: value for key, (value, _) in fields.items()}, 'evidence': {
            key: [{'document_id': d['document_id'], 'page': f['page'], 'box': f['box']} for d, f in contributors]
            for key, (_, contributors) in fields.items()}}
        provenance[tid] = {key: {'method': 'decimal-sum-and-independent-integer-cents',
                                'contributors': [{'task_id': 'extract_' + d['document_id'], 'field': f['field']}
                                                 for d, f in contributors]}
                           for key, (_, contributors) in fields.items()}

    groups, duplicates = source_groups(manifest)
    for document in manifest:
        document['source_group_id'] = groups[document['case_id']]
    for task in tasks:
        task['source_group_id'] = groups[task['case_id']]
        task['split'] = 'development'
    write(destination / 'tasks.json', {'case_id': 'TAX-DOCUMENT-COLLECTION', 'tax_year': 2025,
                                     'dataset_format': VERSION, 'tasks': tasks})
    write(destination / 'manifest.json', manifest)
    write(destination / 'ground_truth/expected.json', {'answers': answers})
    write(destination / 'ground_truth/field_types.json', types)
    write(destination / 'ground_truth/provenance.json', provenance)
    examples, dataset_version = load_examples(destination)
    values = [v for answer in answers.values() for v in answer['values'].values()]
    amount_values = [v for tid, answer in answers.items() for key, v in answer['values'].items() if types[tid][key] == 'money']
    report = {
        'preparation_version': VERSION, 'source': source.name, **verification,
        'dataset_version': dataset_version, 'model_calls': 0,
        'documents': len(manifest), 'cases': len(groups), 'tasks': len(examples), 'fields': len(values),
        'extraction_tasks': len(manifest), 'reconciliation_tasks': len(tasks) - len(manifest),
        'document_families': dict(sorted(Counter(d['family'] for d in manifest).items())),
        'document_formats': dict(sorted(Counter(Path(d['path']).suffix for d in manifest).items())),
        'field_types': dict(sorted(Counter(kind for fields in types.values() for kind in fields.values()).items())),
        'monetary_fields': len(amount_values), 'printed_or_declared_zero_amounts': sum(Decimal(v) == 0 for v in amount_values),
        'source_groups': len(set(groups.values())), 'duplicate_content_groups': duplicates,
        'unobservable_aggregate_fields': absent_aggregates,
        'split_policy': 'All tasks are development; no held-out quality claim. Keep source groups together for future splits.',
        'reference_scope': 'Selected observable fields and explicitly defined withholding sums. No full tax-return or leadsheet oracle.',
        'source_exclusions': {'official_pdfs': {'count': 39, 'reason': '37 blank templates and 2 reference documents, not populated labelled cases'},
                              'taxcalc_output_xml': {'count': 50, 'reason': 'Candidate computed tax outputs; not extraction or general fiscal ground truth'},
                              'extractbench_manifest_tasks': {'count': 77, 'reason': 'PDF and ground-truth files not acquired'},
                              'fields_outside_projection': 'Blank/unreadable/unselected fields are not silently treated as zero or counted as correct.'},
        'preparation_source_sha256': {f'scripts/{name}': sha(REPO / 'scripts' / name) for name in
                                     ('prepare_full_dataset.py', 'taxcalc_boxes.py', 'prior_1040_labels.py', 'fake_w2_labels.py')},
    }
    write(destination / 'audit.json', report)
    return report


def check(source, destination):
    with TemporaryDirectory(prefix='doc-intell-verify-') as temporary:
        rebuilt = Path(temporary) / destination.name
        report = build(source, rebuilt)
        generated = {p.relative_to(rebuilt) for p in rebuilt.rglob('*') if p.is_file()}
        actual = {p.relative_to(destination) for p in destination.rglob('*') if p.is_file() and p.name != '.DS_Store'}
        if generated != actual:
            raise ValueError('Prepared dataset membership differs from reproducible output')
        mismatches = [p.as_posix() for p in sorted(generated) if sha(rebuilt / p) != sha(destination / p)]
        if mismatches:
            raise ValueError(f'Prepared dataset bytes differ: {", ".join(mismatches[:8])}')
        return {**report, 'reproduction': 'byte-for-byte-identical'}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=DESTINATION)
    parser.add_argument('--check', action='store_true', help='Rebuild in a temporary folder and compare every byte')
    args = parser.parse_args()
    source, destination = args.source.resolve(), args.output.resolve()
    if destination == source or destination.is_relative_to(source):
        parser.error('Output must be outside the immutable source kit')
    try:
        if args.check:
            result = check(source, destination)
        else:
            if destination.exists():
                raise ValueError('Destination already exists; use --check or a separate --output')
            destination.parent.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(prefix='.prepare-doc-intell-', dir=destination.parent) as temporary:
                staging = Path(temporary) / destination.name
                result = build(source, staging)
                staging.rename(destination)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Dataset preparation failed: {exc}\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'duplicate_content_groups'}, indent=2))


if __name__ == '__main__':
    main()
