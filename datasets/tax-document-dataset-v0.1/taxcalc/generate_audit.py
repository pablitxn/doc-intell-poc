"""Audit actual downloaded bytes; never prints personal identifiers or case values."""
from pathlib import Path
import argparse
import collections
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
COMMIT = "8f89c2cf00a8906f4d896a02a2f45f9c9e85ae9b"
TREE = "521d2767436e9a6c9ce4ad9ce71443694afa3838"


def leaves(obj, path=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from leaves(value, path + "." + key)
    elif isinstance(obj, list):
        for value in obj:
            yield from leaves(value, path + "[]")
    else:
        yield path, obj


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    tree = json.loads((ROOT / "ty25_tree.json").read_text())
    files = [r for r in tree["tree"] if r["type"] == "blob"]
    manifest = []
    xml_form_cases = collections.defaultdict(set)
    json_key_cases = collections.defaultdict(set)
    json_nonzero_key_cases = collections.defaultdict(set)
    descriptions = collections.Counter()
    failures = []
    for row in files:
        rel = row["path"]
        file = ROOT / "download" / rel
        case = rel.split("/")[0]
        entry = {"path": rel, "case_id": case, "role": "input" if "/input/" in rel else "ground_truth_output", "source_url": f"https://github.com/column-tax/tax-calc-bench/blob/{COMMIT}/tax_calc_bench/ty25/test_data/{rel}", "git_blob_sha": row["sha"], "size_expected": row["size"]}
        manifest.append(entry)
        if not file.exists():
            entry["status"] = "missing"
            failures.append(rel)
            continue
        data = file.read_bytes()
        sha = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        entry.update({"status": "verified" if sha == row["sha"] else "hash_mismatch", "size_actual": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        if sha != row["sha"]:
            failures.append(rel)
        if file.suffix == ".pdf":
            reader = PdfReader(file)
            texts = [p.extract_text() or "" for p in reader.pages]
            entry.update({"family_from_filename": file.name.split("_")[0], "pdf_pages": len(reader.pages), "pdf_text_chars": sum(map(len, texts)), "acroform_fields": len(reader.get_fields() or {}), "years_in_text": sorted(set(re.findall(r"\b202[0-9]\b", "\n".join(texts))))})
        elif file.suffix == ".xml":
            root = ET.fromstring(data)
            tags = {e.tag.split("}")[-1] for e in root.iter()}
            forms = sorted(t for t in tags if re.match(r"IRS(?:\d|W2|1099)", t))
            entry["xml_form_tags"] = forms
            for form in forms:
                xml_form_cases[form].add(case)
            for e in root.iter():
                if e.tag.split("}")[-1] == "OtherDeductionsBenefitsGrp":
                    for c in e:
                        if c.tag.split("}")[-1] == "Desc":
                            descriptions[c.text] += 1
        elif file.suffix == ".json":
            obj = json.loads(data)
            keys = set()
            for k, v in leaves(obj):
                if re.search(r"(?i)k[-_]?1|8959|6251|schedulea|scha_|estimated_tax_payment|extension_payment|applied.*prior|applied_py|taxable.*refund|ptet|composite|sdi|sui|disability", k):
                    keys.add(k)
                    json_key_cases[k].add(case)
                    if k.endswith(".value") and v not in (0, "0", False, None, "", "false"):
                        json_nonzero_key_cases[k].add(case)
            entry["relevant_json_paths"] = sorted(keys)
    summary = {"repository": "column-tax/tax-calc-bench", "commit": COMMIT, "test_data_tree_sha": TREE, "tree_truncated": tree.get("truncated"), "expected_files": len(files), "verified_files": sum(r["status"] == "verified" for r in manifest), "failures": failures, "cases": len({r["case_id"] for r in manifest}), "pdf_count": sum(r["path"].endswith(".pdf") for r in manifest), "pdf_pages_downloaded": sum(r.get("pdf_pages", 0) for r in manifest), "pdf_family_counts": dict(collections.Counter(r.get("family_from_filename") for r in manifest if "family_from_filename" in r)), "case_regions": dict(collections.Counter(c.split("-")[1] for c in {r["case_id"] for r in manifest})), "xml_form_case_counts": {k: len(v) for k,v in sorted(xml_form_cases.items())}, "xml_form_cases": {k: sorted(v) for k,v in sorted(xml_form_cases.items())}, "input_json_relevant_key_case_counts": {k:len(v) for k,v in sorted(json_key_cases.items())}, "input_json_nonzero_relevant_key_case_counts": {k:len(v) for k,v in sorted(json_nonzero_key_cases.items())}, "w2_box14_output_description_counts": dict(descriptions)}
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (ROOT / "taxcalc_findings.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k:summary[k] for k in ("expected_files","verified_files","failures","cases","pdf_count","pdf_pages_downloaded","pdf_family_counts","xml_form_case_counts","w2_box14_output_description_counts")},indent=2))
