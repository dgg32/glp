"""Resolve CMS generic names to RxNorm ingredients, ATC codes and drug classes.

Input (curated): scripts/cms_generic_names.csv, the CMS Part D spellings to download. The
optional rxnorm_term column overrides the search term where CMS abbreviates a name beyond
what RxNorm can match (three names; each row says why).

Every other fact is looked up; nothing about a drug is typed by hand:
  1. CMS name -> RxCUI         RxNorm exact (normalized) match, else RxNorm approximate match
  2. RxCUI -> ingredients      RxNorm related concepts of type IN; the substance id is the
                               ingredient name in camelCase (insulin glargine -> insulinGlargine)
  3. ingredient -> ATC code    the ingredient's own level-5 ATC code in RxNorm (metformin A10BA02).
                               (RxClass's ATC lookup is not used: it credits combination codes to
                               every ingredient, which puts liraglutide among the insulins via Xultophy.)
  4. ATC code -> drug class    level 4 of the code (A10BA02 -> A10BA), matched to the atc column of
                               vocab/src/therapeutic_classes.csv. If ATC has no project class
                               (tirzepatide is A10BX "other"), the FDA Established Pharmacologic
                               Class from RxClass decides, by the fda_epc column.
  5. MeSH ID                   the MeSH record whose label is the RxNorm name or a synonym
  6. synonyms                  RxNorm synonyms (glyburide: glibenclamide) and precise-ingredient
                               names (salts: metformin hydrochloride), and the CMS spellings of
                               single-ingredient generics
Any ingredient that does not land in a diabetes drug class stops the script, which catches
wrong fuzzy matches (RxNorm matches "Dapaglifloz Propaned/Metformin" to "propane").

API responses are cached in data/raw/rxnav/, so reruns are offline. (KEGG's ATC tree was tried
and gave the same codes, but its API is licensed for academic use only; see docs/decisions.md.)

Outputs (generated, do not edit):
  scripts/drugs.csv       one row per CMS generic name: substances, classes, RxCUI
  scripts/substances.csv  one row per substance: RxCUI, ATC, class and its evidence, synonyms

Usage: python3 scripts/resolve_drugs.py
"""
import csv
import urllib.parse

from build_skos import RAW, ROOT, cached_json, mesh_records, read_csv, slug

RXNAV = "https://rxnav.nlm.nih.gov/REST/"


def rxnav(cache_name, path, **params):
    url = RXNAV + path + ("?" + urllib.parse.urlencode(params) if params else "")
    return cached_json(RAW / "rxnav" / cache_name, url)


def rxnorm_name(rxcui):
    return rxnav(f"props_{rxcui}.json", f"rxcui/{rxcui}/properties.json")["properties"]["name"]


def resolve_rxcui(term):
    """(rxcui, name, method) for a drug name."""
    ids = rxnav(f"rxcui2_{slug(term)}.json", "rxcui.json", name=term, search=2)
    ids = ids.get("idGroup", {}).get("rxnormId") or []
    if len(ids) == 1:
        return ids[0], rxnorm_name(ids[0]), "exact"
    body = rxnav(f"approx_{slug(term)}.json", "approximateTerm.json", term=term, maxEntries=5, option=0)
    cands = [c for c in body.get("approximateGroup", {}).get("candidate", []) if c.get("source") == "RXNORM"]
    if not cands:
        raise SystemExit(f"RxNorm has no match for {term!r}; set rxnorm_term in scripts/cms_generic_names.csv")
    return cands[0]["rxcui"], cands[0]["name"], "approximate"


def related(rxcui, tty):
    body = rxnav(f"related_{tty.lower()}_{rxcui}.json", f"rxcui/{rxcui}/related.json", tty=tty)
    return sorted({c["rxcui"] for g in body["relatedGroup"].get("conceptGroup", [])
                   for c in g.get("conceptProperties", [])})


def rxclass(rxcui, source, relas=None):
    params = {"rxcui": rxcui, "relaSource": source}
    if relas:
        params["relas"] = relas
    body = rxnav(f"rxclass_{source.lower()}_{rxcui}.json", "rxclass/class/byRxcui.json", **params)
    return {i["rxclassMinConceptItem"]["classId"]
            for i in body.get("rxclassDrugInfoList", {}).get("rxclassDrugInfo", [])}


def rxnorm_codes(rxcui, prop):
    body = rxnav(f"{prop}_{rxcui}.json", f"rxcui/{rxcui}/allProperties.json", prop=prop)
    return [(p["propName"], p["propValue"]) for p in body.get("propConceptGroup", {}).get("propConcept", [])]


def atc_codes(rxcui):
    return sorted({v for k, v in rxnorm_codes(rxcui, "codes") if k == "ATC"})


def synonyms(rxcui, name):
    names = {v.lower() for k, v in rxnorm_codes(rxcui, "names") if k == "RxNorm Synonym"}
    names |= {rxnorm_name(p).lower() for p in related(rxcui, "PIN")}
    return sorted(names - {name})


def classify(atc, rxcui, by_atc, by_epc):
    """(class id, evidence) for an ingredient, or None."""
    hits = {by_atc[c[:5]] for c in atc if c[:5] in by_atc}
    evidence = "ATC " + ",".join(sorted(c for c in atc if c[:5] in by_atc))
    if not hits:
        epc = {c for c in rxclass(rxcui, "FDASPL", "has_epc") if c in by_epc}
        hits, evidence = {by_epc[c] for c in epc}, "FDA EPC " + ",".join(sorted(epc))
    if len(hits) != 1:
        return None
    return hits.pop(), evidence


def camel(name):
    words = name.split()
    return words[0] + "".join(w.capitalize() for w in words[1:])


def main():
    from resolve_vocab import class_names  # class labels from the RxClass ATC tree
    rxnav("version.json", "version.json")  # RxNorm release, cached with the responses (for provenance)
    classes = read_csv("therapeutic_classes.csv")
    order = [c["id"] for c in classes]
    label = {cid: name for cid, (name, _) in class_names(classes).items()}
    by_atc = {c["atc"]: c["id"] for c in classes if len(c["atc"]) == 5}
    by_epc = {c["fda_epc"]: c["id"] for c in classes if c["fda_epc"]}

    with open(ROOT / "scripts" / "cms_generic_names.csv", newline="") as f:
        names = list(csv.DictReader(f))

    drugs, subs = [], {}
    for n in names:
        rxcui, rx_name, method = resolve_rxcui(n["rxnorm_term"] or n["gnrc_name"])
        ins = related(rxcui, "IN")
        if not ins:
            raise SystemExit(f"{n['gnrc_name']!r} -> {rx_name!r} has no RxNorm ingredients")
        rows = []
        for i in ins:
            name = rxnorm_name(i)
            atc = atc_codes(i)
            hit = classify(atc, i, by_atc, by_epc)
            if hit is None:
                raise SystemExit(f"{n['gnrc_name']!r} -> {rx_name!r}: ingredient {name!r} has no diabetes drug "
                                 "class in ATC or FDA EPC (wrong match? set rxnorm_term)")
            sid = camel(name)
            s = subs.setdefault(sid, {"substance": sid, "rxcui": i, "rxnorm_name": name, "atc": "|".join(atc),
                                      "therapeutic_class": hit[0], "class_evidence": hit[1],
                                      "alt_en": "|".join(synonyms(i, name)),
                                      "cms_names": []})
            if len(ins) == 1:
                s["cms_names"].append(n["gnrc_name"])
            rows.append((order.index(hit[0]), sid, hit[0]))
        rows.sort()
        drugs.append({"gnrc_name": n["gnrc_name"],
                      "drug_class": " + ".join(label[c] for _, _, c in rows),
                      "is_combination": str(len(rows) > 1).lower(),
                      "substances": "|".join(s for _, s, _ in rows),
                      "rxcui": rxcui, "rxnorm_name": rx_name, "rxnorm_match": method})
        print(f"{n['gnrc_name']:32} -> {rx_name} [{method}] -> {drugs[-1]['drug_class']}")

    mesh = mesh_records([n for s in subs.values() for n in [s["rxnorm_name"]] + s["alt_en"].split("|") if n])
    for s in subs.values():
        s["cms_names"] = "|".join(s["cms_names"])
        found = [n for n in [s["rxnorm_name"]] + s["alt_en"].split("|") if n in mesh]
        s["mesh"] = str(mesh[found[0]]).rsplit("/", 1)[1] if found else ""
    for path, rows in [("drugs.csv", drugs), ("substances.csv", sorted(subs.values(), key=lambda r: r["substance"]))]:
        with open(ROOT / "scripts" / path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    print(f"\nwrote scripts/drugs.csv ({len(drugs)} names), scripts/substances.csv ({len(subs)} substances)")


if __name__ == "__main__":
    main()
