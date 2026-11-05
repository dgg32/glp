"""The PROV-O lineage is a complete bronze -> silver -> gold chain.

Reads the built files (data/rdf/provenance.ttl and, if an export exists, data/snowflake/provenance.ttl);
nothing touches Stardog or Snowflake.

Usage: .venv/bin/python -m pytest tests/test_provenance.py
"""
import json
import re
import sys
from pathlib import Path

import pytest
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDFS

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import provenance  # noqa: E402

PROV = Namespace("http://www.w3.org/ns/prov#")
D = provenance.D
SOURCE, GENERATED, GOLD = str(D["source/"]), str(D["generated/"]), str(D["snowflake/"])
HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
RDF_PROV = ROOT / "data" / "rdf" / "provenance.ttl"
GOLD_PROV = ROOT / "data" / "snowflake" / "provenance.ttl"
TABLES = ROOT / "data" / "snowflake" / "tables.json"


@pytest.fixture(scope="module")
def g():
    if not RDF_PROV.exists():
        pytest.skip("no build: run scripts/build_rdf.py first")
    graph = Graph().parse(RDF_PROV)
    if GOLD_PROV.exists():
        graph.parse(GOLD_PROV)
    return graph


def ancestors(g, node):
    """Everything node was derived from, transitively (prov:wasDerivedFrom+)."""
    seen, todo = set(), [node]
    while todo:
        for parent in g.objects(todo.pop(), PROV.wasDerivedFrom):
            if parent not in seen:
                seen.add(parent)
                todo.append(parent)
    return seen


def generated(g):
    return sorted({s for s in g.subjects() if str(s).startswith(GENERATED)})


def test_derived_covers_every_intermediate():
    needed = {f for files in provenance.GENERATED.values() for f in files} | \
             {f for _, _, _, upstream in provenance.DERIVED.values() for f in upstream}
    assert needed <= provenance.DERIVED.keys()
    for script, sources, curated, upstream in provenance.DERIVED.values():
        assert (ROOT / script).exists(), script
        assert set(sources) <= provenance.SOURCES.keys()
        assert sources or curated or upstream


def test_every_intermediate_is_derived_and_generated_by_its_script(g):
    nodes = generated(g)
    assert len(nodes) == len(provenance.DERIVED)
    for n in nodes:
        assert list(g.objects(n, PROV.wasDerivedFrom)), f"{n} has no wasDerivedFrom"
        scripts = [str(g.value(a, RDFS.label)) for a in g.objects(n, PROV.wasGeneratedBy)]
        assert len(scripts) == 1 and scripts[0].startswith("scripts/") and scripts[0].endswith(".py"), (n, scripts)


def test_every_intermediate_reaches_bronze_through_its_own_chain(g):
    for n in generated(g):
        assert any(str(a).startswith(SOURCE) for a in ancestors(g, n)), f"{n} does not reach a d:source/*"


def test_every_named_graph_with_sources_reaches_bronze(g):
    for name, (_, sources, _) in provenance.LINEAGE.items():
        if not sources:
            continue  # the hand-authored SHACL shapes
        iri = URIRef("tag:stardog:api:context:schema" if name == "schema" else str(provenance.GRAPH[name]))
        assert any(str(a).startswith(SOURCE) for a in ancestors(g, iri)), name


def test_every_lineage_node_is_hashed(g):
    for s in {s for s in g.subjects(PROV.wasDerivedFrom)} | {o for o in g.objects(None, PROV.wasDerivedFrom)}:
        if str(s).startswith(str(D)) or str(s).startswith(str(provenance.GRAPH)):
            ids = [str(i) for i in g.objects(s, DCTERMS.identifier)]
            assert ids and all(HASH.match(i) for i in ids), f"{s}: {ids}"


def test_source_hashes_are_deterministic_and_match_the_build(g):
    for key in sorted({str(s)[len(SOURCE):] for s in g.subjects() if str(s).startswith(SOURCE)}):
        first, n = provenance.source_hash(key)
        assert first and n > 0, f"{key}: no cached raw files"
        assert provenance.source_hash(key) == (first, n)
        assert str(g.value(D[f"source/{key}"], DCTERMS.identifier)) == first, \
            f"{key}: data/raw/ changed since the build (rerun build_rdf.py)"


def test_gold_tables_reach_bronze_and_match_the_export(g):
    if not TABLES.exists():
        pytest.skip("no Snowflake export")
    manifest = json.loads(TABLES.read_text())
    for t in manifest["tables"]:
        node = D[f"snowflake/{t['name']}"]
        assert str(g.value(node, DCTERMS.identifier)) == "sha256:" + t["sha256"], t["name"]
        assert any(str(a).startswith(SOURCE) for a in ancestors(g, node)), t["name"]
