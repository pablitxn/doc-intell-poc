---
license: apache-2.0
configs:
- config_name: extract-bench
  features:
  - name: id
    dtype: string
  - name: category
    dtype: string
  - name: pdf
    dtype: string
  - name: data_schema
    dtype: string
  - name: expected_output
    dtype: string
  - name: field_rules
    dtype: string
  - name: repeated_structure
    dtype: string
  - name: tags
    sequence: string
  data_files:
  - split: short
    path: short.jsonl
  - split: medium
    path: medium.jsonl
  - split: long
    path: long.jsonl
language:
- en
pretty_name: ExtractBench
size_categories:
- n<1K
tags:
- document-extraction
- structured-extraction
- information-extraction
- pdf
- benchmark
- evaluation
- json-schema
- visual-grounding
- forms
- tables
citation: |
  @misc{zhang2026extractbenchbenchmarkschemaguidedenterprise,
        title={ExtractBench: A Benchmark for Schema-Guided Enterprise Document Extraction},
        author={Boyang Zhang and Adrian Lyjak and Eli Stewart and Zhaoqi Li and Simon Suo},
        year={2026},
        eprint={2607.29677},
        archivePrefix={arXiv},
        primaryClass={cs.AI},
        url={https://arxiv.org/abs/2607.29677},
  }
---

# ExtractBench

![ExtractBench](thumbnails/extractbench_teaser.png)

**Quick links:** [\[🌐 Website\]](https://extractbench.ai) [\[📜 Paper\]](https://arxiv.org/abs/2607.29677) [\[💻 Code\]](https://github.com/run-llama/ExtractBench)

Given a document and a schema, a system returns structured data with evidence. The input is a full document, born-digital or scanned, and a schema written by the user. The output is a schema-valid JSON object, with the source page and a bounding box for each value as evidence. It must return correct, exhaustive values (including repeated records), correctly use `null` for absent information, and ground each extracted value.

ExtractBench contains 370 documents (4,869 pages) across 8 business domains and 67 document types. Each document type has one schema shared across its documents. Each document is tagged by task challenge, perception challenge, table structure, domain, and length.

The [evaluation framework](https://github.com/run-llama/ExtractBench) runs pipelines and reports scores by split, tag, and system.

## Dataset Introduction

A document type is a family of documents that carry the same kind of information, such as SEC 13F filings, utility bills, or mortgage closing disclosures, however much their layouts differ. In ExtractBench, each document type has exactly one schema, shared by all of its documents.

The benchmark spans finance and fund holdings (D1), energy-sector regulatory forms (D2), government procurement and customs (D3), auto valuation (D4), supply-chain and other transactional documents (D5), healthcare remittance (D6), legal and bankruptcy filings (D7), and real-estate closing disclosures (D8).

A task challenge defines the nature of the extraction task and what makes it difficult:

- **T1: long-list completeness.** Recover *every* record of a repeated structure that can span many pages. Typical failures are truncation, duplicated or merged rows, hallucinated records, and values attached to the wrong record.
- **T2: needle-in-haystack.** Find a small number of requested facts in a long document. T2 has few target records but many plausible mentions, only one of which is canonical; failures are missed targets, wrong occurrences, and unnormalized paraphrases.
- **T3: dense documents.** Fill many fields from a document dense with labels, blanks, checkboxes, handwriting, and scan artifacts. The characteristic failure is over-extraction, inventing a value for a field that is actually blank, compounded by missed checkboxes and mislabeled fields.

| Task challenge | Documents | Pages | Expected values |
|------------------|----------:|------:|----------------:|
| T1: Long-list completeness | 154 | 3,710 | 813,792 |
| T2: Needle-in-haystack | 39 | 1,109 | 10,300 |
| T3: Dense documents | 214 | 905 | 31,200 |
| **Total (unique)** | **370** | **4,869** | **841,934** |

A document can carry more than one task challenge, so the rows overlap; totals reflect unique documents, pages, and values.

ExtractBench tags each document along five independent axes: task challenge (what makes extraction hard), perception challenge (how the page was captured), table structure, length, and business domain. Because the axes are independent, a low score can be traced to its actual cause.

![Tag coverage](thumbnails/extractbench_taxonomy.png)

Documents fall into three length buckets: short (L1, up to 10 pages), medium (L2, 11 to 50), and long (L3, more than 50). The split files and page counts are listed under [Usage](#usage).

<details>
  <summary>Document sources and capture conditions</summary>

The benchmark is composed of real born-digital documents, synthetic long lists based on real layouts, and real regulatory and tax forms with schemas authored from blank templates. The public sources include SEC and other regulatory filings, government procurement and customs forms, court and agency exhibits, Texas Railroad Commission energy filings, and published business documents. PDF metadata has been removed from every file.

Of the 370 documents, 325 are real and 45 are synthetic long lists with values fixed before rendering. The dataset includes 134 documents with scanned page images and 55 with handwriting.

Another 38 documents are degraded re-captures of clean documents. Their expected values stay the same, so the difference between clean and degraded scores measures the effect of capture degradation.

</details>

## Usage

Load a split with `datasets`:

```python
from datasets import load_dataset
import json

ds = load_dataset("llamaindex/ExtractBench", split="short")
case = ds[0]
schema = json.loads(case["data_schema"])
expected = json.loads(case["expected_output"])
```

To run an extraction system, download the files in the layout expected by the [evaluation framework](https://github.com/run-llama/ExtractBench), then run a pipeline:

```bash
uv run extract-bench download          # data/<split>/<doc>.pdf + <doc>.test.json
uv run extract-bench run <pipeline>    # inference -> evaluation -> reports
```

ExtractBench measures two things. Value accuracy asks whether a system returned the right values, and is scored with unified value F1 on every document. Grounding asks whether the system can show where each value came from, and is scored only on documents whose box ground truth is verified.

- **Unified value F1:** whether the extracted values match the expected output, under one definition for scalar fields and arrays of records.
- **Word-level grounding F1:** a field counts as grounded only when its value is correct and its predicted box overlaps an accepted box for that field at IoU 0.5.
- **Page-level grounding F1:** requires the correct source page rather than a box.

Scoring is fully deterministic: the same predictions and ground truth always produce the same score, with no model in the loop. The [code repository](https://github.com/run-llama/ExtractBench) contains the full metric definitions.

The evaluation dataset files include:

- [short.jsonl](short.jsonl): 252 test cases across 615 pages, up to 10 pages each
- [medium.jsonl](medium.jsonl): 98 test cases across 2,438 pages, 11–50 pages each
- [long.jsonl](long.jsonl): 20 test cases across 1,816 pages, more than 50 pages each
- [docs/](https://huggingface.co/datasets/llamaindex/ExtractBench/tree/main/docs): source PDFs organized by split

<details>
  <summary>Dataset Format</summary>

Each line in a JSONL file represents one document-schema test case:

```json
{
    "id": "short/grafton_isotrope_invoice_19503",  // Unique test-case id: <split>/<stem>
    "category": "short",                            // Split name (short | medium | long)
    "pdf": "docs/short/grafton_isotrope_invoice_19503.pdf",  // Relative path to the source document
    "data_schema": "{...}",         // JSON-encoded JSON Schema the output must validate against
    "expected_output": "{...}",     // JSON-encoded ground-truth extraction
    "field_rules": "{...}",         // JSON-encoded per-field scoring rules (see below)
    "repeated_structure": "{...}",  // JSON-encoded record-identity config for arrays of records
    "tags": ["source:real", "challenge:T3.b", "length:short", "domain:D1"]
}
```

Because schemas differ by document, `data_schema`, `expected_output`, `field_rules`, and `repeated_structure` are stored as JSON-encoded strings rather than fixed columns. Decode them with `json.loads`. On the largest long-list document, `field_rules` reaches 21 MB, so the dataset viewer shows only a preview of each cell. The downloaded file contains the complete data.

**`field_rules`** maps each schema path to a scoring rule:

- `comparator`: how predicted values are compared (`exact`, `case_insensitive`, `number`, `date`, `boolean`, `enum`, ...)
- `evidence`: accepted readings and their source locations, stored as `{page, bbox, quote, value}`; any accepted reading counts as correct
- `source_policy`: whether the value must appear verbatim in the document
- `evidence_required` / `verified`: whether grounded evidence exists and was verified by a person

**`repeated_structure`** gives the identity key used to align records in an array. For example, invoice line items may be matched by `(description, amount)`. Array order does not affect the score. This field also records the completeness requirements for exhaustive lists.

</details>

<details>
  <summary>Tag Taxonomy</summary>

The five analysis axes are:

- **`challenge`:** `T1.a`–`T1.e` for long-list completeness, `T2.a`–`T2.d` for needle-in-haystack, and `T3.a`–`T3.e` for dense documents.
- **`perception`:** rotated or image-only capture (`P1`), scanned page images (`P2`), and handwriting (`P3`).
- **`structure`:** merged or hierarchical headers (`S1`), a header that does not sit above its data (`S2`), a table that continues across pages (`S3`), a table beyond 1,000 rows (`S4`), and a table packed inside a single cell (`S5`).
- **`length`:** `short` (L1, up to 10 pages), `medium` (L2, 11 to 50), and `long` (L3, more than 50). This tag always matches `category`.
- **`domain`:** `D1` finance (145), `D2` energy (98), `D3` government (49), `D4` automotive (27), `D5` supply chain (20), `D6` healthcare (15), `D7` legal (10), and `D8` real estate (6).

The dataset also records `delivery` requirements (`G1`–`G4`) and whether the source is `real` (325) or `synthetic` (45).

</details>

## Data Display

### Long lists (T1)

<table>
  <tr>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/long/real_oklahoma_unclaimed_2024.pdf"><img src="thumbnails/f1_01.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/long/real_ftx_full.pdf"><img src="thumbnails/f1_02.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/long/real_ishares_iboxx_bond_etfs.pdf"><img src="thumbnails/f1_03.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/medium/13f__leonteq_securities_2025q4.pdf"><img src="thumbnails/f1_04.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/medium/real_pueblo_oct_2025.pdf"><img src="thumbnails/f1_05.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/short/viega_price_list_propress_2026.pdf"><img src="thumbnails/f1_06.png" width="150" /></a></td>
  </tr>
</table>

### Needle-in-haystack (T2)

<table>
  <tr>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/medium/sf1449_supplies_services_0046.pdf"><img src="thumbnails/f2_01.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/medium/byline_bancorp_investor_deck_q2_2023.pdf"><img src="thumbnails/f2_02.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/medium/hpe_earnings_deck_q4fy25.pdf"><img src="thumbnails/f2_03.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/long/dd1155_schedule_continuation_0012.pdf"><img src="thumbnails/f2_04.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/medium/transunion_earnings_deck_q4fy25.pdf"><img src="thumbnails/f2_05.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/long/sf1449_supplies_services_0042.pdf"><img src="thumbnails/f2_06.png" width="150" /></a></td>
  </tr>
</table>

### Dense documents (T3)

<table>
  <tr>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/short/W14-58509_W14%202nd%20sub%20revised.pdf"><img src="thumbnails/f3_01.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/short/cbp_7501_continuation_0018.pdf"><img src="thumbnails/f3_02.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/short/cfpb_closing-disclosure_filled-sample.pdf"><img src="thumbnails/f3_03.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/short/we-energies-sample-bill.pdf"><img src="thumbnails/f3_04.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/short/pershing_0001.pdf"><img src="thumbnails/f3_05.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/short/caterpillar_spec_sheet_312c_excavator.pdf"><img src="thumbnails/f3_06.png" width="150" /></a></td>
  </tr>
</table>

### Scanned, handwritten, and degraded captures

<table>
  <tr>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/short/W14-57728_W14_REVISED.pdf"><img src="thumbnails/capture_01.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/short/08-15427%20H-12%201-21-2003%20F-01341.pdf"><img src="thumbnails/capture_02.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/short/golden_corral_receipt_refugio_county_auditor.pdf"><img src="thumbnails/capture_03.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/short/aclu_cdwg_invoice.pdf"><img src="thumbnails/capture_04.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/short/caterpillar_spec_sheet_312c_excavator_corrupted.pdf"><img src="thumbnails/capture_05.png" width="150" /></a></td>
    <td><a href="https://huggingface.co/datasets/llamaindex/ExtractBench/blob/main/docs/medium/real_bbb_service_list_corrupted.pdf"><img src="thumbnails/capture_06.png" width="150" /></a></td>
  </tr>
</table>

## Copyright Statement

All source documents come from publicly available records. The dataset is released under the [Apache 2.0 License](https://www.apache.org/licenses/LICENSE-2.0). For copyright questions or concerns, contact us through the [GitHub repository](https://github.com/run-llama/ExtractBench).

## Citation

```bibtex
@misc{zhang2026extractbenchbenchmarkschemaguidedenterprise,
      title={ExtractBench: A Benchmark for Schema-Guided Enterprise Document Extraction},
      author={Boyang Zhang and Adrian Lyjak and Eli Stewart and Zhaoqi Li and Simon Suo},
      year={2026},
      eprint={2607.29677},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2607.29677},
}
```

## Links

- **Code:** [run-llama/ExtractBench](https://github.com/run-llama/ExtractBench)
- **ParseBench:** [llamaindex/ParseBench](https://huggingface.co/datasets/llamaindex/ParseBench), a companion benchmark for document parsing
