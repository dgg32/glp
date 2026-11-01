# glp-stardog MCP server

Lets Claude (or any MCP client) answer questions about the Diabetes Drug Market knowledge graph in
Stardog, in English, Japanese or Chinese.

| Tool | What it does |
|---|---|
| `resolve_term` | Any drug, drug class, specialty, indication or company name, in any language or spelling (including raw CMS spellings and full-width characters), to the concept IRIs in the graph. Uses SKOS preferred, alternative and hidden labels. |
| `describe_model` | Classes, properties, conventions, named graphs and worked example queries, read live from the ontology in Stardog. |
| `run_sparql` | Read-only SPARQL over all named graphs, with optional OWL reasoning. |

## Read-only, three layers

1. The server rejects anything but SELECT, ASK, CONSTRUCT and DESCRIBE (update keywords are
   detected outside strings, IRIs and comments).
2. Queries go to Stardog's read endpoint, which refuses updates.
3. The server logs in as a user with **READ permission only**. It never falls back to the
   loader account.

## Setup

1. In Stardog Studio (Security, lock icon), create a user, e.g. `glp_reader`, with only
   `READ` on `db` `glp`.
2. Add to `.env` in the project root:
   ```
   STARDOG_ENDPOINT=https://<your-endpoint>.stardog.cloud:5820
   STARDOG_DATABASE=glp
   STARDOG_READER_USERNAME=glp_reader
   STARDOG_READER_PASSWORD=...
   ```
3. Install: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`

### Claude Code

The project's `.mcp.json` registers the server as `glp-stardog`. Restart Claude Code in this folder
and approve the server when asked.

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (use your own paths) and
restart Claude Desktop:

```json
{
  "mcpServers": {
    "glp-stardog": {
      "command": "/path/to/glp/.venv/bin/python",
      "args": ["/path/to/glp/mcp_server/server.py"]
    }
  }
}
```

### Any other MCP client

Run `.venv/bin/python mcp_server/server.py` as a stdio server.

## Test

`.venv/bin/python tests/test_mcp_server.py` starts the server through a real MCP client and checks
term resolution in three languages, the model description, reasoning on/off and update rejection.

## glp-snowflake: the same pattern over the Snowflake semantic views

`snowflake_server.py` answers the same kind of questions from Snowflake (`GLP.SEMANTIC.DIABETES_MARKET` and
`JAPAN_MARKET`, generated from the ontology by `scripts/build_osi.py`).

| Tool | What it does |
|---|---|
| `resolve_term` | Any drug, class, specialty, company, prefecture or age band, in any language or spelling, to its id and how to filter on it. Uses the SKOS labels exported to `GLP.VOCAB.LABEL`, plus product and company names (a Japanese holder resolves to its global corporate group). |
| `describe_model` | The semantic view's definition (`GET_DDL`): datasets, dimensions, facts, metrics, descriptions and, in the native views, synonyms, instructions and verified queries. |
| `run_sql` | One read-only statement, preferably `SELECT * FROM SEMANTIC_VIEW(...)`. |

`GLP_SF_LAYER=osi` makes it describe the `_OSI` views instead (imported from OSI YAML).

Read-only in three layers: a statement check (SELECT, WITH, SHOW, DESCRIBE, EXPLAIN; one statement per call); the
role `GLP_READER` with only USAGE, SELECT and REFERENCES (`scripts/setup_snowflake_reader.py`); and **secondary
roles switched off** in the session. The last one matters: Snowflake users default to
`DEFAULT_SECONDARY_ROLES = ('ALL')`, so `USE ROLE GLP_READER` alone still carries the privileges of every other role
the user holds, ACCOUNTADMIN included. The server refuses to start unless the session's secondary roles are empty.

Setup: `.venv-snowflake/bin/python scripts/setup_snowflake_reader.py` (as the admin role), then
`SNOWFLAKE_READER_ROLE=GLP_READER` in `.env`. Register `.venv-snowflake/bin/python mcp_server/snowflake_server.py`
like the Stardog server. Test: `.venv-snowflake/bin/python tests/test_snowflake_mcp_server.py`.
Evaluation against Cortex Analyst: `scripts/eval_claude.py` (see `snowflake_extension.md`).

## Example questions

- Which specialties prescribe the most Jardiance, and what share of their SGLT2 claims is it?
- 循環器内科医はSGLT2阻害薬とGLP-1受容体作動薬のどちらを多く処方していますか？
- 勃林格殷格翰在SGLT2抑制剂中的市场份额是多少？
- What does a month of each diabetes drug class cost Medicare?
