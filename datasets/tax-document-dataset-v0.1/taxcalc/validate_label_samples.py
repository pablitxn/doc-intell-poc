"""Check five PDF/XML pairs using visually located numeric boxes, not LLM labels."""
from pathlib import Path
import argparse
from decimal import Decimal
import json
import re
import xml.etree.ElementTree as ET
import pdfplumber

ROOT = Path(__file__).resolve().parent
CHECKS = [
    (case, "w2_1.pdf", "CAFormW2" if case.startswith("ty25-ca") else "IRSW2", {
        "box_1": ((330, 72, 450, 84), "WagesAmt"),
        "box_2": ((450, 72, 577, 84), "WithholdingAmt"),
    }) for case in ["ty25-us-001", "ty25-us-003", "ty25-us-005", "ty25-ca-001"]
] + [("ty25-us-010", "1099r_1.pdf", "IRS1099R", {
    "box_1": ((294, 57, 393, 71), "GrossDistributionAmt"),
    "box_2a": ((294, 93, 393, 108), "TaxableAmt"),
    "box_4": ((394, 165, 489, 180), "FederalIncomeTaxWithheldAmt"),
})]

def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    results = []
    for case, filename, tag, fields in CHECKS:
        case_path = ROOT / "download" / case
        tree = ET.parse(case_path / "output.xml")
        forms = [e for e in tree.iter() if e.tag.split("}")[-1] == tag]
        if len(forms) != 1:
            raise ValueError(f"Ambiguous XML form association in {case}: {len(forms)}")
        with pdfplumber.open(case_path / "input" / filename) as pdf:
            for field, (bbox, xml_tag) in fields.items():
                raw = pdf.pages[0].crop(bbox).extract_text()
                value = Decimal(re.sub(r"[^0-9.-]", "", raw))
                expected_nodes = [e for e in forms[0].iter() if e.tag.split("}")[-1] == xml_tag]
                if len(expected_nodes) != 1:
                    raise ValueError(f"Ambiguous field {case}: {xml_tag}")
                expected = Decimal(expected_nodes[0].text)
                results.append({"case_id":case,"pdf":filename,"page":1,"bbox_points_top_left":bbox,"pdf_field":field,"pdf_value":str(value),"xml_form":tag,"xml_tag":xml_tag,"xml_value":str(expected),"exact_match":value==expected})

    summary={"pairs_checked":len(CHECKS),"fields_checked":len(results),"exact_matches":sum(x["exact_match"] for x in results),"scope":"Only these numeric fields in these five document pairs are validated. Other XML fields remain label candidates; no page/box evidence is supplied upstream.","checks":results}
    (ROOT / "sample_label_validation.json").write_text(json.dumps(summary,indent=2))
    print({k:v for k,v in summary.items() if k!="checks"})
    return 0 if all(x["exact_match"] for x in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
