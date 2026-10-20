"""Validate the knowledge graph in Stardog against the SHACL shapes and summarize the report.

Runs `VALIDATE ALL USING SHAPES GRAPH <.../graph/shapes>` over the API (credentials in .env),
saves the full SHACL report to data/validation/, and writes docs/validation-report.md:
results grouped by severity and message, with counts and example focus nodes.

Exit code 1 if any sh:Violation is found, so it can gate a pipeline.

Usage: .venv/bin/python scripts/validate.py
"""
import sys
import urllib.parse
from collections import defaultdict
from datetime import date
from pathlib import Path

from rdflib import Graph, Namespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_stardog import Stardog, settings  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SH = Namespace("http://www.w3.org/ns/shacl#")
SHAPES_GRAPH = "https://dgg32.github.io/glp/graph/shapes"
BASE = "https://dgg32.github.io/glp/"
ORDER = {"Violation": 0, "Warning": 1, "Info": 2}


def short(node):
    s = str(node)
    return s.replace(BASE, "") if s.startswith(BASE) else s


def main():
    sd = Stardog(settings())
    query = f"VALIDATE ALL USING SHAPES GRAPH <{SHAPES_GRAPH}>"
    body = sd.call("/query?" + urllib.parse.urlencode({"query": query}), method="GET", accept="text/turtle")

    out_dir = ROOT / "data" / "validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"report-{date.today().isoformat()}.ttl"
    report_path.write_text(body)

    g = Graph().parse(data=body, format="turtle")
    groups = defaultdict(list)
    for r in g.subjects(SH.resultSeverity, None):
        severity = str(g.value(r, SH.resultSeverity)).split("#")[-1]
        message = str(g.value(r, SH.resultMessage) or g.value(r, SH.sourceConstraintComponent))
        groups[(severity, message)].append((g.value(r, SH.focusNode), g.value(r, SH.value)))

    totals = defaultdict(int)
    for (severity, _), items in groups.items():
        totals[severity] += len(items)

    lines = [
        "# SHACL validation report",
        "",
        f"*Generated {date.today().isoformat()} by `scripts/validate.py` against Stardog database "
        f"`{settings()['STARDOG_DATABASE']}` with [shapes/diabetes-market-shapes.ttl](../shapes/diabetes-market-shapes.ttl). "
        f"Full report: `{report_path.relative_to(ROOT)}`.*",
        "",
        f"**{totals['Violation']} violations, {totals['Warning']} warnings, {totals['Info']} info.**",
        "",
        "| Severity | Count | Rule | Examples (focus node → value) |",
        "|---|---:|---|---|",
    ]
    for (severity, message), items in sorted(groups.items(), key=lambda kv: (ORDER.get(kv[0][0], 9), -len(kv[1]))):
        examples = "; ".join(f"`{short(f)}`" + (f" → `{short(v)}`" if v is not None else "")
                             for f, v in items[:3])
        lines.append(f"| {severity} | {len(items)} | {message} | {examples} |")
    if not groups:
        lines.append("| — | 0 | The data conforms to all shapes. | |")
    (ROOT / "docs" / "validation-report.md").write_text("\n".join(lines) + "\n")

    print("\n".join(lines[6:]))
    print(f"\nfull report: {report_path.relative_to(ROOT)}; summary: docs/validation-report.md")
    sys.exit(1 if totals["Violation"] else 0)


if __name__ == "__main__":
    main()
