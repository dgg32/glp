"""Resolve the drug class tree and the indication concepts from RxClass, UMLS and MeSH.

Run after resolve_drugs.py (it reads each substance's class and MeSH ID from scripts/substances.csv)
and before resolve_products.py (which reads scripts/indications.csv).

Drug classes. Curated (vocab/src/therapeutic_classes.csv): which classes exist (id = stable IRI
name, plus its ATC code), the Japanese and Chinese labels, and the one project class (dual GIP/GLP-1
agonists, defined by an FDA EPC code and placed under GLP-1 receptor agonists by decision; its
English label, definition and scope note are curated too). Looked up:
  - hierarchy and English prefLabel: the ATC tree in RxClass (levels 1-3 are written in capitals
    by WHO and are converted to sentence case)
  - MeSH link, in this order: (1) a MeSH descriptor that NLM's Metathesaurus editors relate to the
    ATC class in UMLS (needs UMLS_API_KEY in .env); (2) the MeSH pharmacological action held by all
    member substances that have one and by no other substance; (3) the curated mesh_id (top class
    and the two insulin classes). The mesh_source column says which. English altLabels are the
    MeSH entry terms and the definition is the MeSH scope note
  - the project class's label: the FDA EPC class name in RxClass
Indications. Curated (vocab/src/indications.csv): which MeSH descriptors are in scope and their
Japanese and Chinese fallback labels. Looked up in MeSH: English label, entry terms (altLabels and
the terms resolve_products.py looks for in FDA labels), scope note, and the entry terms of broader
descriptors that group several in-scope ones, which imply each of them ("diabetes mellitus" in an
insulin label means type 1 and type 2).

API responses are cached in data/raw/{rxnav,umls,mesh}/, so reruns are offline.

Outputs (generated, do not edit): scripts/therapeutic_classes.csv, scripts/indications.csv

Usage: python3 scripts/resolve_vocab.py
"""
import csv
import hashlib
import json
import os
import urllib.parse
from collections import Counter

from build_skos import RAW, ROOT, cached_json, read_csv
from resolve_drugs import rxnav

UMLS = "https://uts-ws.nlm.nih.gov/rest/"
MESH_SPARQL = "https://id.nlm.nih.gov/mesh/sparql"


def umls_key():
    key = os.environ.get("UMLS_API_KEY")
    if not key and (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text().splitlines():
            if line.startswith("UMLS_API_KEY="):
                key = line.split("=", 1)[1].strip()
    return key


def umls_get(cache_name, path, **params):
    """Cached GET on the UMLS API; the key goes into the URL only, never into the cache."""
    cache = RAW / "umls" / cache_name
    if not cache.exists():
        key = umls_key()
        if not key:
            raise SystemExit("UMLS_API_KEY is not set: add your UMLS API key to .env (see .env.example)")
        url = UMLS + path + "?" + urllib.parse.urlencode({**params, "apiKey": key})
        try:
            cached_json(cache, url)
        except Exception as exc:
            if getattr(exc, "code", None) != 404:  # 404 = nothing found
                raise
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"result": []}))
    return json.loads(cache.read_text())


def umls_mesh(code):
    """MeSH descriptors that NLM's Metathesaurus editors (source MTH) relate to an ATC class concept.
    (The UMLS crosswalk ATC -> MSH is empty for A10 classes: UMLS keeps ATC classes as concepts of
    their own, e.g. "Sulfonylureas for blood glucose lowering", apart from MeSH "Sulfonylurea Compounds".)"""
    search = umls_get(f"search_atc_{code}.json", "search/current", string=code, sabs="ATC",
                      searchType="exact", inputType="sourceUi")
    out = set()
    for concept in search.get("result", {}).get("results", []):
        rels = umls_get(f"relations_{concept['ui']}.json", f"content/current/CUI/{concept['ui']}/relations",
                        pageSize=200).get("result") or []
        for r in rels if isinstance(rels, list) else []:
            if r.get("rootSource") != "MTH":
                continue
            cui = r["relatedId"].rsplit("/", 1)[-1]
            atoms = umls_get(f"atoms_msh_{cui}.json", f"content/current/CUI/{cui}/atoms", sabs="MSH",
                             ttys="MH,PA,NM").get("result") or []
            out |= {a["code"].rsplit("/", 1)[-1] for a in atoms if isinstance(atoms, list)
                    and a["code"].rsplit("/", 1)[-1].startswith("D")}
    return sorted(out)


def pharmacological_actions(mesh_ids):
    """MeSH record ID -> set of its pharmacological action descriptor IDs."""
    values = " ".join(f"mesh:{i}" for i in sorted(mesh_ids))
    query = f"""PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
PREFIX mesh: <http://id.nlm.nih.gov/mesh/>
SELECT ?s ?pa FROM <http://id.nlm.nih.gov/mesh> WHERE {{ VALUES ?s {{ {values} }} ?s meshv:pharmacologicalAction ?pa }}"""
    key = hashlib.sha256(query.encode()).hexdigest()[:16]
    url = MESH_SPARQL + "?" + urllib.parse.urlencode({"query": query, "format": "JSON", "limit": 10000})
    out = {}
    for b in cached_json(RAW / "mesh" / f"actions_{key}.json", url)["results"]["bindings"]:
        out.setdefault(b["s"]["value"].rsplit("/", 1)[1], set()).add(b["pa"]["value"].rsplit("/", 1)[1])
    return out


def member_mesh(cid, curated, substances, actions):
    """The MeSH pharmacological action held by every member substance that has one (members of the
    class and its narrower classes) and by no substance outside the class, or []."""
    narrower = {cid}
    while True:
        more = {c["id"] for c in curated if c["broader"] in narrower} - narrower
        if not more:
            break
        narrower |= more
    inside = [actions.get(s["mesh"], set()) for s in substances if s["therapeutic_class"] in narrower]
    outside = set().union(*(actions.get(s["mesh"], set()) for s in substances if s["therapeutic_class"] not in narrower))
    known = [a for a in inside if a]
    common = set.intersection(*known) - outside if known else set()
    return sorted(common)


def mesh_descriptors(ids):
    """MeSH descriptor ID -> label, scope note, entry terms, broader descriptor IDs."""
    if not ids:
        return {}
    values = " ".join(f"mesh:{i}" for i in sorted(ids))
    query = f"""PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
PREFIX mesh: <http://id.nlm.nih.gov/mesh/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?d ?label ?scope ?term ?broader FROM <http://id.nlm.nih.gov/mesh> WHERE {{
  VALUES ?d {{ {values} }}
  ?d rdfs:label ?label .
  OPTIONAL {{ ?d meshv:preferredConcept/meshv:scopeNote ?scope }}
  OPTIONAL {{ ?d meshv:concept|meshv:preferredConcept ?c . ?c meshv:term|meshv:preferredTerm ?t .
             ?t meshv:prefLabel|meshv:altLabel ?term }}
  OPTIONAL {{ ?d meshv:broaderDescriptor ?broader }}
}}"""
    key = hashlib.sha256(query.encode()).hexdigest()[:16]
    url = MESH_SPARQL + "?" + urllib.parse.urlencode({"query": query, "format": "JSON", "limit": 10000})
    body = cached_json(RAW / "mesh" / f"descriptors_{key}.json", url)
    out = {}
    for b in body["results"]["bindings"]:
        d = out.setdefault(b["d"]["value"].rsplit("/", 1)[1], {"label": "", "scope": "", "terms": set(), "broader": set()})
        d["label"] = b["label"]["value"]
        if "scope" in b:
            d["scope"] = " ".join(b["scope"]["value"].split())
        if "term" in b:
            d["terms"].add(b["term"]["value"])
        if "broader" in b:
            d["broader"].add(b["broader"]["value"].rsplit("/", 1)[1])
    missing = set(ids) - set(out)
    if missing:
        raise SystemExit(f"MeSH descriptors not found: {sorted(missing)}")
    return out


def sentence_case(name):
    return name[:1] + name[1:].lower() if name.isupper() else name


def atc_tree():
    """ATC code -> (name, parent code) for the A10 tree in RxClass."""
    body = rxnav("rxclass_tree_A10.json", "rxclass/classTree.json", classId="A10")
    out = {}

    def walk(node, parent):
        c = node["rxclassMinConceptItem"]
        out[c["classId"]] = (c["className"], parent)
        for child in node.get("rxclassTree", []):
            walk(child, c["classId"])

    for node in body["rxclassTree"]:
        walk(node, None)
    return out


def epc_name(code):
    body = rxnav(f"rxclass_class_{code}.json", "rxclass/class/byId.json", classId=code)
    return body["rxclassMinConceptList"]["rxclassMinConcept"][0]["className"]


def class_names(curated):
    """Class id -> (English prefLabel, broader id) from the RxClass ATC tree, or the FDA EPC name for the
    project class. Also used by resolve_drugs.py."""
    tree = atc_tree()
    id_of = {c["atc"]: c["id"] for c in curated if c["atc"]}
    out = {}
    for c in curated:
        if c["atc"]:
            if c["atc"] not in tree:
                raise SystemExit(f"{c['id']}: ATC {c['atc']} is not in the RxClass A10 tree")
            name, parent = tree[c["atc"]]
            if parent and parent not in id_of:
                raise SystemExit(f"{c['id']}: its ATC parent {parent} has no row in vocab/src/therapeutic_classes.csv")
            if c["broader"]:
                raise SystemExit(f"{c['id']}: broader comes from the ATC tree; leave the column empty")
            out[c["id"]] = (sentence_case(name), id_of.get(parent, ""))
        else:  # the project class: an FDA EPC class placed in the tree by decision
            out[c["id"]] = (epc_name(c["fda_epc"]) + "s", c["broader"])
    return out


def resolve_classes():
    curated = read_csv("therapeutic_classes.csv")
    names = class_names(curated)
    with open(ROOT / "scripts" / "substances.csv", newline="", encoding="utf-8") as f:
        substances = list(csv.DictReader(f))  # from resolve_drugs.py
    actions = pharmacological_actions({s["mesh"] for s in substances if s["mesh"]})
    links = {}
    for c in curated:  # 1. NLM-curated UMLS link, 2. shared pharmacological action, 3. curated ID
        found = umls_mesh(c["atc"]) if c["atc"] else []
        source = "UMLS (MTH relation)"
        if not found and c["atc"]:
            found, source = member_mesh(c["id"], curated, substances, actions), "MeSH action of member substances"
        if not found and c["mesh_id"]:
            found, source = [c["mesh_id"]], "curated"
        elif found and c["mesh_id"] and c["mesh_id"] not in found:
            raise SystemExit(f"{c['id']}: curated mesh_id {c['mesh_id']} disagrees with {source} {found}; "
                             "remove the curated value")
        links[c["id"]] = (found, source if found else "")
    mesh = mesh_descriptors({m for found, _ in links.values() for m in found})
    rows = []
    for c in curated:
        pref_en, broader = names[c["id"]]
        found, source = links[c["id"]]
        ms = [mesh[m] for m in found]
        alt_en = {t for m in ms for t in m["terms"]} | set(filter(None, c["alt_en"].split("|")))
        rows.append({"id": c["id"], "atc": c["atc"], "fda_epc": c["fda_epc"], "broader": broader,
                     "pref_en": pref_en, "alt_en": "|".join(sorted(alt_en - {pref_en}, key=str.lower)),
                     "mesh": "|".join(found), "mesh_source": source,
                     "definition_en": c["definition_en"] or (ms[0]["scope"] if ms else ""),
                     "scope_note_en": c["scope_note_en"],
                     "pref_ja": c["pref_ja"], "pref_zh": c["pref_zh"], "alt_ja": c["alt_ja"], "alt_zh": c["alt_zh"]})
        print(f"{c['id']:20} {c['atc'] or c['fda_epc']:12} {pref_en[:42]:42} "
              f"MeSH={'|'.join(m['label'] for m in ms) or '-'} [{source or 'none'}]")
    return rows


def resolve_indications():
    curated = read_csv("indications.csv")
    mesh = mesh_descriptors({i["mesh_id"] for i in curated})
    # A broader descriptor counts only when it groups several in-scope indications ("Diabetes Mellitus"
    # groups type 1 and type 2), so that a single-parent link such as Autoimmune Diseases -> type 1
    # diabetes does not make "autoimmune disease" in a label read as type 1 diabetes.
    groups = Counter(b for i in curated for b in mesh[i["mesh_id"]]["broader"])
    broader = mesh_descriptors({b for b, n in groups.items() if n > 1})
    rows = []
    for i in curated:
        m = mesh[i["mesh_id"]]
        implied = {t for b in m["broader"] if b in broader for t in broader[b]["terms"]}
        rows.append({"id": i["id"], "mesh_id": i["mesh_id"], "pref_en": m["label"],
                     "alt_en": "|".join(sorted(m["terms"] - {m["label"]}, key=str.lower)),
                     "match_terms": "|".join(sorted(m["terms"], key=str.lower)),
                     "implied_by_terms": "|".join(sorted(implied, key=str.lower)),
                     "definition_en": m["scope"], "scope_note_en": i["scope_note_en"],
                     "pref_ja": i["pref_ja"], "pref_zh": i["pref_zh"]})
        print(f"{i['id']:10} {i['mesh_id']:9} {m['label']:28} {len(m['terms'])} terms; implied by "
              f"{sorted(broader[b]['label'] for b in m['broader'] if b in broader)}")
    return rows


def main():
    for path, rows in [("therapeutic_classes.csv", resolve_classes()), ("indications.csv", resolve_indications())]:
        with open(ROOT / "scripts" / path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"wrote scripts/{path} ({len(rows)} rows)\n")


if __name__ == "__main__":
    main()
