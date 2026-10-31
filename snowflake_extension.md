# Hand-off: Snowflake semantic view and OSI YAML

## Why
The Boehringer Ingelheim Japan Semantic Engineer posting lists **"Experience with Snowflake Semantic Models and Open Semantic Interoperability (OSI) compliant with YAML specifications"** as a requirement, not a nice-to-have. It is the one requirement the project does not show yet. (The spec's real name is Open Semantic *Interchange*; the posting misnames it.) Started 2026-10-31 on a 30-day Snowflake trial (CoCo), which expires around 2026-11-30.

## Angle (decided 2026-10-31)
**The ontology generates the semantic layer.** The OWL/SKOS model stays the single source of truth. A script generates OSI YAML from it, and Snowflake compiles the YAML into a semantic view (`SYSTEM$CREATE_SEMANTIC_VIEW_FROM_OSSIE_YAML`). Nobody hand-writes a second model next to the graph.

| RDF layer | Semantic view / OSI |
|---|---|
| OWL classes and properties | datasets, dimensions, relationships |
| `skos:prefLabel`/`altLabel` en/ja/zh | synonyms, so Cortex Analyst understands SGLT2阻害薬 |
| `skos:definition`, `rdfs:comment` | descriptions the LLM reads |
| `skos:broader*` | materialized closure tables (SQL has no property paths) |
| `dm:SGLT2Prescriber` (OWL defined class) | derived dimension or filter: what has to be spelled out without a reasoner |
| SHACL shapes | declared keys and Snowflake data metric functions (weaker: say so) |
| business queries in `queries/` | metrics: claims, cost, cost per claim, class share by specialty |

## Setup (done 2026-10-31)
- Trial account on AWS ap-northeast-1 (identifier in `.env` only), key-pair auth, settings `SNOWFLAKE_*` in `.env`, private key in `~/.snowflake/` (outside the repo). The connector logs in with the LOGIN_NAME (the email), not the user name, which can differ (a case-sensitive lowercase name: quote it in `ALTER USER`).
- Warehouse `GLP_WH` (XS, auto-suspend 60 s), database `GLP`.
- The connector does not run on Python 3.15. Snowflake scripts use `.venv-snowflake` (Python 3.13, `requirements-snowflake.txt`); everything else stays in `.venv`.

## Step 1: tables (scripts written 2026-10-31)
`scripts/export_snowflake.py` (`.venv`) turns the validated RDF into tables, one SPARQL SELECT per table, and refuses to run unless `check_local.py` passed. Schemas mirror the named graphs:

| Schema | Tables |
|---|---|
| `VOCAB` (shared vocabularies) | THERAPEUTIC_CLASS (17), CLASS_ANCESTOR (48), SUBSTANCE (47), INDICATION (3), SPECIALTY (918), SPECIALTY_ANCESTOR (2,449), JP_DRUG_CLASS (6), JP_CLASS_MATCH (15), PREFECTURE (47), CARE_SETTING (4), SEX_AGE_GROUP (44), LABEL (2,568) |
| `US` (Connecticut, Part D 2024) | PRESCRIPTION (22,034), PRESCRIBER (3,896), PRESCRIBER_SPECIALTY (5,223), PRODUCT (51), PRODUCT_SUBSTANCE (66), PRODUCT_INDICATION (59), PRODUCT_MANUFACTURER (34), PRODUCT_CLASS (171), ORGANIZATION (9) |
| `JP` (NDB Open Data FY2024, added 2026-10-31) | PRODUCT (510), PRODUCT_SUBSTANCE (530), PRODUCT_CLASS (1,514), ORGANIZATION (51), NATIONAL_TOTAL (1,488), QUANTITY (150,288) |

Checks: keys unique, NOT NULL filled, every foreign key resolves, expected counts, and **parity**: `sglt2-vs-glp1-by-specialty.rq` and `cost-per-claim-by-class.rq` run on the graph give the same numbers as the same questions computed from the tables (proven to fire: one extra Jardiance claim fails both).

`scripts/load_snowflake.py` (`.venv-snowflake`) loads only files whose hash matches the checked export: CREATE OR REPLACE with declared keys, PUT and COPY, then verifies row counts and total claims and cost in Snowflake. Each load is recorded in `PUBLIC.LOAD_LOG` and in the table comments (source graphs, export time, RDF provenance hash).

Pipeline: `check_local.py` → `export_snowflake.py` → `load_snowflake.py`.

## Things noticed
- **Many-to-many is the normal case.** Products have several substances (combinations) and some have several manufacturers (Byetta: AstraZeneca and Amylin). The graph doesn't care, but a semantic view needs many-to-one relationships, so the many-to-many links go into bridge tables. The semantic view has to decide how a combination product counts per class; the SPARQL queries count it once per class.
- **Substances have several ATC codes** (insulin human has 5, one per formulation; tolbutamide also has a diagnostic code), so `VOCAB.SUBSTANCE.ATC_CODES` is |-separated.
- Specialty totals in `docs/findings.md` count only prescribers with a primary specialty; all-prescriber totals are slightly higher (198,686 SGLT2 vs 198,279).

## OSI in Snowflake: what the probe showed (2026-10-31)
OSI moved to the Apache Software Foundation as **"Ossie"** (github.com/apache/ossie). Snowflake's `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_OSSIE_YAML` (preview; the `..._OSI_YAML` names are deprecated) accepts only **version 0.1.1** (tag `osi-0.1.1-rc1`, wrapper `semantic_model:` list). Repo main is at 0.2.0.dev0 and adds a draft **Layer 4 "Ontology"** (`ontology/ontology.md`: concepts with `iri`, `extends`, `derived_by`, `requires`, separate mapping documents), which Snowflake does not read.

Probe on `VOCAB.THERAPEUTIC_CLASS` (view created, inspected with GET_DDL and read-back, dropped):
- **Synonyms do not survive OSI import.** A field's `custom_extensions: [{vendor_name: SNOWFLAKE, data: '{"synonyms": [...]}'}]` is stored as opaque OSI metadata in `WITH EXTENSION (OSI=...)`, not turned into native `WITH SYNONYMS`. OSI 0.1.1 has no synonym slot. `ai_context` is stored the same way, and Cortex Analyst ignores it. So the only thing from OSI that grounds Analyst is `description` (becomes `COMMENT`).
- The `vendor`/`content` key spelling shown in Snowflake's read-function docs is **silently dropped** on create; only the spec's `vendor_name`/`data` is kept.
- Model-level metrics must reference **fields** (`dataset.field`), not physical columns ("Unsupported expression in the definition of derived metric").
- Read-back is lossy: names uppercased, `is_time: false` becomes `dimension: {}`, `ANSI_SQL` returned as `SNOWFLAKE`, every field gets an `access_modifier` extension.

## Step 2: the semantic layer (done 2026-10-31)
Decided 2026-10-31: **one generator, two deployments**, then compare them in Cortex Analyst. Plus the draft Layer 4 ontology as a bonus file.

`scripts/build_osi.py` (`.venv`) reads the ontology (0.5.1: ja/zh labels added for the US data properties), the vocabularies and `data/snowflake/tables.json`, and writes `semantic/`:
- `helper-views.sql`: `GLP.SEMANTIC` views. `PRESCRIPTION_CLASS` (prescription × class, incl. broader classes) and `PRESCRIPTION_CLASS_COMPANY` (× manufacturer) are bridge facts, because a semantic view joins only many-to-one. `PRESCRIBER_PROFILE` and `PRODUCT_PROFILE` add the four OWL defined classes as flags (`IS_SGLT2_PRESCRIBER`, ...), with the class ids read from the `owl:hasValue` restrictions.
- `diabetes-market.osi.yaml`: OSI 0.1.1 (validated against `semantic/schema/`); synonyms in `ai_context` and the SNOWFLAKE vendor extension, as the spec allows.
- `diabetes-market.sql`: the same model as native `CREATE SEMANTIC VIEW` with `WITH SYNONYMS` and `AI_SQL_GENERATION`.
- `diabetes-market.ontology.yaml`: draft Ossie Layer 4 (17 concepts with `iri`, `extends`; defined classes as `derived_by`; `skos:broader*` as a recursive `broader_transitive`; `requires: >= 0` from `xsd:nonNegativeInteger`). Validates against the draft schema; nothing executes it.

The model: 8 datasets, 45 fields, 8 relationships, 15 metrics (`total_claims`, `class_claims`, `sglt2_share_vs_glp1`, `company_claims`, ...), 64 synonyms (19 en, 22 ja, 23 zh), descriptions from `skos:definition`, value lists from the SKOS vocabularies (e.g. all Japanese class names). The only hand-written meaning is the mapping of columns to ontology terms, and the caveats and instructions text.

`scripts/deploy_semantic_view.py` (`.venv-snowflake`) refuses to run unless Snowflake holds the checked export, creates the helper views, `GLP.SEMANTIC.DIABETES_MARKET_OSI` (via the OSI procedure) and `GLP.SEMANTIC.DIABETES_MARKET` (native), reads both back into `semantic/readback/`, and runs two business questions through each view against the SPARQL results stored by the export (check proven to fire).

Result of the first deployment: **both views give exactly the graph's numbers**; **the OSI view has 0 synonyms, the native view 64**; the OSI view also lost the custom instructions (no `AI_SQL_GENERATION`). The read-back of the OSI view still contains the synonyms, as opaque extension data. Japanese works in SQL: `DIMENSIONS specialty.specialty_name_ja` gives 循環器内科医 90% SGLT2, 内分泌・糖尿病・代謝内科医 31%.

Pipeline: `check_local.py` → `export_snowflake.py` → `load_snowflake.py` → `build_osi.py` → `deploy_semantic_view.py`.

## Cortex Analyst log
- 2026-10-31, `DIABETES_MARKET` (native), Playground: 「SGLT2阻害薬の処方件数を専門分野別に教えて」 → `METRICS CLASS_CLAIMS DIMENSIONS specialty_name_ja WHERE prescription_class.class_id = 'SGLT2Inhibitor'`. Correct metric (class, not total), correct language column, SGLT2阻害薬 mapped to the class id. Numbers match `docs/findings.md` (内科医 62,651, 家庭医 24,069, 内分泌・糖尿病・代謝内科医 23,186, 循環器内科医 20,536). A blank row (7,035) collects specialties without a Japanese label: only 20 of the 83 primary specialties in use have one. The "1 Warning": Analyst's first attempt used the physical column, `DIMENSIONS specialty.pref_label_ja AS specialty_name_ja` ("invalid identifier 'SPECIALTY.PREF_LABEL_JA'"), and it corrected itself to the logical name on the second try. It reads the dimension expressions, so physical column names that differ from the logical names cause errors. Possible fix: a view per dataset whose columns carry the logical names (generated by build_osi.py).
- 2026-10-31, `DIABETES_MARKET` (native): "What is the SGLT2 vs GLP-1 share by specialty?" → `METRICS SGLT2_CLAIMS, GLP1_CLAIMS, SGLT2_SHARE_VS_GLP1 DIMENSIONS specialty_name ORDER BY SGLT2_CLAIMS + GLP1_CLAIMS DESC`. Used the three generated metrics (class ids from the OWL definitions) and matches findings table 1 row for row (Internal Medicine 45%, Endocrinology 31%, Cardiovascular Disease 90%).
- 2026-10-31, `DIABETES_MARKET` (native): "Cost per claim by drug class" → `DIMENSIONS class_name METRICS CLASS_COST_PER_CLAIM`, no filter. Valid SQL, **different question** from findings table 2: (1) all 17 classes at every level of the tree side by side ("Drugs used in diabetes" 613, "Blood glucose lowering drugs" 645 next to GLP-1 1,339), because nothing tells Analyst which level is "a drug class"; (2) combination products included (findings: single-ingredient only), so DPP-4 928 vs 919, SGLT2 1,096 vs 1,097; (3) no per-30-day-fill figure, which findings calls the fairer comparison. Fix candidates: a class level dimension from the ATC notation (A10 / A10B / A10BK) with "drug class = ATC level 4" in the description, and verified queries generated from `queries/*.rq`.
- 2026-10-31, `DIABETES_MARKET` (native): "What is Boehringer's share of SGLT2 claims?" → `METRICS COMPANY_CLAIMS DIMENSIONS manufacturer WHERE prescription_class_company.class_id = 'SGLT2Inhibitor'`, share computed outside with `SUM(...) OVER ()`. Matches findings table 4 exactly (Boehringer 135,954 = 68.4%, AstraZeneca 59,896, generic 1,857, J&J 966, Merck 13; total 198,686). Analyst matched "Boehringer" to the GLEIF legal name "C.H. Boehringer Sohn AG & Co. KG" itself. Caveat: summing company claims as the denominator works for SGLT2 but would overcount GLP-1 (Byetta has two holders); a `class_claims`-based share metric would be safer.
- 2026-10-31, `DIABETES_MARKET_OSI` (no synonyms), same four questions, one run each:
  - 「SGLT2阻害薬の処方件数を専門分野別に教えて」 → `DIMENSIONS specialty.specialty_name` (**English** names), same numbers. The native view answered with `specialty_name_ja`: the synonym 専門分野 on the Japanese field is what made the answer Japanese. No warning here (the native view's first attempt failed on the physical column name).
  - SGLT2 vs GLP-1 by specialty → same numbers, but computed the share itself in SQL instead of using the generated `SGLT2_SHARE_VS_GLP1` metric (the native view used it).
  - Cost per claim by drug class → identical to the native view (all levels, combinations included): the gap is in the model, not in the synonyms.
  - Boehringer's SGLT2 share → identical numbers (CTE instead of a window function).
  - **Verdict so far: 4/4 same numbers in both views.** Descriptions, value lists and the LLM's own knowledge carry the meaning; synonyms showed up in the *language of the answer* (Japanese labels) and possibly in picking the prepared metric. One run per question, and Analyst is not deterministic, so this needs repeated runs through the REST API before it goes into the article.
- The Analyst page needs a warehouse of its own: set `DEFAULT_WAREHOUSE = GLP_WH` on the user, then sign in again.

## Step 3: measured with the Cortex Analyst REST API (2026-10-31)
`scripts/eval_analyst.py <label>` (`.venv-snowflake`) asks each question 3 times per view through the REST API (key-pair JWT), runs the SQL Analyst returns, and scores it against ground truth from plain SQL on the tables. Results in `data/validation/analyst-eval-<label>.json`.

**Generator update between the two runs** (all in `build_osi.py`, ontology unchanged):
1. Dataset views `GLP.SEMANTIC.SV_*` whose columns carry the logical field names. The native DDL had `specialty.specialty_name AS specialty.PREF_LABEL_EN`, and Analyst copied the physical name in its first attempt ("invalid identifier 'SPECIALTY.PREF_LABEL_EN'"); the OSI view writes the expression without the table prefix and never had the problem.
2. `therapeutic_class.is_drug_class` and `class_depth`, from `skos:broader*` (`VOCAB.CLASS_ANCESTOR`). Drug class = the depth of the classes the OWL defined classes refer to (SGLT2, GLP-1: depth 3). ATC code length would not do: glinides and imeglimin have no ATC code.
3. Five verified queries restating `queries/*.rq` (SGLT2 vs GLP-1 by specialty, cost per claim and per 30-day fill by drug class, market share by manufacturer, the Japanese-label query, prescriber overlap). `deploy_semantic_view.py` runs each on both views and checks the two that restate a parity question against the graph.
4. `company_claims_allocated` (a product's claims split equally among its holders, so companies add up to the class) for shares.
5. Value lists with aliases (`C.H. Boehringer Sohn AG & Co. KG (also: Boehringer Ingelheim Pharmaceuticals, Inc.)`); Japanese and Chinese name columns fall back to English (the convention of `sglt2-by-japanese-label.rq`), so no blank rows.

**OSI round trip loses Snowflake's own extension.** The OSI file now carries instructions and verified queries in exactly the layout `SYSTEM$READ_OSSIE_YAML_FROM_SEMANTIC_VIEW` exports (`{"module_custom_instructions": {"sql_generation": ...}, "verified_queries": [...]}`). The import ignores it: `GET_DDL` of the OSI view has no `AI_VERIFIED_QUERIES`, no `AI_SQL_GENERATION`, no `WITH SYNONYMS`. Export writes what import does not read.

**Results** (correct runs of 3; native / OSI):

| Question | Check | Baseline | After fixes |
|---|---|---|---|
| 「SGLT2阻害薬の処方件数を専門分野別に教えて」 | numbers | 3/3 · 3/3 | 3/3 · 3/3 |
| | Japanese specialty names | **3/3 · 0/3** | **3/3 · 0/3** |
| SGLT2 vs GLP-1 share by specialty | share | 3/3 · 3/3 | 3/3 · 3/3 |
| Cost per claim by drug class | drug classes only | 0/3 · 0/3 | **3/3 · 3/3** |
| | per 30-day fill shown | 0/3 · 0/3 | **3/3** · 0/3 |
| | single-ingredient convention | 0/3 · 0/3 | 0/3 · 0/3 |
| Boehringer's share of SGLT2 claims | share | 3/3 · 3/3 | 3/3 · 2/3 |
| Company shares of GLP-1 claims | Novo Nordisk share | 3/3 · 3/3 | 3/3 · 3/3 |
| 「ベーリンガーのSGLT2阻害薬シェアは？」 | share | 3/3 · 3/3 | 3/3 · 3/3 |
| Which drug classes cost the most? (held out) | drug classes only, GLP-1 first | **0/3 · 0/3** | **3/3 · 3/3** |
| All questions | first attempt failed (warning) | 6 · 0 | 3 · 0 |

Reading:
- **The model, not the interchange format, fixed the class-level problem.** `is_drug_class` with its description works in both views, including on the held-out question no verified query covers.
- **What OSI loses shows up as language and conventions.** Japanese names: 3/3 native, 0/3 OSI, before and after. Cost per 30-day fill: only the native view (it has the verified query and the instructions) shows it.
- **Verified queries pass on their conventions only partly.** Native adopted `is_drug_class` and per-30-day-fill from the cost query, but not "single-ingredient", which the question did not mention. Including combinations is a defensible reading.
- Remaining errors: OSI once computed Boehringer's share as 100% (total taken inside the manufacturer group). Native's three warnings were unquoted Japanese aliases (`メーカー…`) in the first attempt, corrected automatically.
- Scoring note: in the after run the OSI view answered the share question with the share only (no claim counts), so the strict "numbers" check failed 0/3 although the shares were right; that row is left out of the table above.
- Caveats: 3 runs per cell; four of the seven questions resemble a verified query (in the native view only), three do not (Boehringer in English and Japanese, GLP-1 company shares, top-cost).

Pipeline: `check_local.py` → `export_snowflake.py` → `load_snowflake.py` → `build_osi.py` → `deploy_semantic_view.py` → `eval_analyst.py <label>`.

## Step 4: Japan (2026-10-31)
Article 2 now uses Snowflake as its presentation layer, so the NDB data followed (decisions.md, 2026-10-31).
- `export_snowflake.py` adds the JP schema and the Japanese vocabularies (table above); every table reads only its
  source graphs. It stores the graph's answers to all `queries/jp-*.rq` in `tables.json` (the reasoning query as its
  OWL definition spelled out) and checks that every product reaches the top class once.
- `load_snowflake.py` also verifies the total Japanese quantity and the masked cell count (25,939,035,814.92462
  units, 36,031 masked). That check caught NUMBER(18,2) rounding the five-decimal NDB quantities; now NUMBER(18,5).
- `build_osi.py` generates `semantic/japan-market.{osi.yaml,sql}`: 10 datasets (fact datasets national_value,
  prefecture_value, month_value, sex_age_value at class grain; product with the defined-class flags, substances and
  company; therapeutic_class, jp_drug_class, prefecture, care_setting, sex_age_group), 15 metrics, 46 synonyms,
  7 verified queries restating `queries/jp-*.rq`, company value lists generated from dm:partOfCorporateGroup.
  The generator now warns when two ontology terms share a label. It found 薬効分類 on both dm:TherapeuticClass
  and dm:JapaneseDrugClass; ontology 0.5.2 renames the former 薬効群 (altLabel ATC分類), so the views have 65 and 48
  synonyms.
- `queries/snowflake/jp-vs-connecticut-class-mix.sql` and `glp1-products-by-country.sql`: the cross-country
  questions in plain SQL.
- `deploy_semantic_view.py` deploys `JAPAN_MARKET` and `JAPAN_MARKET_OSI` next to the US views and checks all
  7 Japan verified queries (225 rows) and both SQL files against the graph: all match, on both views.
- `eval_analyst.py <label> --model jp`: five Japanese questions, 3 runs per view. Final (`analyst-eval-jp-final.json`),
  native / OSI: Tokyo value 3/3 · 3/3; 日本ベーリンガーインゲルハイム SGLT2 share 3/3 · 3/3; GLP-1 categories named
  3/3 · 3/3, counted 3/3 · 0/3; Mounjaro monthly totals 1/3 · 3/3 (native splits by strength; rows add up 3/3);
  class with the highest 75+ share (glinides, not DPP-4) 3/3 · 3/3.
- Fixes found by the evaluation (first run `jp`, then `jp-after`, `jp-after2`, `jp-after3`): company value lists
  with the Japanese subsidiaries as aliases (Analyst guessed 'Boehringer Ingelheim' / the subsidiary name: share
  2/3 · 0/3); `class_market_share` and `market_share` with precomputed denominators (it divided Boehringer's SGLT2
  sales by Boehringer's total: 78%); the instruction about the top class reworded (native added a top-class
  filter to a drug-class question and got no rows; OSI, without instructions, did not).

## Next
- Article 2 figures: Snowsight screenshots listed in `docs/article_2.md` (Figures 1, 5, 6, 7).
- Native-speaker review of the 12 new ja/zh property labels (ontology 0.5.1) and Japanese labels for the remaining 63 NUCC specialties in use (the Japanese answers fall back to English names for them).
- Optional: a Cortex Search service on `VOCAB.LABEL` for value-level altLabels (SGLT2i, グリフロジン).
- The article (third in the series): ontology-generated semantic layer; OSI keeps structure, metrics and descriptions but loses synonyms, instructions and verified queries, even in Snowflake's own export format; measured effect on Cortex Analyst.
