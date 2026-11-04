"""Check the generated graphs on this machine before anything is pushed to Stardog.

Stardog Cloud Free is the publication target, not the test bench: on 2026-10-25 repeated full reloads
and reasoning-on validations there filled its disk and corrupted the database. Every check that used
to need the server runs here instead, on the files of data/rdf/manifest.csv:

  1. budget     total triples below the Cloud Free limit of 1M edges, with a safety margin
  2. contract   SHACL validation of all graphs (pyshacl, incl. SHACL-SPARQL): 0 violations
  3. coverage   every rule of the shapes fires on tests/shacl/broken-examples.ttl
  4. consistency  the disjointness axiom fires: after an OWL 2 RL closure of the ontology and
                tests/owl/inconsistent-examples.ttl, owlrl reports exactly the individuals marked
                t:mustClash as inconsistent, and nothing else
  5. reasoning  an OWL 2 RL closure (owlrl) of everything except the NDB observations: no
                inconsistency, then SHACL again: 0 violations, so no shape breaks under the
                ontology's inferences
  6. queries    every query in queries/ runs on the local store (scripts/run_queries.py --local)

owlrl does not raise on an inconsistency. It writes each one into the graph as
[] a err:ErrorMessage ; err:error "Disjoint classes ... have a common individual ..." and carries on,
so the reasoning and consistency checks read those triples back.

If all pass, data/validation/local-check.json records the hash of data/rdf/provenance.ttl (new with
every build), and scripts/load_stardog.py pushes only files with that hash.

Differences from Stardog: owlrl implements OWL 2 RL, Stardog's reasoner its SL profile (a superset for
what this ontology uses: subclass, subproperty, inverse, property chains, domain/range, hasValue and
someValuesFrom restrictions). The in-transaction gate in load_stardog.py still runs as a last check.

Usage: .venv/bin/python scripts/check_local.py [--skip-reasoning]
"""
import csv
import json
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from rdflib import Graph, Namespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_stardog import LOCAL_CHECK, provenance_digest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SH = Namespace("http://www.w3.org/ns/shacl#")
ERR = Namespace("http://www.daml.org/2002/03/agents/agent-ont#")  # where owlrl writes its error messages
TEST = Namespace("https://dgg32.github.io/glp/test/")
ONTOLOGY = ["ontology/diabetes-market.ttl", "ontology/imports/idmp-o-1.4.0-extract.ttl"]
SHAPES = ROOT / "shapes" / "diabetes-market-shapes.ttl"
EDGE_LIMIT, MARGIN = 1_000_000, 50_000
# The NDB observations: validated without reasoning only (no inference touches what their shapes check).
OBSERVATIONS = "data/rdf/ndb-2024.ttl"


def manifest():
    with open(ROOT / "data" / "rdf" / "manifest.csv", newline="") as f:
        return [r["file"] for r in csv.DictReader(f)]


def load(files):
    g = Graph()
    for f in files:
        g.parse(ROOT / f)
    return g


def violations(data, shapes):
    from pyshacl import validate
    _, report, _ = validate(data, shacl_graph=shapes, inference="none", advanced=True, allow_warnings=True)
    return Counter(str(report.value(r, SH.resultMessage)) for r in report.subjects(SH.resultSeverity, SH.Violation))


def inconsistencies(g):
    """The error messages owlrl left in g after a closure (inconsistencies such as cax-dw/cax-adc)."""
    return sorted(str(m) for m in g.objects(None, ERR.error))


def step(name, fn):
    t = time.time()
    print(f"[{name}] ...", flush=True)
    ok, detail = fn()
    print(f"[{name}] {'PASS' if ok else 'FAIL'} ({time.time() - t:.0f} s) {detail}", flush=True)
    return ok


def main():
    files = manifest()
    data_files = [f for f in files if f != "shapes/diabetes-market-shapes.ttl"]
    shapes = Graph().parse(SHAPES)
    results = {}

    def budget():
        n = len(load(files))
        return n <= EDGE_LIMIT - MARGIN, f"{n:,} triples (limit {EDGE_LIMIT:,}, margin {MARGIN:,})"

    def contract():
        v = violations(load(data_files), shapes)
        return not v, "; ".join(f"{n} x {m}" for m, n in v.most_common(5)) or "0 violations"

    def coverage():
        expected = {str(m) for m in shapes.objects(None, SH.message)}
        from pyshacl import validate
        _, report, _ = validate(Graph().parse(ROOT / "tests" / "shacl" / "broken-examples.ttl"), shacl_graph=shapes,
                                inference="none", advanced=True, allow_warnings=True)
        fired = {str(m) for m in report.objects(None, SH.resultMessage)}
        missing = sorted(expected - fired)
        return not missing, f"{len(expected & fired)} of {len(expected)} rules fired" + \
            ("; did not fire: " + " | ".join(missing) if missing else "")

    def consistency():
        import owlrl
        from rdflib import Literal
        g = load(ONTOLOGY)
        g.parse(ROOT / "tests" / "owl" / "inconsistent-examples.ttl")
        expected = {str(s) for s in g.subjects(TEST.mustClash, Literal(True))}
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)
        errors = inconsistencies(g)
        # owlrl's message ends with the individual: "Disjoint classes A and B have a common individual X"
        clashed = {m.rsplit(" ", 1)[-1] for m in errors if m.startswith("Disjoint classes")}
        other = [m for m in errors if not m.startswith("Disjoint classes")]
        missing, extra = sorted(expected - clashed), sorted(clashed - expected)
        ok = not missing and not extra and not other
        return ok, f"{len(expected & clashed)} of {len(expected)} wrong links reported inconsistent" + \
            ("; not reported: " + ", ".join(missing) if missing else "") + \
            ("; reported but correct: " + ", ".join(extra) if extra else "") + \
            ("; other errors: " + " | ".join(other[:3]) if other else "")

    def reasoning():
        import owlrl
        g = load([f for f in data_files if f != OBSERVATIONS])
        n = len(g)
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)
        errors = inconsistencies(g)
        v = violations(g, shapes)
        return not v and not errors, f"{n:,} triples, {len(g):,} after OWL 2 RL closure; " + \
            (f"{len(errors)} inconsistencies: " + " | ".join(errors[:3]) + "; " if errors else "consistent; ") + \
            ("; ".join(f"{k} x {m}" for m, k in v.most_common(5)) or "0 violations")

    def queries():
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "run_queries.py"), "--local"],
                           capture_output=True, text=True)
        failed = [l for l in r.stdout.splitlines() if "FAILED" in l]
        return r.returncode == 0, "; ".join(failed) or "all queries ran (data/validation/query-results-local.md)"

    checks = [("budget", budget), ("contract", contract), ("coverage", coverage), ("consistency", consistency),
              ("queries", queries)]
    if "--skip-reasoning" not in sys.argv:
        checks.insert(4, ("reasoning", reasoning))
    for name, fn in checks:
        results[name] = step(name, fn)
    passed = all(results.values())
    LOCAL_CHECK.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_CHECK.write_text(json.dumps({
        "provenance": provenance_digest(), "passed": passed, "checks": results,
        "reasoning_checked": "reasoning" in results,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, indent=2))
    print(f"\n{'ALL CHECKS PASSED' if passed else 'CHECKS FAILED'}; wrote {LOCAL_CHECK.relative_to(ROOT)}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
