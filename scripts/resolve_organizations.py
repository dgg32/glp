"""Resolve Drugs@FDA application holders (sponsors) to companies via GLEIF.

Run after resolve_products.py (brands come from scripts/products.csv).

Curated: vocab/src/sponsor_lei.csv, one row per Drugs@FDA sponsor name. Drugs@FDA abbreviates
names ("MSD", "NOVO", "JANSSEN PHARMS") and automatic GLEIF search maps 5 of 13 to the wrong
entity, so each row names the applicant and how it maps to GLEIF (`match`):
  applicant  the applicant has a current LEI: `lei`, found by a legal-name search for `gleif_search`
  group      the applicant has no current LEI: `lei` is the top-level entity of its group, the
             ultimate parent of most GLEIF autocompletion matches for `gleif_search`
  none       neither exists (Amylin, dissolved in 2012); the sponsor keeps its Drugs@FDA name
Every run re-runs these searches and stops if the evidence no longer holds: the applicant row's
LEI must carry exactly that legal name; a group row's applicant must have no current LEI and its
LEI must be a top-level entity that wins the parent vote. A sponsor missing from the table also
stops the script.

The company is the GLEIF ultimate parent of the LEI (itself when it has none).

API responses are cached in data/raw/{drugsfda,gleif}/, so reruns are offline.

Output (generated, do not edit): scripts/organizations.csv, one row per sponsor name.

Usage: python3 scripts/resolve_organizations.py
"""
import csv
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

from build_rdf import drugsfda_sponsors
from build_skos import RAW, ROOT, read_csv, slug

GLEIF = "https://api.gleif.org/api/v1/"


def gleif(cache_name, path):
    cache = RAW / "gleif" / cache_name
    if not cache.exists():
        for attempt in range(4):
            time.sleep(1.1)  # GLEIF allows 60 requests per minute
            try:
                with urllib.request.urlopen(GLEIF + path, timeout=60) as resp:
                    body = json.load(resp)
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 404:  # e.g. no ultimate parent on record
                    body = {"data": None}
                    break
                time.sleep(10 * (attempt + 1))
            except OSError:  # URLError, timeouts, DNS failures
                time.sleep(10 * (attempt + 1))
        else:
            raise RuntimeError(f"GLEIF request failed: {path}")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(body, ensure_ascii=False, indent=1))
    return json.loads(cache.read_text())["data"]


def entity(lei):
    data = gleif(f"lei_{lei}.json", f"lei-records/{lei}")
    if not data:
        raise SystemExit(f"LEI {lei} not found in GLEIF; fix vocab/src/sponsor_lei.csv")
    a = data["attributes"]
    return {"lei": lei, "name": a["entity"]["legalName"]["name"], "status": a["registration"]["status"],
            "country": a["entity"]["legalAddress"]["country"]}


LEGAL_FORMS = {"inc", "llc", "lp", "ltd", "co", "corp", "plc", "ab", "ag", "gmbh", "sa", "as"}


def norm(name):
    name = name.lower().replace("&", " and ").replace(".", "")
    return " ".join(re.sub(r"[^\w]+", " ", name).split())


def legal_name_search(term):
    """GLEIF records whose legal name contains the words of term (legal-form words dropped)."""
    words = " ".join(w.strip(",") for w in term.split() if norm(w) not in LEGAL_FORMS)
    query = urllib.parse.urlencode({"filter[entity.legalName]": words, "page[size]": 200})
    data = gleif(f"legalname_{slug(words)}.json", f"lei-records?{query}")
    if len(data or []) == 200:
        raise SystemExit(f"GLEIF search {words!r} is too broad to check; use a more specific gleif_search")
    return [(r["attributes"]["lei"], r["attributes"]["entity"]["legalName"]["name"],
             r["attributes"]["registration"]["status"]) for r in data or []]


def top_of(lei):
    parent = gleif(f"ultimate_parent_{lei}.json", f"lei-records/{lei}/ultimate-parent")
    return parent["attributes"]["lei"] if parent else lei


def group_vote(term):
    """Counter of ultimate-parent LEIs over GLEIF autocompletion matches that start with term."""
    query = urllib.parse.urlencode({"field": "fulltext", "q": term})
    data = gleif(f"autocomplete_{slug(term)}.json", f"autocompletions?{query}")
    matches = [m["relationships"]["lei-records"]["data"]["id"] for m in data or []
               if m.get("relationships", {}).get("lei-records")
               and (norm(m["attributes"]["value"]) + " ").startswith(norm(term) + " ")]
    return Counter(top_of(lei) for lei in matches), len(matches)


def check(row):
    """Re-run the evidence for one curated row; return a one-line summary or stop."""
    sponsor, applicant, lei = row["sponsor_name"], row["applicant_name"], row["lei"]
    current = [(l, n) for l, n, status in legal_name_search(applicant)
               if norm(n) == norm(applicant) and status == "ISSUED"]
    if row["match"] == "applicant":
        if norm(row["gleif_search"]) not in norm(applicant):
            raise SystemExit(f"{sponsor}: gleif_search must be part of the applicant name")
        if lei not in {l for l, _ in current}:
            raise SystemExit(f"{sponsor}: no current LEI {lei} named {applicant!r} in GLEIF")
        return f"legal-name search {row['gleif_search']!r} finds {applicant} = {lei}"
    if current:
        raise SystemExit(f"{sponsor}: {applicant!r} has a current LEI {current[0][0]}; use match=applicant")
    votes, n = group_vote(row["gleif_search"])
    if row["match"] == "none":
        if votes:
            raise SystemExit(f"{sponsor}: GLEIF now has matches for {row['gleif_search']!r}; review this row")
        return f"no current LEI for {applicant}; no GLEIF match for {row['gleif_search']!r}"
    winner, k = votes.most_common(1)[0] if votes else (None, 0)
    if winner != lei or top_of(lei) != lei:
        raise SystemExit(f"{sponsor}: {lei} is not the top-level parent of most {row['gleif_search']!r} matches "
                         f"({dict(votes)})")
    return f"no current LEI for {applicant}; {k}/{n} {row['gleif_search']!r} matches have top parent {lei}"


def main():
    with open(ROOT / "scripts" / "products.csv", newline="") as f:
        brands = sorted({r["fda_brand"] for r in csv.DictReader(f) if r["fda_brand"]})
    sponsors = sorted({s for b in brands for s, _ in drugsfda_sponsors(b)})
    curated = {r["sponsor_name"]: r for r in read_csv("sponsor_lei.csv")}
    missing = [s for s in sponsors if s not in curated]
    if missing:
        raise SystemExit(f"Drugs@FDA sponsors missing from vocab/src/sponsor_lei.csv: {missing}")

    rows = []
    for sponsor in sponsors:
        c = curated[sponsor]
        evidence = check(c)
        row = {"sponsor_name": sponsor, "applicant_name": c["applicant_name"], "match": c["match"],
               "applicant_lei": c["lei"] if c["match"] == "applicant" else "",
               "organization": slug(sponsor), "legal_name": sponsor, "country": "", "lei": "", "evidence": evidence}
        if c["lei"]:
            company = entity(top_of(c["lei"]))
            row.update({"organization": company["lei"], "legal_name": company["name"],
                        "country": company["country"], "lei": company["lei"]})
        rows.append(row)
        print(f"{sponsor:20} {c['match']:9} -> {row['legal_name']:34} [{evidence}]")

    with open(ROOT / "scripts" / "organizations.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote scripts/organizations.csv ({len(rows)} sponsors, "
          f"{len({r['organization'] for r in rows})} organizations)")


if __name__ == "__main__":
    main()
