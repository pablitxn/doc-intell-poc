#!/usr/bin/env python3
"""Verify the acquired source snapshot locally; no network or model calls."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative):
    return json.loads((ROOT / relative).read_text(encoding='utf-8'))


def check_file(path, expected, algorithm='sha256'):
    if not path.is_file():
        raise AssertionError(f'Missing file: {path.relative_to(ROOT)}')
    raw = path.read_bytes()
    if algorithm == 'git':
        actual = hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest()
    else:
        actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise AssertionError(f'Hash mismatch: {path.relative_to(ROOT)}')


def verify(release=False):
    tax = read('taxcalc/manifest.json')
    assert len(tax) == 364
    for row in tax:
        p = ROOT / 'taxcalc/download' / row['path']
        check_file(p, row['sha256'])
        check_file(p, row['git_blob_sha'], 'git')
    cases = {r['case_id'] for r in tax}
    pdfs = [r for r in tax if r['path'].endswith('.pdf')]
    assert len(cases) == 50 and len(pdfs) == 264
    assert len(list((ROOT / 'taxcalc/download').rglob('output.xml'))) == 50
    official = read('official/inventory.json') + read('official/additional_inventory.json')
    available = [r for r in official if r['status'] == 'downloaded_and_parsed']
    assert len(available) == 39 and len(official) == 42
    for row in available:
        check_file(ROOT / row['file'], row['sha256'])
    extract = read('extractbench/tax_manifest.json')
    assert len(extract) == len({r['id'] for r in extract}) == 77
    smoke = read('fake_w2/manifest.json')
    assert len(smoke) == 5
    for row in smoke:
        check_file(ROOT / 'fake_w2' / row['image'], row['sha256'])
        read('fake_w2/' + row['ground_truth'])
    checked = 0
    if release:
        for line in (ROOT / 'SHA256SUMS').read_text().splitlines():
            digest, relative = line.split('  ', 1)
            check_file(ROOT / relative, digest)
            checked += 1
    return {
        'status': 'passed', 'taxcalc_cases': len(cases),
        'taxcalc_files_sha256_and_git_verified': len(tax),
        'taxcalc_input_pdfs': len(pdfs),
        'taxcalc_pages_from_audited_manifest': sum(r['pdf_pages'] for r in pdfs),
        'official_pdfs_sha256_verified': len(available),
        'official_failed_urls_recorded': len(official) - len(available),
        'extractbench_tax_tasks_manifest_only': len(extract),
        'fake_w2_image_label_pairs': len(smoke),
        'release_file_hashes_verified': checked,
        'scope': 'Integrity and inventory only. Does not certify tax labels or harness accuracy.'
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', action='store_true', help='Also check every SHA256SUMS entry')
    args = parser.parse_args()
    print(json.dumps(verify(args.release), indent=2))
