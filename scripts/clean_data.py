"""Clean the raw Part D, NPI Registry and NUCC downloads into tidy CSVs in data/clean/.

Cleaning here is deliberately lossless: types are normalized, columns renamed to
snake_case and drug classes attached, but rows with data-quality problems are kept
and only *reported* (data/clean/cleaning_report.json). Catching those problems is
the job of the SHACL shapes later.

Outputs:
  partd_claims.csv     one row per prescriber x brand x generic (the claim aggregate)
  prescribers.csv      one row per NPI: CMS name/city/specialty + NPI Registry fields
  npi_taxonomies.csv   one row per NPI x NUCC taxonomy code (all, not only primary)
  nucc_taxonomy.csv    the NUCC code set, whitespace-trimmed

Usage: python3 scripts/clean_data.py [--nucc-version 261]
"""
import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
CLEAN = ROOT / "data" / "clean"

DIABETES_INDICATIONS = {"T2DM", "T1DM"}

COUNT_COLS = ["Tot_Clms", "Tot_Day_Suply", "Tot_Benes",
              "GE65_Tot_Clms", "GE65_Tot_Day_Suply", "GE65_Tot_Benes"]
# 30-day fills are prorated by CMS (e.g. a 90-day fill = 3.0), so they are decimals like costs.
DECIMAL_COLS = ["Tot_30day_Fills", "Tot_Drug_Cst", "GE65_Tot_30day_Fills", "GE65_Tot_Drug_Cst"]


def snake(name):
    return re.sub(r"(?<!^)(?=[A-Z][a-z])", "_", name).lower().replace("__", "_")


def tidy(s):
    return re.sub(r"\s+", " ", s).strip() if isinstance(s, str) else s


def to_number(value, cast):
    """'' -> None (suppressed or not applicable); otherwise int/float. Bad values stay as text."""
    value = tidy(value)
    if value in ("", None):
        return None
    try:
        return cast(value)
    except ValueError:
        return value


def write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: "" if r.get(k) is None else r[k] for k in fields})


def clean_partd(drugs, obesity_brands, report):
    raw_rows = []
    for path in sorted((RAW / "partd").glob("*.json")):
        raw_rows.extend(json.loads(path.read_text()))
    report["partd_raw_rows"] = len(raw_rows)

    drug_lookup = {k.lower(): v for k, v in drugs.items()}
    out, seen, issues = [], set(), Counter()
    for r in raw_rows:
        r = {k: tidy(v) for k, v in r.items()}
        key = (r["Prscrbr_NPI"], r["Brnd_Name"], r["Gnrc_Name"])
        if key in seen:
            issues["duplicate_rows_dropped"] += 1
            continue
        seen.add(key)

        row = {snake(k): v for k, v in r.items()}
        for c in COUNT_COLS:
            row[snake(c)] = to_number(r[c], int)
        for c in DECIMAL_COLS:
            row[snake(c)] = to_number(r[c], float)

        drug = drug_lookup.get(r["Gnrc_Name"].lower())
        row["drug_class"] = drug["drug_class"] if drug else None
        row["is_combination"] = drug["is_combination"] if drug else None
        row["is_obesity_brand"] = str(r["Brnd_Name"] in obesity_brands).lower()
        # CMS blanks Tot_Benes for 1-10 beneficiaries but has no flag column for it.
        row["tot_benes_suppressed"] = str(row["tot_benes"] is None).lower()

        # Report, don't fix.
        if not drug:
            issues["generic_not_in_drug_list"] += 1
        if not re.fullmatch(r"\d{10}", r["Prscrbr_NPI"] or ""):
            issues["npi_not_10_digits"] += 1
        for c in COUNT_COLS + DECIMAL_COLS:
            v = row[snake(c)]
            if isinstance(v, str):
                issues[f"non_numeric_{snake(c)}"] += 1
            elif v is not None and v < 0:
                issues[f"negative_{snake(c)}"] += 1
        if row["tot_benes"] is None:
            issues["tot_benes_blank"] += 1
        if row["ge65_sprsn_flag"] and row["ge65_tot_clms"] is not None:
            issues["ge65_flagged_but_count_present"] += 1
        if not row["ge65_sprsn_flag"] and row["ge65_tot_clms"] is None:
            issues["ge65_count_blank_without_flag"] += 1
        if row["is_obesity_brand"] == "true":
            issues["obesity_brand_rows"] += 1
        out.append(row)

    report["partd_issues"] = dict(sorted(issues.items()))
    report["partd_rows_by_class"] = dict(Counter(r["drug_class"] for r in out).most_common())
    return out


def clean_nucc(version):
    path = RAW / "nucc" / f"nucc_taxonomy_{version}.csv"
    with open(path, newline="", encoding="utf-8") as f:
        rows = [{snake(k.replace(" ", "")): tidy(v) for k, v in r.items()} for r in csv.DictReader(f)]
    return rows


def clean_npi(claims, nucc_codes, report):
    # CMS-side prescriber attributes; check they are consistent per NPI.
    cms = defaultdict(lambda: defaultdict(set))
    for r in claims:
        for k in ("prscrbr_last_org_name", "prscrbr_first_name", "prscrbr_city",
                  "prscrbr_type", "prscrbr_type_src"):
            cms[r["prscrbr_npi"]][k].add(r[k] or "")

    prescribers, taxonomies, issues = [], [], Counter()
    for npi in sorted(cms):
        attrs = {k: sorted(v) for k, v in cms[npi].items()}
        for k, vals in attrs.items():
            if len(vals) > 1:
                issues[f"inconsistent_{k}"] += 1
        row = {"npi": npi, **{k: " | ".join(v) for k, v in attrs.items()}}

        path = RAW / "npi" / f"{npi}.json"
        if not path.exists():
            issues["npi_record_missing_run_fetch_npi"] += 1
            prescribers.append(row)
            continue
        body = json.loads(path.read_text())
        results = body.get("results") or []
        if not results:
            issues["npi_not_found_in_registry"] += 1
            row["registry_status"] = "not found"
            prescribers.append(row)
            continue

        rec = results[0]
        basic = rec.get("basic", {})
        row.update({
            "registry_status": basic.get("status"),
            "enumeration_type": rec.get("enumeration_type"),
            "credential": tidy(basic.get("credential")),
            "sex": basic.get("sex") or basic.get("gender"),
            "last_updated": basic.get("last_updated"),
        })
        primary = [t for t in rec.get("taxonomies", []) if t.get("primary")]
        if len(primary) != 1:
            issues[f"primary_taxonomy_count_{len(primary)}"] += 1
        if primary:
            row["primary_taxonomy_code"] = primary[0]["code"]
            row["primary_taxonomy_desc"] = primary[0]["desc"]
        for t in rec.get("taxonomies", []):
            if t["code"] not in nucc_codes:
                issues["taxonomy_code_not_in_nucc"] += 1
            taxonomies.append({"npi": npi, "taxonomy_code": t["code"], "taxonomy_desc": t["desc"],
                               "is_primary": str(bool(t.get("primary"))).lower(),
                               "license_state": t.get("state")})
        prescribers.append(row)

    report["prescriber_count"] = len(prescribers)
    report["npi_issues"] = dict(sorted(issues.items()))
    report["top_primary_taxonomies"] = dict(Counter(
        p.get("primary_taxonomy_desc") for p in prescribers).most_common(15))
    return prescribers, taxonomies


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nucc-version", default="261")
    args = ap.parse_args()
    CLEAN.mkdir(parents=True, exist_ok=True)
    report = {}

    with open(ROOT / "scripts" / "drugs.csv", newline="") as f:
        drugs = {r["gnrc_name"]: r for r in csv.DictReader(f)}

    # Brands whose FDA labels state no diabetes indication (Wegovy), from scripts/resolve_products.py.
    with open(ROOT / "scripts" / "products.csv", newline="") as f:
        obesity_brands = {r["brnd_name"] for r in csv.DictReader(f)
                          if not set(r["indications"].split("|")) & DIABETES_INDICATIONS}
    claims = clean_partd(drugs, obesity_brands, report)
    claim_fields = list(claims[0].keys())
    write_csv(CLEAN / "partd_claims.csv", claims, claim_fields)

    nucc = clean_nucc(args.nucc_version)
    write_csv(CLEAN / "nucc_taxonomy.csv", nucc, list(nucc[0].keys()))
    report["nucc_codes"] = len(nucc)

    prescribers, taxonomies = clean_npi(claims, {r["code"] for r in nucc}, report)
    write_csv(CLEAN / "prescribers.csv", prescribers,
              ["npi", "prscrbr_last_org_name", "prscrbr_first_name", "prscrbr_city",
               "prscrbr_type", "prscrbr_type_src", "registry_status", "enumeration_type",
               "credential", "sex", "last_updated", "primary_taxonomy_code", "primary_taxonomy_desc"])
    write_csv(CLEAN / "npi_taxonomies.csv", taxonomies,
              ["npi", "taxonomy_code", "taxonomy_desc", "is_primary", "license_state"])

    (CLEAN / "cleaning_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
