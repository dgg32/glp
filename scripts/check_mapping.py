"""Check the R2RML mapping locally before it goes to the Stardog virtual graph.

Morph-KGC runs mapping/glp.r2rml.ttl against Snowflake (read-only login GLP_STARDOG, role GLP_READER) and the
result is compared with the graph the tables were exported from: every triple of the vocabularies and data
graphs, except the ones the tables do not carry (NOT_IN_TABLES below, counted in the report), plus the closure
of skos:broader that VOCAB.CLASS_ANCESTOR and VOCAB.SPECIALTY_ANCESTOR stand for. Numbers are compared by value
(Snowflake prints NUMBER(14,1) as 16.0 where the Turtle has 16.0 or 16). The check passes when both sides hold
exactly the same triples.

Runs in .venv-snowflake: .venv-snowflake/bin/python scripts/check_mapping.py   (~5 min, most of it parsing)
Needs SNOWFLAKE_ACCOUNT, SNOWFLAKE_WAREHOUSE and SNOWFLAKE_STARDOG_PASSWORD in .env. Only SELECTs are sent.
"""
import os
import sys
import time
from collections import Counter
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

import morph_kgc
from dotenv import load_dotenv
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS, SKOS, XSD

ROOT = Path(__file__).resolve().parent.parent
MAPPING = ROOT / "mapping" / "glp.r2rml.ttl"
SOURCES = [ROOT / "vocab" / f"{n}.ttl" for n in ("therapeutic-class", "substance", "indication", "nucc-specialty",
                                                 "jp-drug-class", "jp-prefecture", "ndb-dimensions")] + \
          [ROOT / "data" / "rdf" / f"{n}.ttl" for n in ("products", "drugsfda", "npi-registry", "cms-partd-2024",
                                                        "ndb-products", "ndb-2024")]
DM = Namespace("https://dgg32.github.io/glp/ontology#")
QB = Namespace("http://purl.org/linked-data/cube#")
JP_PRODUCT = "https://dgg32.github.io/glp/data/product/jp/"
NUMERIC = {XSD.integer, XSD.decimal, XSD.double}


def not_in_tables(s, p, o, types):
    """Why a graph triple has no column to come from, or None if the mapping must produce it."""
    if str(o) == "None":
        # NUCC's own placeholder for 13 deactivated codes; Morph-KGC reads the text "None" as SQL NULL
        # (na_values), so only this check cannot see it. Stardog maps it like any other string.
        return 'the text "None" (NUCC placeholder; Morph-KGC only)'
    if types & {SKOS.ConceptScheme, QB.DataSet, QB.SliceKey}:
        return "scheme, dataset and slice key records"
    if p in (SKOS.editorialNote, SKOS.scopeNote):
        return "notes"
    if p == SKOS.narrower:
        return "skos:narrower (only partly asserted; skos:broader is the direction stored)"
    if p == SKOS.closeMatch or (p == SKOS.exactMatch and types & {DM.Substance, DM.Indication}):
        return "cross-references kept as '|' lists"
    if p == SKOS.definition and DM.Indication in types:
        return "indication definitions"
    if DM.Organization in types and p in (SKOS.altLabel, SKOS.hiddenLabel, RDFS.seeAlso):
        return "company alt/hidden names, web links"
    if p == DM.hasIndication and str(s).startswith(JP_PRODUCT):
        return "indication of Japanese products"
    return None


def norm(term):
    """Numbers by value, everything else as it is."""
    if isinstance(term, Literal) and term.datatype in NUMERIC:
        return ("number", Decimal(str(term)).normalize(), term.datatype)
    return term


def virtual_graph():
    load_dotenv(ROOT / ".env")
    url = (f"snowflake://GLP_STARDOG:{quote(os.environ['SNOWFLAKE_STARDOG_PASSWORD'], safe='')}"
           f"@{os.environ['SNOWFLAKE_ACCOUNT']}/GLP/VOCAB"
           f"?warehouse={os.environ['SNOWFLAKE_WAREHOUSE']}&role=GLP_READER")
    url = url.replace("$", "$$")  # Morph-KGC reads its config with extended interpolation
    # Morph-KGC turns SQL NULLs from the Snowflake dialect into the string "None"; treat that as missing
    config = (f"[CONFIGURATION]\noutput_format=N-TRIPLES\nna_values=,None\nlogging_level=WARNING\n"
              f"\n[Snowflake]\nmappings={MAPPING}\ndb_url={url}\n")
    return morph_kgc.materialize(config)


def expected_graph():
    source = Graph()
    for f in SOURCES:
        source.parse(f)
    expected, skipped = Graph(), Counter()
    for s, p, o in source:
        reason = not_in_tables(s, p, o, set(source.objects(s, RDF.type)))
        if reason:
            skipped[reason] += 1
        else:
            expected.add((s, p, o))
    # what a reasoner would add for skos:broaderTransitive, without the reflexive pairs
    for cls in (DM.TherapeuticClass, DM.Specialty):
        for c in source.subjects(RDF.type, cls):
            for ancestor in source.transitive_objects(c, SKOS.broader):
                if ancestor != c:
                    expected.add((c, SKOS.broaderTransitive, ancestor))
    return expected, skipped


def main():
    t0 = time.time()
    expected, skipped = expected_graph()
    print(f"graph: {len(expected):,} triples to reproduce ({time.time() - t0:.0f} s); "
          f"{sum(skipped.values()):,} not in the tables:")
    for reason, n in skipped.most_common():
        print(f"  {n:>7,}  {reason}")
    t0 = time.time()
    virtual = virtual_graph()
    print(f"mapping: {len(virtual):,} triples from Snowflake ({time.time() - t0:.0f} s)")
    exp = {(s, p, norm(o)): (s, p, o) for s, p, o in expected}
    got = {(s, p, norm(o)): (s, p, o) for s, p, o in virtual}
    missing, extra = exp.keys() - got.keys(), got.keys() - exp.keys()
    by_predicate = Counter(p for _, p, _ in got)
    print("\nper predicate (mapping = graph unless listed below):")
    for p, n in sorted(by_predicate.items(), key=lambda x: -x[1]):
        print(f"  {n:>8,}  {virtual.namespace_manager.normalizeUri(p)}")
    for name, diff, side in (("missing from the mapping", missing, exp), ("not in the graph", extra, got)):
        if diff:
            print(f"\n{len(diff):,} {name}; by predicate: "
                  f"{dict(Counter(virtual.namespace_manager.normalizeUri(k[1]) for k in diff))}")
            for k in sorted(diff, key=str)[:15]:
                print("  ", *(x.n3() for x in side[k]))
    if missing or extra:
        sys.exit(1)
    print(f"\nidentical: {len(got):,} triples")


if __name__ == "__main__":
    main()
