"""Download NDB Open Data (11th release, FY2024 prescription drugs) and the current NHI price list.

  data/raw/ndb/ndb11_prescription.zip   MHLW NDB Open Data, 11th release, prescription drugs incl.
                                        public-expense claims (FY2024 = Apr 2024 - Mar 2025)
  data/raw/ndb/extracted/               the oral (内服) and injection (注射) workbooks of folder 01_
  data/raw/ndb/yakka_<date>_01.xlsx     薬価基準収載品目リスト, oral drugs (内用薬): YJ code, 成分名,
  data/raw/ndb/yakka_<date>_02.xlsx     メーカー名, 先発品 flag; injections (注射薬). Two dates: current, end of FY2024

The ZIP's file names are Shift-JIS without the UTF-8 flag, so they are decoded as cp932 (macOS
unzip mangles them). Files that already exist are skipped, so the script is safe to rerun.
Licence: NDB Open Data may be used without application if the source is cited (MHLW FAQ).

Usage: python3 scripts/download_ndb.py
"""
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "ndb"
NDB_ZIP = "https://www.mhlw.go.jp/content/12400000/001744600.zip"
# Price lists: the one in force from 2026-10-14 (NDB's own prices were updated to the 2026-09-02 list) and the
# last one of FY2024 (2025-03-19), for products delisted since; clean_ndb.py prefers the newer one.
YAKKA = {f"yakka_{date}_{n}.xlsx": f"https://www.mhlw.go.jp/topics/{folder}/xls/{date}_{n}.xlsx"
         for folder, date in (("2026/04", "tp20261014-01"), ("2024/04", "tp20250319-01")) for n in ("01", "02")}
KEEP = ("【内服】", "【注射】")  # oral and injection workbooks; topical (外用) has no diabetes drugs


def fetch(url, path):
    if path.exists():
        print(f"exists: {path.relative_to(ROOT)}")
        return
    print(f"download {url}")
    tmp = path.with_suffix(path.suffix + ".part")
    with urllib.request.urlopen(url, timeout=600) as resp, open(tmp, "wb") as f:
        while chunk := resp.read(1 << 20):
            f.write(chunk)
    tmp.rename(path)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    zip_path = OUT / "ndb11_prescription.zip"
    fetch(NDB_ZIP, zip_path)
    for name, url in YAKKA.items():
        fetch(url, OUT / name)

    extracted = 0
    with zipfile.ZipFile(zip_path, metadata_encoding="cp932") as z:
        for info in z.infolist():
            name = Path(info.filename).name
            if "01_処方薬" in info.filename and name.endswith(".xlsx") and name.startswith(KEEP):
                if ".." in Path(info.filename).parts or Path(info.filename).is_absolute():
                    sys.exit(f"unsafe path in ZIP: {info.filename}")
                z.extract(info, OUT / "extracted")
                extracted += 1
    if extracted != 12:  # 内服 3 settings x 3 dimensions + 注射 3 dimensions
        sys.exit(f"expected 12 workbooks, found {extracted}: the ZIP layout changed")
    print(f"extracted {extracted} workbooks to {(OUT / 'extracted').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
