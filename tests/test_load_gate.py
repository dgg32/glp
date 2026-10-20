"""Check that the SHACL gate in load_stardog.py blocks invalid data.

Opens a transaction, adds one prescription with a negative claim count to a temporary named graph,
runs the same gate as load_stardog.py on the uncommitted state, and rolls back. The gate must
report the violation, and the database must not contain the test node afterwards. Needs the
STARDOG_* settings in .env.

Usage: .venv/bin/python tests/test_load_gate.py
"""
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from load_stardog import Stardog, gate, settings  # noqa: E402

TEST_GRAPH = "https://dgg32.github.io/glp/graph/test-load-gate"
NODE = "https://dgg32.github.io/glp/data/rx/2024/test-load-gate/x"
BAD = (f"<{NODE}> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <https://dgg32.github.io/glp/ontology#Prescription> .\n"
       f"<{NODE}> <https://dgg32.github.io/glp/ontology#totalClaims> "
       f"\"-5\"^^<http://www.w3.org/2001/XMLSchema#integer> .\n")


def main():
    sd = Stardog(settings())
    tx = sd.call("/transaction/begin").strip()
    try:
        sd.call(f"/{tx}/add?" + urllib.parse.urlencode({"graph-uri": TEST_GRAPH}), data=BAD.encode(),
                content_type="application/n-triples")
        violations = gate(sd, tx)
    finally:
        sd.call(f"/transaction/rollback/{tx}")
    ok = True
    print(f"gate found {sum(violations.values())} violations: {sorted(violations)}")
    if not violations:
        print("FAIL the gate let a negative claim count through")
        ok = False
    q = f"ASK {{ <{NODE}> ?p ?o }}"
    left = sd.call("/query?" + urllib.parse.urlencode({"query": q}), method="GET", accept="text/boolean")
    if left.strip().lower() == "true":
        print("FAIL the test node is still in the database after rollback")
        ok = False
    print("gate blocks invalid data and the rollback leaves the database unchanged" if ok else "")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
