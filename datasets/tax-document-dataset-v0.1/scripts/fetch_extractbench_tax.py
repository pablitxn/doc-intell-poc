#!/usr/bin/env python3
"""Fetch the audited ExtractBench tax subset using only Python's standard library.

Downloads real public-record documents and labels, some with personal identifiers.
Keep labels outside the filesystem exposed to an evaluated agent.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

REPO = "llamaindex/ExtractBench"
REVISION = "f6180e917a050a84582e6366cff85b7dc1e84e58"
ROOT_URL = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/"
SPLITS = {
    "short": (252, "e4b07b3612f1d4bcf4157d5b97b8692d671aeddaf96e5b5898338345b654e740"),
    "medium": (98, "8ae0884d8e8dddb1282eb98282d942b65c8d99b82dd37e650edc53cd0f5bb5df"),
    "long": (20, "ac5b22bbf810548a5e086e792d4afe0aa98dc572d24deceab820a2558570f3bd"),
}
USER_AGENT = "TaxDocumentDatasetFetcher/1.0 (Python urllib)"


def safe_relative(value: str) -> Path:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"Unsafe dataset-relative path: {value!r}")
    return Path(*path.parts)


def open_url(url: str):
    return urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=120)


def download(url: str, target: Path, expected: str, kind: str = "sha256", size: int | None = None) -> dict:
    """Stream atomically, verifying LFS SHA-256 or a regular Git blob SHA-1."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    digest = hashlib.sha256() if kind == "sha256" else hashlib.sha1()
    if kind == "git-blob-sha1":
        if size is None:
            raise ValueError("Git blob hashing requires the source file size")
        digest.update(f"blob {size}\0".encode())
    actual_size = 0
    try:
        with open_url(url) as response, partial.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                written = output.write(chunk)
                if written != len(chunk):
                    raise OSError(f"Short local write: {partial}")
                digest.update(chunk)
                actual_size += len(chunk)
        if digest.hexdigest() != expected:
            raise ValueError(f"Hash mismatch for {target.name}: got {digest.hexdigest()}, expected {expected}")
        if size is not None and actual_size != size:
            raise ValueError(f"Size mismatch for {target.name}: {actual_size} != {size}")
        partial.replace(target)
        return {"bytes": actual_size, "hash_algorithm": kind, "hash": expected}
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def pdf_metadata(wanted: set[str]) -> dict:
    """Read pinned HF tree metadata; never download a PDF without an expected hash."""
    url = f"https://huggingface.co/api/datasets/{REPO}/tree/{REVISION}/docs?recursive=true&limit=1000"
    found = {}
    while url:
        if urlparse(url).hostname != "huggingface.co":
            raise ValueError("Unexpected metadata pagination host")
        with open_url(url) as response:
            entries = json.load(response)
            link = response.headers.get("Link", "")
        for entry in entries:
            if entry.get("type") != "file" or entry.get("path") not in wanted:
                continue
            lfs = entry.get("lfs") or {}
            expected = lfs.get("oid") or lfs.get("sha256")
            kind = "sha256"
            if not expected:
                expected, kind = entry.get("oid"), "git-blob-sha1"
            length = 64 if kind == "sha256" else 40
            if not isinstance(expected, str) or not re.fullmatch(rf"[0-9a-f]{{{length}}}", expected):
                raise ValueError(f"Missing/invalid source hash for {entry['path']}")
            size = lfs.get("size", entry.get("size"))
            if not isinstance(size, int):
                raise ValueError(f"Missing source byte size for {entry['path']}")
            found[entry["path"]] = {"hash": expected, "kind": kind, "size": size}
        next_link = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = next_link.group(1) if next_link else None
    missing = wanted - found.keys()
    if missing:
        raise ValueError(f"Pinned file metadata missing for {len(missing)} requested PDFs")
    return found


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download 77 audited tax extraction cases from a pinned ExtractBench revision.",
        epilog="Downloads ~253 MB of raw metadata even with --metadata-only; retains ~22 MB of tax labels. Full mode adds 77 real-source PDFs. Temporary raw splits are deleted automatically.",
    )
    parser.add_argument("--manifest", required=True, type=Path, help="Path to the supplied tax_manifest.json (77 audited IDs)")
    parser.add_argument("--output", required=True, type=Path, help="Destination directory for tax_cases_77.jsonl, PDFs and provenance")
    parser.add_argument("--metadata-only", action="store_true", help="Download/verify all metadata and save selected cases; skip PDFs")
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 9), metavar="1-8", help="Concurrent PDF downloads (default: 4)")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, list) or len(manifest) != 77:
        parser.error("Manifest must contain exactly the 77 audited entries")
    requested = {row["id"]: row for row in manifest}
    if len(requested) != 77:
        parser.error("Manifest has duplicate IDs")
    for row in manifest:
        safe_relative(row["pdf"])
    args.output.mkdir(parents=True, exist_ok=True)
    retained = []
    split_provenance = []
    print("Fetching real public-source tax documents/labels. Do not expose labels to the evaluated agent.", flush=True)
    with tempfile.TemporaryDirectory(prefix="extractbench_download_", dir=args.output) as temporary:
        temp = Path(temporary)
        for split, (expected_count, digest) in SPLITS.items():
            filename = f"{split}.jsonl"
            print(f"Downloading and verifying {filename}...", flush=True)
            source_url = ROOT_URL + filename
            info = download(source_url, temp / filename, digest)
            count = 0
            with (temp / filename).open(encoding="utf-8") as source:
                for line in source:
                    row = json.loads(line)
                    count += 1
                    if row["id"] in requested:
                        if row["pdf"] != requested[row["id"]]["pdf"]:
                            raise ValueError(f"Manifest path differs from pinned source: {row['id']}")
                        retained.append(row)
            if count != expected_count:
                raise ValueError(f"Unexpected {split} row count: {count}")
            split_provenance.append({"url": source_url, "rows": count, **info})
            (temp / filename).unlink()
        if len(retained) != 77 or {r["id"] for r in retained} != requested.keys():
            raise ValueError("Downloaded cases do not match the 77-ID manifest")
        labels = temp / "tax_cases_77.jsonl"
        with labels.open("w", encoding="utf-8") as output:
            for row in sorted(retained, key=lambda r: r["id"]):
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
        labels.replace(args.output / labels.name)
    if args.manifest.resolve() != (args.output / "tax_manifest.json").resolve():
        shutil.copyfile(args.manifest, args.output / "tax_manifest.json")
    documents = []
    if not args.metadata_only:
        paths = {row["pdf"] for row in retained}
        metadata = pdf_metadata(paths)
        print(f"Downloading {len(paths)} PDFs ({sum(m['size'] for m in metadata.values()) / 1e6:.1f} MB), with source hash verification...", flush=True)

        def fetch_pdf(path: str) -> dict:
            item = metadata[path]
            url = ROOT_URL + quote(path, safe="/")
            info = download(url, args.output / safe_relative(path), item["hash"], item["kind"], item["size"])
            return {"path": path, "source_url": url, **info}

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            documents = list(pool.map(fetch_pdf, sorted(paths)))
    provenance = {
        "dataset": REPO, "revision": REVISION, "case_count": len(retained),
        "metadata_only": args.metadata_only, "split_downloads": split_provenance,
        "documents": documents,
        "publisher_dataset_license": "Apache-2.0",
        "dataset_card": "https://huggingface.co/datasets/llamaindex/ExtractBench",
        "source_note": "Real public records may contain personal identifiers. Dataset license is the publisher's declaration; preserve source provenance.",
        "evaluation_note": "Keep expected_output and field_rules outside the agent-accessible workspace. These are single-document extraction labels, not leadsheet workflow labels.",
    }
    (args.output / "download_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(retained)} labelled cases and {len(documents)} PDFs in {args.output}.", flush=True)


if __name__ == "__main__":
    main()
