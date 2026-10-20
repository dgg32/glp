"""Resolve the CMS brand names in the Part D downloads to RxNorm brands and FDA-label indications.

Run after download_partd.py (brand names come from data/raw/partd/) and resolve_drugs.py (each
generic's substances come from scripts/drugs.csv / substances.csv), before clean_data.py.

  1. brand        the longest leading run of words in the CMS brand name that is an RxNorm brand
                  name (BN) with the same ingredients as the CMS generic: "Victoza 2-Pak" -> Victoza,
                  "Basaglar Kwikpen U-100" -> Basaglar. No such brand = a multi-source generic
                  ("Metformin Hcl Er", "Insulin Glargine Solostar").
  2. FDA labels   the brand's RxNorm branded drugs (SBD), or for a generic the RxNorm clinical drugs
                  (SCD) that contain all of the generic's ingredients, looked up in openFDA drug labels by openfda.rxcui. Only
                  prescription labels with the same number of active substances count, so a
                  metformin query does not pick up Janumet. A brand without a current label in
                  openFDA (Bydureon BCise is discontinued) falls back to the labels of products
                  with the same ingredients; the label_source column says which was used.
  3. indications  each label's "Indications and usage" section, minus sentences that limit use
                  ("not recommended in patients with type 1 diabetes"), searched for the MeSH entry
                  terms of each indication in scripts/indications.csv (from resolve_vocab.py); a
                  broader MeSH term such as "diabetes mellitus" (insulin labels) implies type 1 and
                  type 2. An indication is kept when more than half of the product's labels state it.

API responses are cached in data/raw/{rxnav,openfda-label}/, so reruns are offline.

Output (generated, do not edit): scripts/products.csv

Usage: python3 scripts/resolve_products.py
"""
import csv
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

from build_skos import RAW, ROOT, cached_json, slug
from resolve_drugs import related, rxnav, rxnorm_name

LABELS = "https://api.fda.gov/drug/label.json"
LIMITING = re.compile(r"limitations of use|\bnot (for|recommended|indicated|been studied|been established|to be used)\b|"
                      r"should not", re.I)


def openfda_labels(rxcuis):
    """openFDA label records whose openfda.rxcui is any of rxcuis (cached per query batch)."""
    out = {}
    for start in range(0, len(rxcuis), 40):
        batch = rxcuis[start:start + 40]
        search = "openfda.rxcui:(" + " ".join(f'"{r}"' for r in batch) + ")"
        cache = RAW / "openfda-label" / f"rxcui_{hashlib.sha256(search.encode()).hexdigest()[:16]}.json"
        if cache.exists():
            results = json.loads(cache.read_text())
        else:
            results, skip = [], 0
            while True:
                url = f"{LABELS}?{urllib.parse.urlencode({'search': search, 'limit': 100, 'skip': skip})}"
                for attempt in range(4):
                    try:
                        with urllib.request.urlopen(url, timeout=60) as resp:
                            body = json.load(resp)
                        break
                    except urllib.error.HTTPError as exc:
                        if exc.code == 404:  # openFDA answers "no matches" with 404
                            body = {"results": [], "meta": {"results": {"total": 0}}}
                            break
                        time.sleep(5 * (attempt + 1))
                else:
                    raise RuntimeError(f"openFDA label lookup failed: {search}")
                results += body["results"]
                skip += 100
                if skip >= body["meta"]["results"]["total"]:
                    break
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(results, indent=1))
        for r in results:
            if r["set_id"] not in out or int(r["version"]) > int(out[r["set_id"]]["version"]):
                out[r["set_id"]] = r
    return list(out.values())


def term_spans(text, terms):
    return [(m.start(), m.end()) for t in terms
            for m in re.finditer(r"(?<!\w)" + re.escape(t) + r"(?!\w)", text, re.I)]


def stated_indications(label, indications):
    """Indications whose MeSH entry terms occur in the label's indications section. A broader term
    ("diabetes mellitus") implies its narrower indications unless it is part of a narrower match."""
    text = " ".join(label.get("indications_and_usage", []))
    # split into sentences and bullets, and before "Limitations of Use", which some labels run on
    # without a full stop ("... with type 2 diabetes mellitus Limitations of Use: ...")
    sentences = re.split(r"(?<=[.;])\s+|\s*[•●]\s*|\s+(?=limitations of use)", re.sub(r"\s+", " ", text), flags=re.I)
    text = " ".join(s for s in sentences if not LIMITING.search(s))
    direct = {i["id"]: term_spans(text, i["match_terms"].split("|")) for i in indications}
    found = {i for i, spans in direct.items() if spans}
    taken = [span for spans in direct.values() for span in spans]
    for i in indications:
        implied = [t for t in i["implied_by_terms"].split("|") if t]
        if any(not any(a < e and s < b for s, e in taken) for a, b in term_spans(text, implied)):
            found.add(i["id"])
    return found


def product_labels(concepts, ingredient_rxcuis):
    return [l for l in openfda_labels(concepts)
            if "HUMAN PRESCRIPTION DRUG" in l.get("openfda", {}).get("product_type", [])
            and len(l["openfda"].get("substance_name", [])) == len(ingredient_rxcuis)]


def find_brand(cms_brand, ingredient_rxcuis):
    words = re.sub(r"\([^)]*\)", " ", cms_brand).split()
    for k in range(len(words), 0, -1):
        term = " ".join(words[:k])
        ids = rxnav(f"rxcui2_{slug(term)}.json", "rxcui.json", name=term, search=2)
        for rxcui in ids.get("idGroup", {}).get("rxnormId") or []:
            props = rxnav(f"props_{rxcui}.json", f"rxcui/{rxcui}/properties.json")["properties"]
            if props["tty"] == "BN" and set(related(rxcui, "IN")) == ingredient_rxcuis:
                return rxcui, props["name"]
    return None, None


def main():
    drugs = {r["gnrc_name"]: r for r in csv.DictReader(open(ROOT / "scripts" / "drugs.csv", newline=""))}
    substance_rxcui = {r["substance"]: r["rxcui"]
                       for r in csv.DictReader(open(ROOT / "scripts" / "substances.csv", newline=""))}
    with open(ROOT / "scripts" / "indications.csv", newline="", encoding="utf-8") as f:
        indication_terms = list(csv.DictReader(f))
    tidy = lambda v: re.sub(r"\s+", " ", v).strip()
    brand_generic = sorted({(tidy(r["Brnd_Name"]), tidy(r["Gnrc_Name"]))
                            for path in (RAW / "partd").glob("*.json") for r in json.loads(path.read_text())})

    # openFDA label index date, cached with the responses (for provenance)
    cached_json(RAW / "openfda-label" / "meta.json", LABELS + "?limit=1")
    rows = []
    for brand, generic in brand_generic:
        drug = drugs[generic]
        ingredient_rxcuis = {substance_rxcui[s] for s in drug["substances"].split("|")}
        bn_rxcui, bn_name = find_brand(brand, ingredient_rxcuis)
        labels, label_source = [], ""
        if bn_rxcui:
            labels, label_source = product_labels(related(bn_rxcui, "SBD"), ingredient_rxcuis), "brand"
        if not labels:  # generic, or a discontinued brand whose label openFDA no longer carries
            # clinical drugs that contain every ingredient (salt-form concepts have no SCD links)
            scd = sorted(set.intersection(*(set(related(i, "SCD")) for i in ingredient_rxcuis)))
            labels, label_source = product_labels(scd, ingredient_rxcuis), "same ingredients"
        votes = Counter(i for l in labels for i in stated_indications(l, indication_terms))
        indications = sorted(i for i, n in votes.items() if n > len(labels) / 2)
        if not indications:
            raise SystemExit(f"{brand}: no indication found in {len(labels)} FDA labels")
        rows.append({"brnd_name": brand, "gnrc_name": generic, "rxnorm_brand": bn_name or "",
                     "rxnorm_brand_rxcui": bn_rxcui or "", "fda_brand": (bn_name or "").upper(),
                     "indications": "|".join(indications), "label_source": label_source, "fda_labels": len(labels),
                     "label_votes": "; ".join(f"{i} {n}/{len(labels)}" for i, n in sorted(votes.items()))})
        print(f"{brand:28} -> {bn_name or '(generic)':12} {rows[-1]['indications']:28} [{label_source}: {rows[-1]['label_votes']}]")

    with open(ROOT / "scripts" / "products.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote scripts/products.csv ({len(rows)} products)")


if __name__ == "__main__":
    main()
