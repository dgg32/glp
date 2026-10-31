"""Load the tables exported by scripts/export_snowflake.py into Snowflake (database from .env, schemas VOCAB and US).

Loads only what the export checked: every CSV must still have the sha256 recorded in
data/snowflake/tables.json, which export_snowflake.py writes only after its checks passed.
Then, per table: CREATE OR REPLACE with primary and foreign keys (declared, not enforced by Snowflake),
PUT to the table stage, COPY INTO (abort on the first bad row). Snowflake commits DDL immediately, so
there is no all-or-nothing transaction as in load_stardog.py; instead the load is verified afterwards
(row counts, total claims and cost) and stops with an error if anything differs. Rerunnable.

Provenance: each table comment names its source graphs and the export it came from, and every load
appends one row per table to PUBLIC.LOAD_LOG (time, RDF provenance hash, file hash, rows).

Credentials come from .env (SNOWFLAKE_ACCOUNT, _USER, _PRIVATE_KEY_PATH, _ROLE, _WAREHOUSE, _DATABASE);
key-pair authentication. Runs in its own environment because the connector does not support Python 3.15:
  uv venv --python 3.13 .venv-snowflake && uv pip install --python .venv-snowflake/bin/python -r requirements-snowflake.txt

Usage: .venv-snowflake/bin/python scripts/load_snowflake.py
"""
import csv
import hashlib
import json
import os
import sys
import warnings
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
EXPORT = ROOT / "data" / "snowflake"


def connect():
    import snowflake.connector
    warnings.filterwarnings("ignore", category=FutureWarning, module="snowflake")
    load_dotenv(ROOT / ".env")
    env = {k: os.environ.get("SNOWFLAKE_" + k) for k in
           ("ACCOUNT", "USER", "PRIVATE_KEY_PATH", "ROLE", "WAREHOUSE", "DATABASE")}
    if missing := [k for k, v in env.items() if not v]:
        sys.exit("missing in .env: " + ", ".join("SNOWFLAKE_" + k for k in missing))
    return snowflake.connector.connect(
        account=env["ACCOUNT"], user=env["USER"], authenticator="SNOWFLAKE_JWT",
        private_key_file=os.path.expanduser(env["PRIVATE_KEY_PATH"]), role=env["ROLE"],
        warehouse=env["WAREHOUSE"], database=env["DATABASE"])


def checked_export():
    path = EXPORT / "tables.json"
    if not path.exists():
        sys.exit("no checked export: run .venv/bin/python scripts/export_snowflake.py first")
    manifest = json.loads(path.read_text())
    for t in manifest["tables"]:
        if hashlib.sha256((EXPORT / t["file"]).read_bytes()).hexdigest() != t["sha256"]:
            sys.exit(f"{t['file']} changed since the export was checked; run export_snowflake.py again")
    return manifest


def quote(text):
    return "'" + text.replace("\\", "\\\\").replace("'", "''") + "'"


def ddl(t):
    lines = list(t["columns"]) + [f"PRIMARY KEY ({', '.join(t['key'])})"]
    lines += [f"FOREIGN KEY ({col}) REFERENCES {target}" for col, target in t["refs"].items()]
    return f"CREATE OR REPLACE TABLE {t['name']} (\n  " + ",\n  ".join(lines) + "\n)"


def local_totals():
    claims, cost = 0, Decimal(0)
    with open(EXPORT / "US.PRESCRIPTION.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            claims += int(r["TOTAL_CLAIMS"])
            cost += Decimal(r["TOTAL_DRUG_COST"] or 0)
    return claims, cost


def main():
    manifest = checked_export()
    tables = manifest["tables"]
    con = connect()
    cur = con.cursor()
    run = lambda sql, *params: cur.execute(sql, params or None).fetchall()  # noqa: E731
    for schema in sorted({t["name"].split(".")[0] for t in tables} | {"PUBLIC"}):
        run(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    run("""CREATE FILE FORMAT IF NOT EXISTS PUBLIC.GLP_CSV TYPE = CSV SKIP_HEADER = 1
           FIELD_OPTIONALLY_ENCLOSED_BY = '"' EMPTY_FIELD_AS_NULL = TRUE ENCODING = 'UTF8'
           ERROR_ON_COLUMN_COUNT_MISMATCH = TRUE""")
    run("""CREATE TABLE IF NOT EXISTS PUBLIC.LOAD_LOG (LOADED_AT TIMESTAMP_TZ, TABLE_NAME VARCHAR, ROWS_LOADED NUMBER,
           FILE_SHA256 VARCHAR, RDF_PROVENANCE VARCHAR, EXPORTED_AT VARCHAR)""")

    # Drop referencing tables before the tables they point to, then create in dependency order.
    for t in reversed(tables):
        run(f"DROP TABLE IF EXISTS {t['name']}")
    export_id = f"export {manifest['exported_at']}, RDF provenance {manifest['rdf_provenance']}"
    for t in tables:
        schema, table = t["name"].split(".")
        run(ddl(t))
        run(f"COMMENT ON TABLE {t['name']} IS {quote(t['comment'] + '. Loaded from ' + export_id)}")
        run(f"PUT 'file://{EXPORT / t['file']}' @{schema}.%{table} AUTO_COMPRESS = TRUE OVERWRITE = TRUE")
        result = run(f"""COPY INTO {t['name']} FROM @{schema}.%{table}
                         FILE_FORMAT = (FORMAT_NAME = PUBLIC.GLP_CSV) ON_ERROR = ABORT_STATEMENT PURGE = TRUE""")
        print(f"{t['rows']:>8,}  {t['name']}  ({result[0][1]})")

    errors = []
    for t in tables:
        n = run(f"SELECT COUNT(*) FROM {t['name']}")[0][0]
        if n != t["rows"]:
            errors.append(f"{t['name']}: {n:,} rows in Snowflake, {t['rows']:,} exported")
    claims, cost = run("SELECT SUM(TOTAL_CLAIMS), SUM(TOTAL_DRUG_COST) FROM US.PRESCRIPTION")[0]
    if (claims, cost) != local_totals():
        errors.append(f"US.PRESCRIPTION totals differ: Snowflake {(claims, cost)}, export {local_totals()}")
    if errors:
        sys.exit("load verification failed:\n  " + "\n  ".join(errors))

    cur.executemany("INSERT INTO PUBLIC.LOAD_LOG VALUES (CURRENT_TIMESTAMP(), %s, %s, %s, %s, %s)",
                    [(t["name"], t["rows"], t["sha256"], manifest["rdf_provenance"], manifest["exported_at"])
                     for t in tables])
    con.commit()
    print(f"verified: {len(tables)} tables, {claims:,} claims, ${cost:,.2f} gross cost")
    con.close()


if __name__ == "__main__":
    main()
