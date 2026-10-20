"""Build the SKOS vocabularies in vocab/ from curated CSVs plus codes looked up at the source.

  vocab/therapeutic-class.ttl  drug classes (A10 tree), en/ja/zh labels, exactMatch ATC, closeMatch MeSH
  vocab/substance.ttl          active substances, en/ja/zh labels, CMS spellings as hiddenLabel,
                               exactMatch RxNorm / ATC / MeSH, dm:inTherapeuticClass
  vocab/indication.ttl         indications (type 2 / type 1 diabetes, chronic weight management), MeSH links
  vocab/nucc-specialty.ttl     NUCC Health Care Provider Taxonomy as SKOS (format conversion only).
                               NOT committed: the AMA/NUCC permission forbids derivative works and is
                               limited to US products, so it is generated locally (see .gitignore).

Codes are never typed by hand. Substances, their ATC codes and English synonyms (RxNorm), classes and
English synonyms come from scripts/substances.csv, written by scripts/resolve_drugs.py; class ATC
codes are checked against RxClass and MeSH IDs come from the NLM MeSH SPARQL endpoint. Curated:
the class tree (an ATC A10 subset plus one project class) and indication concepts with their labels,
and the Japanese and Chinese labels (vocab/src/). Every API response is cached in
data/raw/{rxnav,mesh}/ so reruns are offline and auditable; delete the cache to refresh.

Usage: .venv/bin/python scripts/build_skos.py [--nucc-version 261]
"""
import argparse
import csv
import hashlib
import json
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS, XSD

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "vocab" / "src"
RAW = ROOT / "data" / "raw"
BASE = "https://dgg32.github.io/glp/"
DM = Namespace(BASE + "ontology#")
DMTC = Namespace(BASE + "vocab/therapeutic-class/")
DMSUB = Namespace(BASE + "vocab/substance/")
DMSP = Namespace(BASE + "vocab/specialty/")
DMIND = Namespace(BASE + "vocab/indication/")
PROV = Namespace("http://www.w3.org/ns/prov#")
ATC = Namespace("http://purl.bioontology.org/ontology/ATC/")
RXNORM = Namespace("http://purl.bioontology.org/ontology/RXNORM/")
MESH = Namespace("http://id.nlm.nih.gov/mesh/")
TODAY = date.today().isoformat()
# Curated ja/zh labels were drafted on this date; the date must not move on rebuilds.
REVIEW_NOTE = Literal("Japanese and Chinese labels not taken from Wikidata were drafted 2026-10-14 and are pending "
                      "native-speaker review (docs/label-review.md).", lang="en")
WD = Namespace("http://www.wikidata.org/entity/")

# id.nlm.nih.gov is unreliable over IPv6 from some networks; resolve it to IPv4 only.
_getaddrinfo = socket.getaddrinfo
def _ipv4_for_nlm(host, *args, **kwargs):
    if host == "id.nlm.nih.gov":
        return _getaddrinfo(host, args[0], socket.AF_INET, *args[2:], **kwargs)
    return _getaddrinfo(host, *args, **kwargs)
socket.getaddrinfo = _ipv4_for_nlm


def cached_json(cache_path, url, retries=4):
    if cache_path.exists():
        return json.loads(cache_path.read_text())
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=90) as resp:
                body = json.load(resp)
            break
        except Exception as exc:
            if attempt == retries - 1:
                raise
            print(f"  retry {attempt + 1}: {exc}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(body, ensure_ascii=False, indent=1))
    return body


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def read_csv(name):
    with open(SRC / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def split(s):
    return [x.strip() for x in (s or "").split("|") if x.strip()]


# ---------------------------------------------------------------- lookups

def mesh_records(labels):
    """Map label -> current MeSH descriptor or supplementary chemical record IRI (exact label match)."""
    variants = {}
    for l in set(labels):  # MeSH capitalizes descriptors, not supplementary records; try both
        for v in {l, l.lower(), l[:1].upper() + l[1:], l.title()}:
            variants[v] = l
    labels = sorted(variants)
    values = " ".join(json.dumps(l) + "@en" for l in labels)
    query = f"""PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?label ?rec FROM <http://id.nlm.nih.gov/mesh> WHERE {{
  VALUES ?label {{ {values} }}
  ?rec rdfs:label ?label .
  {{ ?rec a meshv:TopicalDescriptor }} UNION {{ ?rec a meshv:SCR_Chemical }}
}}"""
    key = slug("-".join(labels))[:80] + "-" + hashlib.sha256("|".join(labels).encode()).hexdigest()[:8]
    url = "https://id.nlm.nih.gov/mesh/sparql?" + urllib.parse.urlencode({"query": query, "format": "JSON"})
    body = cached_json(RAW / "mesh" / f"lookup_{key}.json", url)
    found = {}
    for b in body["results"]["bindings"]:
        rec = b["rec"]["value"]
        if re.fullmatch(r"http://id\.nlm\.nih\.gov/mesh/[CD]\d+", rec):  # skip year-versioned copies
            found[variants[b["label"]["value"]]] = URIRef(rec)
    return found


# ---------------------------------------------------------------- builders

def new_graph():
    g = Graph()
    for p, ns in [("dm", DM), ("dmtc", DMTC), ("dmsub", DMSUB), ("dmsp", DMSP), ("dmind", DMIND), ("skos", SKOS),
                  ("dcterms", DCTERMS), ("prov", PROV), ("atc", ATC), ("rxnorm", RXNORM), ("mesh", MESH), ("wd", WD)]:
        g.bind(p, ns)
    return g


def scheme_header(g, scheme, titles, description, sources):
    g.add((scheme, RDF.type, SKOS.ConceptScheme))
    for lang, t in titles.items():
        g.add((scheme, DCTERMS.title, Literal(t, lang=lang)))
    g.add((scheme, DCTERMS.description, Literal(description, lang="en")))
    g.add((scheme, DCTERMS.creator, Literal("Sixing Huang")))
    g.add((scheme, DCTERMS.modified, Literal(TODAY, datatype=XSD.date)))
    for s in sources:
        g.add((scheme, PROV.wasDerivedFrom, URIRef(s)))


def mirror_pref_labels(g):
    """Copy every skos:prefLabel to rdfs:label. Many tools only read rdfs:label; Stardog's stardog:label,
    which Voicebox uses to find entities by name, is one of them (found 2026-10-14)."""
    for s, label in list(g.subject_objects(SKOS.prefLabel)):
        g.add((s, RDFS.label, label))
    return g


def labels(g, node, en, ja=None, zh=None, alt_en=(), alt_ja=(), alt_zh=()):
    g.add((node, SKOS.prefLabel, Literal(en, lang="en")))
    if ja:
        g.add((node, SKOS.prefLabel, Literal(ja, lang="ja")))
    if zh:
        g.add((node, SKOS.prefLabel, Literal(zh, lang="zh")))
    for lang, alts in (("en", alt_en), ("ja", alt_ja), ("zh", alt_zh)):
        for a in alts:
            g.add((node, SKOS.altLabel, Literal(a, lang=lang)))


def label_note(g, node, l):
    """Per-concept note on where the Japanese and Chinese labels come from (scripts/labels_ja_zh.csv)."""
    parts = []
    for lang, name in (("ja", "Japanese"), ("zh", "Chinese")):
        if l[f"{lang}_source"] == "wikidata":
            parts.append(f"{name} label from Wikidata {l['wikidata']} (CC0)")
        else:
            parts.append(f"{name} label curated, pending native-speaker review")
    g.add((node, SKOS.editorialNote, Literal("; ".join(parts) + ".", lang="en")))


def build_therapeutic_classes(classes, ja_zh):
    g = new_graph()
    scheme = URIRef(BASE + "vocab/therapeutic-class")
    scheme_header(g, scheme, {"en": "Therapeutic classes of diabetes drugs", "ja": "糖尿病治療薬の薬効分類",
                              "zh": "糖尿病治疗药物分类"},
                  "Drug classes for the type 2 diabetes market, following the WHO ATC A10 tree (as served by RxClass) "
                  "with one project-specific refinement (dual GIP/GLP-1 agonists under GLP-1 receptor agonists).",
                  ["https://lhncbc.nlm.nih.gov/RxNav/applications/RxClassIntro.html",
                   "https://www.nlm.nih.gov/research/umls/", "https://id.nlm.nih.gov/mesh/"])
    g.add((scheme, SKOS.editorialNote, REVIEW_NOTE))
    ids = {c["id"] for c in classes}
    for c in classes:
        node = DMTC[c["id"]]
        l = ja_zh[("class", c["id"])]
        g.add((node, RDF.type, SKOS.Concept))
        g.add((node, RDF.type, DM.TherapeuticClass))
        g.add((node, SKOS.inScheme, scheme))
        labels(g, node, c["pref_en"], l["pref_ja"], l["pref_zh"], split(c["alt_en"]), split(c["alt_ja"]), split(c["alt_zh"]))
        label_note(g, node, l)
        if c["definition_en"]:
            g.add((node, SKOS.definition, Literal(c["definition_en"], lang="en")))
        if c["scope_note_en"]:
            g.add((node, SKOS.scopeNote, Literal(c["scope_note_en"], lang="en")))
        if c["broader"]:
            assert c["broader"] in ids, f"unknown broader {c['broader']}"
            g.add((node, SKOS.broader, DMTC[c["broader"]]))
            g.add((DMTC[c["broader"]], SKOS.narrower, node))
        else:
            g.add((node, SKOS.topConceptOf, scheme))
            g.add((scheme, SKOS.hasTopConcept, node))
        if c["atc"]:
            g.add((node, SKOS.exactMatch, ATC[c["atc"]]))
            g.add((node, SKOS.notation, Literal(c["atc"])))
        for m in split(c["mesh"]):
            # MeSH pharmacological actions and chemical groups are close to, not identical with, a drug class.
            g.add((node, SKOS.closeMatch, MESH[m]))
    return g


def build_substances(substances, ja_zh, report):
    g = new_graph()
    scheme = URIRef(BASE + "vocab/substance")
    scheme_header(g, scheme, {"en": "Active substances of diabetes drugs", "ja": "糖尿病治療薬の有効成分",
                              "zh": "糖尿病治疗药物活性成分"},
                  "Active substances (moieties) found in the Part D diabetes subset, with CMS spellings as hidden labels "
                  "for term normalization.",
                  ["https://www.nlm.nih.gov/research/umls/rxnorm/",
                   "https://id.nlm.nih.gov/mesh/",
                   "https://data.cms.gov/provider-summary-by-type-of-service/medicare-part-d-prescribers"])
    g.add((scheme, SKOS.editorialNote, REVIEW_NOTE))
    for s in substances:
        l = ja_zh[("substance", s["substance"])]
        node = DMSUB[s["substance"]]
        g.add((node, RDF.type, SKOS.Concept))
        g.add((node, RDF.type, DM.Substance))
        g.add((node, SKOS.inScheme, scheme))
        g.add((node, SKOS.topConceptOf, scheme))
        g.add((scheme, SKOS.hasTopConcept, node))
        labels(g, node, s["rxnorm_name"], l["pref_ja"], l["pref_zh"], split(s["alt_en"]))
        label_note(g, node, l)
        if l["wikidata"]:
            g.add((node, SKOS.exactMatch, WD[l["wikidata"]]))
        for cms in split(s["cms_names"]):
            g.add((node, SKOS.hiddenLabel, Literal(cms, lang="en")))
        g.add((node, DM.inTherapeuticClass, DMTC[s["therapeutic_class"]]))
        g.add((node, SKOS.exactMatch, RXNORM[s["rxcui"]]))
        for code in split(s["atc"]):
            g.add((node, SKOS.exactMatch, ATC[code]))
        if s["class_evidence"].startswith("FDA EPC"):
            report.append(f"{s['substance']}: class {s['therapeutic_class']} from {s['class_evidence']} "
                          f"(ATC {s['atc']} has no project class)")
        if s["mesh"]:  # looked up by resolve_drugs.py
            g.add((node, SKOS.exactMatch, MESH[s["mesh"]]))
        else:
            report.append(f"{s['substance']}: no MeSH record for {s['rxnorm_name']!r} or its synonyms")
    return g


def build_indications(indications, ja_zh):
    g = new_graph()
    scheme = URIRef(BASE + "vocab/indication")
    scheme_header(g, scheme, {"en": "Indications", "ja": "適応症", "zh": "适应症"},
                  "Conditions the medicinal products in the dataset are authorized to treat, as MeSH descriptors.",
                  ["https://id.nlm.nih.gov/mesh/", "https://www.wikidata.org/"])
    g.add((scheme, SKOS.editorialNote, REVIEW_NOTE))
    for i in indications:
        node = DMIND[i["id"]]
        l = ja_zh[("indication", i["id"])]
        for t in (SKOS.Concept, DM.Indication):
            g.add((node, RDF.type, t))
        g.add((node, SKOS.inScheme, scheme))
        g.add((node, SKOS.topConceptOf, scheme))
        g.add((scheme, SKOS.hasTopConcept, node))
        labels(g, node, i["pref_en"], l["pref_ja"], l["pref_zh"], split(i["alt_en"]))
        label_note(g, node, l)
        if i["definition_en"]:
            g.add((node, SKOS.definition, Literal(i["definition_en"], lang="en")))
        if i["scope_note_en"]:
            g.add((node, SKOS.scopeNote, Literal(i["scope_note_en"], lang="en")))
        g.add((node, SKOS.exactMatch, MESH[i["mesh_id"]]))
        if l["wikidata"]:
            g.add((node, SKOS.exactMatch, WD[l["wikidata"]]))
    return g


def build_nucc(version, ja_zh, report):
    with open(RAW / "nucc" / f"nucc_taxonomy_{version}.csv", newline="", encoding="utf-8") as f:
        rows = [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    g = new_graph()
    scheme = URIRef(BASE + "vocab/specialty")
    scheme_header(g, scheme, {"en": "Health Care Provider Taxonomy (NUCC) as SKOS"},
                  f"Format conversion of the NUCC Health Care Provider Taxonomy version {version[:-1]}.{version[-1]} "
                  "to SKOS. Grouping, Classification and Specialization become a three-level skos:broader hierarchy; "
                  "codes, names and definitions are unchanged.",
                  [f"https://www.nucc.org/images/stories/CSV/nucc_taxonomy_{version}.csv"])
    g.add((scheme, DCTERMS.rights, Literal(f"Copyright {date.today().year} American Medical Association. The AMA holds "
                                           "copyright in the Provider Taxonomy on behalf of the NUCC. Provided AS IS.")))
    g.add((scheme, SKOS.editorialNote, REVIEW_NOTE))

    groupings = {}
    for r in rows:
        if r["Grouping"] not in groupings:
            node = DMSP["grouping-" + slug(r["Grouping"])]
            groupings[r["Grouping"]] = node
            g.add((node, RDF.type, SKOS.Concept))
            g.add((node, RDF.type, DM.Specialty))
            g.add((node, SKOS.inScheme, scheme))
            g.add((node, SKOS.topConceptOf, scheme))
            g.add((scheme, SKOS.hasTopConcept, node))
            g.add((node, SKOS.prefLabel, Literal(r["Grouping"], lang="en")))

    base_codes = {(r["Grouping"], r["Classification"]): r["Code"] for r in rows if not r["Specialization"]}
    display_names, minted = {}, []
    for r in rows:
        node = DMSP[r["Code"]]
        g.add((node, RDF.type, SKOS.Concept))
        g.add((node, RDF.type, DM.Specialty))
        g.add((node, SKOS.inScheme, scheme))
        g.add((node, SKOS.notation, Literal(r["Code"])))
        pref = r["Display Name"] or r["Specialization"] or r["Classification"]
        display_names.setdefault(pref, []).append(r["Code"])
        g.add((node, SKOS.prefLabel, Literal(pref, lang="en")))
        own_name = r["Specialization"] or r["Classification"]
        if own_name != pref:
            g.add((node, SKOS.altLabel, Literal(own_name, lang="en")))
        if r["Definition"]:
            g.add((node, SKOS.definition, Literal(r["Definition"], lang="en")))
        if not r["Specialization"]:
            parent = groupings[r["Grouping"]]
        elif (r["Grouping"], r["Classification"]) in base_codes:
            parent = DMSP[base_codes[(r["Grouping"], r["Classification"])]]
        else:
            # NUCC has specializations under some classifications without a code of their own
            # (e.g. Psychiatry & Neurology); add that level from the Classification column.
            parent = DMSP["classification-" + slug(r["Classification"])]
            if (parent, RDF.type, SKOS.Concept) not in g:
                minted.append(r["Classification"])
                for t in (SKOS.Concept, DM.Specialty):
                    g.add((parent, RDF.type, t))
                g.add((parent, SKOS.inScheme, scheme))
                g.add((parent, SKOS.prefLabel, Literal(r["Classification"], lang="en")))
                g.add((parent, SKOS.broader, groupings[r["Grouping"]]))
                g.add((groupings[r["Grouping"]], SKOS.narrower, parent))
        g.add((node, SKOS.broader, parent))
        g.add((parent, SKOS.narrower, node))

    for key, row in ja_zh.items():
        node = groupings.get(key) or DMSP[key]
        if (node, RDF.type, SKOS.Concept) not in g:
            raise RuntimeError(f"ja/zh label for unknown NUCC code or grouping: {key}")
        g.add((node, SKOS.prefLabel, Literal(row["pref_ja"], lang="ja")))
        g.add((node, SKOS.prefLabel, Literal(row["pref_zh"], lang="zh")))

    if minted:
        report.append(f"NUCC: added {len(minted)} classification concepts that have no NUCC code: " + ", ".join(minted))
    dups = {k: v for k, v in display_names.items() if len(v) > 1}
    if dups:
        report.append(f"NUCC: {len(dups)} English prefLabels shared by several codes, e.g. "
                      + "; ".join(f"{k} {v}" for k, v in list(dups.items())[:3]))
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nucc-version", default="261")
    args = ap.parse_args()

    # Generated by the resolve_*.py scripts and fetch_wikidata_labels.py (see their docstrings).
    def generated(name):
        with open(ROOT / "scripts" / name, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    classes, substances, indications = (generated(n) for n in
                                        ("therapeutic_classes.csv", "substances.csv", "indications.csv"))
    labels_ja_zh = {(r["kind"], r["concept"]): r for r in generated("labels_ja_zh.csv")}
    ja_zh = {r["code_or_grouping"]: r for r in read_csv("nucc_labels_ja_zh.csv")}

    report = []
    out_dir = ROOT / "vocab"
    for name, g in [("therapeutic-class.ttl", build_therapeutic_classes(classes, labels_ja_zh)),
                    ("substance.ttl", build_substances(substances, labels_ja_zh, report)),
                    ("indication.ttl", build_indications(indications, labels_ja_zh)),
                    ("nucc-specialty.ttl", build_nucc(args.nucc_version, ja_zh, report))]:
        mirror_pref_labels(g).serialize(out_dir / name, format="turtle")
        print(f"wrote vocab/{name}: {len(g)} triples")
    print("\nreport:" if report else "\nreport: nothing to flag")
    for line in report:
        print("  " + line)


if __name__ == "__main__":
    main()
