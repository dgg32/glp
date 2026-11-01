"""MCP server for the Diabetes Drug Market data in Snowflake (the semantic views generated from the ontology).

The Snowflake counterpart of server.py (Stardog). Gives any MCP client three tools:

  resolve_term    any drug, drug class, specialty, indication, company, prefecture or age band, in any
                  language or spelling -> its id and names, and how to filter on it (SKOS labels in VOCAB.LABEL,
                  product and company names)
  describe_model  the semantic views' definitions (GET_DDL: datasets, dimensions, facts, metrics, descriptions and,
                  in the native views, synonyms, instructions and verified queries), read live from Snowflake
  run_sql         one read-only SQL statement, preferably SELECT ... FROM SEMANTIC_VIEW(...)

GLP_SF_LAYER=native (default) or osi chooses which views describe_model shows: GLP.SEMANTIC.DIABETES_MARKET and
JAPAN_MARKET, or their _OSI twins, imported from OSI YAML without synonyms, instructions and verified queries.

Read-only by design. The guarantee is the login: with SNOWFLAKE_READER_USER set, the server signs in as a service
user that holds no role but SNOWFLAKE_READER_ROLE (USAGE, SELECT and REFERENCES only;
scripts/setup_snowflake_reader.py), so no statement in the session can gain more. Without it, the server signs in
as SNOWFLAKE_USER with the reader role and secondary roles off; that user also holds the admin role, and Snowflake
lets any of its sessions take it back (USE ROLE, USE SECONDARY ROLES ALL, accepted without a privilege check), so
the statement check is then the only layer that holds: only SELECT/WITH/SHOW/DESCRIBE/EXPLAIN pass, one statement
per call. The session's role and secondary roles are checked at connect time and again before every statement; the
server refuses to run otherwise.

Run: .venv-snowflake/bin/python mcp_server/snowflake_server.py   (stdio transport)
"""
import logging
import os
import re
import unicodedata
import warnings
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

ROOT = Path(__file__).resolve().parent.parent
LAYER = os.environ.get("GLP_SF_LAYER", "native").lower()
MODELS = {"us": "DIABETES_MARKET", "jp": "JAPAN_MARKET"}
SUFFIX = {"native": "", "osi": "_OSI"}[LAYER]
VIEWS = {key: f"GLP.SEMANTIC.{name}{SUFFIX}" for key, name in MODELS.items()}

# How to filter on each kind of concept: semantic view dimensions where one exists, else the tables.
HOW_TO_USE = {
    "therapeutic_class": "therapeutic_class.class_id = '{id}' (both views; includes narrower classes)",
    "substance": "class {class_id}. US: product.cms_generic_name; Japan: product.active_substances (lists names). "
                 "Tables: GLP.VOCAB.SUBSTANCE, GLP.US.PRODUCT_SUBSTANCE, GLP.JP.PRODUCT_SUBSTANCE (SUBSTANCE_ID = '{id}')",
    "specialty": "specialty.specialty_code = '{id}' (US; a prescriber's primary specialty). Broader groupings: "
                 "GLP.VOCAB.SPECIALTY_ANCESTOR",
    "indication": "no dimension; GLP.US.PRODUCT_INDICATION (INDICATION_ID = '{id}')",
    "prefecture": "prefecture.prefecture_code = '{id}' (Japan)",
    "jp_drug_class": "jp_drug_class.jp_class_code = '{id}' (Japan)",
    "care_setting": "care_setting.care_setting_id = '{id}' (Japan)",
    "sex_age_group": "sex_age_group.sex_age_code = '{id}' (Japan)",
    "us_company": "US: prescription_class_company.manufacturer = '{name}' or organization.organization_id = '{id}'; "
                  "Japan: the corporate group of the Japanese holders, product.company",
    "jp_company": "Japan: product.marketing_authorization_holder = '{name}'; corporate group: {group}",
    "us_product": "US: product.product_id = '{id}' (brand {name})",
    "jp_product": "Japan: product.product_id = '{id}'",
}

INSTRUCTIONS = f"""\
Type 2 diabetes drug market data in Snowflake, as two semantic views generated from an OWL/SKOS ontology. Both share
one substance and drug class vocabulary (ATC-based tree; names in English, Japanese and Chinese):
- {VIEWS['us']}: Medicare Part D prescribing in Connecticut, data year 2024: 3,896 prescribers (pseudonymized),
  22,034 prescriber x product claim aggregates, 51 brand-level products, NUCC specialties, manufacturers.
- {VIEWS['jp']}: NDB Open Data, FY2024 (April 2024 - March 2025), all of Japan: 510 strength-level products with
  NHI prices, dispensed quantities and values in yen by prefecture, month or sex-age band, in three care settings.
  No prescribers or specialties exist for Japan.

How to answer a question:
1. Call describe_model with model="us" or "jp" (or both, for a comparison) to read the semantic view's definition.
2. Call resolve_term for every drug, drug class, specialty, company, prefecture or condition the user mentions, in
   whatever language or spelling they used. Use the returned ids in filters instead of guessing names.
3. Call run_sql. Prefer SELECT * FROM SEMANTIC_VIEW(<view> DIMENSIONS ... METRICS ... WHERE ...): the metrics carry
   the business rules. Wrap it in an outer SELECT for ordering, shares or joins. Raw tables (GLP.VOCAB, GLP.US,
   GLP.JP) are readable too. One statement per call.
4. Answer in the user's language, with names in that language where the data has them.

Caveats to mention when relevant: Medicare Part D only (mostly people 65+); counts are claims (fills and refills),
not patients; CMS omits prescriber/drug rows with fewer than 11 claims; costs are gross, before rebates; the data
cannot say why a drug was prescribed. Japan: quantities are tablets, pens or kits, not patients or prescriptions;
compare in yen. Small cells are masked, so prefecture and age figures are lower bounds. Country comparisons: use
shares, not amounts. Privacy: prescribers are pseudonyms. Report aggregates; never try to identify an individual.
"""

SYNTAX = """\
## Querying a semantic view
```sql
SELECT * FROM SEMANTIC_VIEW(
  GLP.SEMANTIC.DIABETES_MARKET
  DIMENSIONS specialty.specialty_name          -- entity.dimension, comma-separated
  METRICS class_claims                         -- metric names as defined in the view
  WHERE therapeutic_class.class_id = 'SGLT2Inhibitor'
)
ORDER BY class_claims DESC
```
- DIMENSIONS, METRICS and WHERE refer to the view's logical names, not to the physical columns after AS.
- A FACTS clause returns row-level facts; it cannot be combined with METRICS.
- Metrics are aggregated at the grain of the DIMENSIONS listed. Compute shares or rankings in an outer SELECT
  (e.g. SUM(x) OVER ()).
"""

server = MCPServer("glp-snowflake", instructions=INSTRUCTIONS)


# ------------------------------------------------------------------ Snowflake access

@lru_cache(maxsize=1)
def _connection():
    import snowflake.connector
    warnings.filterwarnings("ignore", category=FutureWarning, module="snowflake")
    logging.getLogger("snowflake").setLevel(logging.WARNING)
    load_dotenv(ROOT / ".env")
    env = {k: os.environ.get("SNOWFLAKE_" + k) for k in
           ("ACCOUNT", "USER", "PRIVATE_KEY_PATH", "READER_ROLE", "WAREHOUSE", "DATABASE")}
    if missing := [k for k, v in env.items() if not v]:
        # Deliberately no fallback to SNOWFLAKE_ROLE: that is the admin role of the pipeline.
        raise RuntimeError("Missing in .env: " + ", ".join("SNOWFLAKE_" + k for k in missing)
                           + " (a read-only role is required; see scripts/setup_snowflake_reader.py)")
    user, key = env["USER"], env["PRIVATE_KEY_PATH"]
    if os.environ.get("SNOWFLAKE_READER_USER"):  # the service user that holds only the reader role
        user = os.environ["SNOWFLAKE_READER_USER"]
        key = os.environ.get("SNOWFLAKE_READER_PRIVATE_KEY_PATH") or key
    con = snowflake.connector.connect(
        account=env["ACCOUNT"], user=user, authenticator="SNOWFLAKE_JWT",
        private_key_file=os.path.expanduser(key), role=env["READER_ROLE"],
        warehouse=env["WAREHOUSE"], database=env["DATABASE"],
        session_parameters={"STATEMENT_TIMEOUT_IN_SECONDS": 120, "QUERY_TAG": "glp-mcp"})
    con.cursor().execute("USE SECONDARY ROLES NONE")
    try:
        _check_session(con, env["READER_ROLE"])
    except RuntimeError:
        con.close()
        raise
    return con


def _check_session(con, reader_role):
    role, secondary = con.cursor().execute("SELECT CURRENT_ROLE(), CURRENT_SECONDARY_ROLES()").fetchone()
    if role != reader_role.upper() or '"roles":""' not in secondary.replace(" ", ""):
        raise RuntimeError(f"Session is not read-only (role {role}, secondary roles {secondary}); refusing to run.")


def _cursor():
    """A cursor on the read-only session, after checking that the session is still read-only."""
    con = _connection()
    _check_session(con, os.environ["SNOWFLAKE_READER_ROLE"])
    return con.cursor()


def _rows(sql, params=None):
    cur = _cursor()
    cur.execute(sql, params)
    return [d[0] for d in cur.description], cur.fetchall()


# ------------------------------------------------------------------ read-only guard

_FIRST_WORDS = {"SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN"}


def _strip_strings_comments(sql):
    """Blank out string literals, quoted identifiers and comments so checks only see SQL syntax."""
    sql = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\$\$.*?\$\$", "''", sql, flags=re.S)


def _check_read_only(sql):
    bare = _strip_strings_comments(sql).strip().rstrip(";").strip()
    if ";" in bare:
        raise ValueError("One statement per call.")
    first = (bare.split() or [""])[0].upper()
    if first not in _FIRST_WORDS:
        raise ValueError(f"Only read statements are allowed ({', '.join(sorted(_FIRST_WORDS))}).")


# ------------------------------------------------------------------ term index

def _norm(text):
    return unicodedata.normalize("NFKC", text or "").casefold().strip()


@lru_cache(maxsize=1)
def _terms():
    """(normalized name, original name, how it matched, concept) for every searchable name."""
    concepts, entries = {}, []

    def add(kind, cid, names, matched, **extra):
        c = concepts.setdefault((kind, cid), {"kind": kind, "id": cid, "names": {}, **extra})
        for lang, name in names.items():
            if name:
                c["names"].setdefault(lang, name)
        for name, how in matched:
            if name:
                entries.append((_norm(name), name, how, c))

    _, labels = _rows("SELECT CONCEPT_KIND, CONCEPT_ID, LANGUAGE, LABEL_TYPE, LABEL FROM GLP.VOCAB.LABEL "
                      "ORDER BY LABEL_TYPE DESC")  # pref first, so names hold preferred labels
    substance_class = dict(_rows("SELECT SUBSTANCE_ID, CLASS_ID FROM GLP.VOCAB.SUBSTANCE")[1])
    for kind, cid, lang, how, label in labels:
        add(kind, cid, {lang: label} if how == "pref" else {}, [(label, f"{how}Label@{lang}")],
            class_id=substance_class.get(cid) if kind == "substance" else None)
    groups = {}
    for oid, en, ja, zh, alt in _rows("SELECT ORGANIZATION_ID, NAME_EN, NAME_JA, NAME_ZH, ALT_NAMES "
                                      "FROM GLP.US.ORGANIZATION")[1]:
        groups[oid] = en
        add("us_company", oid, {"en": en, "ja": ja, "zh": zh},
            [(en, "name"), (ja, "name@ja"), (zh, "name@zh")] + [(a, "alt name") for a in (alt or "").split("|")])
    for oid, en, ja, group in _rows("SELECT ORGANIZATION_ID, NAME_EN, NAME_JA, CORPORATE_GROUP_ID "
                                    "FROM GLP.JP.ORGANIZATION")[1]:
        add("jp_company", oid, {"en": en, "ja": ja}, [(en, "name"), (ja, "name@ja")],
            group=f"{groups[group]} (organization_id {group})" if group in groups else "none")
    for pid, brand, generic in _rows("SELECT PRODUCT_ID, BRAND_NAME, CMS_GENERIC_NAME FROM GLP.US.PRODUCT")[1]:
        add("us_product", pid, {"en": brand}, [(brand, "brand name"), (generic, "CMS generic name")])
    for pid, ja, name in _rows("SELECT PRODUCT_ID, PRODUCT_NAME_JA, PRODUCT_NAME FROM GLP.JP.PRODUCT")[1]:
        add("jp_product", pid, {"ja": name}, [(ja, "product name@ja"), (name, "product name@ja")])
    return entries


KINDS = ["therapeutic_class", "substance", "specialty", "indication", "us_company", "jp_company", "us_product",
         "jp_product", "prefecture", "jp_drug_class", "care_setting", "sex_age_group"]


# ------------------------------------------------------------------ tools

@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def resolve_term(text: str, kind: str = "any") -> str:
    """Find what a user's word refers to in the data, in any language or spelling.

    Matches English, Japanese and Chinese preferred, alternative and hidden SKOS labels (including raw CMS
    spellings), brand and product names, company names (with the Japanese holders' global corporate groups),
    prefectures and age bands. Case- and width-insensitive; falls back to a substring match when nothing matches
    exactly. Returns ids and how to filter on them in the semantic views.

    Args:
        text: the term as the user wrote it, e.g. "Jardiance", "SGLT2阻害薬", "恩格列净", "cardiology", "東京都"
        kind: any | therapeutic_class | substance | specialty | indication | us_company | jp_company |
            us_product | jp_product | prefecture | jp_drug_class | care_setting | sex_age_group
    """
    term = _norm(text)
    if not term:
        return "Empty term."
    if kind != "any" and kind not in KINDS:
        return f"Unknown kind {kind!r}; use one of: any, {', '.join(KINDS)}"
    entries = [e for e in _terms() if kind in ("any", e[3]["kind"])]
    hits, match_type = [e for e in entries if e[0] == term], "exact"
    if not hits and len(term) >= 2:
        hits, match_type = [e for e in entries if term in e[0]], "partial"
    if not hits:
        return f"No concept matches {text!r}. Try another spelling, a broader term, or kind='any'."

    found = {}
    for _, name, how, c in hits:
        found.setdefault(id(c), (c, set()))[1].add(f"{name} ({how})")
    lines = [f"{match_type} matches for {text!r} ({len(found)}):"]
    for c, matched in list(found.values())[:15]:
        names = " / ".join(c["names"].get(lang, "") for lang in ("en", "ja", "zh") if c["names"].get(lang))
        name = c["names"].get("en") or c["names"].get("ja") or c["id"]
        lines.append(f"- [{c['kind']}] id {c['id']}: {names}")
        lines.append(f"    matched: {', '.join(sorted(matched))[:200]}")
        lines.append("    use: " + HOW_TO_USE[c["kind"]].format(id=c["id"], name=name.replace("'", "''"),
                                                                 class_id=c.get("class_id"), group=c.get("group")))
    if len(found) > 15:
        lines.append(f"(and {len(found) - 15} more; narrow the term or set kind)")
    return "\n".join(lines)


@lru_cache(maxsize=4)
def _ddl(view):
    return _rows("SELECT GET_DDL('SEMANTIC_VIEW', %s)", (view,))[1][0][0]


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def describe_model(model: str = "") -> str:
    """Describe the data: which semantic view holds what, how to query it, and the view's full definition.

    Call once per model before writing SQL. The definition (GET_DDL) lists the datasets, relationships,
    dimensions, facts and metrics with their descriptions, read live from Snowflake.

    Args:
        model: "us" (Connecticut Medicare Part D, DIABETES_MARKET) or "jp" (Japan NDB, JAPAN_MARKET); empty for an
            overview of both
    """
    model = model.lower().strip()
    if model and model not in VIEWS:
        return f"Unknown model {model!r}; use 'us', 'jp' or ''."
    out = [INSTRUCTIONS, SYNTAX]
    if not model:
        out.append("Call describe_model('us') or describe_model('jp') for a view's definition.")
        return "\n".join(out)
    out += [f"## Definition of {VIEWS[model]}", "```sql", _ddl(VIEWS[model]), "```"]
    return "\n".join(out)


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def run_sql(sql: str, limit: int = 200) -> str:
    """Run one read-only SQL statement (SELECT, WITH, SHOW, DESCRIBE, EXPLAIN) in Snowflake.

    Prefer SELECT * FROM SEMANTIC_VIEW(...) over the views named by describe_model; the raw tables in GLP.VOCAB,
    GLP.US and GLP.JP are readable too. Times out after 120 s.

    Args:
        sql: one SQL statement, fully qualified names (GLP.SEMANTIC.DIABETES_MARKET, GLP.US.PRESCRIPTION, ...)
        limit: maximum rows returned (1-1000)
    """
    try:
        _check_read_only(sql)
    except ValueError as exc:
        return f"Rejected: {exc}"
    limit = max(1, min(int(limit), 1000))
    try:
        cur = _cursor()
        cur.execute(sql)
        columns = [d[0] for d in cur.description]
        rows = cur.fetchmany(limit + 1)
    except Exception as exc:  # Snowflake's message tells the model what to fix
        return f"Snowflake error: {str(exc).strip()[:800]}"
    if not rows:
        return "No rows. Check the ids with resolve_term and the names with describe_model."
    clean = lambda v: "" if v is None else str(v).replace("\t", " ").replace("\n", " ")  # noqa: E731
    lines = ["\t".join(columns)] + ["\t".join(clean(v) for v in r) for r in rows[:limit]]
    if len(rows) > limit:
        lines.append(f"(stopped at limit={limit}; raise limit or aggregate for more)")
    return "\n".join(lines)


if __name__ == "__main__":
    server.run()
