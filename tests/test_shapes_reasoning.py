"""Check that OWL and SHACL agree: the live data has 0 SHACL violations with reasoning off and on.

The ontology adds facts at query time (property chains, inverses, defined classes); a shape that
counts values can then see more than was asserted. Validating both ways catches a shape that only
holds for the asserted data. Needs the STARDOG_* settings in .env.

With reasoning on, validating everything at once exceeds what Stardog Cloud Free can do (5-minute limit;
the instance answered 503 for minutes afterwards), so it runs in two parts: the US data with all
vocabularies (as before the Japan extension), and the Japanese products with all vocabularies. The NDB
observation graph (ndb-2024, 478k triples) is validated with reasoning off only: reasoning adds nothing
its shapes look at (no property of a slice or an observation has a sub-property, inverse, chain or domain
that infers values; qb:observation's range only types the observations).

Usage: .venv/bin/python tests/test_shapes_reasoning.py
"""
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

from rdflib import Graph, Namespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from load_stardog import SHAPES_GRAPH, Stardog, settings  # noqa: E402

SH = Namespace("http://www.w3.org/ns/shacl#")

G = "https://dgg32.github.io/glp/graph/"
US = {G + "cms-partd-2024", G + "npi-registry", G + "products", G + "drugsfda"}
JAPAN = {G + "ndb-products", G + "ndb-2024"}

sd = Stardog(settings())
all_graphs = set(sd.count_per_graph())


def validate_graphs(graphs):
    return f"VALIDATE GRAPH {' '.join(f'<{g}>' for g in sorted(graphs))} USING SHAPES GRAPH <{SHAPES_GRAPH}>"


runs = [("false", "all graphs", f"VALIDATE ALL USING SHAPES GRAPH <{SHAPES_GRAPH}>"),
        ("true", "US data + vocabularies", validate_graphs(all_graphs - JAPAN)),
        ("true", "Japanese products + vocabularies", validate_graphs(all_graphs - US - {G + "ndb-2024"}))]
failed = False
for reasoning, scope, query in runs:
    params = {"query": query, "reasoning": reasoning}
    report = Graph().parse(data=sd.call("/query?" + urllib.parse.urlencode(params), method="GET",
                                        accept="text/turtle"), format="turtle")
    violations = Counter(str(report.value(r, SH.resultMessage))
                         for r in report.subjects(SH.resultSeverity, SH.Violation))
    print(f"reasoning {reasoning} ({scope}): {sum(violations.values())} violations")
    for message, n in violations.most_common():
        print(f"  {n:>6}  {message}")
    failed |= bool(violations)
sys.exit(1 if failed else 0)
