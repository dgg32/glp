"""Check that every SHACL rule can fire: validate tests/shacl/broken-examples.ttl in Stardog.

Loads the file into a temporary named graph of the project database, validates only that graph
against the shapes graph, drops the temporary graph, and checks that every message in the shapes
file appears in the report. Needs the STARDOG_* settings in .env.

Usage: .venv/bin/python tests/test_shapes_stardog.py
"""
import sys
import urllib.parse
from pathlib import Path

from rdflib import Graph, Namespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from load_stardog import Stardog, settings  # noqa: E402

SH = Namespace("http://www.w3.org/ns/shacl#")
TEST_GRAPH = "https://dgg32.github.io/glp/graph/test-broken-examples"
SHAPES_GRAPH = "https://dgg32.github.io/glp/graph/shapes"

shapes = Graph().parse(ROOT / "shapes" / "diabetes-market-shapes.ttl")
expected = {str(m) for m in shapes.objects(None, SH.message)}

sd = Stardog(settings())
graph_param = urllib.parse.urlencode({"graph-uri": TEST_GRAPH})
data = Graph().parse(ROOT / "tests" / "shacl" / "broken-examples.ttl").serialize(format="nt").encode()
tx = sd.call("/transaction/begin").strip()
sd.call(f"/{tx}/clear?{graph_param}")
sd.call(f"/{tx}/add?{graph_param}", data=data, content_type="application/n-triples")
sd.call(f"/transaction/commit/{tx}")
try:
    query = f"VALIDATE GRAPH <{TEST_GRAPH}> USING SHAPES GRAPH <{SHAPES_GRAPH}>"
    report = Graph().parse(data=sd.call("/query?" + urllib.parse.urlencode({"query": query}), method="GET",
                                        accept="text/turtle"), format="turtle")
finally:
    tx = sd.call("/transaction/begin").strip()
    sd.call(f"/{tx}/clear?{graph_param}")
    sd.call(f"/transaction/commit/{tx}")

fired = {str(m) for m in report.objects(None, SH.resultMessage)}
missing = sorted(expected - fired)
print(f"{len(expected & fired)} of {len(expected)} rules fired")
for m in missing:
    print("  DID NOT FIRE:", m)
sys.exit(1 if missing else 0)
