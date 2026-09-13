"""Reproduce a pinned, read-only TaxCalcBench TY25 corpus audit (stdlib only)."""
import argparse
import concurrent.futures
import json
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
COMMIT = "8f89c2cf00a8906f4d896a02a2f45f9c9e85ae9b"
TREE = "521d2767436e9a6c9ce4ad9ce71443694afa3838"
PREFIX = "tax_calc_bench/ty25/test_data/"


def fetch(path):
    dest = ROOT / "download" / path
    if dest.exists():
        return path, dest.stat().st_size
    url = f"https://raw.githubusercontent.com/column-tax/tax-calc-bench/{COMMIT}/{PREFIX}{path}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = resp.read()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return path, len(data)
    except Exception as exc:
        return path, {"error": str(exc)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--all", action="store_const", const="--all", dest="mode", help="Download the complete pinned corpus (default).")
    modes.add_argument("--initial", action="store_const", const="--initial", dest="mode", help="Download structured data and two sample PDF packets.")
    modes.add_argument("--remaining-pdfs", action="store_const", const="--remaining-pdfs", dest="mode", help="Download the PDF files excluded from --initial.")
    parser.add_argument("--workers", type=int, default=24, help="Concurrent requests; default 24.")
    parser.set_defaults(mode="--all")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    tree = json.loads((ROOT / "ty25_tree.json").read_text())
    files = [r for r in tree["tree"] if r["type"] == "blob"]
    # --remaining-pdfs complements initial structured-data + two-packet download.
    initial = lambda r: r["path"].endswith((".json", ".xml")) or r["path"].split("/")[0] in ("ty25-ca-001", "ty25-ca-008")
    mode = args.mode
    chosen = [r["path"] for r in files if mode == "--all" or (not initial(r) if mode == "--remaining-pdfs" else initial(r))]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = dict(pool.map(fetch, chosen))
    (ROOT / f"download_log{mode}.json").write_text(json.dumps(results, indent=2))
    print(json.dumps({"selected": len(chosen), "downloaded": sum(isinstance(x, int) for x in results.values()), "failed": {k:v for k,v in results.items() if not isinstance(v,int)}},indent=2))
    raise SystemExit(0 if all(isinstance(v, int) for v in results.values()) else 1)
