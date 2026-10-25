"""Clean the NDB Open Data workbooks (diabetes drugs only) into tidy CSVs in data/clean/.

Scope (decided 2026-10-25, japan_extension.md): all of 薬効分類 396 (糖尿病用剤, incl. the combination
pens Xultophy and Soliqua), every insulin (YJ prefix 2492) and the GLP-1 / GIP-GLP-1 ingredients that
Japan files under 249 (その他のホルモン剤), selected by YJ ingredient prefix in GLP1_YJ.

Lossless like clean_data.py: every cell of every in-scope row is kept, including zeros and masked
cells ("‐"/"-": < 1,000 in oral tables, < 400 in injection tables, plus secondary masking).

Outputs:
  ndb_products.csv     one row per receipt code (医薬品コード): name, unit, YJ code, price, generic flag,
                       NDB class, plus 成分名, メーカー名 and 先発品 from the NHI price list (薬価基準収載品目リスト)
  ndb_slices.csv       one row per product x setting x dimension with the national total (総計), which is
                       masked too where the whole product is below the threshold in that setting
  ndb_cells.csv        one row per cell: slice, key (prefecture JIS code | YYYY-MM | sex + age band),
                       quantity, masked
  ndb_report.json      counts and products missing from the price list

Usage: .venv/bin/python scripts/clean_ndb.py
"""
import csv
import json
import re
from collections import Counter
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "ndb"
CLEAN = ROOT / "data" / "clean"
GLP1_YJ = {"2499410": "liraglutide", "2499411": "exenatide", "2499415": "lixisenatide", "2499416": "dulaglutide",
           "2499418": "semaglutide (injection)", "2499014": "semaglutide (oral)", "2499422": "tirzepatide"}
MASK = {"-", "‐", "－"}
SETTINGS = {"外来（院外）": "outpatient-external", "外来（院内）": "outpatient-internal", "入院": "inpatient",
            "外来 (院外)": "outpatient-external", "外来 (院内)": "outpatient-internal"}
DIMENSIONS = {"都道府県別": "prefecture", "診療月別": "month", "性年齢別": "sex-age"}
FY = 2024  # FY2024 = April 2024 .. March 2025


def in_scope(ndb_class, yj):
    return ndb_class == 396 or yj.startswith("2492") or yj[:7] in GLP1_YJ


def column_keys(dimension, header, labels):
    """Cell keys for the data columns (index 9 on): JIS code, YYYY-MM, or sex + lower age bound (M65, F100)."""
    if dimension == "prefecture":
        keys = [str(h) for h in header[9:]]
        assert keys == [f"{i:02d}" for i in range(1, 48)], keys
    elif dimension == "month":
        months = [int(re.fullmatch(r"(\d+)月", h)[1]) for h in header[9:]]
        keys = [f"{FY if m >= 4 else FY + 1}-{m:02d}" for m in months]
        assert len(keys) == 12
    else:
        keys, sex = [], None
        for h, label in zip(header[9:], labels[9:]):
            sex = {"男": "M", "女": "F"}.get(h, sex)
            keys.append(f"{sex}{int(re.match(r'(\d+)', label)[1])}")
        assert len(keys) == 42 and keys[0] == "M0" and keys[-1] == "F100", keys
    return keys


def number(v):
    return format(v, "f").rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def price_list():
    out = {}
    for f in sorted(RAW.glob("yakka_*.xlsx"), reverse=True):  # newest list first; older lists only fill gaps
        for r in openpyxl.load_workbook(f, read_only=True).worksheets[0].iter_rows(min_row=2, values_only=True):
            if r[1] and r[1] not in out:
                out[r[1]] = {"ingredient_ja": r[2] or "", "manufacturer_ja": r[8] or "",
                             "originator": "true" if r[10] == "先発品" else "false", "price_list": f.stem}
    return out


def main():
    prices = price_list()
    products, slices, cells = {}, [], []
    report = Counter()
    for path in sorted((RAW / "extracted").rglob("*.xlsx")):
        name = path.name
        route = "oral" if name.startswith("【内服】") else "injection"
        dimension = next(v for k, v in DIMENSIONS.items() if k in name)
        for ws in openpyxl.load_workbook(path, read_only=True).worksheets:
            # Oral workbooks have one setting each (in the file name), injection workbooks one per sheet.
            setting = next(v for k, v in SETTINGS.items() if k in (ws.title if route == "injection" else name))
            rows = ws.iter_rows(min_row=3, values_only=True)
            keys = column_keys(dimension, next(rows), next(rows))
            ndb_class = class_name = None
            for r in rows:
                if r[0] is not None:
                    ndb_class, class_name = r[0], r[1]  # only on the first row of each class block
                yj = str(r[5] or "")
                if not in_scope(ndb_class, yj):
                    continue
                code = str(r[2])
                listed = prices.get(yj)
                p = {"receipt_code": code, "yj_code": yj, "name_ja": r[3], "unit_ja": r[4], "nhi_price": number(r[6]),
                     "ndb_generic": str(r[7]), "ndb_class": str(ndb_class), "ndb_class_name": class_name, "route": route,
                     "ingredient_ja": listed["ingredient_ja"] if listed else "",
                     "manufacturer_ja": listed["manufacturer_ja"] if listed else "",
                     "originator": listed["originator"] if listed else "",
                     "price_list": listed["price_list"] if listed else ""}
                if products.setdefault(code, p) != p:
                    raise SystemExit(f"receipt code {code} differs between workbooks: {products[code]} vs {p}")
                slice_id = f"{code}/{route}/{setting}/{dimension}"
                total_masked = isinstance(r[8], str) and r[8].strip() in MASK  # 429 small products
                slices.append({"slice": slice_id, "receipt_code": code, "route": route, "setting": setting,
                               "dimension": dimension, "total": "" if total_masked else number(r[8]),
                               "total_masked": str(total_masked).lower()})
                for key, v in zip(keys, r[9:9 + len(keys)]):
                    masked = isinstance(v, str) and v.strip() in MASK
                    if v is None or (isinstance(v, str) and not masked):
                        raise SystemExit(f"{name} {code} {key}: unexpected cell {v!r}")
                    cells.append({"slice": slice_id, "key": key, "quantity": "" if masked else number(v),
                                  "masked": str(masked).lower()})
                    report["masked" if masked else "zero" if v == 0 else "value"] += 1
                report[f"slices {dimension}"] += 1

    CLEAN.mkdir(parents=True, exist_ok=True)
    for file, rows in [("ndb_products.csv", sorted(products.values(), key=lambda p: p["receipt_code"])),
                       ("ndb_slices.csv", slices), ("ndb_cells.csv", cells)]:
        with open(CLEAN / file, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"wrote data/clean/{file}: {len(rows):,} rows")
    missing = sorted(f"{p['receipt_code']} {p['name_ja']}" for p in products.values() if not p["price_list"])
    out = {"products": len(products), "generics": sum(p["ndb_generic"] == "1" for p in products.values()),
           "cells": dict(report), "not_in_price_lists": missing}
    (CLEAN / "ndb_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in out.items() if k != "not_in_price_lists"}, ensure_ascii=False))
    print(f"{len(missing)} products in neither price list, e.g. {missing[:3]}")


if __name__ == "__main__":
    main()
