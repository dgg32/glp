"""Check that OWL and SHACL agree: the live data has 0 SHACL violations with reasoning off and on.

The ontology adds facts at query time (property chains, inverses, defined classes); a shape that
counts values can then see more than was asserted. Validating both ways catches a shape that only
holds for the asserted data. Needs the STARDOG_* settings in .env.

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

sd = Stardog(settings())
query = f"VALIDATE ALL USING SHAPES GRAPH <{SHAPES_GRAPH}>"
failed = False
for reasoning in ("false", "true"):
    params = {"query": query, "reasoning": reasoning, "timeout": 600000}
    report = Graph().parse(data=sd.call("/query?" + urllib.parse.urlencode(params), method="GET",
                                        accept="text/turtle"), format="turtle")
    violations = Counter(str(report.value(r, SH.resultMessage))
                         for r in report.subjects(SH.resultSeverity, SH.Violation))
    print(f"reasoning {reasoning}: {sum(violations.values())} violations")
    for message, n in violations.most_common():
        print(f"  {n:>6}  {message}")
    failed |= bool(violations)
sys.exit(1 if failed else 0)
