# ExtractBench and Fake W-2 audit — 2026-09-12

## What was actually inspected

All 370 ExtractBench JSONL records were downloaded and parsed at revision `f6180e917a050a84582e6366cff85b7dc1e84e58`. SHA-256 checks match the Hugging Face files. The local `audit.py` reproduces the inventory. Four small PDFs were initially fetched (W-2, partnership K-1, S-corp K-1 and Fidelity brokerage sample); Pershing sample fetched separately. The audit did **not** inspect every PDF page, so it establishes labelled schema coverage rather than all incidental forms inside tax-return packets.

Fake W-2: publisher metadata, Kaggle upstream metadata, HF split metadata and five test images/JSON labels were inspected/downloaded. The first downloaded test image was visually checked.

## ExtractBench tax coverage

| Dedicated schema | Records | Meaning and limitations |
|---|---:|---|
| W-2 | 20 | Tax year 2020. All originate in one source collection, indexed as four rows per source page. Not 20 layout families. |
| K-1 (1065) | 10 | Seven distinct expected-output objects; three exact GT repeats. Two public-case source prefixes. Group related source material when splitting. |
| K-1 (1120-S) | 9 | Nine distinct GT objects, one public-case prefix shared with some 1065s. |
| 1099-B historical consolidated-page schema | 17 | Fourteen extracted pages from one source and three from another, all 2009. Not 17 independent statements. |
| 1040 + Schedules 1/2/3 schema | 18 | 2021:5; 2022:5; 2023:4; 2024:4. Five source-person groups based on document names; years must stay together in holdout splitting. |
| BrokerageConsolidated1099 | 3 | Fidelity sample, Pershing sample and Schwab sample. Pershing and Schwab GT have non-null DIV, INT, OID and MISC sections plus B; Fidelity sample has B and null other sections. This is two examples of each additional section, not broad subtype coverage. |
| **Total target tax-schema records** | **77** | Single-document extraction tasks, not 77 coherent client dossiers. |

No dedicated labelled schema for W-2c, 1099-R/NEC/G, K-1 1041, Form 8959, SUI/SDI/DI, state K-1/PTET/composite withholding, tax payment confirmations or state-refund workflow was found among the 370 schemas. Some extra forms could be unlabelled pages within the 1040 packets; this was not assessed page by page.

Each of the 77 tax records supplies JSON Schema, expected values and nonempty field-scoring rules; 74 records have at least one rule marked `verified_by: human` (this does not mean every field is human-verified). Rules include evidence/page/bounding-box metadata where provided. The benchmark scores document extraction and evidence; it does not supply this project's leadsheet mapping, cross-document deduplication, jurisdiction/year event ledger or workflow outputs.

## Fake W-2 coverage and quality

- HF revision: `ea077dbeb5715e7765308220c1d8c6e7d36cfd52`.
- 2,000 images: train 1,800, validation 100, test 100; approx. 310 MB download. The upstream Kaggle corpus reports 2.109 GB and clean/noisy PDF/JPG variants, but the entire upstream archive was not downloaded or counted.
- HF columns: `image` and `ground_truth`; labels wrap a `gt_parse` object.
- The inspected first test label has 45 fields, including federal, state and local amounts, but **no tax-year field and no box 14**. It cannot directly score SUI/SDI box-14 extraction or tax-year attribution.
- The inspected first test image is a **2010** W-2, marked REISSUED, with two copies of the same statement on one image. REISSUED is not Form W-2c. This is valuable as a duplicate-copy reading example, but not proof of correction coverage.
- Labels use the literal string `"None"` for some blanks and contain misspelled field names. Normalize through an adapter without silently converting ambiguous states.
- Synthetic amounts should not be assumed tax-consistent: e.g. the inspected image repeats the entire social-security-wages amount in the social-security-tips box. Suitable for OCR smoke testing; unsuitable as a tax-calculation oracle without regeneration/review.
- Five test image+GT pairs are in `fake_w2_smoke/` with row IDs, split, revision and image checksums in `manifest.json`.

## Reuse and provenance

- ExtractBench's **dataset card explicitly declares Apache-2.0 for the dataset**, independently of its Apache-2.0 code license. Source forms are from real public records; some visible fields include real personal identifiers. Preserve provenance and distinguish this research corpus from a fully synthetic public demonstration dataset. Public availability alone is not a statement about personal-data handling or corporate suitability.
- Kaggle's official dataset API declares upstream Fake W-2 **CC0: Public Domain**. Saved as `w2_kaggle_view.txt`.
- The HF repack README explicitly links that upstream corpus, but omits its own license tag/text. Record upstream CC0 plus the repack provenance; don't claim an explicit HF license that is not present.

## Recommendation

Use ExtractBench's 77 labelled tasks as an extraction/regression suite with grouping by source collection. Use Fake W-2 for inexpensive image/field smoke tests. Neither is the full workflow dataset: complement them with coherent synthetic client dossiers, current-year official forms, state supporting documents and independently checked event/lead-sheet ground truth. Do not treat the published train/test splits or row counts as proof of independent clients or layouts.

## Primary sources

- ExtractBench dataset/card/files: https://huggingface.co/datasets/llamaindex/ExtractBench
- Pinned JSONL: https://huggingface.co/datasets/llamaindex/ExtractBench/tree/f6180e917a050a84582e6366cff85b7dc1e84e58
- Code and scorer: https://github.com/run-llama/ExtractBench
- Fake W-2 HF: https://huggingface.co/datasets/singhsays/fake-w2-us-tax-form-dataset
- Fake W-2 Kaggle: https://www.kaggle.com/datasets/mcvishnu1/fake-w2-us-tax-form-dataset
- Upstream machine-readable license metadata: https://www.kaggle.com/api/v1/datasets/view/mcvishnu1/fake-w2-us-tax-form-dataset

## Local files

`findings.json`, `inventory_all_370.json`, `tax_manifest.json`, `tax_cases_77.jsonl`, `audit.py`, `fake_w2_smoke/`, `samples/`, publisher READMEs/API snapshots and license evidence.

`extractbench_long_complete.jsonl` is the complete long split; its hash is checked by `audit.py`. Incomplete early downloads were removed.
