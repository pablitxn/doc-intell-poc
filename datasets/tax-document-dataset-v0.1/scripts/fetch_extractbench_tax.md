# Obtain the audited ExtractBench tax subset

Requires Python 3.10+; uses only the standard library. No model calls or API keys. Internet access to Hugging Face and its public file CDN is required.

Run from any working directory, supplying paths appropriate to your copy of the kit:

```bash
python scripts/fetch_extractbench_tax.py --manifest extractbench/tax_manifest.json --output external/extractbench --metadata-only
```

To additionally fetch the 77 source PDFs:

```bash
python scripts/fetch_extractbench_tax.py --manifest extractbench/tax_manifest.json --output external/extractbench
```

`--workers 1` reduces simultaneous PDF downloads; the default is four.

The script pins dataset revision `f6180e917a050a84582e6366cff85b7dc1e84e58`. It downloads the full short, medium and long metadata splits (~253 MB transferred), checks their previously audited SHA-256 hashes and 252/98/20 record counts, and selects exactly the 77 supplied manifest IDs. It retains approximately 22 MB of labels as `tax_cases_77.jsonl`; raw split files are automatically removed. Full mode adds 77 PDFs under `docs/`, announces their total size from pinned upstream metadata and verifies each against its LFS SHA-256 or Git blob SHA-1. Any hash mismatch fails the download. `download_provenance.json` records source URLs, revision, hashes and file sizes.

These PDFs are **real public-source records**, not a synthetic demonstration set; some contain personal identifiers. The publisher declares the dataset Apache-2.0. Preserve that provenance when assessing or reusing source documents. These labels measure single-document extraction; they do not supply the project's leadsheet or cross-document workflow ground truth.

Keep `tax_cases_77.jsonl` outside the workspace exposed to the harness: it contains expected answers and evidence. Give the evaluated agent the PDF inputs and separately prepared tasks/schemas.

Validation performed for this downloader: Python compilation and `--help`. The network download path was not rerun after authoring the script; its pinned source hashes come from the completed source audit.
