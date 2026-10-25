"""MCP server for the Diabetes Drug Market knowledge graph in Stardog.

Gives any MCP client (Claude Desktop, Claude Code, other LLM apps) three tools:

  resolve_term    any drug, drug class, specialty, indication or company name, in any language or
                  spelling, -> the concept IRIs in the graph (SKOS pref/alt/hidden labels)
  describe_model  classes, properties, conventions and example queries, read live from Stardog
  run_sparql      read-only SPARQL over all named graphs, optional OWL reasoning

Read-only by design, in three layers: only SELECT/ASK/CONSTRUCT/DESCRIBE pass the query check;
queries go to Stardog's read endpoint, which refuses updates; and the server logs in as a user
with READ permission only (STARDOG_READER_USERNAME / STARDOG_READER_PASSWORD in .env).

Run: .venv/bin/python mcp_server/server.py   (stdio transport)
"""
import base64
import json
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

ROOT = Path(__file__).resolve().parent.parent
ALL_GRAPHS = "tag:stardog:api:context:all"
PREFIXES = """PREFIX dm:   <https://dgg32.github.io/glp/ontology#>
PREFIX dmtc: <https://dgg32.github.io/glp/vocab/therapeutic-class/>
PREFIX dmsub: <https://dgg32.github.io/glp/vocab/substance/>
PREFIX dmsp: <https://dgg32.github.io/glp/vocab/specialty/>
PREFIX dmind: <https://dgg32.github.io/glp/vocab/indication/>
PREFIX d:    <https://dgg32.github.io/glp/data/>
PREFIX pref: <https://dgg32.github.io/glp/vocab/prefecture/>
PREFIX sexage: <https://dgg32.github.io/glp/vocab/sex-age/>
PREFIX setting: <https://dgg32.github.io/glp/vocab/care-setting/>
PREFIX jpc:  <https://dgg32.github.io/glp/vocab/jp-drug-class/>
PREFIX qb:   <http://purl.org/linked-data/cube#>
PREFIX sdmx-attribute: <http://purl.org/linked-data/sdmx/2009/attribute#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
"""
KINDS = {
    "https://dgg32.github.io/glp/ontology#TherapeuticClass": "drug_class",
    "https://dgg32.github.io/glp/ontology#Substance": "substance",
    "https://dgg32.github.io/glp/ontology#MedicinalProduct": "product",
    "https://dgg32.github.io/glp/ontology#Specialty": "specialty",
    "https://dgg32.github.io/glp/ontology#Indication": "indication",
    "https://dgg32.github.io/glp/ontology#Organization": "company",
    "https://dgg32.github.io/glp/ontology#Prefecture": "prefecture",
    "https://dgg32.github.io/glp/ontology#JapaneseDrugClass": "jp_drug_class",
    "https://dgg32.github.io/glp/ontology#CareSetting": "care_setting",
    "https://dgg32.github.io/glp/ontology#SexAgeGroup": "sex_age",
}
HOW_TO_USE = {
    "drug_class": "?sub dm:inTherapeuticClass/skos:broader* <{iri}> . ?prod dm:hasActiveSubstance ?sub .",
    "substance": "?prod dm:hasActiveSubstance <{iri}> .",
    "product": "US: ?rx dm:forProduct <{iri}> .  Japan: ?slice dm:aboutProduct <{iri}> .",
    "specialty": "?doc dm:hasSpecialty/skos:broader* <{iri}> . (for shares by specialty, use "
                 "dm:hasPrimarySpecialty so that each prescriber counts once)",
    "indication": "?prod dm:hasIndication <{iri}> .",
    "company": "?prod dm:manufacturedBy <{iri}> .  (corporate group of a Japanese holder: "
               "?prod dm:manufacturedBy/dm:partOfCorporateGroup <{iri}> .)",
    "prefecture": "?obs dm:prefecture <{iri}> ; dm:quantity ?q .",
    "jp_drug_class": "?prod dm:inJapaneseDrugClass <{iri}> .",
    "care_setting": "?slice dm:careSetting <{iri}> .  (setting:outpatient has the two outpatient settings as "
                    "narrower: ?slice dm:careSetting/skos:broader* <{iri}> .)",
    "sex_age": "?obs dm:sexAgeGroup/skos:broader* <{iri}> ; dm:quantity ?q .",
}

INSTRUCTIONS = """\
Knowledge graph of the type 2 diabetes drug market in two countries, sharing one substance and drug
class vocabulary (ATC-based tree, labels in English, Japanese and Chinese):
- US: Medicare Part D prescribing in Connecticut, data year 2024: 3,896 prescribers (pseudonymized),
  22,034 prescriber x product claim aggregates, 51 brand-level products, NUCC specialties, manufacturers.
- Japan: NDB Open Data, FY2024 (April 2024 - March 2025), all of Japan: 510 strength-level products with
  NHI prices, dispensed quantities by prefecture, month or sex-age band, in three care settings, as an
  RDF Data Cube. No prescribers or specialties exist for Japan.

How to answer a question:
1. Call describe_model once to learn the classes, properties and example queries.
2. Call resolve_term for every drug, drug class, specialty, company or condition the user mentions,
   in whatever language or spelling they used. Use the returned IRIs in SPARQL instead of guessing
   names. Drug classes roll up: query classes with dm:inTherapeuticClass/skos:broader*.
3. Call run_sparql. Queries see all named graphs automatically. dm:SGLT2Prescriber,
   dm:GLP1Prescriber, dm:SGLT2Product and dm:GLP1Product exist only with reasoning=true.
4. Answer in the user's language; prefer labels in that language (skos:prefLabel with lang tag).

Caveats to mention when relevant: Medicare Part D only (mostly people 65+); counts are claims
(fills and refills), not patients; CMS omits prescriber/drug rows with fewer than 11 claims;
costs are gross, before rebates; the data cannot say why a drug was prescribed.
Japan: quantities are tablets, pens or kits, not patients or prescriptions, and cannot be added across
products; compare in yen (quantity x dm:nhiPrice, prices as of 2026-09-02). Cells below 1,000 (oral) or
400 (injection) are masked, so prefecture and age figures are lower bounds; national totals are mostly
unmasked. The prefecture is where the claim was issued. Country comparisons: use shares, not amounts.
Privacy: prescribers are pseudonyms. Report aggregates; never try to identify an individual.
"""

server = MCPServer("glp-stardog", instructions=INSTRUCTIONS)


# ------------------------------------------------------------------ Stardog access

def _settings():
    env = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    env.update({k: v for k, v in os.environ.items() if k.startswith("STARDOG_")})
    needed = ["STARDOG_ENDPOINT", "STARDOG_DATABASE", "STARDOG_READER_USERNAME", "STARDOG_READER_PASSWORD"]
    missing = [k for k in needed if not env.get(k)]
    if missing:
        # Deliberately no fallback to the loader account: that one can write.
        raise RuntimeError(f"Missing in .env: {', '.join(missing)} (a READ-only Stardog user is required)")
    return env


def _query(sparql, *, reasoning=False, limit=None, accept="application/sparql-results+json", timeout_s=60,
           all_graphs=True):
    """all_graphs: make the union of all named graphs the default graph. Under the SPARQL protocol this
    also empties the named-graph set, so queries that use GRAPH clauses must pass all_graphs=False."""
    env = _settings()
    params = {"query": sparql, "timeout": timeout_s * 1000}
    if all_graphs:
        params["default-graph-uri"] = ALL_GRAPHS
    if reasoning:
        params["reasoning"] = "true"
    if limit:
        params["limit"] = limit
    url = f"{env['STARDOG_ENDPOINT'].rstrip('/')}/{env['STARDOG_DATABASE']}/query?" + urllib.parse.urlencode(params)
    token = base64.b64encode(f"{env['STARDOG_READER_USERNAME']}:{env['STARDOG_READER_PASSWORD']}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {token}", "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s + 10) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        try:
            detail = json.loads(detail).get("message", detail)
        except ValueError:
            pass
        raise RuntimeError(f"Stardog error {exc.code}: {detail[:600]}") from None
    return json.loads(body) if accept.endswith("json") else body


def _rows(result):
    return [{k: v["value"] for k, v in b.items()} for b in result["results"]["bindings"]]


def _literal(text):
    return json.dumps(text, ensure_ascii=False)  # valid SPARQL string literal: quotes and backslashes escaped


# ------------------------------------------------------------------ read-only guard

# Keywords only; not ?variables, $variables or prefixed names such as dm:copy.
_UPDATE_WORDS = re.compile(r"(?<![?$:\w-])(INSERT|DELETE|LOAD|CLEAR|DROP|CREATE|ADD|MOVE|COPY|WITH)\b", re.I)


def _strip_strings_iris_comments(q):
    """Blank out string literals, IRIs and comments so keyword checks only see SPARQL syntax."""
    out, i, n = [], 0, len(q)
    while i < n:
        c = q[i]
        if c == "#":
            while i < n and q[i] != "\n":
                i += 1
        elif c == "<" and re.match(r"<[^\s<>\"{}|^`]*>", q[i:]):
            m = re.match(r"<[^\s<>\"{}|^`]*>", q[i:])
            out.append("<>")
            i += m.end()
        elif c in "\"'":
            quote = q[i:i + 3] if q[i:i + 3] in ('"""', "'''") else c
            i += len(quote)
            while i < n and not q.startswith(quote, i):
                i += 2 if q[i] == "\\" else 1
            i += len(quote)
            out.append('""')
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _check_read_only(q):
    bare = _strip_strings_iris_comments(q)
    body = re.sub(r"\b(PREFIX\s+[\w-]*:\s*<>|BASE\s+<>)", " ", bare, flags=re.I).strip()
    first = (body.split() or [""])[0].upper()
    if first not in ("SELECT", "ASK", "CONSTRUCT", "DESCRIBE"):
        raise ValueError("Only read queries are allowed (SELECT, ASK, CONSTRUCT, DESCRIBE).")
    m = _UPDATE_WORDS.search(body)
    if m:
        raise ValueError(f"Update keyword '{m.group(1)}' is not allowed; this server is read-only.")
    return first


# ------------------------------------------------------------------ tools

@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def resolve_term(text: str, kind: str = "any") -> str:
    """Find the concepts in the graph that a user's word refers to, in any language or spelling.

    Matches English, Japanese and Chinese preferred, alternative and hidden labels (including the raw
    CMS and NDB spellings), product brand names, company names and Japanese prefectures. Case- and width-insensitive; falls back to
    a substring match when nothing matches exactly. Use the returned IRIs in run_sparql.

    Args:
        text: the term as the user wrote it, e.g. "Jardiance", "SGLT2阻害薬", "恩格列净", "cardiology"
        kind: any | drug_class | substance | product | specialty | indication | company | prefecture |
            jp_drug_class | care_setting | sex_age
    """
    term = unicodedata.normalize("NFKC", text).strip()
    if not term:
        return "Empty term."
    types = [t for t, k in KINDS.items() if kind in ("any", k)]
    if not types:
        return f"Unknown kind {kind!r}; use one of: any, {', '.join(KINDS.values())}"
    type_values = " ".join(f"<{t}>" for t in types)

    def search(condition, limit):
        q = PREFIXES + f"""
SELECT DISTINCT ?concept ?type ?label ?how ?en ?ja ?zh WHERE {{
  VALUES ?type {{ {type_values} }}
  VALUES ?p {{ skos:prefLabel skos:altLabel skos:hiddenLabel rdfs:label dm:cmsGenericName }}
  ?concept a ?type ; ?p ?label .
  FILTER({condition})
  BIND(STRAFTER(STR(?p), "#") AS ?how)
  OPTIONAL {{ ?concept skos:prefLabel|rdfs:label ?en FILTER(lang(?en) = "en") }}
  OPTIONAL {{ ?concept skos:prefLabel|rdfs:label ?ja FILTER(lang(?ja) = "ja") }}
  OPTIONAL {{ ?concept skos:prefLabel|rdfs:label ?zh FILTER(lang(?zh) = "zh") }}
}} LIMIT {limit}"""
        return _rows(_query(q))

    lit = _literal(term.lower())
    rows = search(f"LCASE(STR(?label)) = {lit}", 50)
    match_type = "exact"
    if not rows and len(term) >= 2:
        rows = search(f"CONTAINS(LCASE(STR(?label)), {lit})", 40)
        match_type = "partial"
    if not rows:
        return f"No concept matches {text!r}. Try another spelling, a broader term, or kind='any'."

    concepts = {}
    for r in rows:
        c = concepts.setdefault(r["concept"], {"iri": r["concept"], "kind": KINDS[r["type"]], "matched": set(),
                                               "en": r.get("en"), "ja": r.get("ja"), "zh": r.get("zh")})
        c["matched"].add(f'{r["label"]} ({r["how"]})')
    lines = [f"{match_type} matches for {text!r}:"]
    for c in list(concepts.values())[:15]:
        names = " / ".join(x for x in (c["en"], c["ja"], c["zh"]) if x)
        lines.append(f"- <{c['iri']}>  [{c['kind']}]  {names}")
        lines.append(f"    matched: {', '.join(sorted(c['matched']))[:200]}")
        lines.append(f"    use: {HOW_TO_USE[c['kind']].format(iri=c['iri'])}")
    return "\n".join(lines)


@lru_cache(maxsize=1)
def _model_description():
    classes = _rows(_query(PREFIXES + """
SELECT ?c ?label ?def ?super WHERE {
  GRAPH <tag:stardog:api:context:schema> {
    ?c a owl:Class ; rdfs:label ?label FILTER(lang(?label) = "en" && STRSTARTS(STR(?c), STR(dm:)))
    OPTIONAL { ?c skos:definition ?def }
    OPTIONAL { ?c rdfs:subClassOf ?super FILTER(isIRI(?super)) }
  }
} ORDER BY ?c""", all_graphs=False))
    props = _rows(_query(PREFIXES + """
SELECT ?p ?kind ?domain ?range ?def ?comment WHERE {
  GRAPH <tag:stardog:api:context:schema> {
    VALUES ?kind { owl:ObjectProperty owl:DatatypeProperty }
    ?p a ?kind FILTER(STRSTARTS(STR(?p), STR(dm:)))
    OPTIONAL { ?p rdfs:domain ?domain } OPTIONAL { ?p rdfs:range ?range }
    OPTIONAL { ?p skos:definition ?def } OPTIONAL { ?p rdfs:comment ?comment }
  }
} ORDER BY ?kind ?p""", all_graphs=False))
    graphs = _rows(_query("SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g ORDER BY ?g", all_graphs=False))

    def short(iri):
        return (iri or "").replace("https://dgg32.github.io/glp/ontology#", "dm:") \
            .replace("http://www.w3.org/2001/XMLSchema#", "xsd:") \
            .replace("http://www.w3.org/2004/02/skos/core#", "skos:")

    out = ["# Diabetes Drug Market knowledge graph", "", "## Prefixes", "```", PREFIXES.strip(), "```", "",
           "## Classes"]
    seen = set()
    for c in classes:
        if c["c"] in seen:
            continue
        seen.add(c["c"])
        sup = f" (subclass of {short(c.get('super'))})" if c.get("super") else ""
        out.append(f"- {short(c['c'])}: {c['label']}{sup}. {c.get('def', '')}".rstrip())
    out += ["", "## Properties"]
    seen = set()
    for p in props:
        if p["p"] in seen:
            continue
        seen.add(p["p"])
        note = p.get("def") or p.get("comment") or ""
        out.append(f"- {short(p['p'])}: {short(p.get('domain'))} -> {short(p.get('range'))}. {note}".rstrip())
    out += ["", "## Conventions",
            "- Prescription aggregate: ?rx dm:prescribedBy ?doc ; dm:forProduct ?prod ; dm:totalClaims ?n ; "
            "dm:totalDrugCost ?usd ; dm:total30DayFills ?fills .",
            "- dm:writes is the inverse of dm:prescribedBy and exists only with reasoning; use ^dm:prescribedBy otherwise.",
            "- Drug class roll-up without reasoning: ?sub dm:inTherapeuticClass/skos:broader* ?class .",
            "- Specialty: ?doc dm:hasSpecialty ?sp lists every NPI Registry specialty of a prescriber (NUCC concept); "
            "dm:hasPrimarySpecialty is the one flagged primary. Use hasSpecialty to find prescribers of a specialty and "
            "hasPrimarySpecialty for shares or tables by specialty, so that no prescriber counts twice. The SKOS tree "
            "is grouping > classification > specialization; roll up with skos:broader*. dm:cmsPrescriberType is CMS's "
            "own free-text specialty.",
            "- In Stardog, GRAPH ?g { ?g ?p ?o } (the graph variable as subject inside its own GRAPH block) returns "
            "no rows; bind the subject to a separate variable.",
            "- Labels: skos:prefLabel on concepts, rdfs:label on products and companies; filter with lang().",
            "- Combination products link to every substance they contain; avoid double counting cost across classes.",
            "- 13 prescribers have no NPI Registry record, hence no specialty. 130 have the primary specialty "
            "'Student in an Organized Health Care Education/Training Program'.",
            "- Japan (NDB): ?slice a dm:QuantitySlice ; dm:aboutProduct ?prod ; dm:careSetting ?setting ; "
            "qb:sliceStructure ?key ; dm:totalQuantity ?total ; qb:observation ?obs . ?obs dm:prefecture ?pref "
            "(or dm:month \"2024-10\"^^xsd:gYearMonth, or dm:sexAgeGroup ?band) ; dm:quantity ?q . "
            "?key is <https://dgg32.github.io/glp/data/ndb/key/prefecture>, .../month or .../sex-age (full IRIs). "
            "Each product x setting has one slice per key, "
            "so for national totals use the prefecture slices only (else every total counts three times).",
            "- Japan: a masked cell or total has sdmx-attribute:confStatus instead of a value. Value in yen = "
            "?q * ?price with ?prod dm:nhiPrice ?price. Products: dm:yjCode, dm:receiptCode, dm:isGeneric, "
            "dm:isOriginator, dm:dispensingUnit, dm:routeOfAdministration, dm:inJapaneseDrugClass (薬効分類 249 "
            "or 396; GLP-1 drugs are mostly 249). Holders: dm:manufacturedBy, then dm:partOfCorporateGroup for "
            "the global group shared with the US data.",
            "- Ages: ?band dm:minAge ?age ; skos:broader ?sex (sexage:M or sexage:F).",
            "", "## Named graphs (queried together automatically)"]
    out += [f"- {g['g']}: {int(g['n']):,} triples" for g in graphs]
    out += ["", "## Example queries"]
    for path in sorted((ROOT / "queries").glob("*.rq")):
        out += [f"### {path.stem}", "```sparql", path.read_text(encoding="utf-8").strip(), "```"]
    return "\n".join(out)


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def describe_model() -> str:
    """Describe the graph: classes, properties, conventions, named graphs and worked example queries.

    Call this once before writing SPARQL. Read live from the ontology loaded in Stardog.
    """
    return _model_description()


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def run_sparql(query: str, reasoning: bool = False, limit: int = 200) -> str:
    """Run a read-only SPARQL query (SELECT, ASK, CONSTRUCT or DESCRIBE) over all named graphs.

    Args:
        query: SPARQL query. No FROM clause needed. Prefixes (dm:, dmtc:, qb:, ...) must still be
            declared (copy them from describe_model).
        reasoning: true to apply the OWL ontology at query time (needed for dm:SGLT2Prescriber,
            dm:GLP1Prescriber, dm:SGLT2Product, dm:GLP1Product and dm:writes).
        limit: maximum rows returned (1-1000).
    """
    try:
        form = _check_read_only(query)
    except ValueError as exc:
        return f"Rejected: {exc}"
    limit = max(1, min(int(limit), 1000))
    try:
        if form in ("CONSTRUCT", "DESCRIBE"):
            return _query(query, reasoning=reasoning, limit=limit, accept="text/turtle")[:20000]
        result = _query(query, reasoning=reasoning, limit=limit)
    except RuntimeError as exc:
        return str(exc)
    if form == "ASK":
        return str(result.get("boolean"))
    variables = result["head"]["vars"]
    rows = _rows(result)
    if not rows:
        return "No results. Check IRIs with resolve_term, prefixes, and whether the query needs reasoning=true."
    lines = ["\t".join(variables)]
    lines += ["\t".join(r.get(v, "").replace("\t", " ").replace("\n", " ") for v in variables) for r in rows]
    if len(rows) == limit:
        lines.append(f"(stopped at limit={limit}; raise limit or aggregate for more)")
    return "\n".join(lines)


if __name__ == "__main__":
    server.run()
