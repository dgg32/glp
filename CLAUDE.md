# Project hand-off: Semantic diabetes drug market graph in Stardog

## Why this project exists
Sixing Huang (Neo4j Ninja, knowledge graph engineer, Tokyo) applied for **Semantic Engineer (Staff), Boehringer Ingelheim Japan** (job ID 38340). This project closes the gaps between their profile and that job, and ends as a **Medium article plus a public GitHub repo** (their usual format; see dgg32.medium.com).

Gaps to close, in priority order:
1. Hands-on **OWL, SKOS, SHACL** (so far they have mostly used property graphs; they have used SHACL-like validation in their HELMS project)
2. **Stardog** (they signed up for Stardog Free)
3. Industry ontology alignment, mainly **IDMP-O** (Pistoia Alliance, OWL, on GitHub)
4. **Pharma commercial data** (prescribers/HCPs, specialties, market share)
5. Governance: modeling standards, provenance, versioning
6. Optional sequel: **Snowflake semantic view + OSI YAML** over the same data

## Scope
US type 2 diabetes drugs (GLP-1, SGLT2, DPP-4, metformin, sulfonylureas, insulin glargine, plus pioglitazone) and the doctors who prescribe them, **one state only: Connecticut** (decided 2026-10-14). Connecticut is Boehringer's US HQ state (Ridgefield), which is a good article hook. Jardiance (empagliflozin) and Tradjenta (linagliptin) are Boehringer products.

## Data sources
- **CMS Medicare Part D Prescribers by Provider and Drug**, data year 2024 (28M rows total, so never download the full file).
  - API, verified 2026-10-14: `https://data.cms.gov/data-api/v1/dataset/d5aa71a8-dcc0-4570-8bcf-bd39deac69fe/data`
  - Filter: `filter[Prscrbr_State_Abrvtn]=CT&filter[Gnrc_Name]=Empagliflozin` (the name filter is exact but case-insensitive; `filter[g][condition][operator]=CONTAINS` works for substring searches but is slow). Page with `size=5000&offset=N`; an empty page returns `[]`. Row counts are at `.../data/stats?<same filters>`. Use `curl -g`. The API is slow (about 5 s per call).
  - Columns: Prscrbr_NPI, Prscrbr_Last_Org_Name, Prscrbr_First_Name, Prscrbr_City, Prscrbr_State_Abrvtn, Prscrbr_Type (specialty), Brnd_Name, Gnrc_Name, Tot_Clms, Tot_30day_Fills, Tot_Day_Suply, Tot_Drug_Cst, Tot_Benes, GE65_* and suppression flags (`*`).
  - Connecticut subset: 32 generic names, 22,034 rows, 3,896 prescribers. The verified CMS spellings are in `scripts/cms_generic_names.csv`; substances, ATC codes and drug classes are looked up (RxNorm incl. its ATC codes, FDA EPC) by `scripts/resolve_drugs.py`, and brands and indications (RxNorm, openFDA labels) by `scripts/resolve_products.py`, and companies (GLEIF, from a curated sponsor → LEI table) by `scripts/resolve_organizations.py`, into generated `scripts/{drugs,substances,products,organizations}.csv`. The class tree and indications come from RxClass ATC, UMLS and MeSH (`scripts/resolve_vocab.py`), and ja/zh labels partly from Wikidata (`scripts/fetch_wikidata_labels.py`; disagreements in `docs/label-review.md`). CMS spells some names unexpectedly: "Ertugliflozin Pidolate", "Saxagliptin Hcl", "Insulin Glargine,hum.Rec.Anlog", "Dapaglifloz Propaned/Metformin", "Empaglifloz/Linaglip/Metformin".
  - Other years' API IDs are in `https://data.cms.gov/data.json`. Search for titles "Medicare Part D Prescribers - by Provider and Drug". Add 2019 or 2021 only if you want a trend story.
- **NPI Registry API** (`https://npiregistry.cms.hhs.gov/api/?version=2.1&number=<NPI>`) gives NUCC taxonomy codes. Query only the unique NPIs in the subset; do not use the 9 GB NPPES file.
- **NUCC Health Care Provider Taxonomy** (CSV from nucc.org): convert to a SKOS concept scheme.
- **RxNorm** (the user has a UMLS license), **openFDA drug labels**, **MeSH RDF**, and **IDMP-O**.

## What to build
1. **OWL ontology**, small (10–15 classes): MedicinalProduct, Substance, Indication, HealthcareProfessional, Organization, Prescription (claim aggregate), Specialty. Align to IDMP-O with subClassOf/equivalentClass rather than inventing new classes. Add one or two Stardog inference rules (e.g. `SGLT2Prescriber`) and show query results with reasoning off and on.
2. **SKOS vocabularies**: the NUCC specialty taxonomy, and a therapeutic class scheme (antidiabetics → SGLT2 inhibitors → empagliflozin). Give it **en/ja/zh prefLabel and altLabel** (multilingual labels are the user's differentiator) and `skos:exactMatch` links to ATC, MeSH and RxNorm.
3. **SHACL shapes**: product has ≥1 substance; NPI is 10 digits; exactly one English prefLabel per concept; counts are non-negative; a count is present OR its suppression flag is set. Run them on the real data and **show the violations they catch**.
4. **SPARQL business questions**: SGLT2 vs GLP-1 share by specialty (roll up with `skos:broader*`); cost per claim by class; a query by Japanese label (e.g. SGLT2阻害薬).
5. **GenAI layer**: an **MCP server** (`mcp_server/`, decided 2026-10-14 instead of a LangGraph agent) over the Stardog SPARQL endpoint that uses SKOS labels for term normalization (the user's DrugBot pattern on RDF), usable from Claude or any MCP client. Compare it with Stardog Voicebox (included in Cloud Free; must be enabled per database).
6. **Governance**: one named graph per source, PROV-O provenance, ontology versioning, and SHACL shapes as the modeling contract.

## Constraints
- **Public data only.** Never use or mention data from the user's client work for Taiwan's national drug evaluation center or drug regulator, which is under NDA.
- **Privacy-by-design**: the data includes real doctor names. Hash or pseudonymize NPIs and names in anything published, and say so in the article.
- **Stardog Cloud Free** (verified 2026-10-14, Stardog 12.1.4): 1M edges, 3 databases, 3 Voicebox databases, no backups. Reasoning (SL), SHACL (`VALIDATE`) and SHACL-SPARQL work (no `VALUES` inside SHACL-SPARQL constraints). The dataset is ~734k triples since the Japan extension (Connecticut with shared vocabularies ~247k, Japan ~487k). Queries are capped at 5 minutes, and heavy reasoning queries can make the instance answer 503 for a few minutes. Data lives in named graphs, so queries need `FROM <tag:stardog:api:context:all>` (or `default-graph-uri`).
- Keep raw downloads in `data/raw/` and generated RDF in `data/rdf/`. Make all scripts rerunnable. Code will be published on GitHub, so put no credentials in the repo (use `.env`).

## Status (2026-10-14)
Done: download and cleaning, OWL ontology 0.4.0 aligned to IDMP-O 1.4.0, SKOS vocabularies (en/ja/zh), RDF with pseudonymized prescribers, loaded into Stardog database `glp`, SHACL shapes (0 violations on real data; every rule proven to fire), five business queries, MCP server tested from Claude Code.

Open: native-speaker review of the curated ja/zh labels that `docs/label-review.md` does not cover (labels without a Wikidata counterpart: most class names, NUCC specialties; the disagreement list was accepted 2026-10-15); Voicebox comparison; the article. Governance: `docs/governance.md` (provenance per graph with source releases and content hashes, SHACL gate inside the load transaction, modelling standards).

Japan extension (2026-10-25, see `japan_extension.md`): NDB Open Data FY2024 (11th release) for all diabetes drugs (510 strength-level products, 150,288 cells incl. masked) loaded into the same database as an RDF Data Cube; ontology 0.5.0, shapes 0.3.0 (59 rules, all proven to fire; 0 violations on the real data), 26 new substances (12 not in RxNorm, identified by UMLS), a computed 薬効分類 ↔ ATC crosswalk, Japan queries `queries/jp-*.rq`. Open: the second article; Japan-only indications (CHF/CKD); 12th release (monthly FY2025) needs its own database.

Snowflake extension (2026-10-31, see `snowflake_extension.md`): Connecticut graph exported as 16 tables (schemas VOCAB, US) by `export_snowflake.py` (parity-checked against the SPARQL queries) and loaded into the trial account by `load_snowflake.py` (runs in `.venv-snowflake`, Python 3.13). `build_osi.py` generates OSI 0.1.1 YAML, native semantic view DDL and a draft Ossie Layer 4 ontology from the ontology (0.5.1) into `semantic/`; `deploy_semantic_view.py` deploys `GLP.SEMANTIC.DIABETES_MARKET_OSI` and `DIABETES_MARKET` (both match the graph; OSI loses all 64 synonyms). Cortex Analyst measured over the REST API (`eval_analyst.py`; results in `snowflake_extension.md`). Japan added 2026-10-31: JP schema, semantic views `JAPAN_MARKET` and `JAPAN_MARKET_OSI` (all Japan verified queries and `queries/snowflake/*.sql` match the graph), `eval_analyst.py --model jp`; article 2 (`docs/article_2.md`) now presents the data through Snowflake. Stardog runs ontology 0.5.2 (pushed 2026-10-31, 0 violations), the third article. Trial ends ~2026-11-30.

Where to look: `docs/decisions.md` (why things are the way they are), `docs/findings.md` (business results), `docs/article-notes.md` (story material), `docs/validation-report.md` (latest SHACL run). Pipeline order: `scripts/download_partd.py` → `resolve_drugs.py` → `resolve_vocab.py` (needs `UMLS_API_KEY`) → `resolve_products.py` → `resolve_organizations.py` → `fetch_wikidata_labels.py` → `fetch_npi.py` → `download_nucc.py` → `clean_data.py` → `build_skos.py` → `build_rdf.py` → `check_local.py` (must pass; ~12 min) → `load_stardog.py` (incremental, refuses unchecked files) → `validate.py` → `run_queries.py`. Never iterate against Stardog Cloud: rebuild and check locally, push once. Japan: `download_ndb.py` → `clean_ndb.py` before `resolve_drugs.py`; `build_rdf.py` calls `build_ndb.py`.

## Article angle
"A Neo4j Ninja models the same drug data in RDF": what OWL, SKOS and SHACL add that a property graph doesn't. It should take about 2–3 weekends.
