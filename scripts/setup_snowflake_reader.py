"""Create the read-only Snowflake role for the MCP server (mcp_server/snowflake_server.py).

  role       SNOWFLAKE_READER_ROLE (default GLP_READER), granted to the user of .env
  warehouse  USAGE on SNOWFLAKE_WAREHOUSE (to run queries; no OPERATE, MODIFY or ownership)
  data       USAGE on the database and its schemas VOCAB, US, JP, SEMANTIC; SELECT on every table, view and
             semantic view in them, now and in future (deploy_semantic_view.py recreates the views); REFERENCES on
             the semantic views, which GET_DDL needs

  user       with SNOWFLAKE_READER_USER set: a service user (TYPE = SERVICE, key-pair only) that holds this role and
             nothing else, its public key derived from SNOWFLAKE_READER_PRIVATE_KEY_PATH

Nothing else: the role can create, change or delete nothing. A role alone does not make a session read-only,
though: Snowflake lets a session take back any role its user holds (USE ROLE, USE SECONDARY ROLES ALL, accepted
without a privilege check), and the user of .env holds ACCOUNTADMIN. Only the service user, which holds no other
role, makes the MCP server read-only whatever SQL it is sent. Make its key pair like the admin's:
  openssl genrsa 2048 | openssl pkcs8 -topk8 -nocrypt -out ~/.ssh/glp_reader.p8
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


def public_key(private_key_path):
    """The base64 body of the public key that belongs to a PKCS#8 private key, as ALTER USER wants it."""
    from cryptography.hazmat.primitives import serialization
    private = serialization.load_pem_private_key(Path(private_key_path).expanduser().read_bytes(), password=None)
    pem = private.public_key().public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return "".join(line for line in pem.splitlines() if "PUBLIC KEY" not in line)


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
    if reader := os.environ.get("SNOWFLAKE_READER_USER"):
        key = public_key(os.environ["SNOWFLAKE_READER_PRIVATE_KEY_PATH"])
        statements += [f"CREATE USER IF NOT EXISTS {reader} TYPE = SERVICE COMMENT = 'Read-only login for the MCP server'",
                       f"ALTER USER {reader} SET RSA_PUBLIC_KEY = '{key}' DEFAULT_ROLE = {role} "
                       f"DEFAULT_WAREHOUSE = {wh} DEFAULT_SECONDARY_ROLES = ()",
                       f"GRANT ROLE {role} TO USER {reader}"]
    for sql in statements:
        cur.execute(sql)
        print("ok ", sql)

    grants = cur.execute(f"SHOW GRANTS TO ROLE {role}").fetchall()  # (created_on, privilege, granted_on, name, ...)
    privileges = {r[1] for r in grants}
    if privileges - {"USAGE", "SELECT", "REFERENCES"}:
        sys.exit(f"{role} holds more than USAGE, SELECT and REFERENCES: {sorted(privileges)}")
    # A granted role shows up as USAGE on a ROLE and would bring all of that role's privileges with it
    if inherited := sorted(r[3] for r in grants if r[2] == "ROLE"):
        sys.exit(f"{role} inherits other roles: {inherited}")
    if reader:
        roles = sorted(r[1] for r in cur.execute(f"SHOW GRANTS TO USER {reader}").fetchall())
        if roles != [role.upper()]:
            sys.exit(f"{reader} holds roles other than {role}: {roles}")
        print(f"{reader}: holds only {role}")
    print(f"\n{role}: only USAGE, SELECT and REFERENCES. Set SNOWFLAKE_READER_ROLE={role} in .env for the MCP server.")
    con.close()


if __name__ == "__main__":
    main()
