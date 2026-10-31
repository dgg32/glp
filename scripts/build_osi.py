"""Generate the Snowflake semantic layer from the ontology and vocabularies, into semantic/.

  helper-views.sql               views the semantic view needs (GLP.SEMANTIC): bridge facts for the
                                 many-to-many links, and the OWL defined classes as flags
  diabetes-market.osi.yaml       Apache Ossie (OSI) 0.1.1 semantic model, the interchange format; Snowflake
                                 compiles it with SYSTEM$CREATE_SEMANTIC_VIEW_FROM_OSSIE_YAML
  diabetes-market.sql            the same model as a native CREATE SEMANTIC VIEW, with WITH SYNONYMS
  diabetes-market.ontology.yaml  the OWL ontology as a draft Ossie Layer 4 ontology (0.2.0.dev0); no engine
                                 reads it yet
  verified-queries.json          the business questions of queries/*.rq as SEMANTIC_VIEW SQL ({view} filled per
                                 deployment), in the native DDL as AI_VERIFIED_QUERIES

One model, two deployments, because OSI 0.1.1 has no slot for synonyms: Snowflake stores a field's
SNOWFLAKE extension as opaque metadata and Cortex Analyst never sees it (probe of 2026-10-31,
snowflake_extension.md). The OSI file carries the synonyms where the spec allows (ai_context and the
vendor extension); the native DDL carries them where Snowflake reads them.

Nothing about meaning is written here. MAPPING below only says which column holds which ontology term;
descriptions come from skos:definition, synonyms from the en/ja/zh labels of the ontology term, value
lists from the SKOS vocabularies, defined-class flags and the SGLT2/GLP-1 class ids from the OWL
restrictions of dm:SGLT2Prescriber and friends.

Checks: both YAML files validate against the vendored Apache schemas in semantic/schema/, every column
exists in data/snowflake/tables.json, no synonym is used twice.

Usage: .venv/bin/python scripts/build_osi.py
"""
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

import jsonschema
import yaml
from rdflib import Graph, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "semantic"
EXPORT = ROOT / "data" / "snowflake"
DM = Namespace("https://dgg32.github.io/glp/ontology#")
DMTC = Namespace("https://dgg32.github.io/glp/vocab/therapeutic-class/")
DB = "GLP"
VIEW = "DIABETES_MARKET"
OSI_VERSION = "0.1.1"
LANGS = ("en", "ja", "zh")
VERIFIED_AT = 1793404800  # 2026-10-31T00:00:00Z, when the verified queries were checked against the graph


def F(name, column, dim=True, term=None, lang=None, values=None, note="", sql=None):
    """A field. term: the ontology class or property the column holds (labels, definition).
    lang: the column holds the term's label in that language, so only that language's label is a synonym.
    values: (vocabulary CSV, column) whose distinct values are listed in the description.
    sql: expression for the dataset view (source alias s) when the field is not just the column."""
    return dict(name=name, column=column, dim=dim, term=term, lang=lang, values=values, note=note, sql=sql)


def label_or_english(lang_column, en_column):
    """The SPARQL convention of queries/sglt2-by-japanese-label.rq: the label in the language, else English."""
    return f"COALESCE(s.{lang_column}, s.{en_column})"


MAPPING = {
    "datasets": [
        dict(name="prescription", source="US.PRESCRIPTION", term="Prescription", key=["PRESCRIPTION_ID"], fields=[
            F("prescription_id", "PRESCRIPTION_ID", note="Key: data year / prescriber / product."),
            F("prescriber_id", "PRESCRIBER_ID", note="Pseudonymous prescriber key."),
            F("product_id", "PRODUCT_ID", note="Product key."),
            F("data_year", "DATA_YEAR", term="dataYear", note="Only 2024 is loaded."),
            F("beneficiaries_suppressed", "BENEFICIARIES_SUPPRESSED", term="beneficiaryCountSuppressed"),
            F("claims", "TOTAL_CLAIMS", dim=False, term="totalClaims"),
            F("fills_30day", "TOTAL_30DAY_FILLS", dim=False, term="total30DayFills"),
            F("day_supply", "TOTAL_DAY_SUPPLY", dim=False, term="totalDaySupply"),
            F("drug_cost", "TOTAL_DRUG_COST", dim=False, term="totalDrugCost"),
            F("beneficiaries", "TOTAL_BENEFICIARIES", dim=False, term="totalBeneficiaries"),
        ]),
        dict(name="prescription_class", source="SEMANTIC.PRESCRIPTION_CLASS", key=["PRESCRIPTION_ID", "CLASS_ID"],
             description="Claims attributed to therapeutic classes: one row per prescription and class of any of "
                         "the product's substances, including all broader classes (skos:broader*). A combination "
                         "product counts in each of its classes, so never add claims across classes; filter or "
                         "group by one class.", fields=[
            F("prescription_id", "PRESCRIPTION_ID", note="Prescription key."),
            F("class_id", "CLASS_ID", note="Therapeutic class key."),
            F("claims", "TOTAL_CLAIMS", dim=False, term="totalClaims"),
            F("fills_30day", "TOTAL_30DAY_FILLS", dim=False, term="total30DayFills"),
            F("drug_cost", "TOTAL_DRUG_COST", dim=False, term="totalDrugCost"),
        ]),
        dict(name="prescription_class_company", source="SEMANTIC.PRESCRIPTION_CLASS_COMPANY",
             key=["PRESCRIPTION_ID", "CLASS_ID", "ORGANIZATION_KEY"],
             description="Claims by therapeutic class and manufacturer, for market shares: one row per prescription, "
                         "class and marketing authorization holder. Unbranded generics have no single manufacturer. "
                         "A product with two holders (Byetta) counts for each.", fields=[
            F("prescription_id", "PRESCRIPTION_ID", note="Prescription key."),
            F("class_id", "CLASS_ID", note="Therapeutic class key."),
            F("manufacturer", "MANUFACTURER", term="manufacturedBy",
              note="Company name, or 'generic (no single manufacturer)'."),
            F("claims", "TOTAL_CLAIMS", dim=False, term="totalClaims"),
            F("claims_allocated", "CLAIMS_ALLOCATED", dim=False,
              note="Claims divided equally among the product's marketing authorization holders, so that the "
                   "companies of a class add up to the class's claims. Use for market shares."),
            F("drug_cost", "TOTAL_DRUG_COST", dim=False, term="totalDrugCost"),
        ]),
        dict(name="prescriber", source="SEMANTIC.PRESCRIBER_PROFILE", term="HealthcareProfessional",
             key=["PRESCRIBER_ID"], fields=[
            F("prescriber_id", "PRESCRIBER_ID", term="pseudonymousId"),
            F("cms_prescriber_type", "CMS_PRESCRIBER_TYPE", term="cmsPrescriberType"),
            F("city", "CITY", term="city"),
            F("state", "STATE", term="state"),
            F("is_sglt2_prescriber", "IS_SGLT2_PRESCRIBER", term="SGLT2Prescriber"),
            F("is_glp1_prescriber", "IS_GLP1_PRESCRIBER", term="GLP1Prescriber"),
        ]),
        dict(name="specialty", source="VOCAB.SPECIALTY", term="Specialty", key=["SPECIALTY_CODE"],
             description_note="Joined as the prescriber's primary specialty (NPI Registry).", fields=[
            F("specialty_code", "SPECIALTY_CODE", note="NUCC taxonomy code, e.g. 207RE0101X."),
            F("specialty_name", "PREF_LABEL_EN", term="Specialty", lang="en"),
            F("specialty_name_ja", "PREF_LABEL_JA", term="Specialty", lang="ja",
              values=("US.PRESCRIBER", "PRIMARY_SPECIALTY_CODE"), sql=label_or_english("PREF_LABEL_JA", "PREF_LABEL_EN"),
              note="English name where no Japanese label exists yet."),
            F("specialty_name_zh", "PREF_LABEL_ZH", term="Specialty", lang="zh",
              sql=label_or_english("PREF_LABEL_ZH", "PREF_LABEL_EN"), note="English name where no Chinese label exists yet."),
        ]),
        dict(name="product", source="SEMANTIC.PRODUCT_PROFILE", term="MedicinalProduct", key=["PRODUCT_ID"], fields=[
            F("product_id", "PRODUCT_ID", note="Product key."),
            F("brand_name", "BRAND_NAME", term="MedicinalProduct", lang="en", values=("US.PRODUCT", None)),
            F("cms_generic_name", "CMS_GENERIC_NAME", term="cmsGenericName"),
            F("is_combination", "IS_COMBINATION", term="isCombinationProduct"),
            F("is_sglt2_product", "IS_SGLT2_PRODUCT", term="SGLT2Product"),
            F("is_glp1_product", "IS_GLP1_PRODUCT", term="GLP1Product"),
        ]),
        dict(name="therapeutic_class", source="VOCAB.THERAPEUTIC_CLASS", term="TherapeuticClass", key=["CLASS_ID"],
             fields=[
            F("class_id", "CLASS_ID", note="Class key, e.g. SGLT2Inhibitor."),
            F("class_name", "PREF_LABEL_EN", term="TherapeuticClass", lang="en", values=("VOCAB.THERAPEUTIC_CLASS", None)),
            F("class_name_ja", "PREF_LABEL_JA", term="TherapeuticClass", lang="ja", values=("VOCAB.THERAPEUTIC_CLASS", None)),
            F("class_name_zh", "PREF_LABEL_ZH", term="TherapeuticClass", lang="zh", values=("VOCAB.THERAPEUTIC_CLASS", None)),
            F("atc_code", "NOTATION", note="ATC code of the class, e.g. A10BK. Glinides and imeglimin have none."),
            F("class_depth", None, sql="d.DEPTH",
              note="Level in the class tree (skos:broader*): 1 drugs used in diabetes, 2 insulins or blood glucose "
                   "lowering drugs, 3 drug classes such as SGLT2 inhibitors, 4 narrower classes such as dual GIP/GLP-1 "
                   "agonists, which also count in their broader class."),
            F("is_drug_class", None, sql="d.DEPTH = {drug_class_depth}",
              note="TRUE for the drug classes (SGLT2 inhibitors, GLP-1 receptor agonists, DPP-4 inhibitors, "
                   "biguanides, long-acting insulins, ...): use it whenever a question says 'by drug class' or "
                   "'by class', so that broader and narrower classes are not listed next to them."),
        ], joins="LEFT JOIN (SELECT CLASS_ID, COUNT(*) AS DEPTH FROM GLP.VOCAB.CLASS_ANCESTOR GROUP BY CLASS_ID) d "
                 "ON d.CLASS_ID = s.CLASS_ID"),
        dict(name="organization", source="US.ORGANIZATION", term="Organization", key=["ORGANIZATION_ID"], fields=[
            F("organization_id", "ORGANIZATION_ID", note="LEI of the GLEIF ultimate parent, or a local id."),
            F("company_name", "NAME_EN", term="Organization", lang="en", values=("US.ORGANIZATION", None, "ALT_NAMES"),
              note="Legal name of the ultimate parent in GLEIF."),
            F("company_name_ja", "NAME_JA", term="Organization", lang="ja", values=("US.ORGANIZATION", None),
              sql=label_or_english("NAME_JA", "NAME_EN")),
            F("company_name_zh", "NAME_ZH", term="Organization", lang="zh", sql=label_or_english("NAME_ZH", "NAME_EN")),
        ]),
    ],
    # (from, to, from columns, to columns, ontology property)
    "relationships": [
        ("prescription", "prescriber", ["PRESCRIBER_ID"], ["PRESCRIBER_ID"], "prescribedBy"),
        ("prescription", "product", ["PRODUCT_ID"], ["PRODUCT_ID"], "forProduct"),
        ("prescriber", "specialty", ["PRIMARY_SPECIALTY_CODE"], ["SPECIALTY_CODE"], "hasPrimarySpecialty"),
        ("prescription_class", "prescription", ["PRESCRIPTION_ID"], ["PRESCRIPTION_ID"], None),
        ("prescription_class", "therapeutic_class", ["CLASS_ID"], ["CLASS_ID"], "inTherapeuticClass"),
        ("prescription_class_company", "prescription", ["PRESCRIPTION_ID"], ["PRESCRIPTION_ID"], None),
        ("prescription_class_company", "therapeutic_class", ["CLASS_ID"], ["CLASS_ID"], "inTherapeuticClass"),
        ("prescription_class_company", "organization", ["ORGANIZATION_ID"], ["ORGANIZATION_ID"], "manufacturedBy"),
    ],
}

CAVEATS = ("Medicare Part D, Connecticut, data year 2024: mostly people aged 65 and over. Counts are claims "
           "(fills and refills), not patients. CMS omits prescriber/product rows with fewer than 11 claims. "
           "Costs are gross, before rebates. Prescribers are pseudonyms; report aggregates only.")
INSTRUCTIONS = ("Use total_claims and total_drug_cost for overall volume. For anything by therapeutic class use the "
                "class_* metrics and filter or group by one class: a combination product counts in every class it "
                "belongs to, so class figures never add up to the total. 'By drug class' means "
                "therapeutic_class.is_drug_class = TRUE. Cost comparisons between classes: also show "
                "class_cost_per_30day_fill, the fair comparison when fill lengths differ. For market shares by "
                "company divide company_claims_allocated by its sum over all companies of the class. Names exist in "
                "English, Japanese (*_ja) and Chinese (*_zh): answer with the names in the language of the question.")


class Ontology:
    def __init__(self):
        self.g = Graph()
        self.g.parse(ROOT / "ontology" / "diabetes-market.ttl")
        for v in ("therapeutic-class", "substance", "indication"):
            self.g.parse(ROOT / "vocab" / f"{v}.ttl")

    def labels(self, term, lang=None):
        return [str(l) for l in self.g.objects(DM[term], RDFS.label) if lang in (None, l.language)]

    def label(self, term, lang="en"):
        return next(iter(self.labels(term, lang)), term)

    def definition(self, term):
        return next((str(d) for d in self.g.objects(DM[term], SKOS.definition) if d.language == "en"), "")

    def class_depth(self, cls):
        """Number of classes on the skos:broader* path from cls to the top, cls included."""
        return len(list(self.g.transitive_objects(DMTC[cls], SKOS.broader)))

    def defined_classes(self):
        """{defined class: (base class, therapeutic class it requires)} from owl:equivalentClass restrictions."""
        out = {}
        for c, eq in self.g.subject_objects(OWL.equivalentClass):
            members = list(Collection(self.g, self.g.value(eq, OWL.intersectionOf)))
            nodes, required = [members[1]], None
            while nodes:
                n = nodes.pop()
                if (v := self.g.value(n, OWL.hasValue)) is not None:
                    required = v
                nodes += [self.g.value(n, OWL.someValuesFrom)] if self.g.value(n, OWL.someValuesFrom) else []
            out[local(c)] = (local(members[0]), local(required))
        return out


def local(iri):
    return re.split(r"[#/]", str(iri))[-1]


def read_rows(table):
    with open(EXPORT / f"{table}.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def value_list(dataset, field):
    """The values a label column takes, from the exported vocabulary (only the ones in use where given)."""
    table, used_by, *aliases = field["values"]
    rows = read_rows(dataset_table(dataset))
    if used_by:  # e.g. only the specialties some prescriber has as primary
        used = {r[used_by] for r in read_rows(table)}
        rows = [r for r in rows if r[dataset["key"][0]] in used]
    values = {}
    for r in rows:
        if r[field["column"]]:
            also = [a for col in aliases for a in r[col].split("|") if a]
            values[r[field["column"]]] = f"{r[field['column']]} (also: {', '.join(also)})" if also else r[field["column"]]
    return sorted(values.values())


def dataset_table(d):
    return {"SEMANTIC.PRODUCT_PROFILE": "US.PRODUCT", "SEMANTIC.PRESCRIBER_PROFILE": "US.PRESCRIBER"}.get(
        d["source"], d["source"])


def describe(onto, dataset, field):
    parts = []
    if field["term"] and field["lang"]:
        parts.append(f"{onto.label(field['term']).capitalize()} name in "
                     f"{dict(en='English', ja='Japanese', zh='Chinese')[field['lang']]}.")
    elif field["term"]:
        parts.append(onto.definition(field["term"]) or onto.label(field["term"]).capitalize() + ".")
    if field["note"]:
        parts.append(field["note"])
    if field["values"]:
        parts.append("Values: " + "; ".join(value_list(dataset, field)) + ".")
    return " ".join(parts)


def synonyms(onto, field):
    if not field["term"]:
        return []
    found = onto.labels(field["term"], field["lang"])
    return [s for s in found if s.lower().replace(" ", "_") != field["name"]]


def build_model(onto, defined):
    """The model in a neutral form both writers use."""
    model = {"name": VIEW, "description": "", "datasets": [], "relationships": [], "metrics": []}
    model["description"] = ("Type 2 diabetes drug prescribing, generated from the diabetes-market ontology "
                            f"{onto.g.value(URIRef('https://dgg32.github.io/glp/ontology'), OWL.versionInfo)}. "
                            + CAVEATS)
    sglt2, glp1 = defined["SGLT2Prescriber"][1], defined["GLP1Prescriber"][1]
    drug_class_depth = onto.class_depth(sglt2)  # the level the OWL defined classes speak about
    if onto.class_depth(glp1) != drug_class_depth:
        sys.exit("SGLT2 and GLP-1 classes sit at different depths: what is a drug class?")
    # Each dataset reads a view (GLP.SEMANTIC.SV_<NAME>) whose columns carry the logical field names, so the
    # physical names (PREF_LABEL_JA) never appear next to the logical ones (specialty_name_ja): Cortex Analyst
    # mixed them up on 2026-10-31.
    renamed = {}
    for d in MAPPING["datasets"]:
        desc = d.get("description") or onto.definition(d["term"])
        if d.get("description_note"):
            desc += " " + d["description_note"]
        plain = {f["column"]: f["name"].upper() for f in d["fields"] if f["column"] and not f["sql"]}
        needed = d["key"] + [c for frm, to, fc, tc, _ in MAPPING["relationships"]
                             for c in (fc if frm == d["name"] else tc if to == d["name"] else [])]
        renamed[d["name"]] = {c: plain.get(c, c) for c in needed}
        view_columns = [((f["sql"] or f"s.{f['column']}").format(drug_class_depth=drug_class_depth), f["name"].upper())
                        for f in d["fields"]]
        view_columns += [(f"s.{c}", c) for c in dict.fromkeys(needed) if c not in plain]
        model["datasets"].append({
            "name": d["name"], "source": f"{DB}.SEMANTIC.SV_{d['name'].upper()}", "physical": f"{DB}.{d['source']}",
            "joins": d.get("joins", ""), "view_columns": view_columns,
            "key": [renamed[d["name"]][c] for c in d["key"]], "description": desc,
            "synonyms": [s for s in onto.labels(d["term"]) if s.lower().replace(" ", "_") != d["name"]] if d.get("term") else [],
            "fields": [{"name": f["name"], "column": f["name"].upper(), "dim": f["dim"],
                        "description": describe(onto, d, f), "synonyms": synonyms(onto, f)} for f in d["fields"]]})
    for frm, to, fc, tc, prop in MAPPING["relationships"]:
        model["relationships"].append({"name": f"{frm}_to_{to}", "from": frm, "to": to,
                                       "from_columns": [renamed[frm][c] for c in fc],
                                       "to_columns": [renamed[to][c] for c in tc]})
    share = (f"CASE WHEN prescription_class.class_id = '{{c}}' THEN prescription_class.claims ELSE 0 END")
    model["metrics"] = [
        ("total_claims", "SUM(prescription.claims)", "totalClaims", "All Part D claims."),
        ("total_drug_cost", "SUM(prescription.drug_cost)", "totalDrugCost", "All gross drug cost in USD."),
        ("total_30day_fills", "SUM(prescription.fills_30day)", "total30DayFills", ""),
        ("total_day_supply", "SUM(prescription.day_supply)", "totalDaySupply", ""),
        ("cost_per_claim", "SUM(prescription.drug_cost) / NULLIF(SUM(prescription.claims), 0)", None,
         "Gross drug cost per claim in USD."),
        ("prescriber_count", "COUNT(DISTINCT prescription.prescriber_id)", None,
         "Number of distinct prescribers with at least one claim (Part D rows of 11 claims or more)."),
        ("class_claims", "SUM(prescription_class.claims)", None,
         "Claims of products in a therapeutic class (including narrower classes). Filter or group by one class."),
        ("class_drug_cost", "SUM(prescription_class.drug_cost)", None,
         "Gross drug cost in USD of products in a therapeutic class. Filter or group by one class."),
        ("class_cost_per_claim", "SUM(prescription_class.drug_cost) / NULLIF(SUM(prescription_class.claims), 0)", None,
         "Gross drug cost per claim in USD within a therapeutic class."),
        ("class_cost_per_30day_fill",
         "SUM(prescription_class.drug_cost) / NULLIF(SUM(prescription_class.fills_30day), 0)", None,
         "Gross drug cost per 30-day fill in USD within a therapeutic class: compares classes fairly when "
         "fill lengths differ."),
        ("sglt2_claims", f"SUM({share.format(c=sglt2)})", None,
         f"Claims of products in the class {onto.g.value(DMTC[sglt2], SKOS.prefLabel)} (from the definition of "
         "dm:SGLT2Prescriber)."),
        ("glp1_claims", f"SUM({share.format(c=glp1)})", None,
         f"Claims of products in the class {onto.g.value(DMTC[glp1], SKOS.prefLabel)}, including dual GIP/GLP-1 "
         "agonists (from the definition of dm:GLP1Prescriber)."),
        ("sglt2_share_vs_glp1",
         f"SUM({share.format(c=sglt2)}) / NULLIF(SUM({share.format(c=sglt2)}) + SUM({share.format(c=glp1)}), 0)",
         None, "SGLT2 inhibitor claims as a fraction of SGLT2 inhibitor plus GLP-1 receptor agonist claims (0 to 1)."),
        ("company_claims", "SUM(prescription_class_company.claims)", None,
         "Claims of products by a manufacturer within a therapeutic class. Filter or group by one class. A product "
         "with two marketing authorization holders counts fully for each, so do not divide by the sum over companies."),
        ("company_claims_allocated", "SUM(prescription_class_company.claims_allocated)", None,
         "Claims by manufacturer within a therapeutic class, with a product's claims split equally among its "
         "marketing authorization holders: the companies of a class add up to the class's claims. Market share = "
         "company_claims_allocated / its sum over all companies of the class."),
        ("company_drug_cost", "SUM(prescription_class_company.drug_cost)", None,
         "Gross drug cost in USD by manufacturer within a therapeutic class."),
    ]
    model["metrics"] = [{"name": n, "expression": e, "description": (onto.definition(t) + " " + d).strip() if t else d,
                         "synonyms": onto.labels(t) if t else []} for n, e, t, d in model["metrics"]]
    # The business questions of queries/*.rq (US part) as verified queries: the SPARQL query catalog becomes the
    # Analyst's answer key. {view} is filled per deployment; deploy_semantic_view.py checks their results.
    sglt2_ja = next(str(l) for l in onto.g.objects(DMTC[sglt2], SKOS.prefLabel) if l.language == "ja")
    model["verified_queries"] = [
        ("sglt2_vs_glp1_by_specialty", "sglt2-vs-glp1-by-specialty.rq", True,
         "What share of SGLT2 inhibitor plus GLP-1 receptor agonist claims are SGLT2 inhibitors, by prescriber specialty?",
         "SELECT * FROM SEMANTIC_VIEW({view} DIMENSIONS specialty.specialty_name "
         "METRICS sglt2_claims, glp1_claims, sglt2_share_vs_glp1) ORDER BY sglt2_claims + glp1_claims DESC"),
        ("cost_per_claim_by_drug_class", "cost-per-claim-by-class.rq", True,
         "What is the cost per claim and per 30-day fill by drug class, for single-ingredient products?",
         "SELECT * FROM SEMANTIC_VIEW({view} DIMENSIONS therapeutic_class.class_name METRICS class_claims, "
         "class_drug_cost, class_cost_per_claim, class_cost_per_30day_fill WHERE therapeutic_class.is_drug_class "
         "AND NOT product.is_combination) ORDER BY class_cost_per_30day_fill DESC"),
        ("market_share_by_manufacturer", "market-share-by-manufacturer.rq", False,
         "What is each manufacturer's share of SGLT2 inhibitor and GLP-1 receptor agonist claims?",
         "SELECT class_name, manufacturer, company_claims, company_claims_allocated / SUM(company_claims_allocated) "
         "OVER (PARTITION BY class_name) AS claim_share FROM SEMANTIC_VIEW({view} DIMENSIONS "
         "therapeutic_class.class_name, prescription_class_company.manufacturer METRICS company_claims, "
         f"company_claims_allocated WHERE prescription_class_company.class_id IN ('{sglt2}', '{glp1}')) "
         "ORDER BY class_name, claim_share DESC"),
        ("sglt2_by_specialty_ja", "sglt2-by-japanese-label.rq", True,
         f"{sglt2_ja}を処方している専門分野は？",
         "SELECT * FROM SEMANTIC_VIEW({view} DIMENSIONS specialty.specialty_name_ja METRICS class_claims "
         f"WHERE therapeutic_class.class_name_ja = '{sglt2_ja}') ORDER BY class_claims DESC LIMIT 10"),
        ("prescriber_overlap", "prescriber-overlap-reasoning.rq", False,
         "How many prescribers write SGLT2 inhibitors, GLP-1 receptor agonists, or both?",
         "SELECT * FROM SEMANTIC_VIEW({view} DIMENSIONS prescriber.is_sglt2_prescriber, prescriber.is_glp1_prescriber "
         "METRICS prescriber_count) ORDER BY 1, 2"),
    ]
    return model


def dedupe_synonyms(model):
    """Synonyms must point at one thing. A label used several times stays with the first owner: metrics (what
    people ask for), then fields (what they group by, e.g. 薬効分類 -> class_name_ja), then datasets."""
    seen = set()
    for item in model["metrics"] + [f for d in model["datasets"] for f in d["fields"]] + model["datasets"]:
        item["synonyms"] = [s for s in item["synonyms"] if not (s.lower() in seen or seen.add(s.lower()))]


def check_columns(model):
    tables = {t["name"]: [c.split()[0] for c in t["columns"]]
              for t in json.loads((EXPORT / "tables.json").read_text())["tables"]}
    views = {"SEMANTIC.PRESCRIPTION_CLASS": ["PRESCRIPTION_ID", "CLASS_ID", "TOTAL_CLAIMS", "TOTAL_30DAY_FILLS", "TOTAL_DRUG_COST"],
             "SEMANTIC.PRESCRIPTION_CLASS_COMPANY": ["PRESCRIPTION_ID", "CLASS_ID", "ORGANIZATION_ID", "ORGANIZATION_KEY",
                                                     "MANUFACTURER", "TOTAL_CLAIMS", "CLAIMS_ALLOCATED", "TOTAL_DRUG_COST"],
             "SEMANTIC.PRESCRIBER_PROFILE": tables["US.PRESCRIBER"] + ["IS_SGLT2_PRESCRIBER", "IS_GLP1_PRESCRIBER"],
             "SEMANTIC.PRODUCT_PROFILE": tables["US.PRODUCT"] + ["IS_SGLT2_PRODUCT", "IS_GLP1_PRODUCT"]}
    columns = tables | views
    errors = []
    for d in model["datasets"]:  # the dataset views read existing columns ...
        have = columns[d["physical"].split(".", 1)[1]]
        errors += [f"{d['name']}: {expr}" for expr, _ in d["view_columns"]
                   if re.fullmatch(r"s\.\w+", expr) and expr[2:] not in have]
        out = [name for _, name in d["view_columns"]]  # ... and provide every key and relationship column
        errors += [f"{d['name']} key {c}" for c in d["key"] if c not in out]
        errors += [f"{d['name']} has {c} twice" for c, n in Counter(out).items() if n > 1]
    for r in model["relationships"]:
        for ds, cols in ((r["from"], r["from_columns"]), (r["to"], r["to_columns"])):
            out = [name for d in model["datasets"] if d["name"] == ds for _, name in d["view_columns"]]
            errors += [f"relationship {r['name']}: {ds}.{c}" for c in cols if c not in out]
    if errors:
        sys.exit("column errors: " + ", ".join(errors))


def helper_views(defined, model):
    flags = {"HealthcareProfessional": [], "MedicinalProduct": []}
    for c, (base, cls) in sorted(defined.items()):
        column = "IS_" + re.sub(r"(Prescriber|Product)$", r"_\1", c).upper()
        flags[base].append(f"BOOLOR_AGG(pc.CLASS_ID = '{cls}') AS {column}")
    prescriber_cols = [f.split(" AS ")[1] for f in flags["HealthcareProfessional"]]
    product_cols = [f.split(" AS ")[1] for f in flags["MedicinalProduct"]]
    s = f"{DB}.SEMANTIC"
    return f"""-- Generated by scripts/build_osi.py from the ontology. Do not edit.
CREATE SCHEMA IF NOT EXISTS {s};

CREATE OR REPLACE VIEW {s}.PRESCRIPTION_CLASS
  COMMENT = 'One row per prescription and therapeutic class (US.PRODUCT_CLASS: substance classes and all broader classes).'
AS SELECT p.PRESCRIPTION_ID, pc.CLASS_ID, p.TOTAL_CLAIMS, p.TOTAL_30DAY_FILLS, p.TOTAL_DRUG_COST
FROM {DB}.US.PRESCRIPTION p JOIN {DB}.US.PRODUCT_CLASS pc ON pc.PRODUCT_ID = p.PRODUCT_ID;

CREATE OR REPLACE VIEW {s}.PRESCRIPTION_CLASS_COMPANY
  COMMENT = 'One row per prescription, therapeutic class and marketing authorization holder (none for unbranded generics).'
AS SELECT p.PRESCRIPTION_ID, pc.CLASS_ID, pm.ORGANIZATION_ID, COALESCE(pm.ORGANIZATION_ID, 'none') AS ORGANIZATION_KEY,
       COALESCE(o.NAME_EN, 'generic (no single manufacturer)') AS MANUFACTURER, p.TOTAL_CLAIMS,
       p.TOTAL_CLAIMS / COUNT(*) OVER (PARTITION BY p.PRESCRIPTION_ID, pc.CLASS_ID) AS CLAIMS_ALLOCATED, p.TOTAL_DRUG_COST
FROM {DB}.US.PRESCRIPTION p
JOIN {DB}.US.PRODUCT_CLASS pc ON pc.PRODUCT_ID = p.PRODUCT_ID
LEFT JOIN {DB}.US.PRODUCT_MANUFACTURER pm ON pm.PRODUCT_ID = p.PRODUCT_ID
LEFT JOIN {DB}.US.ORGANIZATION o ON o.ORGANIZATION_ID = pm.ORGANIZATION_ID;

-- OWL defined classes ({", ".join(sorted(defined))}) as flags: what a reasoner infers, spelled out in SQL.
CREATE OR REPLACE VIEW {s}.PRESCRIBER_PROFILE
  COMMENT = 'US.PRESCRIBER with the OWL defined classes of the ontology as flags.'
AS SELECT d.*, {", ".join(f"COALESCE(f.{c}, FALSE) AS {c}" for c in prescriber_cols)}
FROM {DB}.US.PRESCRIBER d LEFT JOIN (
  SELECT p.PRESCRIBER_ID, {", ".join(flags["HealthcareProfessional"])}
  FROM {DB}.US.PRESCRIPTION p JOIN {DB}.US.PRODUCT_CLASS pc ON pc.PRODUCT_ID = p.PRODUCT_ID
  GROUP BY p.PRESCRIBER_ID) f ON f.PRESCRIBER_ID = d.PRESCRIBER_ID;

CREATE OR REPLACE VIEW {s}.PRODUCT_PROFILE
  COMMENT = 'US.PRODUCT with the OWL defined classes of the ontology as flags.'
AS SELECT d.*, {", ".join(f"COALESCE(f.{c}, FALSE) AS {c}" for c in product_cols)}
FROM {DB}.US.PRODUCT d LEFT JOIN (
  SELECT pc.PRODUCT_ID, {", ".join(flags["MedicinalProduct"])}
  FROM {DB}.US.PRODUCT_CLASS pc GROUP BY pc.PRODUCT_ID) f ON f.PRODUCT_ID = d.PRODUCT_ID;

-- One view per dataset of the semantic view, with the logical field names as column names.
""" + "\n".join(
        f"CREATE OR REPLACE VIEW {d['source']}\n  COMMENT = {sql_string('Dataset ' + d['name'] + ' of the semantic view.')}\n"
        f"AS SELECT {', '.join(f'{expr} AS {name}' for expr, name in d['view_columns'])}\n"
        f"FROM {d['physical']} s{(' ' + d['joins']) if d['joins'] else ''};\n" for d in model["datasets"])


def ansi(expression):
    return {"dialects": [{"dialect": "ANSI_SQL", "expression": expression}]}


def with_synonyms(item, synonyms):
    if synonyms:
        item["ai_context"] = "Synonyms: " + ", ".join(synonyms)
        item["custom_extensions"] = [{"vendor_name": "SNOWFLAKE",
                                      "data": json.dumps({"synonyms": synonyms}, ensure_ascii=False)}]
    return item


def osi(model):
    datasets = []
    for d in model["datasets"]:
        fields = [with_synonyms({"name": f["name"], "expression": ansi(f["column"]),
                                 **({"dimension": {"is_time": False}} if f["dim"] else {}),
                                 **({"description": f["description"]} if f["description"] else {})}, f["synonyms"])
                  for f in d["fields"]]
        datasets.append(with_synonyms({"name": d["name"], "source": d["source"], "primary_key": d["key"],
                                       "description": d["description"], "fields": fields}, d["synonyms"]))
    metrics = [with_synonyms({"name": m["name"], "expression": ansi(m["expression"]),
                              **({"description": m["description"]} if m["description"] else {})}, m["synonyms"])
               for m in model["metrics"]]
    return {"version": OSI_VERSION, "semantic_model": [{
        "name": model["name"] + "_OSI", "description": model["description"], "ai_context": INSTRUCTIONS,
        "datasets": datasets, "relationships": model["relationships"], "metrics": metrics,
        # The layout SYSTEM$READ_OSSIE_YAML_FROM_SEMANTIC_VIEW itself exports for instructions and verified queries.
        "custom_extensions": [{"vendor_name": "SNOWFLAKE", "data": json.dumps({
            "module_custom_instructions": {"sql_generation": INSTRUCTIONS},
            "verified_queries": [{"name": n, "question": q, "sql": s.format(view=f"{DB}.SEMANTIC.{model['name']}_OSI"),
                                  "verified_at": VERIFIED_AT, "use_as_onboarding_question": o}
                                 for n, _, o, q, s in model["verified_queries"]]}, ensure_ascii=False)}]}]}


def sql_string(text):
    return "'" + text.replace("\\", "\\\\").replace("'", "''") + "'"


def ddl_options(item):
    out = ""
    if item["synonyms"]:
        out += f"\n      WITH SYNONYMS = ({', '.join(sql_string(s) for s in item['synonyms'])})"
    if item["description"]:
        out += f"\n      COMMENT = {sql_string(item['description'])}"
    return out


def native(model):
    tables = [f"    {d['name']} AS {d['source']} PRIMARY KEY ({', '.join(d['key'])}){ddl_options(d)}"
              for d in model["datasets"]]
    rels = [f"    {r['name']} AS {r['from']} ({', '.join(r['from_columns'])}) REFERENCES {r['to']} ({', '.join(r['to_columns'])})"
            for r in model["relationships"]]
    facts = [f"    {d['name']}.{f['name']} AS {d['name']}.{f['column']}{ddl_options(f)}"
             for d in model["datasets"] for f in d["fields"] if not f["dim"]]
    dims = [f"    {d['name']}.{f['name']} AS {d['name']}.{f['column']}{ddl_options(f)}"
            for d in model["datasets"] for f in d["fields"] if f["dim"]]
    metrics = [f"    {m['name']} AS {m['expression']}{ddl_options(m)}" for m in model["metrics"]]
    block = lambda name, rows: f"  {name} (\n" + ",\n".join(rows) + "\n  )"  # noqa: E731
    return ("-- Generated by scripts/build_osi.py from the ontology. Do not edit.\n"
            f"CREATE OR REPLACE SEMANTIC VIEW {DB}.SEMANTIC.{model['name']}\n"
            + "\n".join([block("TABLES", tables), block("RELATIONSHIPS", rels), block("FACTS", facts),
                         block("DIMENSIONS", dims), block("METRICS", metrics)])
            + f"\n  COMMENT = {sql_string(model['description'])}"
            + f"\n  AI_SQL_GENERATION {sql_string(INSTRUCTIONS)}"
            + "\n  AI_VERIFIED_QUERIES (\n" + ",\n".join(
                f"    {name} AS (\n      QUESTION {sql_string(question)}\n      VERIFIED_AT {VERIFIED_AT}\n"
                f"      ONBOARDING_QUESTION {str(onboarding).upper()}\n"
                f"      SQL {sql_string(sql.format(view=f'{DB}.SEMANTIC.{model['name']}'))}\n    )"
                for name, _, onboarding, question, sql in model["verified_queries"]) + "\n  );\n")


XSD_BUILTIN = {XSD.string: "String", XSD.boolean: "Boolean", XSD.decimal: "Decimal", XSD.integer: "Integer",
               XSD.nonNegativeInteger: "Integer", XSD.gYear: "Integer", XSD.gYearMonth: "String", XSD.date: "Date"}


def ontology_layer(onto, defined):
    """The OWL ontology as a draft Ossie Layer 4 ontology: classes -> concepts, properties -> relationships."""
    g = onto.g
    snake = lambda name: re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()  # noqa: E731
    classes = sorted({local(c) for c in g.subjects(RDF.type, OWL.Class) if str(c).startswith(str(DM))})
    concepts = {c: {"concept": c, "type": "EntityType", "iri": f"dm:{c}"} for c in classes}
    for c in classes:
        if d := onto.definition(c):
            concepts[c]["description"] = d
        supers = [local(s) for s in g.objects(DM[c], RDFS.subClassOf) if local(s) in concepts]
        if c in defined:
            supers.append(defined[c][0])
            path = "writes.for_product." if defined[c][0] == "HealthcareProfessional" else ""
            notation = g.value(DMTC[defined[c][1]], SKOS.notation)
            concepts[c]["derived_by"] = [f"EXISTS ( {defined[c][0]}.{path}has_active_substance.in_therapeutic_class"
                                         f".broader_transitive.notation == '{notation}' )"]
        if supers:
            concepts[c]["extends"] = supers
    concepts["TherapeuticClass"].setdefault("relationships", []).extend([
        {"name": "notation", "roles": [{"concept": "String"}], "verbalizes": ["{TherapeuticClass} has ATC code {String}"],
         "multiplicity": "ManyToOne", "iri": "skos:notation"},
        {"name": "broader", "roles": [{"concept": "TherapeuticClass", "name": "parent"}],
         "verbalizes": ["{TherapeuticClass} has broader class {TherapeuticClass:parent}"], "iri": "skos:broader"},
        {"name": "broader_transitive", "roles": [{"concept": "TherapeuticClass", "name": "ancestor"}],
         "verbalizes": ["{TherapeuticClass} is within {TherapeuticClass:ancestor}"], "iri": "skos:broaderTransitive",
         "derived_by": ["TherapeuticClass == ancestor", "TherapeuticClass.broader(ancestor)",
                        "TherapeuticClass.broader.broader_transitive(ancestor)"]}])
    skipped = []
    for kind in (OWL.ObjectProperty, OWL.DatatypeProperty):
        for p in sorted(g.subjects(RDF.type, kind)):
            if not str(p).startswith(str(DM)):
                continue
            domain = g.value(p, RDFS.domain) or g.value(g.value(p, RDFS.subPropertyOf), RDFS.domain)
            rng = g.value(p, RDFS.range) or g.value(g.value(p, RDFS.subPropertyOf), RDFS.range)
            if domain is None or local(domain) not in concepts:
                skipped.append(local(p))
                continue
            role = XSD_BUILTIN.get(rng, local(rng) if rng is not None and local(rng) in concepts else "Any")
            rel = {"name": snake(local(p)), "roles": [{"concept": role}],
                   "verbalizes": [f"{{{local(domain)}}} {onto.label(local(p))} {{{role}}}"], "iri": f"dm:{local(p)}"}
            if (p, RDF.type, OWL.FunctionalProperty) in g:
                rel["multiplicity"] = "ManyToOne"
            if rng == XSD.nonNegativeInteger:
                rel["requires"] = [f"{local(domain)}.{rel['name']} >= 0"]
            if d := onto.definition(local(p)):
                rel["description"] = d
            concepts[local(domain)].setdefault("relationships", []).append(rel)
    doc = {"version": "0.2.0.dev0", "name": "DiabetesMarket",
           "description": "The diabetes-market OWL ontology (https://dgg32.github.io/glp/ontology) as a draft Apache "
                          "Ossie ontology. Generated by scripts/build_osi.py; derivation expressions follow the draft "
                          "expression language and are not checked by any engine.",
           "prefixes": {"dm": str(DM), "skos": str(SKOS)},
           "ontology": list(concepts.values())}
    return doc, skipped


class Dumper(yaml.SafeDumper):
    pass


Dumper.add_representer(str, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", s,
                                                            style='"' if any(c in s for c in ":#{}[]'\n") else None))


def dump(doc, path, header):
    text = yaml.dump(doc, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=110)
    path.write_text(header + text, encoding="utf-8")


def main():
    onto = Ontology()
    defined = onto.defined_classes()
    model = build_model(onto, defined)
    dedupe_synonyms(model)
    check_columns(model)
    OUT.mkdir(exist_ok=True)
    schemas = OUT / "schema"

    osi_doc = osi(model)
    jsonschema.validate(json.loads(json.dumps(osi_doc)), json.loads((schemas / "osi-0.1.1.schema.json").read_text()))
    dump(osi_doc, OUT / "diabetes-market.osi.yaml",
         "# Generated by scripts/build_osi.py from the ontology. Do not edit.\n"
         f"# Apache Ossie (OSI) {OSI_VERSION}, validated against semantic/schema/osi-0.1.1.schema.json.\n")
    layer4, skipped = ontology_layer(onto, defined)
    jsonschema.validate(json.loads(json.dumps(layer4)),
                        json.loads((schemas / "ossie-ontology-0.2.0.dev0-2fd19c7.schema.json").read_text()))
    dump(layer4, OUT / "diabetes-market.ontology.yaml",
         "# Generated by scripts/build_osi.py from ontology/diabetes-market.ttl. Do not edit.\n"
         "# Draft Apache Ossie Layer 4 ontology (0.2.0.dev0, apache/ossie@2fd19c7), validated against\n"
         "# semantic/schema/ossie-ontology-0.2.0.dev0-2fd19c7.schema.json. Snowflake does not read it.\n"
         f"# Not expressed (no rdfs:domain, RDF Data Cube dimensions): {', '.join(skipped)}.\n")
    (OUT / "helper-views.sql").write_text(helper_views(defined, model))
    (OUT / "verified-queries.json").write_text(json.dumps(
        [{"name": n, "source": f"queries/{src}", "onboarding": o, "question": q, "sql": s}
         for n, src, o, q, s in model["verified_queries"]], indent=1, ensure_ascii=False))
    (OUT / "diabetes-market.sql").write_text(native(model))

    n_syn = sum(len(i["synonyms"]) for i in model["datasets"] + model["metrics"]
                + [f for d in model["datasets"] for f in d["fields"]])
    lang_of = {str(l): l.language for l in onto.g.objects(None, RDFS.label)}
    langs = Counter(lang_of.get(s) for i in model["datasets"] + model["metrics"]
                    + [f for d in model["datasets"] for f in d["fields"]] for s in i["synonyms"])
    print(f"{len(model['datasets'])} datasets, {sum(len(d['fields']) for d in model['datasets'])} fields, "
          f"{len(model['relationships'])} relationships, {len(model['metrics'])} metrics, "
          f"{n_syn} synonyms ({dict(langs)}); defined classes: {defined}")
    print(f"Layer 4: {len(layer4['ontology'])} concepts; skipped properties: {skipped}")
    print("wrote semantic/: helper-views.sql, diabetes-market.osi.yaml, diabetes-market.sql, diabetes-market.ontology.yaml")


if __name__ == "__main__":
    main()
