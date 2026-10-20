"""End-to-end test of the MCP server through a real MCP stdio client (as Claude would use it).

Starts mcp_server/server.py, lists its tools, resolves terms in three languages, reads the model
description, runs a reasoning query, and checks that an update query is rejected.
Needs STARDOG_READER_USERNAME / STARDOG_READER_PASSWORD in .env (or the environment).

Usage: .venv/bin/python tests/test_mcp_server.py
"""
import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent


def text_of(result):
    return "\n".join(c.text for c in result.content if getattr(c, "text", None))


async def main():
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server" / "server.py")],
                                   env={**os.environ}, cwd=str(ROOT))
    failures = []

    def check(name, condition, detail=""):
        print(("PASS " if condition else "FAIL ") + name + (f"  [{detail}]" if detail and not condition else ""))
        if not condition:
            failures.append(name)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}
            check("three tools listed", tools == {"resolve_term", "describe_model", "run_sparql"}, str(tools))
            check("server instructions sent", "resolve_term" in (init.instructions or ""))

            for term, expected in [("Jardiance", "product/jardiance"),
                                   ("SGLT2阻害薬", "therapeutic-class/SGLT2Inhibitor"),
                                   ("恩格列净", "substance/empagliflozin"),
                                   ("ＳＧＬＴ２阻害薬", "therapeutic-class/SGLT2Inhibitor"),  # full-width input
                                   ("Insulin Glargine,hum.Rec.Anlog", "substance/insulinGlargine"),
                                   ("循環器内科医", "specialty/207RC0000X"),
                                   ("boehringer", "organization/529900P5FAANZASUYL28")]:  # LEI of the Boehringer group
                out = text_of(await session.call_tool("resolve_term", {"text": term}))
                check(f"resolve_term {term!r}", expected in out, out[:200])

            model = text_of(await session.call_tool("describe_model", {}))
            check("describe_model has classes, conventions and examples",
                  all(k in model for k in ("dm:Prescription", "## Conventions", "## Example queries")), model[:200])

            q = ("PREFIX dm: <https://dgg32.github.io/glp/ontology#>\n"
                 "SELECT (COUNT(DISTINCT ?doc) AS ?n) WHERE { ?doc a dm:SGLT2Prescriber }")
            off = text_of(await session.call_tool("run_sparql", {"query": q}))
            on = text_of(await session.call_tool("run_sparql", {"query": q, "reasoning": True}))
            check("reasoning off -> 0 SGLT2 prescribers", off.splitlines()[-1].strip() == "0", off)
            check("reasoning on -> 2701 SGLT2 prescribers", on.splitlines()[-1].strip() == "2701", on)

            rejected = text_of(await session.call_tool("run_sparql", {"query": "DROP ALL"}))
            check("update rejected", rejected.startswith("Rejected"), rejected)

    print("\nall MCP checks passed" if not failures else f"\n{len(failures)} failed: {failures}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
