"""PROV-O description of every named graph that load_stardog.py loads (used by build_rdf.py).

For each graph: what generated it and when, a content hash, the curated input files and the
generated intermediate files it depends on (each with its own hash), and the source snapshots it
was derived from. A source snapshot is one API (or download) as
retrieved for this build: prov:specializationOf the API, its release where the source publishes
one (RxNorm 05-Oct-2026, UMLS 2026AA, GLEIF golden copy, NUCC 261, ...), and the retrieval
window, taken from the modification times of the cached responses in data/raw/.
"""
import glob
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.compare import to_canonical_graph
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, XSD

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
BASE = "https://dgg32.github.io/glp/"
D = Namespace(BASE + "data/")
GRAPH = Namespace(BASE + "graph/")
PROV = Namespace("http://www.w3.org/ns/prov#")
AUTHOR = URIRef("https://github.com/dgg32")


def _json(pattern, path):
    """Largest value at a dotted path over the JSON files matching pattern (None if absent)."""
    values = []
    for f in glob.glob(str(RAW / pattern)):
        v = json.loads(Path(f).read_text())
        for key in path.split("."):
            v = v.get(key) if isinstance(v, dict) else None
        if v:
            values.append(str(v))
    return max(values) if values else None


def _umls_release():
    for f in sorted(glob.glob(str(RAW / "umls" / "*.json"))):
        if m := re.search(r"/(20\d\dA[AB])[/?]", Path(f).read_text()):
            return m[1]
    return None


def _nucc_release():
    files = sorted(glob.glob(str(RAW / "nucc" / "nucc_taxonomy_*.csv")))
    return "release " + re.search(r"_(\d+)\.csv$", files[-1])[1] if files else None


# key: (label, API or download it specializes, cache glob(s), release function or None)
SOURCES = {
    "cms-partd": ("CMS Medicare Part D Prescribers by Provider and Drug, data year 2024",
                  "https://data.cms.gov/data-api/v1/dataset/d5aa71a8-dcc0-4570-8bcf-bd39deac69fe/data",
                  ["partd/*.json"], lambda: "data year 2024 (dataset d5aa71a8-dcc0-4570-8bcf-bd39deac69fe)"),
    "npi-registry": ("NPPES NPI Registry API", "https://npiregistry.cms.hhs.gov/api/?version=2.1",
                     ["npi/*.json"], None),
    "nucc": ("NUCC Health Care Provider Taxonomy", "https://www.nucc.org/", ["nucc/*.csv"], _nucc_release),
    "rxnorm": ("RxNorm and RxClass (NLM RxNav API)", "https://rxnav.nlm.nih.gov/",
               ["rxnav/*.json"], lambda: _json("rxnav/version.json", "version")),
    "umls": ("UMLS Metathesaurus (UTS API)", "https://uts-ws.nlm.nih.gov/rest/", ["umls/*.json"], _umls_release),
    "mesh": ("MeSH RDF (NLM SPARQL endpoint)", "https://id.nlm.nih.gov/mesh/sparql", ["mesh/*.json"], None),
    "openfda-label": ("openFDA drug labels", "https://api.fda.gov/drug/label.json",
                      ["openfda-label/*.json"], lambda: _json("openfda-label/meta.json", "meta.last_updated")),
    "drugsfda": ("openFDA Drugs@FDA", "https://api.fda.gov/drug/drugsfda.json",
                 ["drugsfda/*.json"], lambda: _json("drugsfda/*.json", "meta.last_updated")),
    "gleif": ("GLEIF LEI records", "https://api.gleif.org/api/v1/", ["gleif/*.json"],
              lambda: _json("gleif/lei_*.json", "meta.goldenCopy.publishDate")),
    "wikidata": ("Wikidata (CC0), labels by identifier", "https://query.wikidata.org/sparql",
                 ["wikidata/*.json"], None),
    "idmp-o": ("IDMP-O (Pistoia Alliance)", "https://github.com/pistoiaalliance/idmp-o", [], lambda: "1.4.0"),
}

# graph name (as in data/rdf/manifest.csv, relative to GRAPH; "schema" for Stardog's schema graph)
# -> (generating step, source snapshots, curated input files)
LINEAGE = {
    "schema": ("hand-authored", ["idmp-o"],
               ["ontology/diabetes-market.ttl", "ontology/imports/idmp-o-1.4.0-extract.ttl"]),
    "vocab/therapeutic-class": ("scripts/resolve_vocab.py + scripts/build_skos.py",
                                ["rxnorm", "umls", "mesh", "wikidata"], ["vocab/src/therapeutic_classes.csv"]),
    "vocab/substance": ("scripts/resolve_drugs.py + scripts/build_skos.py", ["rxnorm", "mesh", "wikidata", "cms-partd"],
                        ["scripts/cms_generic_names.csv", "vocab/src/therapeutic_classes.csv",
                         "vocab/src/substance_labels_ja_zh.csv"]),
    "vocab/indication": ("scripts/resolve_vocab.py + scripts/build_skos.py", ["mesh", "wikidata"],
                         ["vocab/src/indications.csv"]),
    "vocab/nucc-specialty": ("scripts/build_skos.py", ["nucc"], ["vocab/src/nucc_labels_ja_zh.csv"]),
    "products": ("scripts/resolve_products.py + scripts/build_rdf.py", ["cms-partd", "rxnorm", "openfda-label"],
                 ["scripts/cms_generic_names.csv", "vocab/src/indications.csv"]),
    "cms-partd-2024": ("scripts/build_rdf.py", ["cms-partd"], []),
    "npi-registry": ("scripts/build_rdf.py", ["npi-registry"], []),
    "drugsfda": ("scripts/resolve_organizations.py + scripts/build_rdf.py", ["drugsfda", "gleif", "wikidata"],
                 ["vocab/src/sponsor_lei.csv", "vocab/src/organization_labels_ja_zh.csv"]),
    "shapes": ("hand-authored", [], ["shapes/diabetes-market-shapes.ttl"]),
}
# graph name -> intermediate files the build generated and the graph was built from
GENERATED = {
    "vocab/therapeutic-class": ["scripts/therapeutic_classes.csv", "scripts/labels_ja_zh.csv"],
    "vocab/substance": ["scripts/substances.csv", "scripts/labels_ja_zh.csv"],
    "vocab/indication": ["scripts/indications.csv", "scripts/labels_ja_zh.csv"],
    "products": ["scripts/drugs.csv", "scripts/products.csv"],
    "cms-partd-2024": ["data/clean/partd_claims.csv"],
    "npi-registry": ["data/clean/npi_taxonomies.csv"],
    "drugsfda": ["scripts/organizations.csv", "scripts/labels_ja_zh.csv"],
}
DESCRIPTIONS = {
    "products": "CMS brand/generic names, linked to substances via RxNorm ingredients and to indications "
                "stated in their openFDA drug labels.",
    "drugsfda": "Drugs@FDA application holders, mapped to LEIs by a curated, evidence-checked table and grouped "
                "by their GLEIF ultimate parent.",
    "cms-partd-2024": "Pseudonymized: no prescriber names or NPIs.",
    "shapes": "The SHACL modelling contract; load_stardog.py commits only data with 0 violations.",
}


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return None


def content_hash(files):
    """(sha256 of the graph as sorted canonical N-Triples, triple count): the hash is stable across
    rebuilds that change nothing, whatever the serialization order or blank node names."""
    g = Graph()
    for f in files:
        g.parse(ROOT / f)
    n = len(g)
    if any(isinstance(t, BNode) for triple in g for t in triple):
        g = to_canonical_graph(g)
    lines = sorted(g.serialize(format="nt").splitlines())
    return "sha256:" + hashlib.sha256("\n".join(l for l in lines if l).encode()).hexdigest(), n


def file_hash(path):
    return "sha256:" + hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def stamp(ts):
    return Literal(datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds"), datatype=XSD.dateTime)


def build(manifest, now):
    """manifest: list of (file, graph IRI) as loaded; now: build time (ISO string)."""
    g = Graph()
    for prefix, ns in [("prov", PROV), ("dcterms", DCTERMS), ("d", D), ("graph", GRAPH)]:
        g.bind(prefix, ns)
    build_act = D[f"activity/build/{now}"]
    g.add((build_act, RDF.type, PROV.Activity))
    g.add((build_act, RDFS.label, Literal("pipeline build (resolve_*.py, build_skos.py, build_rdf.py)", lang="en")))
    g.add((build_act, PROV.endedAtTime, Literal(now, datatype=XSD.dateTime)))
    g.add((build_act, PROV.wasAssociatedWith, AUTHOR))
    if commit := git_commit():
        g.add((build_act, DCTERMS.hasVersion, Literal(commit)))

    used_sources = {s for _, sources, _ in LINEAGE.values() for s in sources}
    for key in sorted(used_sources):
        label, api, patterns, release = SOURCES[key]
        snap = D[f"source/{key}"]
        g.add((snap, RDF.type, PROV.Entity))
        g.add((snap, RDFS.label, Literal(label, lang="en")))
        g.add((snap, PROV.specializationOf, URIRef(api)))
        if release and (v := release()):
            g.add((snap, DCTERMS.hasVersion, Literal(v)))
        times = [Path(f).stat().st_mtime for p in patterns for f in glob.glob(str(RAW / p))]
        if times:
            act = D[f"activity/retrieve/{key}"]
            g.add((act, RDF.type, PROV.Activity))
            g.add((act, RDFS.label, Literal(f"retrieval of {label} (times of the cached responses)", lang="en")))
            g.add((act, PROV.used, URIRef(api)))
            g.add((act, PROV.startedAtTime, stamp(min(times))))
            g.add((act, PROV.endedAtTime, stamp(max(times))))
            g.add((snap, PROV.wasGeneratedBy, act))

    files_by_graph = {}
    for file, iri in manifest:
        files_by_graph.setdefault(iri, []).append(file)
    for iri, files in files_by_graph.items():
        name = "schema" if iri == "tag:stardog:api:context:schema" else iri.replace(str(GRAPH), "")
        if name == "provenance":
            continue  # a graph does not describe its own hash
        step, sources, curated = LINEAGE[name]
        node = URIRef(iri)
        g.add((node, RDF.type, PROV.Entity))
        digest, n = content_hash(files)
        g.add((node, DCTERMS.identifier, Literal(digest)))
        g.add((node, DCTERMS.extent, Literal(f"{n} triples")))
        g.add((node, DCTERMS.source, Literal(", ".join(files))))
        if step == "hand-authored":
            g.add((node, PROV.wasAttributedTo, AUTHOR))
        else:
            g.add((node, PROV.wasGeneratedBy, build_act))
            g.add((node, RDFS.comment, Literal(f"generated by {step}", lang="en")))
        g.add((node, PROV.generatedAtTime, stamp(max((ROOT / f).stat().st_mtime for f in files))))
        if name == "schema":
            version = Graph().parse(ROOT / files[0]).value(URIRef(BASE + "ontology"), OWL.versionInfo)
            g.add((node, DCTERMS.hasVersion, Literal(str(version))))
        for s in sources:
            g.add((node, PROV.wasDerivedFrom, D[f"source/{s}"]))
        for c in curated:
            cur = D[f"curated/{c}"]
            g.add((cur, RDF.type, PROV.Entity))
            g.add((cur, RDFS.label, Literal(c)))
            g.add((cur, DCTERMS.identifier, Literal(file_hash(c))))
            g.add((cur, PROV.wasAttributedTo, AUTHOR))
            g.add((node, PROV.wasDerivedFrom, cur))
        for f in GENERATED.get(name, []):
            gen = D[f"generated/{f}"]
            g.add((gen, RDF.type, PROV.Entity))
            g.add((gen, RDFS.label, Literal(f)))
            g.add((gen, DCTERMS.identifier, Literal(file_hash(f))))
            g.add((gen, PROV.wasGeneratedBy, build_act))
            g.add((node, PROV.wasDerivedFrom, gen))
        if name in DESCRIPTIONS:
            g.add((node, DCTERMS.description, Literal(DESCRIPTIONS[name], lang="en")))
    return g
