"""Run every SPARQL query in queries/ against Stardog and write the results to docs/query-results.md.

A query file whose first lines contain "# reasoning: true" is run with reasoning on; it is
also run with reasoning off, to show what the reasoner adds. Credentials come from .env.

--local runs the queries against the generated files instead (all graphs of data/rdf/manifest.csv in an
in-memory pyoxigraph store, queried as their union, like Stardog's tag:stardog:api:context:all), without
reasoning, and writes data/validation/query-results-local.md. Part of scripts/check_local.py: every
query is tried locally before anything is pushed to Stardog.

Usage: .venv/bin/python scripts/run_queries.py [--local] [name-filter]
"""
import csv
import json
import sys
import time
import urllib.parse
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_stardog import Stardog, settings  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class Local:
    """The generated graphs in an in-memory store, queried like Stardog's union of all named graphs."""

    def __init__(self):
        import pyoxigraph
        self.ox = pyoxigraph
        self.store = pyoxigraph.Store()
        with open(ROOT / "data" / "rdf" / "manifest.csv", newline="") as f:
            for row in csv.DictReader(f):
                self.store.bulk_load(path=str(ROOT / row["file"]), format=pyoxigraph.RdfFormat.TURTLE,
                                     to_graph=pyoxigraph.NamedNode(row["graph"]))

    def call(self, query, reasoning):
        if reasoning:
            raise NotImplementedError("reasoning runs in Stardog only")
        query = query.replace("FROM <tag:stardog:api:context:all>", "")
        result = self.store.query(query, use_default_graph_as_union=True)
        variables = [v.value for v in result.variables]
        rows = []
        for solution in result:
            row = {}
            for v in variables:
                term = solution[v]
                if term is None:
                    continue
                cell = {"value": term.value}
                if isinstance(term, self.ox.Literal):
                    cell["datatype"] = term.datatype.value
                row[v] = cell
            rows.append(row)
        return variables, rows


def run(sd, query, reasoning):
    if isinstance(sd, Local):
        t = time.time()
        variables, rows = sd.call(query, reasoning)
        return variables, rows, time.time() - t
    params = {"query": query}
    if reasoning:
        params["reasoning"] = "true"
    t = time.time()
    body = sd.call("/query?" + urllib.parse.urlencode(params), method="GET",
                   accept="application/sparql-results+json")
    result = json.loads(body)
    return result["head"]["vars"], result["results"]["bindings"], time.time() - t


def fmt(cell):
    if cell is None:
        return ""
    value = cell["value"]
    if cell.get("datatype", "").endswith(("#integer", "#decimal", "#double", "#long", "#int")):
        number = float(value)
        return f"{number:,.0f}" if number == int(number) else f"{number:,.2f}"
    return value.replace("https://dgg32.github.io/glp/", "")


def table(variables, rows):
    out = ["| " + " | ".join(variables) + " |", "|" + "---|" * len(variables)]
    for r in rows:
        out.append("| " + " | ".join(fmt(r.get(v)) for v in variables) + " |")
    return out


def main():
    args = sys.argv[1:]
    local = "--local" in args
    name_filter = next((a for a in args if a != "--local"), "")
    sd = Local() if local else Stardog(settings())
    target = f"the generated files (local, no reasoning)" if local else \
        f"Stardog database `{settings()['STARDOG_DATABASE']}`"
    lines = ["# Query results", "",
             f"*Generated {date.today().isoformat()} by `scripts/run_queries.py` against {target}. "
             "Interpretation: [findings.md](findings.md).*", ""]
    failures = []
    for path in sorted((ROOT / "queries").glob("*.rq")):
        if name_filter not in path.name:
            continue
        query = path.read_text(encoding="utf-8")
        header = [l[1:].strip() for l in query.splitlines() if l.startswith("#")]
        reasoning = any(h.lower() == "reasoning: true" for h in header)
        description = " ".join(h for h in header if not h.lower().startswith("reasoning:"))
        lines += [f"## {path.stem}", "", f"[queries/{path.name}](../queries/{path.name}): {description}", ""]
        modes = [False, True] if reasoning and not local else [False]
        for mode in modes:
            try:
                variables, rows, seconds = run(sd, query, mode)
            except Exception as exc:  # local: report every failing query, not only the first
                if not local:
                    raise
                failures.append(f"{path.name}: {exc}")
                print(f"{path.name}: FAILED {exc}")
                continue
            label = f"reasoning {'on' if mode else 'off'}, " if reasoning else ""
            lines += [f"*{label}{len(rows)} rows, {seconds:.1f} s*", ""] + table(variables, rows) + [""]
            print(f"{path.name} ({label}{len(rows)} rows, {seconds:.1f} s)")
            print("\n".join(table(variables, rows)[:14]), "\n")
    if local:
        out = ROOT / "data" / "validation" / "query-results-local.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {out.relative_to(ROOT)}" + (f"; {len(failures)} queries failed" if failures else ""))
        if failures:
            sys.exit(1)
    elif not name_filter:
        (ROOT / "docs" / "query-results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("wrote docs/query-results.md")


if __name__ == "__main__":
    main()
