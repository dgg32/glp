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

Japan (NDB Open Data, added 2026-10-25). Curated: vocab/src/ndb_ingredients.csv maps each YJ ingredient
code to substance ids, and vocab/src/ndb_substances.csv gives the English name of each substance the
US data lacks. RxNorm covers US drugs only, so 12 Japanese ingredients (teneligliptin, ipragliflozin,
...) are not in it; they are looked up in UMLS instead (exact name -> CUI; ATC code from the UMLS ATC
source). Classification then also uses, in this order after step 4:
  - several ATC classes: their common broader class (insulin lispro is A10AB04 fast-acting and
    A10AD04 premixed, so the substance is in "insulins and analogues"; the product decides the profile)
  - a project class defined by ATC level-5 codes (glinides: A10BX02, A10BX03, A10BX08)
  - no ATC code (anagliptin, trelagliptin, ...): the class of the substances that share its MeSH
    pharmacological action, if that action is held by one class only
  - the curated fallback_class of vocab/src/ndb_substances.csv, if nothing else applies (glyclopyramide)
The Japanese 成分名 spellings of single-ingredient YJ codes become ndb_names (hidden labels).

API responses are cached in data/raw/rxnav/, so reruns are offline. (KEGG's ATC tree was tried
and gave the same codes, but its API is licensed for academic use only; see docs/decisions.md.)

Outputs (generated, do not edit):
  scripts/drugs.csv       one row per CMS generic name: substances, classes, RxCUI
  scripts/substances.csv  one row per substance: RxCUI or UMLS CUI, ATC, class and its evidence, synonyms

Usage: python3 scripts/resolve_drugs.py
"""
import csv
import urllib.parse

from build_skos import RAW, ROOT, cached_json, mesh_records, read_csv, slug, split

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


def classify(atc, rxcui, by_atc, by_epc, by_member):
    """(class id, evidence) for an ingredient, or None."""
    codes = sorted(c for c in atc if c[:5] in by_atc)
    hits, evidence = {by_atc[c[:5]] for c in codes}, "ATC " + ",".join(codes)
    if len(hits) > 1:  # several ATC classes: their common broader class (ATC codes nest by prefix)
        common = next(n for n in (4, 3, 1) if len({c[:n] for c in codes}) == 1)
        hits, evidence = {by_atc.get(codes[0][:common])} - {None}, evidence + " (common broader class)"
    if not hits:
        members = sorted(c for c in atc if c in by_member)
        hits, evidence = {by_member[c] for c in members}, "ATC " + ",".join(members) + " (project class member)"
    if not hits and rxcui:
        epc = {c for c in rxclass(rxcui, "FDASPL", "has_epc") if c in by_epc}
        hits, evidence = {by_epc[c] for c in epc}, "FDA EPC " + ",".join(sorted(epc))
    if len(hits) != 1:
        return None
    return hits.pop(), evidence


def umls_lookup(term):
    """(CUI, ATC codes) of the UMLS concept with this exact name, for substances not in RxNorm."""
    from resolve_vocab import umls_get
    found = umls_get(f"search_exact_{slug(term)}.json", "search/current", string=term, searchType="exact")
    concepts = found.get("result", {}).get("results", [])
    if len(concepts) != 1:
        raise SystemExit(f"UMLS: {len(concepts)} concepts named {term!r}; expected exactly one")
    cui = concepts[0]["ui"]
    atoms = umls_get(f"atoms_atc_{cui}.json", f"content/current/CUI/{cui}/atoms", sabs="ATC").get("result") or []
    return cui, sorted({a["code"].rsplit("/", 1)[-1] for a in atoms} if isinstance(atoms, list) else set())


def rxnorm_ingredient(term):
    """(RxCUI, name) of the RxNorm ingredient with this (normalized) name, or None. Exact matches only:
    an approximate match of a Japan-only name would be a different drug."""
    ids = rxnav(f"rxcui2_{slug(term)}.json", "rxcui.json", name=term, search=2).get("idGroup", {}).get("rxnormId") or []
    ins = [i for i in ids if rxnav(f"props_{i}.json", f"rxcui/{i}/properties.json")["properties"]["tty"] == "IN"]
    return (ins[0], rxnorm_name(ins[0])) if len(ins) == 1 else None


def by_shared_action(subs, deferred):
    """Classify substances without ATC or FDA class by their MeSH pharmacological actions: an action held
    only by substances of one class decides. Returns {substance: (class, evidence)}."""
    from resolve_vocab import pharmacological_actions
    actions = pharmacological_actions({s["mesh"] for s in subs.values() if s["mesh"]})
    classes_of = {}
    for s in subs.values():
        if s["substance"] not in deferred:
            for a in actions.get(s["mesh"], ()):
                classes_of.setdefault(a, set()).add(s["therapeutic_class"])
    out = {}
    for sid in deferred:
        decisive = {a: next(iter(classes_of[a])) for a in actions.get(subs[sid]["mesh"], ())
                    if len(classes_of.get(a, ())) == 1}
        if len(set(decisive.values())) == 1:
            out[sid] = (next(iter(decisive.values())), "MeSH pharmacological action " + ",".join(sorted(decisive)))
    return out


def camel(name):
    words = name.split()
    return words[0] + "".join(w.capitalize() for w in words[1:])


def main():
    from resolve_vocab import class_names  # class labels from the RxClass ATC tree
    rxnav("version.json", "version.json")  # RxNorm release, cached with the responses (for provenance)
    classes = read_csv("therapeutic_classes.csv")
    order = [c["id"] for c in classes]
    label = {cid: name for cid, (name, _) in class_names(classes).items()}
    by_atc = {c["atc"]: c["id"] for c in classes if c["atc"]}  # level 4 for lookups, upper levels for common classes
    by_epc = {c["fda_epc"]: c["id"] for c in classes if c["fda_epc"]}
    by_member = {code: c["id"] for c in classes for code in split(c["atc_members"])}

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
            hit = classify(atc, i, by_atc, by_epc, by_member)
            if hit is None:
                raise SystemExit(f"{n['gnrc_name']!r} -> {rx_name!r}: ingredient {name!r} has no diabetes drug "
                                 "class in ATC or FDA EPC (wrong match? set rxnorm_term)")
            sid = camel(name)
            s = subs.setdefault(sid, {"substance": sid, "rxcui": i, "umls_cui": "", "rxnorm_name": name,
                                      "pref_en": name, "atc": "|".join(atc),
                                      "therapeutic_class": hit[0], "class_evidence": hit[1],
                                      "alt_en": "|".join(synonyms(i, name)),
                                      "cms_names": [], "ndb_names": []})
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

    # Japan: substances that NDB Open Data has and the CMS data does not
    deferred = {}
    for n in read_csv("ndb_substances.csv"):
        sid, term = n["substance"], n["search_term"]
        if sid in subs:
            raise SystemExit(f"{sid} is already a CMS substance; remove it from vocab/src/ndb_substances.csv")
        rx = rxnorm_ingredient(term)
        if rx:
            rxcui, name, cui, atc = rx[0], rx[1], "", atc_codes(rx[0])
        else:
            rxcui, name, (cui, atc) = "", "", umls_lookup(term)
        hit = classify(atc, rxcui, by_atc, by_epc, by_member)
        subs[sid] = {"substance": sid, "rxcui": rxcui, "umls_cui": cui, "rxnorm_name": name, "pref_en": term,
                     "atc": "|".join(atc), "therapeutic_class": hit[0] if hit else "",
                     "class_evidence": hit[1] if hit else "",
                     "alt_en": "|".join(sorted(set(synonyms(rxcui, name) if rxcui else []) | ({name} - {term, ""}))),
                     "cms_names": [], "ndb_names": []}
        if not hit:
            deferred[sid] = n["fallback_class"]
        print(f"{'(NDB) ' + term:32} -> {'RxNorm ' + rxcui if rxcui else 'UMLS ' + cui} ATC {','.join(atc) or '-'}"
              f" -> {hit[0] if hit else 'deferred'}")
    for y in read_csv("ndb_ingredients.csv"):
        ids = split(y["substances"])
        unknown = [i for i in ids if i not in subs]
        if unknown:
            raise SystemExit(f"YJ {y['yj7']}: unknown substances {unknown}; add them to vocab/src/ndb_substances.csv")
        if len(ids) == 1:
            subs[ids[0]]["ndb_names"].append(y["ingredient_ja"])

    mesh = mesh_records([n for s in subs.values() for n in [s["pref_en"], s["rxnorm_name"]] + s["alt_en"].split("|") if n])
    for s in subs.values():
        s["cms_names"] = "|".join(s["cms_names"])
        s["ndb_names"] = "|".join(sorted(set(s["ndb_names"])))
        found = [n for n in [s["pref_en"], s["rxnorm_name"]] + s["alt_en"].split("|") if n in mesh]
        s["mesh"] = str(mesh[found[0]]).rsplit("/", 1)[1] if found else ""
    for sid, (cid, evidence) in by_shared_action(subs, deferred).items():
        subs[sid].update(therapeutic_class=cid, class_evidence=evidence)
    for sid, fallback in deferred.items():
        if not subs[sid]["therapeutic_class"]:
            if not fallback:
                raise SystemExit(f"{sid}: no class from ATC, FDA EPC or MeSH; set fallback_class in "
                                 "vocab/src/ndb_substances.csv (with the reason in its note)")
            subs[sid].update(therapeutic_class=fallback, class_evidence="curated fallback (ndb_substances.csv)")
        print(f"  {sid}: {subs[sid]['therapeutic_class']} from {subs[sid]['class_evidence']}")
    for path, rows in [("drugs.csv", drugs), ("substances.csv", sorted(subs.values(), key=lambda r: r["substance"]))]:
        with open(ROOT / "scripts" / path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    print(f"\nwrote scripts/drugs.csv ({len(drugs)} names), scripts/substances.csv ({len(subs)} substances)")


if __name__ == "__main__":
    main()
