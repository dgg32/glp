"""Create the read-only Snowflake role for the MCP server (mcp_server/snowflake_server.py).

  role       SNOWFLAKE_READER_ROLE (default GLP_READER), granted to the user of .env
  warehouse  USAGE on SNOWFLAKE_WAREHOUSE (to run queries; no OPERATE, MODIFY or ownership)
  data       USAGE on the database and its schemas VOCAB, US, JP, SEMANTIC; SELECT on every table, view and
             semantic view in them, now and in future (deploy_semantic_view.py recreates the views); REFERENCES on
             the semantic views, which GET_DDL needs

Nothing else: the role can create, change or delete nothing, so the server is read-only whatever SQL it is sent,
provided the session switches secondary roles off (the server does): the user's DEFAULT_SECONDARY_ROLES = ('ALL')
would otherwise add every other role it holds, ACCOUNTADMIN included.
Run as the admin role of .env (SNOWFLAKE_ROLE). Rerunnable.

Usage: .venv-snowflake/bin/python scripts/setup_snowflake_reader.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_snowflake import connect  # noqa: E402  (also loads .env)

SCHEMAS = ["VOCAB", "US", "JP", "SEMANTIC"]
OBJECTS = ["TABLES", "VIEWS", "SEMANTIC VIEWS"]


def main():
    con = connect()
    cur = con.cursor()
    role = os.environ.get("SNOWFLAKE_READER_ROLE", "GLP_READER")
    db, wh = os.environ["SNOWFLAKE_DATABASE"], os.environ["SNOWFLAKE_WAREHOUSE"]
    # SNOWFLAKE_USER is the login name (an email); grants need the user name, which may differ and be lowercase
    user = cur.execute("SELECT CURRENT_USER()").fetchone()[0]
    statements = [f"CREATE ROLE IF NOT EXISTS {role} COMMENT = 'Read-only access to {db} for the MCP server'",
                  f"GRANT USAGE ON WAREHOUSE {wh} TO ROLE {role}",
                  f"GRANT USAGE ON DATABASE {db} TO ROLE {role}"]
    for schema in SCHEMAS:
        statements.append(f"GRANT USAGE ON SCHEMA {db}.{schema} TO ROLE {role}")
        for kind in OBJECTS:
            statements.append(f"GRANT SELECT ON ALL {kind} IN SCHEMA {db}.{schema} TO ROLE {role}")
            statements.append(f"GRANT SELECT ON FUTURE {kind} IN SCHEMA {db}.{schema} TO ROLE {role}")
    # GET_DDL of a semantic view (describe_model) needs REFERENCES, which reveals the definition, not data
    for scope in ("ALL", "FUTURE"):
        statements.append(f"GRANT REFERENCES ON {scope} SEMANTIC VIEWS IN SCHEMA {db}.SEMANTIC TO ROLE {role}")
    statements.append(f'GRANT ROLE {role} TO USER "{user}"')
    for sql in statements:
        cur.execute(sql)
        print("ok ", sql)

    privileges = {r[1] for r in cur.execute(f"SHOW GRANTS TO ROLE {role}").fetchall()}
    if privileges - {"USAGE", "SELECT", "REFERENCES"}:
        sys.exit(f"{role} holds more than USAGE, SELECT and REFERENCES: {sorted(privileges)}")
    print(f"\n{role}: only USAGE, SELECT and REFERENCES. Set SNOWFLAKE_READER_ROLE={role} in .env for the MCP server.")
    con.close()


if __name__ == "__main__":
    main()
