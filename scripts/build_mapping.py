"""Write the R2RML mapping of the whole knowledge graph over the Snowflake tables: mapping/glp.r2rml.ttl.

The 27 tables of export_snowflake.py are projections of the graph; this mapping turns them back into the same
triples (same IRIs, predicates, language tags and datatypes), so a Stardog virtual graph over Snowflake answers
the business queries without a copy of the data. scripts/check_mapping.py runs the mapping locally (Morph-KGC)
and compares the result with the graph; scripts/r2rml_to_sms2.py turns it into SMS2 for Stardog Studio.

R2RML has no loops, and a language tag or a constant in a template cannot come from a column, so the file has
one triples map per table, language and label type (~90 maps). It is generated from the spec below rather than
written by hand; the R2RML file is the artifact, this script only saves typing.

Conventions, all needed by one of the two engines:
  * every column gets a quoted lowercase alias (the Morph-KGC Snowflake dialect lowercases column names, JDBC
    does not), and the reserved word LANGUAGE is quoted (Stardog parses the SQL itself);
  * booleans become the strings 'true'/'false' in SQL, typed with rr:datatype xsd:boolean, and nullable
    integers become text (Morph-KGC fails on a NULL in an xsd:integer column; Stardog types them either way);
  * IRIs are templates over ID columns, never the IRI column, so Stardog can match a join's two sides and push
    it to Snowflake; a template value is percent-encoded, so PRESCRIPTION_ID (it contains "/") is rebuilt
    from its three parts;
  * the closure tables (CLASS_ANCESTOR, SPECIALTY_ANCESTOR) become skos:broaderTransitive, so roll-ups work
    without a reasoner or a property path.

Not mapped, because the tables do not carry them one-to-one: the concept scheme and dataset records, editorial
and scope notes, skos:narrower, the substance and indication cross-references (stored as "|" lists), company
alt/hidden names and web links, and the indication of the Japanese products. check_mapping.py lists them.

Usage: python scripts/build_mapping.py   (then r2rml_to_sms2.py mapping/glp.r2rml.ttl > mapping/glp.sms)
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "mapping" / "glp.r2rml.ttl"
B = "https://dgg32.github.io/glp/"

PREFIXES = {
    "rr": "http://www.w3.org/ns/r2rml#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "dcterms": "http://purl.org/dc/terms/",
    "qb": "http://purl.org/linked-data/cube#",
    "sdmx-attribute": "http://purl.org/linked-data/sdmx/2009/attribute#",
    "sdmx-code": "http://purl.org/linked-data/sdmx/2009/code#",
    "dm": f"{B}ontology#",
    "map": f"{B}mapping/glp#",
}

LANGS = ["en", "ja", "zh"]
BREAKDOWNS = {"prefecture": "Prefecture", "month": "Month", "sex-age": "SexAge"}


# --- object kinds --------------------------------------------------------------------------------------------
def iri(path, col):
    """A template IRI under the project base, e.g. iri("vocab/substance/", "substance_id")."""
    return ("template", f"{B}{path}{{{col}}}")


def const(term):
    return ("constant", term)


def lit(col, lang=None, dt=None):
    return ("column", col, lang, dt)


def boolean(col):
    return f"CASE WHEN {col} THEN 'true' ELSE 'false' END"


def text(col):
    """Nullable integers as text: Morph-KGC casts an xsd:integer column float -> int before dropping NULLs."""
    return f"CAST({col} AS VARCHAR)"


def sql(columns, table, where=None):
    """SELECT with quoted lowercase aliases; columns maps alias -> SQL expression (or the column itself)."""
    cols = ", ".join(f'{expr} AS "{alias}"' for alias, expr in columns.items())
    return f"SELECT {cols} FROM GLP.{table}" + (f" WHERE {where}" if where else "")


def tmap(name, query, subject, classes=(), poms=()):
    """subject is (path, column) of a template, or a full template string; poms are (predicates, object)."""
    if isinstance(subject, tuple):
        subject = f"{B}{subject[0]}{{{subject[1]}}}"
    return dict(name=name, sql=query, subject=subject, classes=list(classes), poms=list(poms))


# --- the SKOS vocabularies -----------------------------------------------------------------------------------
# kind (VOCAB.LABEL.CONCEPT_KIND), table, id column, IRI path, ontology class, and the optional columns
VOCABS = [
    dict(kind="therapeutic_class", table="VOCAB.THERAPEUTIC_CLASS", id="CLASS_ID", path="therapeutic-class",
         cls="TherapeuticClass", broader="BROADER_CLASS_ID", notation="NOTATION", definition="DEFINITION_EN",
         ancestors=("VOCAB.CLASS_ANCESTOR", "ANCESTOR_CLASS_ID"),
         extra={"atc": ("NOTATION", "skos:exactMatch", ("template", "http://purl.bioontology.org/ontology/ATC/{atc}"))}),
    dict(kind="substance", table="VOCAB.SUBSTANCE", id="SUBSTANCE_ID", path="substance", cls="Substance",
         extra={"class_id": ("CLASS_ID", "dm:inTherapeuticClass", iri("vocab/therapeutic-class/", "class_id"))},
         label_types={"pref": LANGS, "alt": LANGS, "hidden": ["en", "ja"]}),
    dict(kind="indication", table="VOCAB.INDICATION", id="INDICATION_ID", path="indication", cls="Indication"),
    dict(kind="specialty", table="VOCAB.SPECIALTY", id="SPECIALTY_CODE", path="specialty", cls="Specialty",
         broader="BROADER_SPECIALTY_CODE", definition="DEFINITION_EN",
         # NUCC codes have a notation; the grouping and classification levels built from the CSV do not
         notation="CASE WHEN SPECIALTY_CODE LIKE 'grouping-%' OR SPECIALTY_CODE LIKE 'classification-%' "
                  "THEN NULL ELSE SPECIALTY_CODE END",
         ancestors=("VOCAB.SPECIALTY_ANCESTOR", "ANCESTOR_SPECIALTY_CODE")),
    dict(kind="jp_drug_class", table="VOCAB.JP_DRUG_CLASS", id="JP_CLASS_CODE", path="jp-drug-class",
         cls="JapaneseDrugClass", broader="BROADER_JP_CLASS_CODE", notation="JP_CLASS_CODE"),
    dict(kind="prefecture", table="VOCAB.PREFECTURE", id="PREFECTURE_CODE", path="prefecture", cls="Prefecture",
         notation="PREFECTURE_CODE",
         extra={"iso_code": ("ISO_CODE", "dcterms:identifier", lit("iso_code")),
                "wikidata_id": ("WIKIDATA_ID", "skos:exactMatch",
                                ("template", "http://www.wikidata.org/entity/{wikidata_id}"))}),
    dict(kind="care_setting", table="VOCAB.CARE_SETTING", id="CARE_SETTING_ID", path="care-setting",
         cls="CareSetting", broader="BROADER_CARE_SETTING_ID", definition="DEFINITION_EN"),
    dict(kind="sex_age_group", table="VOCAB.SEX_AGE_GROUP", id="SEX_AGE_CODE", path="sex-age", cls="SexAgeGroup",
         broader="SEX", notation="CASE WHEN MIN_AGE IS NULL THEN NULL ELSE SEX_AGE_CODE END",
         extra={"min_age": (text("MIN_AGE"), "dm:minAge", lit("min_age", dt="xsd:integer"))}),
]
MATCH_TYPES = {"exact": "skos:exactMatch", "narrow": "skos:narrowMatch", "broad": "skos:broadMatch",
               "related": "skos:relatedMatch"}


def camel(s):
    return "".join(w.capitalize() for w in s.replace("-", "_").split("_"))


def vocab_maps(v):
    name, path = camel(v["kind"]), f"vocab/{v['path']}/"
    scheme = const(f"<{B}vocab/{v['path']}>")
    cols, poms = {"id": v["id"]}, [(["skos:inScheme"], scheme)]
    if v.get("broader"):
        cols["broader"] = v["broader"]
        poms.append((["skos:broader"], iri(path, "broader")))
    if v.get("notation"):
        cols["notation"] = v["notation"]
        poms.append((["skos:notation"], lit("notation")))
    if v.get("definition"):
        cols["definition"] = v["definition"]
        poms.append((["skos:definition"], lit("definition", lang="en")))
    for alias, (expr, pred, obj) in v.get("extra", {}).items():
        cols[alias] = expr
        poms.append(([pred], obj))
    maps = [tmap(name, sql(cols, v["table"]), (path, "id"), ["skos:Concept", f"dm:{v['cls']}"], poms)]
    top = f"{v['broader']} IS NULL" if v.get("broader") else None
    maps.append(tmap(f"{name}Top", sql({"id": v["id"]}, v["table"], top), (path, "id"),
                     poms=[(["skos:topConceptOf"], scheme)]))
    if v.get("ancestors"):
        table, col = v["ancestors"]
        maps.append(tmap(f"{name}Ancestor", sql({"id": v["id"], "ancestor": col}, table, f"{v['id']} <> {col}"),
                         (path, "id"), poms=[(["skos:broaderTransitive"], iri(path, "ancestor"))]))
    for label_type, langs in v.get("label_types", {"pref": LANGS, "alt": LANGS}).items():
        preds = ["skos:prefLabel", "rdfs:label"] if label_type == "pref" else [f"skos:{label_type}Label"]
        for lang in langs:
            where = (f"CONCEPT_KIND = '{v['kind']}' AND LABEL_TYPE = '{label_type}' AND \"LANGUAGE\" = '{lang}'")
            maps.append(tmap(f"{name}{label_type.capitalize()}Label{lang.capitalize()}",
                             sql({"id": "CONCEPT_ID", "label": "LABEL"}, "VOCAB.LABEL", where), (path, "id"),
                             poms=[(preds, lit("label", lang=lang))]))
    return maps


def crosswalk_maps():
    return [tmap(f"JpDrugClass{t.capitalize()}Match",
                 sql({"id": "JP_CLASS_CODE", "class_id": "CLASS_ID"}, "VOCAB.JP_CLASS_MATCH", f"MATCH_TYPE = '{t}'"),
                 ("vocab/jp-drug-class/", "id"), poms=[([p], iri("vocab/therapeutic-class/", "class_id"))])
            for t, p in MATCH_TYPES.items()]


# --- Medicare Part D, Connecticut ----------------------------------------------------------------------------
def us_maps():
    product, org, hcp = "data/product/", "data/organization/", "data/hcp/"
    return [
        tmap("UsOrganization",
             sql({"id": "ORGANIZATION_ID", "en": "NAME_EN", "ja": "NAME_JA", "zh": "NAME_ZH", "lei": "LEI"},
                 "US.ORGANIZATION"),
             (org, "id"), ["dm:Organization"],
             [(["rdfs:label"], lit(l, lang=l)) for l in LANGS] + [(["dcterms:identifier"], lit("lei"))]),
        tmap("UsProduct",
             sql({"id": "PRODUCT_ID", "brand": "BRAND_NAME", "generic": "CMS_GENERIC_NAME",
                  "combination": boolean("IS_COMBINATION")}, "US.PRODUCT"),
             (product, "id"), ["dm:MedicinalProduct"],
             [(["rdfs:label"], lit("brand", lang="en")), (["dm:cmsGenericName"], lit("generic")),
              (["dm:isCombinationProduct"], lit("combination", dt="xsd:boolean"))]),
        tmap("UsProductSubstance", sql({"id": "PRODUCT_ID", "substance_id": "SUBSTANCE_ID"}, "US.PRODUCT_SUBSTANCE"),
             (product, "id"), poms=[(["dm:hasActiveSubstance"], iri("vocab/substance/", "substance_id"))]),
        tmap("UsProductIndication",
             sql({"id": "PRODUCT_ID", "indication_id": "INDICATION_ID"}, "US.PRODUCT_INDICATION"),
             (product, "id"), poms=[(["dm:hasIndication"], iri("vocab/indication/", "indication_id"))]),
        tmap("UsProductManufacturer",
             sql({"id": "PRODUCT_ID", "organization_id": "ORGANIZATION_ID"}, "US.PRODUCT_MANUFACTURER"),
             (product, "id"), poms=[(["dm:manufacturedBy"], iri(org, "organization_id"))]),
        tmap("Prescriber",
             sql({"id": "PRESCRIBER_ID", "type": "CMS_PRESCRIBER_TYPE", "city": "CITY", "state": "STATE",
                  "primary": "PRIMARY_SPECIALTY_CODE"}, "US.PRESCRIBER"),
             (hcp, "id"), ["dm:HealthcareProfessional"],
             [(["dm:pseudonymousId"], lit("id")), (["dm:cmsPrescriberType"], lit("type")),
              (["dm:city"], lit("city")), (["dm:state"], lit("state")),
              (["dm:hasPrimarySpecialty"], iri("vocab/specialty/", "primary"))]),
        tmap("PrescriberSpecialty",
             sql({"id": "PRESCRIBER_ID", "specialty": "SPECIALTY_CODE"}, "US.PRESCRIBER_SPECIALTY"),
             (hcp, "id"), poms=[(["dm:hasSpecialty"], iri("vocab/specialty/", "specialty"))]),
        tmap("Prescription",
             sql({"year": "DATA_YEAR", "prescriber_id": "PRESCRIBER_ID", "product_id": "PRODUCT_ID",
                  "claims": "TOTAL_CLAIMS", "fills": "TOTAL_30DAY_FILLS", "supply": text("TOTAL_DAY_SUPPLY"),
                  "cost": "TOTAL_DRUG_COST", "benes": text("TOTAL_BENEFICIARIES"),
                  "suppressed": boolean("BENEFICIARIES_SUPPRESSED")}, "US.PRESCRIPTION"),
             f"{B}data/rx/{{year}}/{{prescriber_id}}/{{product_id}}", ["dm:Prescription"],
             [(["dm:prescribedBy"], iri(hcp, "prescriber_id")), (["dm:forProduct"], iri(product, "product_id")),
              (["dm:dataYear"], lit("year", dt="xsd:gYear")),
              (["dm:totalClaims"], lit("claims", dt="xsd:integer")),
              (["dm:total30DayFills"], lit("fills", dt="xsd:decimal")),
              (["dm:totalDaySupply"], lit("supply", dt="xsd:integer")),
              (["dm:totalDrugCost"], lit("cost", dt="xsd:decimal")),
              (["dm:totalBeneficiaries"], lit("benes", dt="xsd:integer")),
              (["dm:beneficiaryCountSuppressed"], lit("suppressed", dt="xsd:boolean"))]),
    ]


# --- NDB Open Data, Japan ------------------------------------------------------------------------------------
def jp_maps():
    product, org = "data/product/jp/", "data/organization/jp/"
    slice_t = f"{B}data/ndb/11/slice/{{product_id}}/{{setting}}/"
    obs_t = f"{B}data/ndb/11/obs/{{product_id}}/{{setting}}/{{cell}}"
    maps = [
        tmap("JpOrganization",
             sql({"id": "ORGANIZATION_ID", "en": "NAME_EN", "ja": "NAME_JA", "grp": "CORPORATE_GROUP_ID"},
                 "JP.ORGANIZATION"),
             (org, "id"), ["dm:Organization"],
             [(["rdfs:label"], lit("en", lang="en")), (["rdfs:label"], lit("ja", lang="ja")),
              (["dm:partOfCorporateGroup"], iri("data/organization/", "grp"))]),
        tmap("JpProduct",
             sql({"id": "PRODUCT_ID", "name": "PRODUCT_NAME_JA",
                  # build_ndb.py writes the half-width form only where it differs from the name
                  "hidden": "CASE WHEN PRODUCT_NAME <> PRODUCT_NAME_JA THEN PRODUCT_NAME ELSE NULL END",
                  "yj": "YJ_CODE", "jp_class": "JP_CLASS_CODE", "price": "NHI_PRICE", "unit": "DISPENSING_UNIT",
                  "route": "ROUTE", "generic": boolean("IS_GENERIC"), "originator": boolean("IS_ORIGINATOR"),
                  "combination": boolean("IS_COMBINATION"), "organization_id": "ORGANIZATION_ID"}, "JP.PRODUCT"),
             (product, "id"), ["dm:MedicinalProduct"],
             [(["rdfs:label"], lit("name", lang="ja")), (["skos:hiddenLabel"], lit("hidden", lang="ja")),
              (["dm:receiptCode"], lit("id")), (["dm:yjCode"], lit("yj")),
              (["dm:inJapaneseDrugClass"], iri("vocab/jp-drug-class/", "jp_class")),
              (["dm:nhiPrice"], lit("price", dt="xsd:decimal")), (["dm:dispensingUnit"], lit("unit")),
              (["dm:routeOfAdministration"], lit("route")),
              (["dm:isGeneric"], lit("generic", dt="xsd:boolean")),
              (["dm:isOriginator"], lit("originator", dt="xsd:boolean")),
              (["dm:isCombinationProduct"], lit("combination", dt="xsd:boolean")),
              (["dm:manufacturedBy"], iri(org, "organization_id"))]),
        tmap("JpProductSubstance", sql({"id": "PRODUCT_ID", "substance_id": "SUBSTANCE_ID"}, "JP.PRODUCT_SUBSTANCE"),
             (product, "id"), poms=[(["dm:hasActiveSubstance"], iri("vocab/substance/", "substance_id"))]),
        # masked cells: no quantity, the SDMX confidentiality flag instead
        tmap("ObservationMasked",
             sql({"product_id": "PRODUCT_ID", "setting": "CARE_SETTING_ID", "cell": "CELL"}, "JP.QUANTITY",
                 "IS_MASKED"),
             obs_t, poms=[(["sdmx-attribute:confStatus"], const("sdmx-code:confStatus-C"))]),
    ]
    dimension = {"prefecture": ("PREFECTURE_CODE", "dm:prefecture", iri("vocab/prefecture/", "dim")),
                 "month": ("CELL", "dm:month", lit("dim", dt="xsd:gYearMonth")),
                 "sex-age": ("SEX_AGE_CODE", "dm:sexAgeGroup", iri("vocab/sex-age/", "dim"))}
    for key, short in BREAKDOWNS.items():
        # one slice per product, care setting and breakdown; the national total is the same in all three
        maps.append(tmap(f"{short}Slice",
                         sql({"product_id": "PRODUCT_ID", "setting": "CARE_SETTING_ID", "total": "TOTAL_QUANTITY"},
                             "JP.NATIONAL_TOTAL"),
                         slice_t + key, ["dm:QuantitySlice"],
                         [(["qb:sliceStructure"], const(f"<{B}data/ndb/key/{key}>")),
                          (["dm:aboutProduct"], iri(product, "product_id")),
                          (["dm:careSetting"], iri("vocab/care-setting/", "setting")),
                          (["dm:totalQuantity"], lit("total", dt="xsd:decimal"))]))
        # a national total masked by NDB: the slice carries the SDMX confidentiality flag
        maps.append(tmap(f"{short}SliceMasked",
                         sql({"product_id": "PRODUCT_ID", "setting": "CARE_SETTING_ID"}, "JP.NATIONAL_TOTAL",
                             "IS_MASKED"),
                         slice_t + key, poms=[(["sdmx-attribute:confStatus"], const("sdmx-code:confStatus-C"))]))
        cells = {"product_id": "PRODUCT_ID", "setting": "CARE_SETTING_ID", "cell": "CELL"}
        maps.append(tmap(f"{short}SliceObservation", sql(cells, "JP.QUANTITY", f"BREAKDOWN = '{key}'"),
                         slice_t + key, poms=[(["qb:observation"], ("template", obs_t))]))
        col, pred, obj = dimension[key]
        maps.append(tmap(f"{short}Observation",
                         sql(cells | {"dim": col, "quantity": "QUANTITY"}, "JP.QUANTITY", f"BREAKDOWN = '{key}'"),
                         obs_t, poms=[([pred], obj), (["dm:quantity"], lit("quantity", dt="xsd:decimal"))]))
    return maps


# --- R2RML output --------------------------------------------------------------------------------------------
def turtle_object(obj):
    kind = obj[0]
    if kind == "constant":
        return f"rr:object {obj[1]}"
    if kind == "template":
        return f'rr:objectMap [ rr:template "{obj[1]}" ]'
    _, col, lang, dt = obj
    extra = f" ; rr:language \"{lang}\"" if lang else f" ; rr:datatype {dt}" if dt else ""
    return f'rr:objectMap [ rr:column "{col}"{extra} ]'


def turtle(m):
    query = m["sql"].replace('"""', '\\"\\"\\"')
    lines = [f"map:{m['name']} a rr:TriplesMap ;",
             f'    rr:logicalTable [ rr:sqlQuery """{query}""" ] ;']
    classes = f" ;\n        rr:class {' , '.join(m['classes'])}" if m["classes"] else ""
    subject = f'    rr:subjectMap [\n        rr:template "{m["subject"]}"{classes} ]'
    poms = [f"    rr:predicateObjectMap [ rr:predicate {' , '.join(p)} ;\n        {turtle_object(o)} ]"
            for p, o in m["poms"]]
    return "\n".join(lines) + "\n" + " ;\n".join([subject] + poms) + " .\n"


def main():
    sections = [("SKOS vocabularies (schema VOCAB)", [m for v in VOCABS for m in vocab_maps(v)] + crosswalk_maps()),
                ("Medicare Part D, Connecticut (schema US)", us_maps()),
                ("NDB Open Data, Japan, as an RDF Data Cube (schema JP)", jp_maps())]
    head = [f"# R2RML mapping of the knowledge graph over the Snowflake tables (GLP.VOCAB, GLP.US, GLP.JP).",
            "# Generated by scripts/build_mapping.py: edit the spec there, not this file. Checked against the graph by",
            "# scripts/check_mapping.py (Morph-KGC); scripts/r2rml_to_sms2.py writes the SMS2 that Stardog Studio reads.",
            ""] + [f"@prefix {p}: <{ns}> ." for p, ns in PREFIXES.items()]
    body = [f"\n# === {title} {'=' * (100 - len(title))}\n\n" + "\n".join(turtle(m) for m in maps)
            for title, maps in sections]
    OUT.write_text("\n".join(head) + "\n" + "".join(body))
    print(f"{OUT.relative_to(ROOT)}: {sum(len(ms) for _, ms in sections)} triples maps")


if __name__ == "__main__":
    main()
