"""Reviewed extraction labels for five immutable synthetic 2010 W-2 images.

These are transcription labels, not a fiscal-calculation oracle. Each JPG has
two equivalent copies of one statement. Boxes refer to either copy; state and
local rows are ordered top to bottom within a copy. Source images are unchanged.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


TAX_YEAR = 2010
REVIEW_VERSION = "fake-w2-visual-v1"

# field, canonical evidence box, public instruction
_MONEY_FIELDS = (
    ("box_1_wages", "1", "Read box 1, Wages, tips, other compensation."),
    ("box_2_federal_tax_withheld", "2", "Read box 2, Federal income tax withheld."),
    ("box_3_social_security_wages", "3", "Read box 3, Social security wages."),
    ("box_4_social_security_tax_withheld", "4", "Read box 4, Social security tax withheld."),
    ("box_5_medicare_wages", "5", "Read box 5, Medicare wages and tips."),
    ("box_6_medicare_tax_withheld", "6", "Read box 6, Medicare tax withheld."),
    ("box_7_social_security_tips", "7", "Read box 7, Social security tips."),
    ("box_8_allocated_tips", "8", "Read box 8, Allocated tips."),
    ("box_10_dependent_care_benefits", "10", "Read box 10, Dependent care benefits."),
    ("box_11_nonqualified_plans", "11", "Read box 11, Nonqualified plans."),
    ("box_12a_value", "12:a", "Read the amount in box 12a, ignoring its separate code letter; a blank code does not make the amount blank."),
    ("box_12b_value", "12:b", "Read the amount in box 12b, ignoring its separate code letter; a blank code does not make the amount blank."),
    ("box_12c_value", "12:c", "Read the amount in box 12c, ignoring its separate code letter; a blank code does not make the amount blank."),
    ("box_12d_value", "12:d", "Read the amount in box 12d, ignoring its separate code letter; a blank code does not make the amount blank."),
    ("box_16_first_state_wages", "16:first", "Read State wages, tips, etc. in box 16, first (upper) state row within one copy."),
    ("box_17_first_state_income_tax", "17:first", "Read State income tax in box 17, first (upper) state row within one copy."),
    ("box_18_first_local_wages", "18:first", "Read Local wages, tips, etc. in box 18, first (upper) local row within one copy."),
    ("box_19_first_local_income_tax", "19:first", "Read Local income tax in box 19, first (upper) local row within one copy."),
    ("box_16_second_state_wages", "16:second", "Read State wages, tips, etc. in box 16, second (lower) state row within one copy."),
    ("box_17_second_state_income_tax", "17:second", "Read State income tax in box 17, second (lower) state row within one copy."),
    ("box_18_second_local_wages", "18:second", "Read Local wages, tips, etc. in box 18, second (lower) local row within one copy."),
    ("box_19_second_local_income_tax", "19:second", "Read Local income tax in box 19, second (lower) local row within one copy."),
)
_BOOLEAN_FIELDS = (
    ("box_13_statutory_employee", "13:statutory", "Read the Statutory employee checkbox in box 13; checked is true and unchecked is false."),
    ("box_13_retirement_plan", "13:retirement", "Read the Retirement plan checkbox in box 13; checked is true and unchecked is false."),
    ("box_13_third_party_sick_pay", "13:sick_pay", "Read the Third-party sick pay checkbox in box 13; checked is true and unchecked is false."),
)

# SHA-256 of the visually inspected image, 22 monetary transcriptions in the
# order above, and three visually inspected checkboxes in the order above.
_REVIEWED = {
    "test_000.jpg": (
        "30860368955a641c36af4459cb7d12e63e403641e32dc62abe73fb81f14d2594",
        ("126589.34", "43873.99", "122867.85", "9399.39", "114182.15", "3311.28", "122867.85", "114182.15", "219.00", "158.00", "9090.00", "459.00", "275.00", "688.00", "68442.97", "4761.03", "101209.95", "14120.87", "66147.70", "6996.33", "125139.92", "23035.86"),
        (True, False, True),
    ),
    "test_001.jpg": (
        "6965dbdfb974ca9df21abe984462bae2c939bec3a2b082cacb7c9b43321725f7",
        ("227657.54", "31123.05", "259683.15", "19865.76", "236012.23", "6844.35", "259683.15", "236012.23", "119.00", "162.00", "7753.00", "120.00", "646.00", "193.00", "103716.79", "9225.02", "245997.12", "45335.02", "106130.51", "8013.50", "217928.82", "43110.37"),
        (True, False, False),
    ),
    "test_002.jpg": (
        "b193431f917d9df21e0861e13c921657beaf86ab971367174bcc8ba92fbc191b",
        ("42676.35", "8821.70", "36929.43", "2825.10", "49701.17", "1441.33", "36929.43", "49701.17", "175.00", "166.00", "6028.00", "957.00", "817.00", "967.00", "19626.97", "2042.90", "46921.40", "4426.98", "19536.53", "1560.29", "31643.55", "7340.23"),
        (True, False, False),
    ),
    "test_003.jpg": (
        "5eb34d23bbc0c335019d6ab759a4188aea39574c9018446facf587d7e8fb7159",
        ("202723.87", "50947.95", "204210.14", "15622.08", "236402.83", "6855.68", "204210.14", "236402.83", "296.00", "195.00", "9137.00", "113.00", "349.00", "497.00", "99786.79", "9868.26", "148119.75", "28078.70", "95094.49", "8443.35", "179166.91", "21202.36"),
        (True, True, False),
    ),
    "test_004.jpg": (
        "d31c23485803f3587b537baecd4b270448a04c607a88f0dd6e1b819747f33a95",
        ("201416.42", "43467.16", "245315.32", "18766.62", "201036.03", "5830.04", "245315.32", "201036.03", "161.00", "115.00", "8474.00", "450.00", "560.00", "737.00", "101013.80", "8956.86", "224285.01", "32263.25", "94098.77", "7081.58", "154189.89", "28296.77"),
        (False, False, False),
    ),
}


def extract_document(image_path: str | Path) -> list[dict]:
    """Return private labels only for a byte-identical, reviewed source image.

    ``definition`` is safe for the public task; ``value`` and ``verification``
    belong exclusively to the evaluator dataset and must never reach a harness.
    """
    path = Path(image_path)
    if path.name not in _REVIEWED:
        raise ValueError(f"No visual review exists for image {path.name!r}")
    expected_digest, money, checkboxes = _REVIEWED[path.name]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected_digest:
        raise ValueError(f"Image {path.name!r} changed since visual review")
    labels = []
    for specs, values, kind in (
        (_MONEY_FIELDS, money, "money"),
        (_BOOLEAN_FIELDS, checkboxes, "boolean"),
    ):
        for (field, box, definition), value in zip(specs, values, strict=True):
            labels.append({
                "field": field,
                "box": box,
                "page": 1,
                "value": value,
                "kind": kind,
                "definition": definition,
                "verification": {
                    "method": "visual_transcription_compared_to_source_json",
                    "review_version": REVIEW_VERSION,
                    "source_sha256": digest,
                    "tax_year": TAX_YEAR,
                    "copy_policy": "Either identical copy; never sum duplicate copies",
                },
            })
    return labels
