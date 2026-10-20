"""Fetch NPI Registry records for the unique prescriber NPIs in data/raw/partd/.

One JSON file per NPI in data/raw/npi/ (the full API response, so taxonomy,
enumeration type and other fields stay available). Existing files are skipped,
so the script is safe to rerun.

Usage: python3 scripts/fetch_npi.py [--workers 4]
"""
import argparse
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://npiregistry.cms.hhs.gov/api/?version=2.1&number={}"


def fetch(npi, out_dir, retries=5):
    out_path = out_dir / f"{npi}.json"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(API.format(npi), timeout=60) as resp:
                body = json.load(resp)
            break
        except Exception as exc:
            if attempt == retries - 1:
                return npi, f"error: {exc}"
            time.sleep(5 * (attempt + 1))
    tmp = out_path.with_suffix(".part")
    tmp.write_text(json.dumps(body, ensure_ascii=False))
    tmp.rename(out_path)
    return npi, "ok" if body.get("result_count") else "not found"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    npis = set()
    for path in sorted((ROOT / "data" / "raw" / "partd").glob("*.json")):
        npis.update(r["Prscrbr_NPI"] for r in json.loads(path.read_text()))

    out_dir = ROOT / "data" / "raw" / "npi"
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = sorted(n for n in npis if not (out_dir / f"{n}.json").exists())
    print(f"{len(npis)} unique NPIs, {len(npis) - len(todo)} cached, {len(todo)} to fetch")

    status = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(fetch, n, out_dir) for n in todo]
        for i, fut in enumerate(as_completed(futures), 1):
            npi, s = fut.result()
            status[s] = status.get(s, 0) + 1
            if s != "ok":
                print(f"  {npi}: {s}", file=sys.stderr)
            if i % 500 == 0:
                print(f"  {i}/{len(todo)}", flush=True)
    print("summary:", status)


if __name__ == "__main__":
    main()
