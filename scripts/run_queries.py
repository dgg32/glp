"""Run every SPARQL query in queries/ against Stardog and write the results to docs/query-results.md.

A query file whose first lines contain "# reasoning: true" is run with reasoning on; it is
also run with reasoning off, to show what the reasoner adds. Credentials come from .env.

Usage: .venv/bin/python scripts/run_queries.py [name-filter]
"""
import json
import sys
import time
import urllib.parse
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_stardog import Stardog, settings  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def run(sd, query, reasoning):
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
    name_filter = sys.argv[1] if len(sys.argv) > 1 else ""
    sd = Stardog(settings())
    lines = ["# Query results", "",
             f"*Generated {date.today().isoformat()} by `scripts/run_queries.py` against Stardog database "
             f"`{settings()['STARDOG_DATABASE']}`. Interpretation: [findings.md](findings.md).*", ""]
    for path in sorted((ROOT / "queries").glob("*.rq")):
        if name_filter not in path.name:
            continue
        query = path.read_text(encoding="utf-8")
        header = [l[1:].strip() for l in query.splitlines() if l.startswith("#")]
        reasoning = any(h.lower() == "reasoning: true" for h in header)
        description = " ".join(h for h in header if not h.lower().startswith("reasoning:"))
        lines += [f"## {path.stem}", "", f"[queries/{path.name}](../queries/{path.name}): {description}", ""]
        modes = [False, True] if reasoning else [False]
        for mode in modes:
            variables, rows, seconds = run(sd, query, mode)
            label = f"reasoning {'on' if mode else 'off'}, " if reasoning else ""
            lines += [f"*{label}{len(rows)} rows, {seconds:.1f} s*", ""] + table(variables, rows) + [""]
            print(f"{path.name} ({label}{len(rows)} rows, {seconds:.1f} s)")
            print("\n".join(table(variables, rows)[:14]), "\n")
    if not name_filter:
        (ROOT / "docs" / "query-results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("wrote docs/query-results.md")


if __name__ == "__main__":
    main()
