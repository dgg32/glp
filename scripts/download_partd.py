"""Download CMS Medicare Part D Prescribers by Provider and Drug rows for one state.

One JSON file per generic name in data/raw/partd/. Files that already exist are
skipped, so the script is safe to rerun after an interruption. Each download is
checked against the API's /stats row count before it is kept.

Usage: python3 scripts/download_partd.py [--state CT] [--year-dataset UUID]
"""
import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET_2024 = "d5aa71a8-dcc0-4570-8bcf-bd39deac69fe"
PAGE_SIZE = 5000


def get_json(url, retries=5):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=600) as resp:
                return json.load(resp)
        except Exception as exc:  # network hiccups, 5xx
            wait = 10 * (attempt + 1)
            print(f"  retry {attempt + 1}/{retries} in {wait}s: {exc}", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"failed after {retries} attempts: {url}")


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def download(base, state, gnrc_name, out_path):
    filters = {"filter[Prscrbr_State_Abrvtn]": state, "filter[Gnrc_Name]": gnrc_name}
    expected = get_json(f"{base}/stats?{urllib.parse.urlencode(filters)}")["found_rows"]

    # Sort by NPI + brand so offset paging is deterministic across calls.
    rows, offset = [], 0
    while True:
        params = {**filters, "size": PAGE_SIZE, "offset": offset,
                  "sort": "Prscrbr_NPI,Brnd_Name"}
        page = get_json(f"{base}?{urllib.parse.urlencode(params)}")
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    # Guard against offset paging returning duplicates or dropping rows.
    keys = {(r["Prscrbr_NPI"], r["Brnd_Name"], r["Gnrc_Name"]) for r in rows}
    if len(rows) != expected or len(keys) != len(rows):
        raise RuntimeError(f"{gnrc_name}: got {len(rows)} rows ({len(keys)} unique), "
                           f"stats says {expected}")

    tmp = out_path.with_suffix(".part")
    tmp.write_text(json.dumps(rows, ensure_ascii=False))
    tmp.rename(out_path)
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="CT")
    ap.add_argument("--dataset", default=DATASET_2024, help="CMS data-api dataset UUID")
    ap.add_argument("--drugs", default=ROOT / "scripts" / "cms_generic_names.csv", type=Path)
    args = ap.parse_args()

    base = f"https://data.cms.gov/data-api/v1/dataset/{args.dataset}/data"
    out_dir = ROOT / "data" / "raw" / "partd"
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(args.drugs, newline="") as f:
        names = [r["gnrc_name"] for r in csv.DictReader(f)]

    for name in names:
        out_path = out_dir / f"{args.state}_{slug(name)}.json"
        if out_path.exists():
            print(f"skip  {name} (exists)")
            continue
        t0 = time.time()
        n = download(base, args.state, name, out_path)
        print(f"done  {name}: {n} rows in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
