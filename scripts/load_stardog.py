"""Load ontology, vocabularies and data into Stardog, one named graph per manifest entry.

Reads data/rdf/manifest.csv (written by build_rdf.py) and the STARDOG_* settings in .env.
Push only what passed locally: the script refuses to run unless scripts/check_local.py validated
exactly these files (data/validation/local-check.json holds the hash of data/rdf/provenance.ttl,
which changes with every build). Incremental: only graphs whose content hash differs from the one in
Stardog's provenance graph are rewritten, plus the provenance graph itself; --full rewrites all.
(Stardog Cloud Free ran out of disk on 2026-10-25 after repeated full reloads of 734k triples.)
Everything happens in one transaction: each changed graph is cleared and reloaded, so a rerun
replaces the data instead of duplicating it, and a failure leaves the database unchanged.
Quality gate: before committing, the uncommitted state is validated against the SHACL shapes
inside the transaction; any sh:Violation rolls the transaction back, so data that breaks the
modelling contract never goes live. (Warnings and info results do not block; validate.py reports
them after the load.) Afterwards the triple count of every graph in Stardog is compared with the
local files.

Usage: .venv/bin/python scripts/load_stardog.py [--full] [--dry-run]
"""
import hashlib
import base64
import csv
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from rdflib import Graph, Namespace

ROOT = Path(__file__).resolve().parent.parent
BATCH = 50_000  # triples per HTTP request
SH = Namespace("http://www.w3.org/ns/shacl#")
SHAPES_GRAPH = "https://dgg32.github.io/glp/graph/shapes"
PROVENANCE_GRAPH = "https://dgg32.github.io/glp/graph/provenance"
DCTERMS = Namespace("http://purl.org/dc/terms/")
LOCAL_CHECK = ROOT / "data" / "validation" / "local-check.json"


def provenance_digest():
    return "sha256:" + hashlib.sha256((ROOT / "data" / "rdf" / "provenance.ttl").read_bytes()).hexdigest()


def require_local_check():
    if not LOCAL_CHECK.exists():
        sys.exit("no local check found: run scripts/check_local.py first")
    check = json.loads(LOCAL_CHECK.read_text())
    if check.get("provenance") != provenance_digest() or not check.get("passed"):
        sys.exit("the generated files changed since the last passing scripts/check_local.py run; run it again")


def local_hashes():
    """graph IRI -> content hash, as recorded in the local provenance graph by build_rdf.py."""
    g = Graph().parse(ROOT / "data" / "rdf" / "provenance.ttl")
    return {str(s): str(o) for s, o in g.subject_objects(DCTERMS.identifier) if str(o).startswith("sha256:")}


def settings():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    missing = [k for k in ("STARDOG_ENDPOINT", "STARDOG_DATABASE", "STARDOG_USERNAME", "STARDOG_PASSWORD")
               if not env.get(k)]
    if missing:
        sys.exit(f"missing in .env: {missing}")
    return env


class Stardog:
    def __init__(self, env):
        self.base = f"{env['STARDOG_ENDPOINT'].rstrip('/')}/{env['STARDOG_DATABASE']}"
        token = base64.b64encode(f"{env['STARDOG_USERNAME']}:{env['STARDOG_PASSWORD']}".encode()).decode()
        self.auth = {"Authorization": f"Basic {token}"}

    def call(self, path, data=None, content_type=None, accept=None, method="POST"):
        headers = dict(self.auth)
        if content_type:
            headers["Content-Type"] = content_type
        if accept:
            headers["Accept"] = accept
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                return resp.read().decode()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"{method} {path.split('?')[0]} -> HTTP {exc.code}: "
                               f"{exc.read()[:500].decode(errors='replace')}") from None

    def remote_hashes(self):
        """graph IRI -> content hash in Stardog's provenance graph ({} for an empty database)."""
        q = (f"SELECT ?g ?h WHERE {{ GRAPH <{PROVENANCE_GRAPH}> {{ ?g <{DCTERMS.identifier}> ?h "
             'FILTER STRSTARTS(STR(?h), "sha256:") } }')
        body = self.call("/query?" + urllib.parse.urlencode({"query": q}), method="GET",
                         accept="application/sparql-results+json")
        return {b["g"]["value"]: b["h"]["value"] for b in json.loads(body)["results"]["bindings"]}

    def count_per_graph(self):
        q = "SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g"
        body = self.call("/query?" + urllib.parse.urlencode({"query": q}), method="GET",
                         accept="application/sparql-results+json")
        return {b["g"]["value"]: int(b["n"]["value"]) for b in json.loads(body)["results"]["bindings"]}


def gate(sd, tx):
    """SHACL violations in the transaction's uncommitted state: {message: count}."""
    query = f"VALIDATE ALL USING SHAPES GRAPH <{SHAPES_GRAPH}>"
    report = Graph().parse(data=sd.call(f"/{tx}/query?" + urllib.parse.urlencode({"query": query}),
                                        method="GET", accept="text/turtle"), format="turtle")
    out = defaultdict(int)
    for r in report.subjects(SH.resultSeverity, SH.Violation):
        out[str(report.value(r, SH.resultMessage) or report.value(r, SH.sourceConstraintComponent))] += 1
    return dict(out)


def main():
    full, dry_run = "--full" in sys.argv, "--dry-run" in sys.argv
    require_local_check()
    env = settings()
    sd = Stardog(env)

    files_by_graph = defaultdict(list)
    with open(ROOT / "data" / "rdf" / "manifest.csv", newline="") as f:
        for row in csv.DictReader(f):
            files_by_graph[row["graph"]].append(row["file"])

    local, remote = local_hashes(), ({} if full else sd.remote_hashes())
    changed = [g for g in files_by_graph if g != PROVENANCE_GRAPH and local.get(g) != remote.get(g)]
    stale = sorted(set(sd.count_per_graph()) - set(files_by_graph))
    if not changed and not stale:
        print("Stardog is up to date: every graph's content hash matches; nothing to load")
        return
    changed.append(PROVENANCE_GRAPH)  # records the new hashes
    print(f"{len(changed) - 1} of {len(files_by_graph) - 1} graphs changed: "
          + ", ".join(g.rsplit("/graph/", 1)[-1] for g in changed[:-1]))
    if stale:
        print("graphs in Stardog but not in the manifest (dropped in this transaction): " + ", ".join(stale))
    if dry_run:
        return

    expected = {}
    tx = sd.call("/transaction/begin").strip()
    print(f"transaction {tx}")
    try:
        for graph_iri in stale:
            sd.call(f"/{tx}/clear?" + urllib.parse.urlencode({"graph-uri": graph_iri}))
        for graph_iri in changed:
            files = files_by_graph[graph_iri]
            g = Graph()
            for file in files:
                g.parse(ROOT / file)
            expected[graph_iri] = len(g)
            graph_param = urllib.parse.urlencode({"graph-uri": graph_iri})
            sd.call(f"/{tx}/clear?{graph_param}")
            triples = list(g)
            for start in range(0, len(triples), BATCH):
                chunk = Graph()
                for t in triples[start:start + BATCH]:
                    chunk.add(t)
                sd.call(f"/{tx}/add?{graph_param}", data=chunk.serialize(format="nt").encode("utf-8"),
                        content_type="application/n-triples")
            print(f"  {len(g):>8,}  {graph_iri}  <- {', '.join(files)}")
        violations = gate(sd, tx)
        if violations:
            sd.call(f"/transaction/rollback/{tx}")
            print(f"\nSHACL gate: {sum(violations.values())} violations; rolled back, database unchanged",
                  file=sys.stderr)
            for message, n in sorted(violations.items(), key=lambda x: -x[1]):
                print(f"  {n:>6}  {message}", file=sys.stderr)
            sys.exit(1)
        print("SHACL gate: 0 violations")
        sd.call(f"/transaction/commit/{tx}")
        print("committed")
    except Exception:
        try:
            sd.call(f"/transaction/rollback/{tx}")
            print("rolled back; database unchanged", file=sys.stderr)
        except Exception as exc:  # report the original error, not the failed rollback
            print(f"rollback failed too ({exc}); check the database", file=sys.stderr)
        raise

    actual = sd.count_per_graph()
    problems = {g: (n, actual.get(g, 0)) for g, n in expected.items() if actual.get(g, 0) != n}
    extra = sorted(set(actual) - set(files_by_graph))
    print(f"\nverify: {len(expected)} reloaded graphs, {sum(expected.values()):,} triples expected; "
          f"{sum(actual.values()):,} triples in Stardog in all")
    for g, (want, got) in problems.items():
        print(f"  MISMATCH {g}: expected {want:,}, found {got:,}")
    for g in extra:
        print(f"  graph not in manifest: {g} ({actual[g]:,} triples)")
    if problems:
        sys.exit(1)
    print("all reloaded graphs match")


if __name__ == "__main__":
    main()
