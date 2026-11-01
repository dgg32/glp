"""End-to-end test of the Snowflake MCP server through a real MCP stdio client (as Claude would use it).

Starts mcp_server/snowflake_server.py, lists its tools, resolves terms in three languages, reads both views'
definitions, runs a semantic view query, and checks that writes are refused, by the statement check and, for a
statement that passes it, by the read-only role. The write probes change nothing even if they ran (WHERE 1 = 0).
Needs SNOWFLAKE_READER_ROLE in .env (scripts/setup_snowflake_reader.py).

Usage: .venv-snowflake/bin/python tests/test_snowflake_mcp_server.py
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
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server" / "snowflake_server.py")],
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
            check("three tools listed", tools == {"resolve_term", "describe_model", "run_sql"}, str(tools))
            check("server instructions sent", "resolve_term" in (init.instructions or ""))

            for term, expected in [("Jardiance", "id jardiance"),
                                   ("SGLT2阻害薬", "id SGLT2Inhibitor"),
                                   ("恩格列净", "id empagliflozin"),
                                   ("ＳＧＬＴ２阻害薬", "id SGLT2Inhibitor"),  # full-width input
                                   ("Insulin Glargine,hum.Rec.Anlog", "id insulinGlargine"),
                                   ("循環器内科医", "id 207RC0000X"),
                                   ("boehringer", "id 529900P5FAANZASUYL28"),  # LEI of the Boehringer group
                                   ("日本ベーリンガーインゲルハイム", "529900P5FAANZASUYL28"),  # subsidiary -> group
                                   ("東京都", "prefecture_code = '13'")]:
                out = text_of(await session.call_tool("resolve_term", {"text": term}))
                check(f"resolve_term {term!r}", expected in out, out[:300])

            for model, view in (("us", "DIABETES_MARKET"), ("jp", "JAPAN_MARKET")):
                out = text_of(await session.call_tool("describe_model", {"model": model}))
                check(f"describe_model {model} has the view definition",
                      f"semantic view {view}" in out and "metrics" in out.lower(), out[:200])

            out = text_of(await session.call_tool("run_sql", {"sql": (
                "SELECT * FROM SEMANTIC_VIEW(GLP.SEMANTIC.DIABETES_MARKET METRICS class_claims "
                "WHERE therapeutic_class.class_id = 'SGLT2Inhibitor')")}))
            check("SGLT2 claims = 198,686", out.splitlines()[-1].strip() == "198686", out)

            for sql in ["DELETE FROM GLP.US.PRODUCT WHERE 1 = 0", "SELECT 1; DELETE FROM GLP.US.PRODUCT WHERE 1 = 0"]:
                out = text_of(await session.call_tool("run_sql", {"sql": sql}))
                check(f"statement check refuses {sql!r}", out.startswith("Rejected"), out)
            # passes the statement check (starts with WITH), so only the role stops it
            out = text_of(await session.call_tool("run_sql", {"sql": (
                "WITH x AS (SELECT 1 AS a) DELETE FROM GLP.US.PRODUCT WHERE 1 = 0")}))
            check("role refuses a write that passes the statement check", "Snowflake error" in out, out)

    print("\nall Snowflake MCP checks passed" if not failures else f"\n{len(failures)} failed: {failures}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
