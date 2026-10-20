"""Download the NUCC Health Care Provider Taxonomy CSV into data/raw/nucc/.

The version is pinned for reproducibility; pass --version to change it
(see https://www.nucc.org -> Code Sets -> Taxonomy -> CSV). Skips if present.

Usage: python3 scripts/download_nucc.py [--version 261]
"""
import argparse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="261", help="e.g. 261 = v26.1")
    args = ap.parse_args()

    out_dir = ROOT / "data" / "raw" / "nucc"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"nucc_taxonomy_{args.version}.csv"
    out_path = out_dir / name
    if out_path.exists():
        print(f"skip  {name} (exists)")
        return

    url = f"https://www.nucc.org/images/stories/CSV/{name}"
    with urllib.request.urlopen(url, timeout=120) as resp:
        data = resp.read()
    tmp = out_path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.rename(out_path)
    print(f"done  {name}: {len(data)} bytes from {url}")


if __name__ == "__main__":
    main()
