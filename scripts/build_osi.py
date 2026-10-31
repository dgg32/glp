"""Generate the Snowflake semantic layer from the ontology and vocabularies, into semantic/.

Two models: DIABETES_MARKET (Connecticut, Medicare Part D) and JAPAN_MARKET (NDB Open Data), sharing the
VOCAB tables, the class tree and the OWL defined classes.

  helper-views.sql               views the semantic views need (GLP.SEMANTIC): bridge facts for the
                                 many-to-many links, and the OWL defined classes as flags
  diabetes-market.osi.yaml       Apache Ossie (OSI) 0.1.1 semantic model, the interchange format; Snowflake
  japan-market.osi.yaml          compiles it with SYSTEM$CREATE_SEMANTIC_VIEW_FROM_OSSIE_YAML
  diabetes-market.sql            the same models as native CREATE SEMANTIC VIEW statements, with WITH SYNONYMS
  japan-market.sql
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
OSI_VERSION = "0.1.1"
LANGS = ("en", "ja", "zh")
VERIFIED_AT = 1793404800  # 2026-10-31T00:00:00Z, when the verified queries were checked against the graph


def F(name, column, dim=True, term=None, lang=None, values=None, note="", sql=None, time=False):
    """A field. term: the ontology class or property the column holds (labels, definition).
    lang: the column holds the term's label in that language, so only that language's label is a synonym.
    values: (vocabulary CSV, column) whose distinct values are listed in the description.
    sql: expression for the dataset view (source alias s) when the field is not just the column.
    time: a time dimension."""
    return dict(name=name, column=column, dim=dim, term=term, lang=lang, values=values, note=note, sql=sql,
                time=time)


def label_or_english(lang_column, en_column):
    """The SPARQL convention of queries/sglt2-by-japanese-label.rq: the label in the language, else English."""
    return f"COALESCE(s.{lang_column}, s.{en_column})"


THERAPEUTIC_CLASS = dict(
    name="therapeutic_class", source="VOCAB.THERAPEUTIC_CLASS", term="TherapeuticClass", key=["CLASS_ID"], fields=[
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
             "ON d.CLASS_ID = s.CLASS_ID")

US_MAPPING = {
    "view": "DIABETES_MARKET", "file": "diabetes-market", "prefix": "",
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
        THERAPEUTIC_CLASS,
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
US_MAPPING |= {"subject": "Type 2 diabetes drug prescribing", "caveats": CAVEATS, "instructions": INSTRUCTIONS}


def value_fact(name, note=""):
    return F(name, name.upper(), dim=False, note=note)


def jp_facts(name, source, extra_key, extra_fields, description):
    """A fact dataset of JAPAN_MARKET: NDB values at the grain product x care setting [x cell] x therapeutic class."""
    return dict(name=name, source=source, key=["PRODUCT_ID", "CARE_SETTING_ID"] + extra_key + ["CLASS_ID"],
                description=description + " One row per product and therapeutic class of any of its substances, "
                "including all broader classes (skos:broader*): filter or group by one class, or use the *_all "
                "metrics, which count each product once (the top class).", fields=[
        F("product_id", "PRODUCT_ID", note="Product key (receipt code)."),
        F("care_setting_id", "CARE_SETTING_ID", note="outpatient-external (community pharmacy, 院外), "
          "outpatient-internal (dispensed in-house, 院内) or inpatient (入院)."),
        F("class_id", "CLASS_ID", note="Therapeutic class key."),
        *extra_fields,
        value_fact("value_yen", "Quantity times the NHI price, in yen."),
    ])


def jp_company_values(lang):
    """Value list of product.company[_ja]: each corporate group with the names people use for it, its Japanese
    subsidiary first (日本ベーリンガーインゲルハイム -> the Boehringer Ingelheim group)."""
    def values():
        groups = {r["ORGANIZATION_ID"]: r for r in read_rows("US.ORGANIZATION")}
        subsidiaries = {}
        for r in read_rows("JP.ORGANIZATION"):
            if r["CORPORATE_GROUP_ID"]:
                subsidiaries.setdefault(r["CORPORATE_GROUP_ID"], []).append(r)
        out = []
        for gid, subs in sorted(subsidiaries.items()):
            g = groups[gid]
            if lang == "ja":
                name, also = g["NAME_JA"] or g["NAME_EN"], [r["NAME_JA"] for r in subs]
            else:
                name = g["NAME_EN"]
                also = [x for r in subs for x in (r["NAME_EN"], r["NAME_JA"])] + [a for a in g["ALT_NAMES"].split("|") if a]
            out.append(f"{name} (also: {', '.join(dict.fromkeys(a for a in also if a != name))})")
        return out + ["otherwise the marketing authorization holder's own name"]
    return values


CELL_NOTE = "Masked cells are left out, so sums are lower bounds."
JP_MAPPING = {
    "view": "JAPAN_MARKET", "file": "japan-market", "prefix": "JP_", "subject": "Diabetes drugs dispensed in Japan",
    "datasets": [
        jp_facts("national_value", "SEMANTIC.JP_NATIONAL_VALUE_CLASS", [], [
            F("quantity", "TOTAL_QUANTITY", dim=False, term="totalQuantity"),
            value_fact("class_total_value_yen", "The national value of the row's class (all products, all care "
                       "settings), repeated on every row: the denominator of class_market_share."),
            value_fact("market_total_value_yen", "The national value of all diabetes drugs, repeated on every row: the "
                       "denominator of market_share.")],
            "National totals (総計) per product and care setting, FY2024. Use it unless the question is by "
            "prefecture, month or sex and age. Products whose whole row NDB masked are left out."),
        jp_facts("prefecture_value", "SEMANTIC.JP_PREFECTURE_VALUE_CLASS", ["PREFECTURE_CODE"], [
            F("prefecture_code", "PREFECTURE_CODE", note="JIS X 0401 code, 01-47."),
            F("quantity", "QUANTITY", dim=False, term="quantity")],
            "Values by prefecture of the issuing medical institution. " + CELL_NOTE),
        jp_facts("month_value", "SEMANTIC.JP_MONTH_VALUE_CLASS", ["MONTH"], [
            F("month", "MONTH", term="month", time=True, note="First day of the month of care, 2024-04 to 2025-03."),
            F("quantity", "QUANTITY", dim=False, term="quantity"),
            value_fact("generic_quantity", "Quantity of products flagged generic (reimbursement definition), "
                       "else 0. Comparable with quantity within one class only.")],
            "Values by month of care. " + CELL_NOTE),
        jp_facts("sex_age_value", "SEMANTIC.JP_SEX_AGE_VALUE_CLASS", ["SEX_AGE_CODE"], [
            F("sex_age_code", "SEX_AGE_CODE", note="F or M with the band's minimum age, e.g. F75."),
            F("quantity", "QUANTITY", dim=False, term="quantity"),
            value_fact("value_yen_age75plus", "value_yen of patients aged 75 and over (後期高齢者), else 0."),
            value_fact("value_yen_female", "value_yen of female patients, else 0.")],
            "Values by sex and five-year age band of the patient. " + CELL_NOTE),
        dict(name="product", source="SEMANTIC.JP_PRODUCT_PROFILE", term="MedicinalProduct", key=["PRODUCT_ID"],
             description_note="NDB Open Data products at strength level.", fields=[
            F("product_id", "PRODUCT_ID", term="receiptCode"),
            F("product_name_ja", "PRODUCT_NAME_JA", term="MedicinalProduct", lang="ja",
              note="As printed in NDB, with full-width characters, e.g. ジャディアンス錠１０ｍｇ."),
            F("product_name", "PRODUCT_NAME", note="The same name with half-width characters, e.g. ジャディアンス錠10mg."),
            F("yj_code", "YJ_CODE", term="yjCode"),
            F("active_substances", "ACTIVE_SUBSTANCES", term="Substance", lang="en",
              note="Active substances in English, joined with ' + ' for combination products."),
            F("active_substances_ja", "ACTIVE_SUBSTANCES_JA", term="Substance", lang="ja",
              note="Active substances in Japanese, joined with '・'."),
            F("nhi_price", "NHI_PRICE", dim=False, term="nhiPrice"),
            F("dispensing_unit", "DISPENSING_UNIT", term="dispensingUnit"),
            F("route", "ROUTE", term="routeOfAdministration"),
            F("is_generic", "IS_GENERIC", term="isGeneric",
              note="Generics priced like their originator (most metformin 'MT' generics) are not flagged."),
            F("is_originator", "IS_ORIGINATOR", term="isOriginator"),
            F("is_combination", "IS_COMBINATION", term="isCombinationProduct"),
            F("is_sglt2_product", "IS_SGLT2_PRODUCT", term="SGLT2Product"),
            F("is_glp1_product", "IS_GLP1_PRODUCT", term="GLP1Product"),
            F("marketing_authorization_holder", "MAH_NAME", term="manufacturedBy",
              note="Japanese marketing authorization holder in English; NULL for unified-name generics."),
            F("marketing_authorization_holder_ja", "MAH_NAME_JA",
              note="Japanese marketing authorization holder in Japanese, e.g. 日本ベーリンガーインゲルハイム."),
            F("company", "COMPANY", term="partOfCorporateGroup", values=jp_company_values("en"),
              note="For market shares by company: the corporate group (GLEIF ultimate parent, the same company as "
                   "in the US data) where known, else the marketing authorization holder."),
            F("company_ja", "COMPANY_JA", values=jp_company_values("ja"),
              note="The company in Japanese: the corporate group where known, else the holder."),
        ]),
        THERAPEUTIC_CLASS,
        dict(name="jp_drug_class", source="VOCAB.JP_DRUG_CLASS", term="JapaneseDrugClass", key=["JP_CLASS_CODE"],
             description_note="Joined as the product's category. Most GLP-1 drugs are filed under 249, not 396.",
             fields=[
            F("jp_class_code", "JP_CLASS_CODE", note="Three-digit code, e.g. 396."),
            F("jp_class_name", "PREF_LABEL_EN", term="JapaneseDrugClass", lang="en"),
            F("jp_class_name_ja", "PREF_LABEL_JA", term="JapaneseDrugClass", lang="ja",
              values=("JP.PRODUCT", "JP_CLASS_CODE")),
            F("jp_class_name_zh", "PREF_LABEL_ZH", term="JapaneseDrugClass", lang="zh"),
        ]),
        dict(name="prefecture", source="VOCAB.PREFECTURE", term="Prefecture", key=["PREFECTURE_CODE"], fields=[
            F("prefecture_code", "PREFECTURE_CODE", note="JIS X 0401 code, 01-47."),
            F("prefecture_name", "PREF_LABEL_EN", term="Prefecture", lang="en"),
            F("prefecture_name_ja", "PREF_LABEL_JA", term="Prefecture", lang="ja", values=("VOCAB.PREFECTURE", None)),
            F("prefecture_name_zh", "PREF_LABEL_ZH", term="Prefecture", lang="zh"),
        ]),
        dict(name="care_setting", source="VOCAB.CARE_SETTING", term="CareSetting", key=["CARE_SETTING_ID"], fields=[
            F("care_setting_id", "CARE_SETTING_ID", note="Care setting key."),
            F("care_setting_name", "PREF_LABEL_EN", term="CareSetting", lang="en", values=("VOCAB.CARE_SETTING", None)),
            F("care_setting_name_ja", "PREF_LABEL_JA", term="CareSetting", lang="ja", values=("VOCAB.CARE_SETTING", None)),
            F("care_setting_name_zh", "PREF_LABEL_ZH", term="CareSetting", lang="zh"),
        ]),
        dict(name="sex_age_group", source="VOCAB.SEX_AGE_GROUP", term="SexAgeGroup", key=["SEX_AGE_CODE"], fields=[
            F("sex_age_code", "SEX_AGE_CODE", note="F or M with the band's minimum age, e.g. F75."),
            F("sex_age_name", "PREF_LABEL_EN", term="SexAgeGroup", lang="en"),
            F("sex_age_name_ja", "PREF_LABEL_JA", term="SexAgeGroup", lang="ja"),
            F("sex_age_name_zh", "PREF_LABEL_ZH", term="SexAgeGroup", lang="zh"),
            F("sex", "SEX", note="F (female) or M (male)."),
            F("min_age", "MIN_AGE", term="minAge"),
        ]),
    ],
    "relationships": [
        *[(f, to, [c], [c], prop) for f in ("national_value", "prefecture_value", "month_value", "sex_age_value")
          for to, c, prop in (("product", "PRODUCT_ID", "aboutProduct"), ("therapeutic_class", "CLASS_ID", "inTherapeuticClass"),
                              ("care_setting", "CARE_SETTING_ID", "careSetting"))],
        ("prefecture_value", "prefecture", ["PREFECTURE_CODE"], ["PREFECTURE_CODE"], "prefecture"),
        ("sex_age_value", "sex_age_group", ["SEX_AGE_CODE"], ["SEX_AGE_CODE"], "sexAgeGroup"),
        ("product", "jp_drug_class", ["JP_CLASS_CODE"], ["JP_CLASS_CODE"], "inJapaneseDrugClass"),
    ],
    "caveats": "NDB Open Data, 11th release: FY2024 (April 2024 - March 2025), all of Japan, all ages. Quantities "
               "are dispensed tablets, pens or kits, not patients or prescriptions, and cannot be added across "
               "products; values are quantity times the NHI price (price list of 2026-09-02), in yen. Cells below "
               "1,000 (oral) or 400 (injection) are masked. The prefecture is where the claim was issued. No "
               "prescribers or specialties exist for Japan.",
    "instructions": "Answer in yen (value_yen metrics), never by adding quantities across products. The four fact "
                    "datasets are four breakdowns of the same national figures: never combine them; use national_value "
                    "unless the question is by prefecture, month, or sex and age. Every fact row is one product in one "
                    "therapeutic class, broader classes included: for all diabetes drugs use the *_all metrics, which "
                    "count each product once (they handle the top class internally: never filter class_id yourself to "
                    "get all drugs); for a class, filter or group by one class. 'By drug class' means "
                    "therapeutic_class.is_drug_class = TRUE. A class's share of the market: market_share by class. A "
                    "company's market share in a class: class_market_share with product.company and that class (never "
                    "divide by the company's own total). 'Single-ingredient' means NOT product.is_combination. Prefecture, month and "
                    "age figures are lower bounds (masked cells). Names exist in English, Japanese (*_ja) and Chinese "
                    "(*_zh): answer with the names in the language of the question.",
}
MAPPINGS = [US_MAPPING, JP_MAPPING]


class Ontology:
    def __init__(self):
        self.g = Graph()
        self.g.parse(ROOT / "ontology" / "diabetes-market.ttl")
        for v in ("therapeutic-class", "substance", "indication"):
            self.g.parse(ROOT / "vocab" / f"{v}.ttl")

    def labels(self, term, lang=None):
        """rdfs:label, then skos:altLabel (e.g. ATC分類 for dm:TherapeuticClass)."""
        return [str(l) for p in (RDFS.label, SKOS.altLabel) for l in self.g.objects(DM[term], p)
                if lang in (None, l.language)]

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
    if callable(field["values"]):
        return field["values"]()
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
    return {"SEMANTIC.PRODUCT_PROFILE": "US.PRODUCT", "SEMANTIC.PRESCRIBER_PROFILE": "US.PRESCRIBER",
            "SEMANTIC.JP_PRODUCT_PROFILE": "JP.PRODUCT"}.get(d["source"], d["source"])


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


def build_model(onto, defined, mapping):
    """The model in a neutral form both writers use."""
    model = {"name": mapping["view"], "file": mapping["file"], "instructions": mapping["instructions"],
             "top_class": top_class(onto, defined["SGLT2Prescriber"][1]),
             "datasets": [], "relationships": [], "metrics": []}
    model["description"] = (f"{mapping['subject']}, generated from the diabetes-market ontology "
                            f"{onto.g.value(URIRef('https://dgg32.github.io/glp/ontology'), OWL.versionInfo)}. "
                            + mapping["caveats"])
    sglt2, glp1 = defined["SGLT2Prescriber"][1], defined["GLP1Prescriber"][1]
    drug_class_depth = onto.class_depth(sglt2)  # the level the OWL defined classes speak about
    if onto.class_depth(glp1) != drug_class_depth:
        sys.exit("SGLT2 and GLP-1 classes sit at different depths: what is a drug class?")
    # Each dataset reads a view (GLP.SEMANTIC.SV_<NAME>) whose columns carry the logical field names, so the
    # physical names (PREF_LABEL_JA) never appear next to the logical ones (specialty_name_ja): Cortex Analyst
    # mixed them up on 2026-10-31.
    renamed = {}
    for d in mapping["datasets"]:
        desc = d.get("description") or onto.definition(d["term"])
        if d.get("description_note"):
            desc += " " + d["description_note"]
        plain = {f["column"]: f["name"].upper() for f in d["fields"] if f["column"] and not f["sql"]}
        needed = d["key"] + [c for frm, to, fc, tc, _ in mapping["relationships"]
                             for c in (fc if frm == d["name"] else tc if to == d["name"] else [])]
        renamed[d["name"]] = {c: plain.get(c, c) for c in needed}
        view_columns = [((f["sql"] or f"s.{f['column']}").format(drug_class_depth=drug_class_depth), f["name"].upper())
                        for f in d["fields"]]
        view_columns += [(f"s.{c}", c) for c in dict.fromkeys(needed) if c not in plain]
        model["datasets"].append({
            "name": d["name"], "source": f"{DB}.SEMANTIC.SV_{mapping['prefix']}{d['name'].upper()}",
            "physical": f"{DB}.{d['source']}",
            "joins": d.get("joins", ""), "view_columns": view_columns,
            "key": [renamed[d["name"]][c] for c in d["key"]], "description": desc,
            "synonyms": [s for s in onto.labels(d["term"]) if s.lower().replace(" ", "_") != d["name"]] if d.get("term") else [],
            "term": d.get("term"),
            "fields": [{"name": f["name"], "column": f["name"].upper(), "dim": f["dim"], "time": f["time"], "term": f["term"],
                        "description": describe(onto, d, f), "synonyms": synonyms(onto, f)} for f in d["fields"]]})
    for frm, to, fc, tc, prop in mapping["relationships"]:
        model["relationships"].append({"name": f"{frm}_to_{to}", "from": frm, "to": to,
                                       "from_columns": [renamed[frm][c] for c in fc],
                                       "to_columns": [renamed[to][c] for c in tc]})
    metrics, model["verified_queries"] = (us_metrics if mapping is US_MAPPING else jp_metrics)(onto, sglt2, glp1)
    model["metrics"] = [{"name": n, "expression": e, "description": (onto.definition(t) + " " + d).strip() if t else d,
                         "synonyms": onto.labels(t) if t else []} for n, e, t, d in metrics]
    return model


def us_metrics(onto, sglt2, glp1):
    """Metrics and verified queries of DIABETES_MARKET."""
    share = (f"CASE WHEN prescription_class.class_id = '{{c}}' THEN prescription_class.claims ELSE 0 END")
    metrics = [
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
    # The business questions of queries/*.rq (US part) as verified queries: the SPARQL query catalog becomes the
    # Analyst's answer key. {view} is filled per deployment; deploy_semantic_view.py checks their results.
    sglt2_ja = pref_label(onto, sglt2, "ja")
    verified = [
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
    return metrics, verified


def pref_label(onto, cls, lang):
    return next(str(l) for l in onto.g.objects(DMTC[cls], SKOS.prefLabel) if l.language == lang)


# The classes the Japan queries (queries/jp-*.rq) compare: insulins as one class, the blood glucose lowering classes.
JP_CLASSES = ["Insulin", "Biguanide", "Sulfonylurea", "Thiazolidinedione", "DPP4Inhibitor", "AlphaGlucosidaseInhibitor",
              "Glinide", "Glimin", "SGLT2Inhibitor", "GLP1ReceptorAgonist"]
GENERIC_CLASSES = ["Biguanide", "Sulfonylurea", "Thiazolidinedione", "DPP4Inhibitor", "AlphaGlucosidaseInhibitor",
                   "Glinide"]


def top_class(onto, cls):
    """The top of the class tree above cls."""
    return local(next(c for c in onto.g.transitive_objects(DMTC[cls], SKOS.broader) if onto.g.value(c, SKOS.broader) is None))


def jp_metrics(onto, sglt2, glp1):
    """Metrics and verified queries of JAPAN_MARKET. Every fact row is a product in one class with all broader
    classes, so the top of the class tree (every product reaches it exactly once, checked by export_snowflake.py)
    gives the all-drug totals."""
    top = top_class(onto, sglt2)
    top_name = pref_label(onto, top, "en").lower()

    def when(ds, cls, col="value_yen"):
        return f"CASE WHEN {ds}.class_id = '{cls}' THEN {ds}.{col} END"

    metrics = [
        ("total_value_yen", f"SUM({when('national_value', top)})", None,
         f"Value in yen of all {top_name}, each product counted once (national totals)."),
        ("class_value_yen", "SUM(national_value.value_yen)", None,
         "Value in yen of the products in a therapeutic class (including narrower classes), national totals. Filter or "
         "group by one class; a combination product counts in each of its classes."),
        ("class_market_share", "SUM(national_value.value_yen) / NULLIF(MAX(national_value.class_total_value_yen), 0)", None,
         "Share (0 to 1) of the class's national value, for one class at a time. Grouped or filtered by product.company "
         "it is the company's market share in the class: the denominator stays the whole class whatever the filter on "
         "products or companies (it covers all care settings)."),
        ("market_share", "SUM(national_value.value_yen) / NULLIF(MAX(national_value.market_total_value_yen), 0)", None,
         f"Share (0 to 1) of the national value of all {top_name}, whatever the filter on classes, products or "
         "companies (it covers all care settings). By class: a class's share of the market."),
        ("product_count", "COUNT(DISTINCT product.product_id)", None, "Number of distinct products (strength level)."),
        ("prefecture_value_yen_all", f"SUM({when('prefecture_value', top)})", None,
         f"Value in yen of all {top_name} by prefecture, each product counted once."),
        ("prefecture_class_value_yen", "SUM(prefecture_value.value_yen)", None,
         "Value in yen of a therapeutic class by prefecture. Filter or group by one class."),
        ("prefecture_sglt2_value_share",
         f"SUM({when('prefecture_value', sglt2)}) / NULLIF(SUM({when('prefecture_value', top)}), 0)", None,
         f"Share (0 to 1) of {pref_label(onto, sglt2, 'en')} in the value of all {top_name} (from the definition of "
         "dm:SGLT2Product: products with an SGLT2 inhibitor, alone or in combination)."),
        ("month_value_yen_all", f"SUM({when('month_value', top)})", None,
         f"Value in yen of all {top_name} by month, each product counted once."),
        ("month_class_value_yen", "SUM(month_value.value_yen)", None,
         "Value in yen of a therapeutic class by month. Filter or group by one class."),
        ("month_generic_quantity_share", "SUM(month_value.generic_quantity) / NULLIF(SUM(month_value.quantity), 0)",
         None, "Generic share (0 to 1) of the dispensed quantity. Meaningful within one class only; group or filter by "
               "class and month."),
        ("age_value_yen_all", f"SUM({when('sex_age_value', top)})", None,
         f"Value in yen of all {top_name} by sex and age band, each product counted once."),
        ("age_class_value_yen", "SUM(sex_age_value.value_yen)", None,
         "Value in yen of a therapeutic class by sex and age band. Filter or group by one class."),
        ("age_75plus_value_share",
         "SUM(sex_age_value.value_yen_age75plus) / NULLIF(SUM(sex_age_value.value_yen), 0)", None,
         "Share (0 to 1) of the value dispensed to patients aged 75 and over (後期高齢者)."),
        ("female_value_share", "SUM(sex_age_value.value_yen_female) / NULLIF(SUM(sex_age_value.value_yen), 0)", None,
         "Share (0 to 1) of the value dispensed to female patients."),
    ]
    in_list = lambda ids: ", ".join(f"'{c}'" for c in ids)  # noqa: E731
    glp1_product_ja = next(str(l) for l in onto.g.objects(DM.GLP1Product, RDFS.label) if l.language == "ja")
    verified = [
        ("jp_class_share_yen", "jp-class-share-yen.rq", True,
         "What share of Japan's diabetes drug value does each drug class have, for single-ingredient products?",
         "SELECT * FROM SEMANTIC_VIEW({view} DIMENSIONS therapeutic_class.class_name METRICS class_value_yen, market_share "
         f"WHERE therapeutic_class.class_id IN ({in_list(JP_CLASSES)}) AND NOT product.is_combination) "
         "ORDER BY class_value_yen DESC"),
        ("jp_company_share_sglt2_dpp4", "jp-boehringer-share-by-class.rq", True,
         "Which companies lead the SGLT2 inhibitor and DPP-4 inhibitor markets in Japan by value?",
         "SELECT * FROM SEMANTIC_VIEW({view} DIMENSIONS therapeutic_class.class_name, product.company "
         f"METRICS class_value_yen, class_market_share WHERE therapeutic_class.class_id IN ('{sglt2}', 'DPP4Inhibitor')) "
         "ORDER BY class_name, class_value_yen DESC"),
        ("jp_age_profile_by_class", "jp-age-profile-by-class.rq", False,
         "What share of each drug class's value goes to patients aged 75 and over, and to women?",
         "SELECT * FROM SEMANTIC_VIEW({view} DIMENSIONS therapeutic_class.class_name METRICS age_class_value_yen, "
         f"age_75plus_value_share, female_value_share WHERE therapeutic_class.class_id IN ({in_list(JP_CLASSES)})) "
         "ORDER BY age_75plus_value_share DESC"),
        ("jp_generic_share_by_month", "jp-generic-share-by-month.rq", False,
         "長期収載品の選定療養が始まった2024年10月の前後で、院外処方の後発品の割合は薬効群ごとに毎月どう変わった？",
         "SELECT * FROM SEMANTIC_VIEW({view} DIMENSIONS therapeutic_class.class_name, month_value.month METRICS "
         "month_generic_quantity_share WHERE month_value.care_setting_id = 'outpatient-external' AND NOT "
         f"product.is_combination AND therapeutic_class.class_id IN ({in_list(GENERIC_CLASSES)})) ORDER BY class_name, month"),
        ("jp_glp1_monthly_uptake", "jp-glp1-monthly-uptake.rq", False,
         "How did the monthly value of each GLP-1 receptor agonist substance develop in Japan?",
         "SELECT * FROM SEMANTIC_VIEW({view} DIMENSIONS month_value.month, product.active_substances METRICS "
         f"month_class_value_yen WHERE therapeutic_class.class_id = '{glp1}' AND NOT product.is_combination) "
         "ORDER BY month, month_class_value_yen DESC"),
        ("jp_sglt2_share_by_prefecture", "jp-sglt2-share-by-prefecture.rq", True,
         f"都道府県別の{pref_label(onto, sglt2, 'ja')}のシェアは？",
         "SELECT * FROM SEMANTIC_VIEW({view} DIMENSIONS prefecture.prefecture_name_ja METRICS "
         "prefecture_sglt2_value_share, prefecture_value_yen_all) ORDER BY prefecture_sglt2_value_share DESC"),
        ("jp_glp1_products_by_category", "jp-glp1-by-japanese-category-reasoning.rq", False,
         f"{glp1_product_ja}は薬効分類ごとにいくつある？",
         "SELECT * FROM SEMANTIC_VIEW({view} DIMENSIONS jp_drug_class.jp_class_name_ja METRICS product_count "
         "WHERE product.is_glp1_product) ORDER BY product_count DESC"),
    ]
    return metrics, verified


def dedupe_synonyms(model):
    """Synonyms must point at one thing. A label used several times stays with the first owner: metrics (what
    people ask for), then fields (what they group by), then datasets. Returns the labels that two different
    ontology terms share (a label collision in the ontology, not just a column and its dataset)."""
    owner, collisions = {}, []
    for item in model["metrics"] + [f for d in model["datasets"] for f in d["fields"]] + model["datasets"]:
        kept = []
        for s in item["synonyms"]:
            if s.lower() not in owner:
                owner[s.lower()] = item
                kept.append(s)
            elif owner[s.lower()].get("term") not in (None, item.get("term")):
                collisions.append(f"{s} ({owner[s.lower()]['name']}, not {item['name']})")
        item["synonyms"] = kept
    return collisions


JP_FACT_VIEWS = {  # view: (cell columns, extra facts); every one also has the product, setting and class keys
    "JP_NATIONAL_VALUE_CLASS": ([], ["TOTAL_QUANTITY", "CLASS_TOTAL_VALUE_YEN", "MARKET_TOTAL_VALUE_YEN"]),
    "JP_PREFECTURE_VALUE_CLASS": (["PREFECTURE_CODE"], ["QUANTITY"]),
    "JP_MONTH_VALUE_CLASS": (["MONTH"], ["QUANTITY", "GENERIC_QUANTITY"]),
    "JP_SEX_AGE_VALUE_CLASS": (["SEX_AGE_CODE"], ["QUANTITY", "VALUE_YEN_AGE75PLUS", "VALUE_YEN_FEMALE"]),
}
JP_PROFILE_COLUMNS = ["IS_GLP1_PRODUCT", "IS_SGLT2_PRODUCT", "ACTIVE_SUBSTANCES", "ACTIVE_SUBSTANCES_JA", "MAH_NAME",
                      "MAH_NAME_JA", "COMPANY", "COMPANY_JA"]


def check_columns(model):
    tables = {t["name"]: [c.split()[0] for c in t["columns"]]
              for t in json.loads((EXPORT / "tables.json").read_text())["tables"]}
    views = {**{f"SEMANTIC.{v}": ["PRODUCT_ID", "CARE_SETTING_ID", "CLASS_ID", *cells, *facts, "VALUE_YEN"]
                for v, (cells, facts) in JP_FACT_VIEWS.items()},
             "SEMANTIC.JP_PRODUCT_PROFILE": tables["JP.PRODUCT"] + JP_PROFILE_COLUMNS,"SEMANTIC.PRESCRIPTION_CLASS": ["PRESCRIPTION_ID", "CLASS_ID", "TOTAL_CLAIMS", "TOTAL_30DAY_FILLS", "TOTAL_DRUG_COST"],
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


def helper_views(defined, models):
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
""" + jp_helper_views(flags["MedicinalProduct"], product_cols, models[0]["top_class"]) + """
-- One view per dataset of the semantic views, with the logical field names as column names.
""" + "\n".join(
        f"CREATE OR REPLACE VIEW {d['source']}\n"
        f"  COMMENT = {sql_string('Dataset ' + d['name'] + ' of the semantic view ' + m['name'] + '.')}\n"
        f"AS SELECT {', '.join(f'{expr} AS {name}' for expr, name in d['view_columns'])}\n"
        f"FROM {d['physical']} s{(' ' + d['joins']) if d['joins'] else ''};\n" for m in models for d in m["datasets"])


def jp_helper_views(product_flags, product_cols, top):
    """JAPAN_MARKET: the product profile (defined-class flags, substances, company) and one fact view per RDF Data
    Cube breakdown at the grain product x setting [x cell] x class, with the value in yen."""
    s = f"{DB}.SEMANTIC"
    cell_sql = {"JP_PREFECTURE_VALUE_CLASS": ("prefecture", ""), "JP_MONTH_VALUE_CLASS": (
        "month", ", IFF(p.IS_GENERIC, q.QUANTITY, 0) AS GENERIC_QUANTITY"), "JP_SEX_AGE_VALUE_CLASS": (
        "sex-age", ", IFF(g.MIN_AGE >= 75, q.QUANTITY * p.NHI_PRICE, 0) AS VALUE_YEN_AGE75PLUS"
                   ", IFF(g.SEX = 'F', q.QUANTITY * p.NHI_PRICE, 0) AS VALUE_YEN_FEMALE")}
    out = f"""
-- JAPAN_MARKET. Unified-name generics have no marketing authorization holder.
CREATE OR REPLACE VIEW {s}.JP_PRODUCT_PROFILE
  COMMENT = 'JP.PRODUCT with the OWL defined classes as flags, its substances and its company (corporate group, else holder).'
AS SELECT d.*, {", ".join(f"COALESCE(f.{c}, FALSE) AS {c}" for c in product_cols)},
       sub.ACTIVE_SUBSTANCES, sub.ACTIVE_SUBSTANCES_JA, m.NAME_EN AS MAH_NAME, m.NAME_JA AS MAH_NAME_JA,
       COALESCE(g.NAME_EN, m.NAME_EN, '(no single holder: unified-name generic)') AS COMPANY,
       COALESCE(g.NAME_JA, m.NAME_JA, '（統一名収載の後発品）') AS COMPANY_JA
FROM {DB}.JP.PRODUCT d
LEFT JOIN (SELECT pc.PRODUCT_ID, {", ".join(product_flags)}
           FROM {DB}.JP.PRODUCT_CLASS pc GROUP BY pc.PRODUCT_ID) f ON f.PRODUCT_ID = d.PRODUCT_ID
LEFT JOIN (SELECT ps.PRODUCT_ID,
                  LISTAGG(v.PREF_LABEL_EN, ' + ') WITHIN GROUP (ORDER BY v.PREF_LABEL_EN) AS ACTIVE_SUBSTANCES,
                  LISTAGG(COALESCE(v.PREF_LABEL_JA, v.PREF_LABEL_EN), '・') WITHIN GROUP (ORDER BY v.PREF_LABEL_EN)
                    AS ACTIVE_SUBSTANCES_JA
           FROM {DB}.JP.PRODUCT_SUBSTANCE ps JOIN {DB}.VOCAB.SUBSTANCE v ON v.SUBSTANCE_ID = ps.SUBSTANCE_ID
           GROUP BY ps.PRODUCT_ID) sub ON sub.PRODUCT_ID = d.PRODUCT_ID
LEFT JOIN {DB}.JP.ORGANIZATION m ON m.ORGANIZATION_ID = d.ORGANIZATION_ID
LEFT JOIN {DB}.US.ORGANIZATION g ON g.ORGANIZATION_ID = m.CORPORATE_GROUP_ID;

CREATE OR REPLACE VIEW {s}.JP_NATIONAL_VALUE_CLASS
  COMMENT = 'National totals x therapeutic class (JP.PRODUCT_CLASS), with the value in yen and the class and market totals as share denominators; masked totals left out.'
AS SELECT t.PRODUCT_ID, t.CARE_SETTING_ID, pc.CLASS_ID, t.TOTAL_QUANTITY, t.TOTAL_QUANTITY * p.NHI_PRICE AS VALUE_YEN,
       SUM(t.TOTAL_QUANTITY * p.NHI_PRICE) OVER (PARTITION BY pc.CLASS_ID) AS CLASS_TOTAL_VALUE_YEN,
       SUM(IFF(pc.CLASS_ID = '{top}', t.TOTAL_QUANTITY * p.NHI_PRICE, 0)) OVER () AS MARKET_TOTAL_VALUE_YEN
FROM {DB}.JP.NATIONAL_TOTAL t JOIN {DB}.JP.PRODUCT p ON p.PRODUCT_ID = t.PRODUCT_ID
JOIN {DB}.JP.PRODUCT_CLASS pc ON pc.PRODUCT_ID = t.PRODUCT_ID
WHERE NOT t.IS_MASKED;
"""
    for view, (breakdown, extra) in cell_sql.items():
        cells, _ = JP_FACT_VIEWS[view]
        out += f"""
CREATE OR REPLACE VIEW {s}.{view}
  COMMENT = 'NDB cells of the {breakdown} breakdown x therapeutic class, with the value in yen; masked cells left out.'
AS SELECT q.PRODUCT_ID, q.CARE_SETTING_ID, {", ".join(f"q.{c}" for c in cells)}, pc.CLASS_ID, q.QUANTITY,
       q.QUANTITY * p.NHI_PRICE AS VALUE_YEN{extra}
FROM {DB}.JP.QUANTITY q JOIN {DB}.JP.PRODUCT p ON p.PRODUCT_ID = q.PRODUCT_ID
JOIN {DB}.JP.PRODUCT_CLASS pc ON pc.PRODUCT_ID = q.PRODUCT_ID
{"LEFT JOIN " + DB + ".VOCAB.SEX_AGE_GROUP g ON g.SEX_AGE_CODE = q.SEX_AGE_CODE" + chr(10) if breakdown == "sex-age" else ""}WHERE q.BREAKDOWN = '{breakdown}' AND NOT q.IS_MASKED;
"""
    return out


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
                                 **({"dimension": {"is_time": f["time"]}} if f["dim"] else {}),
                                 **({"description": f["description"]} if f["description"] else {})}, f["synonyms"])
                  for f in d["fields"]]
        datasets.append(with_synonyms({"name": d["name"], "source": d["source"], "primary_key": d["key"],
                                       "description": d["description"], "fields": fields}, d["synonyms"]))
    metrics = [with_synonyms({"name": m["name"], "expression": ansi(m["expression"]),
                              **({"description": m["description"]} if m["description"] else {})}, m["synonyms"])
               for m in model["metrics"]]
    return {"version": OSI_VERSION, "semantic_model": [{
        "name": model["name"] + "_OSI", "description": model["description"], "ai_context": model["instructions"],
        "datasets": datasets, "relationships": model["relationships"], "metrics": metrics,
        # The layout SYSTEM$READ_OSSIE_YAML_FROM_SEMANTIC_VIEW itself exports for instructions and verified queries.
        "custom_extensions": [{"vendor_name": "SNOWFLAKE", "data": json.dumps({
            "module_custom_instructions": {"sql_generation": model["instructions"]},
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
            + f"\n  AI_SQL_GENERATION {sql_string(model['instructions'])}"
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
    models = [build_model(onto, defined, m) for m in MAPPINGS]
    OUT.mkdir(exist_ok=True)
    schemas = OUT / "schema"
    lang_of = {str(l): l.language for p in (RDFS.label, SKOS.altLabel) for l in onto.g.objects(None, p)}
    for model in models:
        if collisions := dedupe_synonyms(model):
            print(f"{model['name']}: WARNING, ontology terms share a label, kept by the first owner: {'; '.join(collisions)}")
        check_columns(model)
        osi_doc = osi(model)
        jsonschema.validate(json.loads(json.dumps(osi_doc)), json.loads((schemas / "osi-0.1.1.schema.json").read_text()))
        dump(osi_doc, OUT / f"{model['file']}.osi.yaml",
             "# Generated by scripts/build_osi.py from the ontology. Do not edit.\n"
             f"# Apache Ossie (OSI) {OSI_VERSION}, validated against semantic/schema/osi-0.1.1.schema.json.\n")
        (OUT / f"{model['file']}.sql").write_text(native(model))
        items = model["datasets"] + model["metrics"] + [f for d in model["datasets"] for f in d["fields"]]
        langs = Counter(lang_of.get(s) for i in items for s in i["synonyms"])
        print(f"{model['name']}: {len(model['datasets'])} datasets, {sum(len(d['fields']) for d in model['datasets'])} "
              f"fields, {len(model['relationships'])} relationships, {len(model['metrics'])} metrics, "
              f"{sum(langs.values())} synonyms ({dict(langs)}), {len(model['verified_queries'])} verified queries")
    layer4, skipped = ontology_layer(onto, defined)
    jsonschema.validate(json.loads(json.dumps(layer4)),
                        json.loads((schemas / "ossie-ontology-0.2.0.dev0-2fd19c7.schema.json").read_text()))
    dump(layer4, OUT / "diabetes-market.ontology.yaml",
         "# Generated by scripts/build_osi.py from ontology/diabetes-market.ttl. Do not edit.\n"
         "# Draft Apache Ossie Layer 4 ontology (0.2.0.dev0, apache/ossie@2fd19c7), validated against\n"
         "# semantic/schema/ossie-ontology-0.2.0.dev0-2fd19c7.schema.json. Snowflake does not read it.\n"
         f"# Not expressed (no rdfs:domain, RDF Data Cube dimensions): {', '.join(skipped)}.\n")
    (OUT / "helper-views.sql").write_text(helper_views(defined, models))
    (OUT / "verified-queries.json").write_text(json.dumps(
        [{"view": m["name"], "name": n, "source": f"queries/{src}", "onboarding": o, "question": q, "sql": s}
         for m in models for n, src, o, q, s in m["verified_queries"]], indent=1, ensure_ascii=False))
    print(f"defined classes: {defined}")
    print(f"Layer 4: {len(layer4['ontology'])} concepts; skipped properties: {skipped}")
    print("wrote semantic/: helper-views.sql, " + ", ".join(f"{m['file']}.osi.yaml, {m['file']}.sql" for m in models)
          + ", diabetes-market.ontology.yaml, verified-queries.json")


if __name__ == "__main__":
    main()
