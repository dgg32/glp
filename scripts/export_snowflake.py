"""Export the knowledge graph (Connecticut and Japan) as relational tables for Snowflake, into data/snowflake/.

Each table is one SPARQL SELECT over the generated graphs, read only from the table's source graphs, so the
tables are projections of the validated knowledge graph, not a second pipeline next to it: same pseudonyms,
same manufacturer links, same class tree. Schemas mirror the named graphs: VOCAB holds the shared SKOS
vocabularies, US the Medicare Part D data and the products and companies it refers to, JP the NDB Open Data
products and the RDF Data Cube flattened to one row per cell (masked cells kept, with IS_MASKED).

What SQL cannot do the export materializes, and says so in the table comment:
  VOCAB.CLASS_ANCESTOR, VOCAB.SPECIALTY_ANCESTOR  skos:broader* as (concept, ancestor) pairs, self included
  US.PRODUCT_CLASS, JP.PRODUCT_CLASS               hasActiveSubstance/inTherapeuticClass/broader*, distinct
The OWL defined classes (SGLT2Prescriber, GLP1Product, ...) are not exported; the semantic views derive them.

Checks before anything is written to tables.json (scripts/load_snowflake.py loads nothing without it):
  1. gate      data/rdf passed scripts/check_local.py (same provenance hash)
  2. keys      primary keys unique, NOT NULL columns filled
  3. refs      every foreign key resolves
  4. counts    22,034 prescriptions, 3,896 prescribers, 51 products; 510 Japanese products, 150,288 cells
  5. parity    queries/sglt2-vs-glp1-by-specialty.rq and cost-per-claim-by-class.rq, run on the graph,
               give the same numbers as the same questions computed from the exported tables; the graph
               results go into tables.json as the expectations for scripts/deploy_semantic_view.py, together
               with the results of every queries/jp-*.rq (checked in Snowflake, through the semantic views)

Privacy: as in data/rdf, no names and no NPIs; prescribers are the HMAC pseudonyms of build_rdf.py.
data/snowflake/ is gitignored for the same reason as data/rdf/ (re-identifiable by joining with CMS).

Usage: .venv/bin/python scripts/export_snowflake.py
"""
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pyoxigraph as ox

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_stardog import provenance_digest, require_local_check  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "snowflake"
BASE = "https://dgg32.github.io/glp/"
GRAPHS = ["vocab/therapeutic-class", "vocab/substance", "vocab/indication", "vocab/nucc-specialty",
          "products", "cms-partd-2024", "npi-registry", "drugsfda",
          "vocab/jp-drug-class", "vocab/jp-prefecture", "vocab/ndb-dimensions", "ndb-products", "ndb-2024"]
# IRI namespaces whose local part becomes the table key (the Japanese ones first: they are nested)
ID_BASES = [BASE + p for p in ("data/product/jp/", "data/organization/jp/", "data/ndb/key/",
                               "data/rx/", "data/hcp/", "data/product/", "data/organization/",
                               "vocab/therapeutic-class/", "vocab/substance/", "vocab/indication/",
                               "vocab/specialty/", "vocab/jp-drug-class/", "vocab/prefecture/",
                               "vocab/care-setting/", "vocab/sex-age/")]
EXPECTED_ROWS = {"US.PRESCRIPTION": 22_034, "US.PRESCRIBER": 3_896, "US.PRODUCT": 51,
                 "JP.PRODUCT": 510, "JP.QUANTITY": 150_288}

PREFIXES = """PREFIX dm: <https://dgg32.github.io/glp/ontology#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX qb: <http://purl.org/linked-data/cube#>
PREFIX sdmx-attribute: <http://purl.org/linked-data/sdmx/2009/attribute#>
"""


def labels(var, prop="skos:prefLabel"):
    return "\n".join(f'OPTIONAL {{ {var} {prop} ?{lang} FILTER(lang(?{lang}) = "{lang}") }}'
                     for lang in ("en", "ja", "zh"))


def code(var, match, base, out):
    return f'OPTIONAL {{ {var} {match} ?{out}_ FILTER(STRSTARTS(STR(?{out}_), "{base}")) ' \
           f'BIND(STRAFTER(STR(?{out}_), "{base}") AS ?{out}) }}'


ATC, RXNORM, MESH = ("http://purl.bioontology.org/ontology/ATC/", "http://purl.bioontology.org/ontology/RXNORM/",
                     "http://id.nlm.nih.gov/mesh/")

# Columns are Snowflake DDL; the SELECT returns them in the same order.
TABLES = [
    dict(name="VOCAB.THERAPEUTIC_CLASS", graphs=["vocab/therapeutic-class"],
         comment="SKOS therapeutic class scheme (ATC-based tree): one row per skos:Concept.",
         columns=["CLASS_ID VARCHAR NOT NULL", "IRI VARCHAR NOT NULL", "PREF_LABEL_EN VARCHAR NOT NULL",
                  "PREF_LABEL_JA VARCHAR", "PREF_LABEL_ZH VARCHAR", "NOTATION VARCHAR",
                  "BROADER_CLASS_ID VARCHAR", "DEFINITION_EN VARCHAR"],
         key=["CLASS_ID"], refs={"BROADER_CLASS_ID": "VOCAB.THERAPEUTIC_CLASS"},
         query=f"""SELECT ?c (?c AS ?iri) ?en ?ja ?zh ?notation ?broader ?def WHERE {{
  ?c a dm:TherapeuticClass .
  {labels("?c")}
  OPTIONAL {{ ?c skos:notation ?notation }}
  OPTIONAL {{ ?c skos:broader ?broader }}
  OPTIONAL {{ ?c skos:definition ?def FILTER(lang(?def) = "en") }} }}"""),
    dict(name="VOCAB.CLASS_ANCESTOR", graphs=["vocab/therapeutic-class"],
         comment="skos:broader* materialized: (class, ancestor) pairs, each class is its own ancestor.",
         columns=["CLASS_ID VARCHAR NOT NULL", "ANCESTOR_CLASS_ID VARCHAR NOT NULL"],
         key=["CLASS_ID", "ANCESTOR_CLASS_ID"],
         refs={"CLASS_ID": "VOCAB.THERAPEUTIC_CLASS", "ANCESTOR_CLASS_ID": "VOCAB.THERAPEUTIC_CLASS"},
         query="SELECT DISTINCT ?c ?a WHERE { ?c a dm:TherapeuticClass ; skos:broader* ?a . ?a a dm:TherapeuticClass }"),
    dict(name="VOCAB.SUBSTANCE", graphs=["vocab/substance"],
         comment="SKOS substance scheme, shared by the US and Japan data. ATC_CODES is |-separated (insulins have one code per formulation).",
         columns=["SUBSTANCE_ID VARCHAR NOT NULL", "IRI VARCHAR NOT NULL", "PREF_LABEL_EN VARCHAR NOT NULL",
                  "PREF_LABEL_JA VARCHAR", "PREF_LABEL_ZH VARCHAR", "CLASS_ID VARCHAR", "ATC_CODES VARCHAR",
                  "RXCUI VARCHAR", "MESH_ID VARCHAR"],
         key=["SUBSTANCE_ID"], refs={"CLASS_ID": "VOCAB.THERAPEUTIC_CLASS"},
         query=f"""SELECT ?s (?s AS ?iri) ?en ?ja ?zh ?cls
  (GROUP_CONCAT(DISTINCT ?atc; separator="|") AS ?atcs) (GROUP_CONCAT(DISTINCT ?rxcui; separator="|") AS ?rxcuis)
  (GROUP_CONCAT(DISTINCT ?mesh; separator="|") AS ?meshs) WHERE {{
  ?s a dm:Substance .
  {labels("?s")}
  OPTIONAL {{ ?s dm:inTherapeuticClass ?cls }}
  {code("?s", "skos:exactMatch", ATC, "atc")}
  {code("?s", "skos:exactMatch", RXNORM, "rxcui")}
  {code("?s", "skos:exactMatch", MESH, "mesh")} }}
GROUP BY ?s ?en ?ja ?zh ?cls"""),
    dict(name="VOCAB.INDICATION", graphs=["vocab/indication"],
         comment="SKOS indication scheme (MeSH-based).",
         columns=["INDICATION_ID VARCHAR NOT NULL", "IRI VARCHAR NOT NULL", "PREF_LABEL_EN VARCHAR NOT NULL",
                  "PREF_LABEL_JA VARCHAR", "PREF_LABEL_ZH VARCHAR", "MESH_ID VARCHAR"],
         key=["INDICATION_ID"], refs={},
         query=f"""SELECT ?i (?i AS ?iri) ?en ?ja ?zh (GROUP_CONCAT(DISTINCT ?mesh; separator="|") AS ?meshs) WHERE {{
  ?i a dm:Indication .
  {labels("?i")}
  {code("?i", "skos:exactMatch|skos:closeMatch", MESH, "mesh")} }}
GROUP BY ?i ?en ?ja ?zh"""),
    dict(name="VOCAB.SPECIALTY", graphs=["vocab/nucc-specialty"],
         comment="NUCC Health Care Provider Taxonomy as a SKOS concept scheme.",
         columns=["SPECIALTY_CODE VARCHAR NOT NULL", "IRI VARCHAR NOT NULL", "PREF_LABEL_EN VARCHAR NOT NULL",
                  "PREF_LABEL_JA VARCHAR", "PREF_LABEL_ZH VARCHAR", "BROADER_SPECIALTY_CODE VARCHAR",
                  "DEFINITION_EN VARCHAR"],
         key=["SPECIALTY_CODE"], refs={"BROADER_SPECIALTY_CODE": "VOCAB.SPECIALTY"},
         query=f"""SELECT ?sp (?sp AS ?iri) ?en ?ja ?zh ?broader ?def WHERE {{
  ?sp a dm:Specialty .
  {labels("?sp")}
  OPTIONAL {{ ?sp skos:broader ?broader }}
  OPTIONAL {{ ?sp skos:definition ?def FILTER(lang(?def) = "en") }} }}"""),
    dict(name="VOCAB.SPECIALTY_ANCESTOR", graphs=["vocab/nucc-specialty"],
         comment="skos:broader* materialized: (specialty, ancestor) pairs, each specialty is its own ancestor.",
         columns=["SPECIALTY_CODE VARCHAR NOT NULL", "ANCESTOR_SPECIALTY_CODE VARCHAR NOT NULL"],
         key=["SPECIALTY_CODE", "ANCESTOR_SPECIALTY_CODE"],
         refs={"SPECIALTY_CODE": "VOCAB.SPECIALTY", "ANCESTOR_SPECIALTY_CODE": "VOCAB.SPECIALTY"},
         query="SELECT DISTINCT ?s ?a WHERE { ?s a dm:Specialty ; skos:broader* ?a . ?a a dm:Specialty }"),
    dict(name="VOCAB.JP_DRUG_CLASS", graphs=["vocab/jp-drug-class"],
         comment="Japan's therapeutic categories (薬効分類, Japan Standard Commodity Classification) as a SKOS scheme.",
         columns=["JP_CLASS_CODE VARCHAR NOT NULL", "IRI VARCHAR NOT NULL", "PREF_LABEL_EN VARCHAR NOT NULL",
                  "PREF_LABEL_JA VARCHAR NOT NULL", "PREF_LABEL_ZH VARCHAR", "BROADER_JP_CLASS_CODE VARCHAR"],
         key=["JP_CLASS_CODE"], refs={"BROADER_JP_CLASS_CODE": "VOCAB.JP_DRUG_CLASS"},
         query=f"""SELECT ?c (?c AS ?iri) ?en ?ja ?zh ?broader WHERE {{
  ?c a dm:JapaneseDrugClass .
  {labels("?c")}
  OPTIONAL {{ ?c skos:broader ?broader }} }}"""),
    dict(name="VOCAB.JP_CLASS_MATCH", graphs=["vocab/jp-drug-class"],
         comment="The computed crosswalk 薬効分類 -> ATC-based class tree (skos:exactMatch, narrowMatch, broadMatch, "
                 "relatedMatch), with the product counts that justify each link (skos:editorialNote).",
         columns=["JP_CLASS_CODE VARCHAR NOT NULL", "MATCH_TYPE VARCHAR NOT NULL", "CLASS_ID VARCHAR NOT NULL",
                  "EVIDENCE VARCHAR"],
         key=["JP_CLASS_CODE", "CLASS_ID"],
         refs={"JP_CLASS_CODE": "VOCAB.JP_DRUG_CLASS", "CLASS_ID": "VOCAB.THERAPEUTIC_CLASS"},
         query=f"""SELECT ?c ?type ?cls ?note WHERE {{
  VALUES (?p ?type) {{ (skos:exactMatch "exact") (skos:narrowMatch "narrow") (skos:broadMatch "broad")
                      (skos:relatedMatch "related") }}
  ?c a dm:JapaneseDrugClass ; ?p ?cls .
  OPTIONAL {{ ?c skos:editorialNote ?note
             FILTER(STRSTARTS(STR(?note), CONCAT(?type, "Match ", STRAFTER(STR(?cls), "{BASE}vocab/therapeutic-class/"), ":"))) }} }}"""),
    dict(name="VOCAB.PREFECTURE", graphs=["vocab/jp-prefecture"],
         comment="Japan's 47 prefectures as a SKOS scheme, keyed by JIS X 0401 code.",
         columns=["PREFECTURE_CODE VARCHAR NOT NULL", "IRI VARCHAR NOT NULL", "PREF_LABEL_EN VARCHAR NOT NULL",
                  "PREF_LABEL_JA VARCHAR NOT NULL", "PREF_LABEL_ZH VARCHAR", "ISO_CODE VARCHAR", "WIKIDATA_ID VARCHAR"],
         key=["PREFECTURE_CODE"], refs={},
         query=f"""SELECT ?c (?c AS ?iri) ?en ?ja ?zh ?iso ?wd WHERE {{
  ?c a dm:Prefecture .
  {labels("?c")}
  OPTIONAL {{ ?c dcterms:identifier ?iso }}
  {code("?c", "skos:exactMatch", "http://www.wikidata.org/entity/", "wd")} }}"""),
    dict(name="VOCAB.CARE_SETTING", graphs=["vocab/ndb-dimensions"],
         comment="NDB care settings (外来（院外）, 外来（院内）, 入院) as a SKOS scheme.",
         columns=["CARE_SETTING_ID VARCHAR NOT NULL", "IRI VARCHAR NOT NULL", "PREF_LABEL_EN VARCHAR NOT NULL",
                  "PREF_LABEL_JA VARCHAR NOT NULL", "PREF_LABEL_ZH VARCHAR", "BROADER_CARE_SETTING_ID VARCHAR",
                  "DEFINITION_EN VARCHAR"],
         key=["CARE_SETTING_ID"], refs={"BROADER_CARE_SETTING_ID": "VOCAB.CARE_SETTING"},
         query=f"""SELECT ?c (?c AS ?iri) ?en ?ja ?zh ?broader ?def WHERE {{
  ?c a dm:CareSetting .
  {labels("?c")}
  OPTIONAL {{ ?c skos:broader ?broader }}
  OPTIONAL {{ ?c skos:definition ?def FILTER(lang(?def) = "en") }} }}"""),
    dict(name="VOCAB.SEX_AGE_GROUP", graphs=["vocab/ndb-dimensions"],
         comment="NDB sex and five-year age bands as a SKOS scheme: F and M on top, bands below with their minimum age.",
         columns=["SEX_AGE_CODE VARCHAR NOT NULL", "IRI VARCHAR NOT NULL", "PREF_LABEL_EN VARCHAR NOT NULL",
                  "PREF_LABEL_JA VARCHAR NOT NULL", "PREF_LABEL_ZH VARCHAR", "SEX VARCHAR", "MIN_AGE NUMBER(3)"],
         key=["SEX_AGE_CODE"], refs={"SEX": "VOCAB.SEX_AGE_GROUP"},
         query=f"""SELECT ?c (?c AS ?iri) ?en ?ja ?zh ?sex ?age WHERE {{
  ?c a dm:SexAgeGroup .
  {labels("?c")}
  OPTIONAL {{ ?c skos:broader ?sex }}
  OPTIONAL {{ ?c dm:minAge ?age }} }}"""),
    dict(name="VOCAB.LABEL", graphs=["vocab/therapeutic-class", "vocab/substance", "vocab/indication",
                                     "vocab/nucc-specialty", "vocab/jp-drug-class", "vocab/jp-prefecture",
                                     "vocab/ndb-dimensions"],
         comment="Every SKOS label (pref, alt, hidden) in en/ja/zh: the source of semantic view synonyms.",
         columns=["CONCEPT_KIND VARCHAR NOT NULL", "CONCEPT_ID VARCHAR NOT NULL", "LANGUAGE VARCHAR NOT NULL",
                  "LABEL_TYPE VARCHAR NOT NULL", "LABEL VARCHAR NOT NULL"],
         key=["CONCEPT_KIND", "CONCEPT_ID", "LANGUAGE", "LABEL_TYPE", "LABEL"], refs={},
         query="""SELECT DISTINCT ?kind ?c (lang(?label) AS ?lang) ?type ?label WHERE {
  VALUES (?t ?kind) { (dm:TherapeuticClass "therapeutic_class") (dm:Substance "substance")
                      (dm:Indication "indication") (dm:Specialty "specialty")
                      (dm:JapaneseDrugClass "jp_drug_class") (dm:Prefecture "prefecture")
                      (dm:CareSetting "care_setting") (dm:SexAgeGroup "sex_age_group") }
  VALUES (?p ?type) { (skos:prefLabel "pref") (skos:altLabel "alt") (skos:hiddenLabel "hidden") }
  ?c a ?t ; ?p ?label . }"""),
    dict(name="US.ORGANIZATION", graphs=["drugsfda"],
         comment="Manufacturers: Drugs@FDA application holders grouped by GLEIF ultimate parent.",
         columns=["ORGANIZATION_ID VARCHAR NOT NULL", "IRI VARCHAR NOT NULL", "NAME_EN VARCHAR NOT NULL",
                  "NAME_JA VARCHAR", "NAME_ZH VARCHAR", "LEI VARCHAR", "ALT_NAMES VARCHAR"],
         key=["ORGANIZATION_ID"], refs={},
         query=f"""SELECT ?o (?o AS ?iri) ?en ?ja ?zh ?lei (GROUP_CONCAT(DISTINCT ?alt; separator="|") AS ?alts) WHERE {{
  ?o a dm:Organization .
  {labels("?o", "rdfs:label")}
  OPTIONAL {{ ?o dcterms:identifier ?lei }}
  OPTIONAL {{ ?o skos:altLabel ?alt }} }}
GROUP BY ?o ?en ?ja ?zh ?lei"""),
    dict(name="US.PRODUCT", graphs=["products"],
         comment="Medicinal products at CMS brand level.",
         columns=["PRODUCT_ID VARCHAR NOT NULL", "IRI VARCHAR NOT NULL", "BRAND_NAME VARCHAR NOT NULL",
                  "CMS_GENERIC_NAME VARCHAR NOT NULL", "IS_COMBINATION BOOLEAN NOT NULL"],
         key=["PRODUCT_ID"], refs={},
         query="""SELECT ?p (?p AS ?iri) ?brand ?generic ?combo WHERE {
  ?p a dm:MedicinalProduct ; rdfs:label ?brand ; dm:cmsGenericName ?generic ; dm:isCombinationProduct ?combo .
  FILTER(lang(?brand) = "en") }"""),
    dict(name="US.PRODUCT_SUBSTANCE", graphs=["products"],
         comment="dm:hasActiveSubstance (many-to-many: combination products have several).",
         columns=["PRODUCT_ID VARCHAR NOT NULL", "SUBSTANCE_ID VARCHAR NOT NULL"],
         key=["PRODUCT_ID", "SUBSTANCE_ID"], refs={"PRODUCT_ID": "US.PRODUCT", "SUBSTANCE_ID": "VOCAB.SUBSTANCE"},
         query="SELECT ?p ?s WHERE { ?p a dm:MedicinalProduct ; dm:hasActiveSubstance ?s }"),
    dict(name="US.PRODUCT_INDICATION", graphs=["products"],
         comment="dm:hasIndication, from FDA labels.",
         columns=["PRODUCT_ID VARCHAR NOT NULL", "INDICATION_ID VARCHAR NOT NULL"],
         key=["PRODUCT_ID", "INDICATION_ID"], refs={"PRODUCT_ID": "US.PRODUCT", "INDICATION_ID": "VOCAB.INDICATION"},
         query="SELECT ?p ?i WHERE { ?p a dm:MedicinalProduct ; dm:hasIndication ?i }"),
    dict(name="US.PRODUCT_MANUFACTURER", graphs=["drugsfda"],
         comment="dm:manufacturedBy (many-to-many: some products have several application holders).",
         columns=["PRODUCT_ID VARCHAR NOT NULL", "ORGANIZATION_ID VARCHAR NOT NULL"],
         key=["PRODUCT_ID", "ORGANIZATION_ID"], refs={"PRODUCT_ID": "US.PRODUCT", "ORGANIZATION_ID": "US.ORGANIZATION"},
         query="SELECT ?p ?o WHERE { ?p dm:manufacturedBy ?o }"),
    dict(name="US.PRODUCT_CLASS", graphs=["products", "vocab/substance", "vocab/therapeutic-class"],
         comment="Materialized roll-up: product -> every class above any of its substances "
                 "(hasActiveSubstance/inTherapeuticClass/broader*), one row per pair.",
         columns=["PRODUCT_ID VARCHAR NOT NULL", "CLASS_ID VARCHAR NOT NULL"],
         key=["PRODUCT_ID", "CLASS_ID"], refs={"PRODUCT_ID": "US.PRODUCT", "CLASS_ID": "VOCAB.THERAPEUTIC_CLASS"},
         query="""SELECT DISTINCT ?p ?c WHERE {
  ?p a dm:MedicinalProduct ; dm:hasActiveSubstance/dm:inTherapeuticClass/skos:broader* ?c . }"""),
    dict(name="US.PRESCRIBER", graphs=["cms-partd-2024", "npi-registry"],
         comment="Connecticut Part D prescribers, pseudonymized (HMAC of the NPI): no names, no NPIs.",
         columns=["PRESCRIBER_ID VARCHAR NOT NULL", "IRI VARCHAR NOT NULL", "CMS_PRESCRIBER_TYPE VARCHAR NOT NULL",
                  "CITY VARCHAR NOT NULL", "STATE VARCHAR NOT NULL", "PRIMARY_SPECIALTY_CODE VARCHAR"],
         key=["PRESCRIBER_ID"], refs={"PRIMARY_SPECIALTY_CODE": "VOCAB.SPECIALTY"},
         query="""SELECT ?h (?h AS ?iri) ?type ?city ?state ?sp WHERE {
  ?h a dm:HealthcareProfessional ; dm:cmsPrescriberType ?type ; dm:city ?city ; dm:state ?state .
  OPTIONAL { ?h dm:hasPrimarySpecialty ?sp } }"""),
    dict(name="US.PRESCRIBER_SPECIALTY", graphs=["npi-registry"],
         comment="All NUCC taxonomies of a prescriber from the NPI Registry.",
         columns=["PRESCRIBER_ID VARCHAR NOT NULL", "SPECIALTY_CODE VARCHAR NOT NULL", "IS_PRIMARY BOOLEAN NOT NULL"],
         key=["PRESCRIBER_ID", "SPECIALTY_CODE"],
         refs={"PRESCRIBER_ID": "US.PRESCRIBER", "SPECIALTY_CODE": "VOCAB.SPECIALTY"},
         query="""SELECT ?h ?sp (EXISTS { ?h dm:hasPrimarySpecialty ?sp } AS ?primary) WHERE {
  ?h dm:hasSpecialty ?sp }"""),
    dict(name="US.PRESCRIPTION", graphs=["cms-partd-2024"],
         comment="Medicare Part D 2024 claim aggregates, one row per prescriber and product. Counts are claims "
                 "(fills and refills), not patients; CMS omits rows under 11 claims; costs are gross.",
         columns=["PRESCRIPTION_ID VARCHAR NOT NULL", "PRESCRIBER_ID VARCHAR NOT NULL", "PRODUCT_ID VARCHAR NOT NULL",
                  "DATA_YEAR NUMBER(4) NOT NULL", "TOTAL_CLAIMS NUMBER(12) NOT NULL", "TOTAL_30DAY_FILLS NUMBER(14,1)",
                  "TOTAL_DAY_SUPPLY NUMBER(14)", "TOTAL_DRUG_COST NUMBER(16,2)", "TOTAL_BENEFICIARIES NUMBER(12)",
                  "BENEFICIARIES_SUPPRESSED BOOLEAN NOT NULL"],
         key=["PRESCRIPTION_ID"], refs={"PRESCRIBER_ID": "US.PRESCRIBER", "PRODUCT_ID": "US.PRODUCT"},
         query="""SELECT ?rx ?h ?p ?year ?claims ?fills ?supply ?cost ?benes ?suppressed WHERE {
  ?rx a dm:Prescription ; dm:prescribedBy ?h ; dm:forProduct ?p ; dm:dataYear ?year ;
      dm:totalClaims ?claims ; dm:beneficiaryCountSuppressed ?suppressed .
  OPTIONAL { ?rx dm:total30DayFills ?fills }
  OPTIONAL { ?rx dm:totalDaySupply ?supply }
  OPTIONAL { ?rx dm:totalDrugCost ?cost }
  OPTIONAL { ?rx dm:totalBeneficiaries ?benes } }"""),
    dict(name="JP.ORGANIZATION", graphs=["ndb-products"],
         comment="Japanese marketing authorization holders (NHI price list). CORPORATE_GROUP_ID links the Japanese "
                 "subsidiary to the same GLEIF group as the US application holder (dm:partOfCorporateGroup).",
         columns=["ORGANIZATION_ID VARCHAR NOT NULL", "IRI VARCHAR NOT NULL", "NAME_EN VARCHAR NOT NULL",
                  "NAME_JA VARCHAR NOT NULL", "CORPORATE_GROUP_ID VARCHAR"],
         key=["ORGANIZATION_ID"], refs={"CORPORATE_GROUP_ID": "US.ORGANIZATION"},
         query=f"""SELECT ?o (?o AS ?iri) ?en ?ja ?grp WHERE {{
  ?o a dm:Organization .
  {labels("?o", "rdfs:label")}
  OPTIONAL {{ ?o dm:partOfCorporateGroup ?grp }} }}"""),
    dict(name="JP.PRODUCT", graphs=["ndb-products"],
         comment="NDB Open Data products at strength level, keyed by receipt code. NHI_PRICE is yen per dispensing "
                 "unit (price list of 2026-09-02). IS_GENERIC follows the reimbursement definition (generics priced "
                 "like their originator, such as most metformin, are not flagged).",
         columns=["PRODUCT_ID VARCHAR NOT NULL", "IRI VARCHAR NOT NULL", "PRODUCT_NAME_JA VARCHAR NOT NULL",
                  "PRODUCT_NAME VARCHAR", "YJ_CODE VARCHAR NOT NULL", "JP_CLASS_CODE VARCHAR NOT NULL",
                  "NHI_PRICE NUMBER(12,2) NOT NULL", "DISPENSING_UNIT VARCHAR NOT NULL", "ROUTE VARCHAR NOT NULL",
                  "IS_GENERIC BOOLEAN NOT NULL", "IS_ORIGINATOR BOOLEAN NOT NULL", "IS_COMBINATION BOOLEAN NOT NULL",
                  "ORGANIZATION_ID VARCHAR"],
         key=["PRODUCT_ID"], refs={"JP_CLASS_CODE": "VOCAB.JP_DRUG_CLASS", "ORGANIZATION_ID": "JP.ORGANIZATION"},
         query="""SELECT ?p (?p AS ?iri) ?name ?hidden ?yj ?jpc ?price ?unit ?route ?generic ?originator ?combo ?mah WHERE {
  ?p a dm:MedicinalProduct ; rdfs:label ?name ; dm:yjCode ?yj ; dm:inJapaneseDrugClass ?jpc ; dm:nhiPrice ?price ;
     dm:dispensingUnit ?unit ; dm:routeOfAdministration ?route ; dm:isGeneric ?generic ;
     dm:isOriginator ?originator ; dm:isCombinationProduct ?combo .
  OPTIONAL { ?p skos:hiddenLabel ?hidden }
  OPTIONAL { ?p dm:manufacturedBy ?mah } }"""),
    dict(name="JP.PRODUCT_SUBSTANCE", graphs=["ndb-products"],
         comment="dm:hasActiveSubstance for the Japanese products (many-to-many: combination products have several).",
         columns=["PRODUCT_ID VARCHAR NOT NULL", "SUBSTANCE_ID VARCHAR NOT NULL"],
         key=["PRODUCT_ID", "SUBSTANCE_ID"], refs={"PRODUCT_ID": "JP.PRODUCT", "SUBSTANCE_ID": "VOCAB.SUBSTANCE"},
         query="SELECT ?p ?s WHERE { ?p a dm:MedicinalProduct ; dm:hasActiveSubstance ?s }"),
    dict(name="JP.PRODUCT_CLASS", graphs=["ndb-products", "vocab/substance", "vocab/therapeutic-class"],
         comment="Materialized roll-up: Japanese product -> every class above any of its substances "
                 "(hasActiveSubstance/inTherapeuticClass/broader*), one row per pair.",
         columns=["PRODUCT_ID VARCHAR NOT NULL", "CLASS_ID VARCHAR NOT NULL"],
         key=["PRODUCT_ID", "CLASS_ID"], refs={"PRODUCT_ID": "JP.PRODUCT", "CLASS_ID": "VOCAB.THERAPEUTIC_CLASS"},
         query="""SELECT DISTINCT ?p ?c WHERE {
  ?p a dm:MedicinalProduct ; dm:hasActiveSubstance/dm:inTherapeuticClass/skos:broader* ?c . }"""),
    dict(name="JP.NATIONAL_TOTAL", graphs=["ndb-2024"],
         comment="National total quantity (総計) per product and care setting, from the RDF Data Cube slices (equal in "
                 "the prefecture, month and sex-age slices). TOTAL_QUANTITY is NULL where NDB masked the whole row.",
         columns=["PRODUCT_ID VARCHAR NOT NULL", "CARE_SETTING_ID VARCHAR NOT NULL", "TOTAL_QUANTITY NUMBER(18,5)",
                  "IS_MASKED BOOLEAN NOT NULL"],
         key=["PRODUCT_ID", "CARE_SETTING_ID"],
         refs={"PRODUCT_ID": "JP.PRODUCT", "CARE_SETTING_ID": "VOCAB.CARE_SETTING"},
         query=f"""SELECT ?p ?setting ?total (!BOUND(?total) AS ?masked) WHERE {{
  ?s a dm:QuantitySlice ; qb:sliceStructure <{BASE}data/ndb/key/prefecture> ; dm:aboutProduct ?p ; dm:careSetting ?setting .
  OPTIONAL {{ ?s dm:totalQuantity ?total }} }}"""),
    dict(name="JP.QUANTITY", graphs=["ndb-2024"],
         comment="NDB Open Data FY2024 cells, one row per product, care setting, breakdown and cell (the RDF Data Cube "
                 "observations). Each breakdown (prefecture, month, sex-age) on its own adds up to the national total, "
                 "so never add cells across breakdowns. QUANTITY is in the product's dispensing unit and NULL where "
                 "masked (IS_MASKED, sdmx-code:confStatus-C).",
         columns=["PRODUCT_ID VARCHAR NOT NULL", "CARE_SETTING_ID VARCHAR NOT NULL", "BREAKDOWN VARCHAR NOT NULL",
                  "CELL VARCHAR NOT NULL", "PREFECTURE_CODE VARCHAR", "MONTH DATE", "SEX_AGE_CODE VARCHAR",
                  "QUANTITY NUMBER(18,5)", "IS_MASKED BOOLEAN NOT NULL"],
         key=["PRODUCT_ID", "CARE_SETTING_ID", "BREAKDOWN", "CELL"],
         refs={"PRODUCT_ID": "JP.PRODUCT", "CARE_SETTING_ID": "VOCAB.CARE_SETTING",
               "PREFECTURE_CODE": "VOCAB.PREFECTURE", "SEX_AGE_CODE": "VOCAB.SEX_AGE_GROUP"},
         query=f"""SELECT ?p ?setting ?key ?cell ?pref (CONCAT(STR(?m), "-01") AS ?month) ?band ?q
       (EXISTS {{ ?o sdmx-attribute:confStatus ?status }} AS ?masked) WHERE {{
  ?s a dm:QuantitySlice ; qb:sliceStructure ?key ; dm:aboutProduct ?p ; dm:careSetting ?setting ; qb:observation ?o .
  OPTIONAL {{ ?o dm:prefecture ?pref }}
  OPTIONAL {{ ?o dm:month ?m }}
  OPTIONAL {{ ?o dm:sexAgeGroup ?band }}
  OPTIONAL {{ ?o dm:quantity ?q }}
  BIND(COALESCE(STRAFTER(STR(?pref), "{BASE}vocab/prefecture/"), STR(?m), STRAFTER(STR(?band), "{BASE}vocab/sex-age/")) AS ?cell) }}"""),
]


def column_names(table):
    return [c.split()[0] for c in table["columns"]]


def cell(term, column):
    if term is None:
        return None
    if isinstance(term, ox.NamedNode):
        if column == "IRI":
            return term.value
        for base in ID_BASES:
            if term.value.startswith(base):
                return term.value[len(base):]
        sys.exit(f"{column}: no ID namespace for {term.value}")
    return term.value or None  # GROUP_CONCAT over nothing gives ""


def load_store():
    store = ox.Store()
    with open(ROOT / "data" / "rdf" / "manifest.csv", newline="") as f:
        files = {row["graph"]: row["file"] for row in csv.DictReader(f)}
    for name in GRAPHS:
        store.bulk_load(path=str(ROOT / files[BASE + "graph/" + name]), format=ox.RdfFormat.TURTLE,
                        to_graph=ox.NamedNode(BASE + "graph/" + name))
    return store


def select(store, query, graphs=None):
    """graphs: read only these named graphs (a table's sources); None: all of them."""
    query = PREFIXES + query.replace("FROM <tag:stardog:api:context:all>", "")
    if graphs is None:
        return store.query(query, use_default_graph_as_union=True)
    return store.query(query, default_graph=[ox.NamedNode(BASE + "graph/" + g) for g in graphs])


def check_table(table, rows, errors):
    names = column_names(table)
    keys = Counter(tuple(r[names.index(k)] for k in table["key"]) for r in rows)
    if dups := [k for k, n in keys.items() if n > 1]:
        errors.append(f"{table['name']}: {len(dups)} duplicate keys, e.g. {dups[0]}")
    for i, col in enumerate(table["columns"]):
        if "NOT NULL" in col and (missing := sum(r[i] is None for r in rows)):
            errors.append(f"{table['name']}.{names[i]}: {missing} rows without a value")


def check_refs(tables, data, errors):
    for t in tables:
        names = column_names(t)
        for col, target in t["refs"].items():
            target_key = {r[0] for r in data[target]}  # every referenced table has a one-column key first
            dangling = {r[names.index(col)] for r in data[t["name"]]} - target_key - {None}
            if dangling:
                errors.append(f"{t['name']}.{col}: {len(dangling)} values not in {target}, e.g. {sorted(dangling)[0]}")


def rows_as_dicts(data, name):
    t = next(t for t in TABLES if t["name"] == name)
    return [dict(zip(column_names(t), r)) for r in data[name]]


def check_parity(store, data, errors):
    """Two business questions, on the graph (the published .rq files) and on the tables."""
    rx = rows_as_dicts(data, "US.PRESCRIPTION")
    classes_of = defaultdict(set)
    for r in rows_as_dicts(data, "US.PRODUCT_CLASS"):
        classes_of[r["PRODUCT_ID"]].add(r["CLASS_ID"])
    combination = {r["PRODUCT_ID"] for r in rows_as_dicts(data, "US.PRODUCT") if r["IS_COMBINATION"] == "true"}
    specialty = {r["SPECIALTY_CODE"]: r["PREF_LABEL_EN"] for r in rows_as_dicts(data, "VOCAB.SPECIALTY")}
    primary = {r["PRESCRIBER_ID"]: specialty[r["PRIMARY_SPECIALTY_CODE"]]
               for r in rows_as_dicts(data, "US.PRESCRIBER") if r["PRIMARY_SPECIALTY_CODE"]}
    class_label = {r["CLASS_ID"]: r["PREF_LABEL_EN"] for r in rows_as_dicts(data, "VOCAB.THERAPEUTIC_CLASS")}

    # 1. SGLT2 vs GLP-1 claims by primary specialty
    tables = defaultdict(lambda: [0, 0])
    for r in rx:
        for i, cls in enumerate(("SGLT2Inhibitor", "GLP1ReceptorAgonist")):
            if cls in classes_of[r["PRODUCT_ID"]] and r["PRESCRIBER_ID"] in primary:
                tables[primary[r["PRESCRIBER_ID"]]][i] += int(r["TOTAL_CLAIMS"])
    graph = {s["specialty"].value: [int(s["sglt2Claims"].value), int(s["glp1Claims"].value)]
             for s in select(store, (ROOT / "queries" / "sglt2-vs-glp1-by-specialty.rq").read_text())}
    tables = {k: v for k, v in tables.items() if sum(v)}
    expected = {"sglt2-vs-glp1-by-specialty": graph}
    if graph != tables:
        diff = sorted(k for k in graph.keys() | tables.keys() if graph.get(k) != tables.get(k))
        errors.append(f"parity sglt2-vs-glp1-by-specialty: {len(diff)} specialties differ, e.g. {diff[0]}: "
                      f"graph {graph.get(diff[0])}, tables {tables.get(diff[0])}")

    # 2. Claims and cost by class, single-substance products only
    wanted = ["Biguanide", "Sulfonylurea", "Thiazolidinedione", "DPP4Inhibitor", "SGLT2Inhibitor",
              "GLP1ReceptorAgonist", "LongActingInsulin"]
    totals = defaultdict(lambda: [0, 0.0])
    for r in rx:
        if r["PRODUCT_ID"] in combination or r["TOTAL_DRUG_COST"] is None or r["TOTAL_30DAY_FILLS"] is None:
            continue
        for cls in wanted:
            if cls in classes_of[r["PRODUCT_ID"]]:
                totals[class_label[cls]][0] += int(r["TOTAL_CLAIMS"])
                totals[class_label[cls]][1] += float(r["TOTAL_DRUG_COST"])
    tables = {k: [v[0], round(v[1])] for k, v in totals.items()}
    graph = {s["class"].value: [int(s["claimsTotal"].value), round(float(s["costTotal"].value))]
             for s in select(store, (ROOT / "queries" / "cost-per-claim-by-class.rq").read_text())}
    if graph != tables:
        diff = sorted(k for k in graph.keys() | tables.keys() if graph.get(k) != tables.get(k))
        errors.append(f"parity cost-per-claim-by-class: {len(diff)} classes differ, e.g. {diff[0]}: "
                      f"graph {graph.get(diff[0])}, tables {tables.get(diff[0])}")
    return expected | {"cost-per-claim-by-class": graph}


def graph_results(store):
    """The Japan questions (queries/jp-*.rq) on the graph, as expectations for the Snowflake side, where
    scripts/deploy_semantic_view.py checks them through the semantic views. The reasoning query becomes its OWL
    definition spelled out (no reasoner here): products with a substance in the GLP-1 class or a narrower one."""
    out = {}
    for path in sorted((ROOT / "queries").glob("jp-*.rq")):
        text = path.read_text()
        if "# reasoning: true" in text:
            text = text.replace("?prod a dm:GLP1Product ;", "?prod dm:hasActiveSubstance/dm:inTherapeuticClass/"
                                "skos:broader* <https://dgg32.github.io/glp/vocab/therapeutic-class/GLP1ReceptorAgonist> ;")
        result = select(store, text)
        out[path.stem] = [{str(v)[1:]: (s[v].value if s[v] is not None else None) for v in result.variables}
                          for s in result]
    return out


def main():
    require_local_check()
    store = load_store()
    data, errors = {}, []
    for t in TABLES:
        names = column_names(t)
        data[t["name"]] = [tuple(cell(s[i], names[i]) for i in range(len(names)))
                           for s in select(store, t["query"], t["graphs"])]
        check_table(t, data[t["name"]], errors)
    check_refs(TABLES, data, errors)
    for name, n in EXPECTED_ROWS.items():
        if len(data[name]) != n:
            errors.append(f"{name}: {len(data[name]):,} rows, expected {n:,}")
    # The Japan semantic view gets all-drug totals from the top class, so every product must reach it once.
    for name in ("US.PRODUCT_CLASS", "JP.PRODUCT_CLASS"):
        products = {r[0] for r in data[name.replace("_CLASS", "")]}
        if missing := products - {r[0] for r in data[name] if r[1] == "DrugsUsedInDiabetes"}:
            errors.append(f"{name}: {len(missing)} products outside DrugsUsedInDiabetes, e.g. {sorted(missing)[0]}")
    parity = check_parity(store, data, errors) | graph_results(store) if not errors else {}
    for t in TABLES:
        print(f"{len(data[t['name']]):>8,}  {t['name']}")
    if errors:
        sys.exit("export failed, nothing written to tables.json:\n  " + "\n  ".join(errors))

    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "rdf_provenance": provenance_digest(), "parity": parity, "tables": []}
    for t in TABLES:
        path = OUT / f"{t['name']}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(column_names(t))
            w.writerows(["" if v is None else v for v in r] for r in data[t["name"]])
        manifest["tables"].append({
            "name": t["name"], "file": path.name, "rows": len(data[t["name"]]),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "columns": t["columns"], "key": t["key"],
            "refs": t["refs"], "comment": t["comment"] + " Source: " + ", ".join(BASE + "graph/" + g for g in t["graphs"])})
    (OUT / "tables.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    print(f"all checks passed; parity on {", ".join(f"{q} ({len(r)} rows)" for q, r in parity.items())}; "
          f"wrote {OUT.relative_to(ROOT)}/tables.json (with the graph results as expectations for the semantic view)")


if __name__ == "__main__":
    main()
