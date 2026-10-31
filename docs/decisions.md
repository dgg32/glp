# Modeling decisions

Short log of decisions that are not obvious from the code.

## 2026-10-14: Target platform is Stardog Cloud Free

Limits (stardog.com/stardog-cloud): 1M edges, 3 databases, 3 Voicebox databases, no backups.
Going over the quota has locked users out of their data, so the scripts plus the repo are
the only source of truth and the full dataset stays well under the cap.

Estimated size of the Connecticut 2024 dataset before the cuts below: ~366k triples.

## 2026-10-14: Three size cuts

1. **`dm:writes` is not stored.** Only `dm:prescribedBy` is asserted; `writes` is inferred by
   `owl:inverseOf`. Saves ~22k triples. Queries without reasoning use `^dm:prescribedBy`.
2. **Age 65+ figures are not modelled in RDF** (ontology 0.2.0 removed the `ge65*` properties).
   Saves ~110k triples. The columns stay in `data/clean/partd_claims.csv`.
   Trade-off: the SHACL rule "a count is present or its suppression flag is set" is now
   demonstrated with `totalBeneficiaries` / `beneficiaryCountSuppressed` only.
3. **IDMP-O is not loaded in full.** `scripts/extract_idmp_terms.py` copies only the terms we
   reference (5 terms, 26 triples since 2026-10-20, with IDMP-O's MIT notice) into
   `ontology/imports/idmp-o-1.4.0-extract.ttl`. Saves ~15k triples.

Estimated size after the cuts: ~245k triples (counted from data/clean). Each extra data
year adds ~236k (prescriptions + prescribers, if prescribers are not shared across years),
so two extra years (~720k) still fit under the 1M cap; three would not.

## 2026-10-14: IDMP-O version 1.4.0

1.4.0 is the newest public release. Releases reach the public GitHub repo one year after
members get them.

## 2026-10-14: Stardog Cloud Free smoke test passed (Stardog 12.1.4)

Run with `tests/stardog_smoke/` on a throwaway database:

1. Defined classes work with the default SL reasoner, including `owl:hasValue` inside nested
   `owl:someValuesFrom`, `owl:inverseOf` (writes inferred from prescribedBy) and the IDMP-O
   property chain: drA -> SGLT2Prescriber, drB -> GLP1Prescriber; nothing with reasoning off.
2. The SKOS roll-up chain works: tirzepatide has 1 class with reasoning off, 3 with it on.
3. SHACL works on Cloud Free via `VALIDATE ALL USING SHAPES GRAPH <...>`: both planted
   violations reported (pattern on dm:npi, minInclusive on dm:totalClaims).

So the design does not need Stardog rules or local pySHACL as fallbacks.

## 2026-10-14: SKOS vocabularies

- **Four schemes**: therapeutic classes (`vocab/therapeutic-class.ttl`), active substances
  (`vocab/substance.ttl`), indications (`vocab/indication.ttl`) and NUCC specialties
  (`vocab/nucc-specialty.ttl`), all built by `scripts/build_skos.py` from the curated CSVs in
  `vocab/src/` and the generated CSVs in `scripts/` (`therapeutic_classes.csv`, `substances.csv`,
  `indications.csv`, `labels_ja_zh.csv`).
- **Tirzepatide counts as a GLP-1 drug**: "dual GIP/GLP-1 receptor agonists" is placed under
  "GLP-1 receptor agonists". ATC puts tirzepatide in A10BX (other), so that class has no ATC
  exactMatch; a skos:scopeNote says so.
- **Codes are looked up, not typed**: RxNorm IDs and substance ATC codes come from RxNav,
  MeSH IDs from the MeSH SPARQL endpoint; responses are cached in `data/raw/{rxnav,mesh}/`.
  Class-level MeSH links are `skos:closeMatch` (pharmacological actions and chemical groups are
  not the same thing as a drug class); ATC and substance-level links are `skos:exactMatch`.
- **CMS spellings are `skos:hiddenLabel`s** on substances (e.g. "Insulin Glargine,hum.Rec.Anlog"),
  so they help term normalization without ever being displayed.
- **NUCC is not published.** The AMA/NUCC permission covers US products only, needs formal
  acceptance and forbids derivative works. `vocab/nucc-specialty.ttl` is a format-only conversion,
  generated locally and git-ignored; only the script is published. Six classifications that
  NUCC lists without a code of their own (e.g. Psychiatry & Neurology) are added as concepts
  from NUCC's Classification column so the hierarchy has three levels everywhere.
- **Japanese and Chinese labels** cover all classes and substances and the 20 most common
  specialties (94.5% of prescribers). They are marked with a skos:editorialNote as pending
  native-speaker review. Language tags are `ja` and `zh` (Simplified Chinese).

## 2026-10-14: Data to RDF (`scripts/build_rdf.py`)

- **One file and one named graph per source**: `graph/cms-partd-2024` (prescribers and
  prescriptions), `graph/npi-registry` (specialty links), `graph/drugsfda` (manufacturers),
  `graph/products` (curated product -> substance / indication links), `graph/provenance`
  (PROV-O: source URL, time and generating run for every graph). `data/rdf/manifest.csv`
  lists file -> graph for loading, with the ontology in `tag:stardog:api:context:schema`.
- **Pseudonymization**: prescribers are `d:hcp/<HMAC-SHA256(PSEUDONYM_KEY, NPI)[:16]>`; no names
  and no NPIs are written (checked: 0 NPIs in the output; surname matches were only town names).
  The key is in `.env`. The source is public and names prescribers, so this keeps identities out
  of the graph and the article, but it is not anonymization (ontology `dm:pseudonymousId` says so).
  `data/rdf/` is git-ignored; the scripts are published, the data is not.
- **Manufacturers** come from openFDA Drugs@FDA (application holder), not from SPL labels, which
  list repackagers. 33 of 51 products have one; multi-source generics have none. Byetta has two
  holders in Drugs@FDA (Amylin, AstraZeneca) and is linked to both.
- **Indications** are curated per brand: all products treat type 2 diabetes, insulins also
  type 1, Wegovy only chronic weight management.
- **Counts typed as `xsd:integer`** (Stardog canonicalizes integer subtypes anyway; the ontology range
  stays `xsd:nonNegativeInteger` and SHACL checks the range), costs and 30-day fills as `xsd:decimal`; blank
  values produce no triple.
- Size: 244k triples in total, all graphs included (Stardog Cloud Free limit: 1M).

## 2026-10-14: Loaded into Stardog Cloud (`scripts/load_stardog.py`)

- Database `glp`, loaded by the API user `glp_loader` (READ + WRITE on `db:glp` only; credentials
  in `.env`). One transaction clears and reloads every graph, then compares per-graph counts:
  244,257 triples in 10 named graphs, all matching.
- **Queries must name the graphs.** Stardog's default dataset is only the default graph, which is
  empty here, so queries use `FROM <tag:stardog:api:context:all>` (or Studio's graph selector set to
  all graphs). Enabling `query.all.graphs` on the database would also work but needs an admin.
- Reasoning on the real data: 2,701 SGLT2 prescribers and 2,362 GLP-1 prescribers inferred,
  under 1 s. The business query gives the same numbers in Stardog as locally (pyoxigraph).

## 2026-10-14: SHACL shapes as the modeling contract

- `shapes/diabetes-market-shapes.ttl` (37 constraints; 38 since 2026-10-20) is loaded into `graph/shapes` and run by
  `scripts/validate.py` (`VALIDATE ALL USING SHAPES GRAPH ...`, ~1 s; exit 1 on any violation).
  The summary goes to `docs/validation-report.md`, the full report to `data/validation/`.
- **Real data: 0 violations**, 17 warnings (13 prescribers without NPI Registry specialty,
  3 prescriptions with zero drug cost, Byetta with two application holders), 130 info
  (primary specialty "Student in an Organized Health Care Education/Training Program").
- **Every rule is proven to fire**: `tests/test_shapes_stardog.py` validates
  `tests/shacl/broken-examples.ttl` (one broken record per rule) in a temporary graph and
  checks that all messages appear (37 of 37 then, 38 of 38 since 2026-10-20).
- **Two Stardog 12 behaviours found by the shapes themselves:**
  1. Stardog stores integer subtypes canonically, so `"26"^^xsd:nonNegativeInteger` comes back
     as `xsd:integer` and an `sh:datatype xsd:nonNegativeInteger` check failed on all 22,034 rows.
     Counts are now written as `xsd:integer` and the range is checked with `sh:minInclusive`.
  2. `sh:pattern` on IRIs inside `sh:qualifiedValueShape` did not match; the RxNorm check is a
     SHACL-SPARQL constraint instead (SPARQL constraints are supported, verified with a probe).
- Severity is part of the contract: Violation = wrong data (blocks), Warning = needs a look,
  Info = known quirk that analyses should account for.

## 2026-10-14: Chatbot as an MCP server instead of a LangGraph agent

- `mcp_server/server.py` (MCP Python SDK 2.3, `MCPServer`, stdio) exposes `resolve_term`,
  `describe_model` and `run_sparql`. Any MCP client can use it; the client runs the conversation,
  so there is no agent loop or model choice to maintain here. A LangGraph agent could reuse the
  same tools later.
- The value over generic Stardog MCP servers is the semantic layer: term resolution through SKOS
  labels in three languages (including CMS hidden labels and full-width input) and a model
  description built live from the ontology plus the worked queries in `queries/`.
- Read-only in three layers: query-form check, Stardog's read endpoint, and a READ-only user
  (`STARDOG_READER_*` in `.env`; no fallback to the loader account).
- Queries run with `default-graph-uri=tag:stardog:api:context:all`, so the model never needs a
  FROM clause. Under the SPARQL protocol this empties the named-graph set, so internal queries
  that use GRAPH clauses run without it.
- `.mcp.json` is git-ignored: it holds credentials for other servers (e.g. Neo4j).

## 2026-10-14: SKOS concepts also carry rdfs:label

`scripts/build_skos.py` copies every `skos:prefLabel` to `rdfs:label` (~1,200 triples). Stardog's
`stardog:label`, which Voicebox uses to find entities by name, reads only `rdfs:label`, so Voicebox
found companies (rdfs:label) but no drug class or substance (skos:prefLabel only) and every total
came back 0. Other tools (Studio, WebProtégé) also display rdfs:label. The SKOS spec defines
skos:prefLabel as a subproperty of rdfs:label, so the copy adds no new meaning.
Also enabled on database `glp`: `voicebox.enabled=true` and `query.all.graphs=true`.

## 2026-10-15: Drug and product facts are looked up, not typed

The only curated drug list is `scripts/cms_generic_names.csv`: the 32 CMS Part D spellings (found
by probing the CMS API) plus a search-term override for the three that RxNorm cannot match
("Exenatide Microspheres", "Insulin Glargine,hum.Rec.Anlog", "Dapaglifloz Propaned/Metformin";
RxNorm's fuzzy match for the last one is "propane"). Two scripts derive everything else:

`scripts/resolve_drugs.py` -> `scripts/drugs.csv`, `scripts/substances.csv`
- CMS name -> RxCUI (RxNorm exact match, else approximate) -> ingredients (RxNorm IN). The
  substance id is the ingredient name in camelCase.
- Ingredient -> its own level-5 ATC code in RxNorm (metformin A10BA02). Level 4 of the code
  is matched to the `atc` column of `vocab/src/therapeutic_classes.csv`.
- Tirzepatide's ATC is A10BX ("other"), so its class comes from the FDA Established Pharmacologic
  Class "GIP Receptor Agonist" (N0000194015, RxClass; `fda_epc` column).
- English synonyms (skos:altLabel) are RxNorm synonyms (glyburide: glibenclamide) and
  precise-ingredient names (salts, biosimilar suffixes); CMS spellings of single-ingredient
  generics become skos:hiddenLabel. MeSH IDs are looked up by the RxNorm name or a synonym.
- RxClass's own ATC lookup is not used: it credits combination codes to each ingredient, which
  puts liraglutide among the long-acting insulins (via Xultophy).
- An ingredient that lands in no diabetes class stops the run (guards against bad fuzzy matches).

`scripts/resolve_products.py` -> `scripts/products.csv`
- CMS brand -> RxNorm brand name (BN): the longest leading run of words that is a BN with the
  same ingredients ("Victoza 2-Pak" -> Victoza). No BN = multi-source generic, no manufacturer.
- Indications come from the openFDA drug labels of the brand's SBDs (or, for generics, of the
  SCDs containing all the ingredients), prescription labels with the same number of substances
  only. Sentences that limit use ("Not for treating type 1 diabetes") are dropped, the rest is
  matched against the `match_terms` and `implied_by_terms` columns of the generated
  `scripts/indications.csv` (MeSH entry terms), and an indication is kept
  when more than half of the labels state it ("with diabetes mellitus", as in insulin labels,
  counts as type 1 and type 2).
- Bydureon BCise is discontinued and has no openFDA label; it falls back to labels of products
  with the same ingredients (`label_source` column).
- `is_obesity_brand` in the cleaned claims now means "labels state no diabetes indication"
  (Wegovy), instead of a hard-coded brand list.

Check against the earlier hand-typed tables: identical substances (32 names), classes and ATC
codes (21 substances), CMS hidden labels, indications (51 products) and manufacturers; the
rebuilt RDF differs only in provenance and in more altLabels from RxNorm (e.g. canagliflozin
anhydrous, insulin glargine-yfgn); "exenatide microspheres" is now only a hiddenLabel.
`fda_brand` loses suffixes (JANUMET XR -> JANUMET), which does not change the Drugs@FDA sponsors.

Still curated at the time: the class tree, the indication concepts and the ja/zh labels (see the
2026-10-15 entry on vocabularies below), and `vocab/src/sponsor_lei.csv` (see the GLEIF entry below).

**ATC source: RxNorm, not KEGG or WHO.** KEGG's copy of the ATC tree (br08303) was tried and
gave the same codes for all 21 substances, and both were current (RxNorm 05-Oct-2026, KEGG BRITE
2026-10-13). KEGG covers more drugs (non-US ones such as imeglimin, Japan only), but its REST API
is free for academic use only, so it is not used. The authoritative WHO ATC/DDD index costs
about EUR 200 and is out of scope. RxNorm only has ATC codes for US-marketed drugs, which is
enough for US Part D data; a Japan extension would need another source.

## 2026-10-15: Companies come from GLEIF; only the sponsor -> LEI step is curated

`vocab/src/organizations.csv` (regexes over Drugs@FDA sponsor names plus hand-typed names) is
replaced by `scripts/resolve_organizations.py` -> `scripts/organizations.csv`:

- Curated: `vocab/src/sponsor_lei.csv`, one row per Drugs@FDA sponsor name with the applicant's
  full name, a `match` type, the LEI, the GLEIF search that proves it, and a note. Automatic
  GLEIF search was tried and rejected: Drugs@FDA abbreviates names ("MSD", "NOVO", "JANSSEN
  PHARMS"), and GLEIF's autocompletion mapped 5 of 13 sponsors to the wrong entity (MSD -> MSD
  AG, NOVO -> "NOVO 1", SANOFI AVENTIS US -> a pension trust).
- `match=applicant` (AstraZeneca AB, Lilly, Janssen, Merck Sharp & Dohme, Mylan): the applicant
  has a current LEI; a GLEIF legal-name search must find that LEI under exactly that name.
- `match=group` (Boehringer, Novo Nordisk, Sanofi): the applicant has no current LEI
  (Boehringer Ingelheim Pharmaceuticals, Inc. and Novo Nordisk Inc. have none; the two Sanofi US
  entities have lapsed ones). The row maps straight to the group's top-level LEI, which must have
  no parent and be the ultimate parent named most often among GLEIF autocompletion matches for
  the group name (Boehringer 10/10, Sanofi 6/10, Novo Nordisk 3/8; the other Novo matches are
  subsidiaries or securities GLEIF records without a parent, one each). No stand-in subsidiary
  is chosen.
- `match=none` (Amylin): no LEI and no GLEIF match.
- Every run re-runs these searches (cached in `data/raw/gleif/`) and stops if the evidence no
  longer holds. Hand-made parts that remain: expanding sponsor names where Drugs@FDA lists no
  usable labeler (Amylin, Mylan, Sanofi US Services) and choosing the group search term.
- From the GLEIF API: legal name, status and country, and the **ultimate parent**, which is the
  company. Organization IRIs are `organization/<LEI>`, with `dcterms:identifier` (the LEI) and
  `rdfs:seeAlso` to the GLEIF record. English rdfs:label is the GLEIF legal name; applicant entity
  names become skos:altLabel and Drugs@FDA spellings skos:hiddenLabel, so "boehringer" still
  resolves. Japanese and Chinese names stay curated (`vocab/src/organization_labels_ja_zh.csv`).
- Amylin (dissolved 2012) has no LEI and keeps its Drugs@FDA name, so Byetta still has two
  application holders (the SHACL warning still fires).
- Same 33 products linked to the same 9 groups as before. Visible changes: legal names in English
  ("C.H. Boehringer Sohn AG & Co. KG", "MERCK & CO., INC."), Janssen is now shown as its parent
  Johnson & Johnson and Mylan as Viatris; IRIs changed from `organization/boehringerIngelheim` to
  `organization/529900P5FAANZASUYL28` (tests/test_mcp_server.py updated).

## 2026-10-15: Class tree, indications and ja/zh labels come from RxClass, UMLS, MeSH and Wikidata

`scripts/resolve_vocab.py` (runs first) and `scripts/fetch_wikidata_labels.py` (after the other
resolvers) replace most of the curated vocabulary tables.

**Drug classes** (`scripts/therapeutic_classes.csv`). Curated: which classes exist (stable id, which
is the IRI, plus ATC code), their ja/zh labels, and the project class (dual GIP/GLP-1 agonists,
defined by FDA EPC N0000194015 and placed under GLP-1 receptor agonists; its English synonyms,
definition and scope note stay curated). Looked up: hierarchy and English prefLabel from the
RxClass ATC tree (WHO capitals in levels 1-3 put in sentence case, e.g. "Sodium-glucose
co-transporter 2 (SGLT2) inhibitors"; the project class is labelled with its EPC name). The MeSH
link, with MeSH entry terms as English altLabels and the MeSH scope note as definition, comes from
the first of: (1) a MeSH descriptor that NLM's Metathesaurus editors relate to the ATC class in UMLS
(source MTH; biguanides, sulfonylureas, thiazolidinediones, DPP-4 inhibitors); (2) the MeSH
pharmacological action held by every member substance that has one and by no other substance
(GLP-1 receptor agonists, SGLT2 inhibitors); (3) a curated `mesh_id` (drugs used in diabetes,
insulins, long-acting insulins). `mesh_source` records which. All nine links equal the earlier
hand-picked ones. Rejected: the UMLS crosswalk ATC -> MSH returns nothing for A10, because UMLS
keeps ATC classes as concepts of their own ("Sulfonylureas for blood glucose lowering"), separate
from MeSH ("Sulfonylurea Compounds"); matching ATC names to MeSH labels found 2 of 10.
The UMLS step needs `UMLS_API_KEY` in `.env` (format `KEY=value`).
Old curated English short forms ("SGLT2 inhibitors", "gliptins", "SU") are gone unless MeSH has
them as entry terms; `drug_class` in the cleaned claims now uses the ATC names.

**Indications** (`scripts/indications.csv`). Curated: the in-scope MeSH descriptors (type 2
diabetes D003924, type 1 diabetes D003922, obesity D009765) and fallback ja/zh labels. From MeSH:
English label, entry terms (altLabels, and the terms looked for in FDA labels instead of the
earlier hand-written regexes), scope note as definition, and the entry terms of broader
descriptors that group several in-scope ones ("Diabetes Mellitus" implies type 1 and type 2 in
insulin labels; single-parent links such as Autoimmune Diseases -> type 1 are ignored).
"Chronic weight management" is not a MeSH concept, so `ChronicWeightManagement` became `Obesity`
(Wegovy). Product indications are unchanged otherwise. While checking, a sentence-splitting bug
was fixed: some labels run "... type 2 diabetes mellitus Limitations of Use: ..." together, which
dropped the indication sentence (liraglutide T2DM votes 13/21 -> 16/21).

**ja/zh labels** (`scripts/labels_ja_zh.csv`). Wikidata (CC0) items are found by identifier only
(RxNorm CUI P3345, LEI P1278, MeSH P486, ATC P267). Probe results: Japanese substance names
16-17/21, matching the curated drafts; Chinese substance names mostly plain "zh" mixing
Traditional script and Taiwanese names (利拉利汀 vs mainland 利格列汀); class links often point to
chemical families (A10BA -> biguanide compounds, A10AE -> lente insulin); companies 7/8; diseases
4/4; no NUCC identifier. Policy: Japanese from Wikidata for substances, companies, indications;
Simplified Chinese (zh-hans/zh-cn only) from Wikidata for companies and indications; curated
otherwise, and where a curated row sets `keep_curated` after review (Merck & Co.: MSD / 默沙东;
Wikidata's 默克药厂 is the usual name of Merck KGaA). Every concept gets a skos:editorialNote saying
where its ja/zh labels come from, substances and indications get skos:exactMatch to the Wikidata
item, companies rdfs:seeAlso. `docs/label-review.md` lists every curated label that disagrees with
Wikidata, for native-speaker review. The scheme-level review note now has a fixed draft date
(2026-10-14) instead of the build date.

## 2026-10-15: Ontology 0.4.0 and label review

- Ontology 0.4.0 changes definitions only: `dm:Indication` (MeSH descriptors stated in FDA labels;
  example "obesity" instead of "chronic weight management") and `dm:Organization` (corporate group
  of a Drugs@FDA application holder, identified by the LEI of its GLEIF ultimate parent). No axiom
  changed, so reasoning results are unchanged. `ontology/diabetes-market.rdf`, which was still
  0.1.0, is now regenerated from the Turtle file and checked to be isomorphic.
- `docs/label-review.md` (24 disagreements between curated ja/zh labels and Wikidata) was reviewed
  by Sixing Huang and accepted as is: the label the graph uses in each row is kept.

## 2026-10-15: Provenance for every graph, and a SHACL gate before commit

- `scripts/provenance.py` (called by `build_rdf.py`) now describes all loaded graphs, including the
  vocabularies, the schema graph and the shapes, not only the four data graphs. Each graph has its
  source snapshots (`prov:specializationOf` the API, `dcterms:hasVersion` where the source
  publishes a release, a retrieval activity timed from the cached responses), its curated input
  files (with sha256), a content hash (sha256 of canonical N-Triples, stable across rebuilds) and
  a triple count. The resolvers cache the RxNorm version and the openFDA label index date so the
  release is known offline. Query: `queries/provenance-of-a-graph.rq`.
- `load_stardog.py` validates the uncommitted state with `VALIDATE` inside the load transaction and
  rolls back on any `sh:Violation` (tested 2026-10-15: Stardog sees uncommitted data inside the
  transaction and not outside). Warnings and info do not block. `tests/test_load_gate.py` proves the
  gate blocks an invalid prescription.
- `docs/governance.md` is the write-up, including the modelling standards.

## 2026-10-20: Fixes from the bug hunt (BUG.md)

- **SHACL now agrees with OWL under reasoning.** The substance rule used `sh:maxCount 1` on
  `dm:inTherapeuticClass`, but the property chain adds every ancestor class, so validating with
  reasoning on gave 21 false violations. The rule is now two: `sh:minCount 1` ("A substance needs a
  therapeutic class.") and a SPARQL constraint that counts only the most specific classes (those
  with no narrower class of the same substance), which gives the same answer with reasoning off and
  on. Rejected: scoping the check to the substance graph (the broken-examples test runs in a
  temporary graph) and splitting the property in two (it would break the "naive query finds
  metformin" behaviour of the chain). 38 rules now; `tests/test_shapes_reasoning.py` validates the
  live data both ways.
- **MCP specialty guidance**: `dm:hasSpecialty` to find prescribers of a specialty (all NPI
  Registry taxonomies), `dm:hasPrimarySpecialty` for shares by specialty (each prescriber once).
- **Provenance records the generated intermediates** (`GENERATED` in `scripts/provenance.py`), each
  with a sha256. The git commit is recorded only when the build runs in a git checkout; this
  directory is not one yet, so governance.md now says so.
- **IDMP-O extract no longer copies `rdfs:label`** for terms the ontology already labels; the two
  files had given each of the five terms an `@en` and an untagged label.
- Network retries in `resolve_organizations.gleif()` and `build_rdf.drugsfda_sponsors()` now also
  cover URLError and timeouts; a failing rollback in `load_stardog.py` no longer hides the original
  error.

## 2026-10-20: Round 2 of the bug hunt

- The project is now a git repository (github.com/dgg32/glp). The provenance graph records the
  build's commit, suffixed `-dirty` when tracked files had uncommitted changes, so a graph built from
  an edited tree never claims a clean commit. Rebuild and reload after committing to record a clean one.
- Shapes 0.2.0 (`owl:versionIRI`, `owl:priorVersion`, `skos:changeNote`), versioned like the ontology.
- `build_rdf.py` stops if a prescriber's claim rows disagree on city or CMS specialty, instead of
  keeping the first row's value (latent: no such prescriber in the 2024 data).
- Not changed: `clean_data.py`'s rows-per-class report stays keyed by ATC class name (BUG.md L7).
  Combination products have composite class names ("Biguanides + DPP-4 inhibitors") with no single
  class id, and the report is an internal check, not a published table.

## 2026-10-25: Japan extension (NDB Open Data)

Plan and triple budget: `japan_extension.md`. Same database (`glp`), new named graphs, so both
countries share the substance and class vocabularies.

- **Scope**: all of 薬効分類 396, every insulin (YJ 2492) and the GLP-1 / GIP-GLP-1 ingredients of
  249 by YJ ingredient prefix: 510 strength-level products, 286 generics. Glucagon (722) is out.
  Every cell is kept (zeros and masked cells too): 150,288 observations.
- **RDF Data Cube** for the NDB tables: one `dm:QuantitySlice` per product x care setting x dimension
  (4,464) holds product, setting, slice key and national total, so a cell costs 3 triples. A flat
  design (~6 per cell) would not fit the 1M-edge limit next to Connecticut. Observations are not typed;
  `qb:observation`'s range types them under reasoning. Total load: 734,101 triples.
- **Masking as SDMX confidentiality** (`sdmx-attribute:confStatus sdmx-code:confStatus-C`), the
  generic code, because the files do not say whether a cell was masked as small (primary) or to
  protect another (secondary). 429 national totals are masked too (small products, mostly inpatient).
- **New property `dm:aboutProduct`** rather than reusing `dm:forProduct`, whose domain
  `dm:Prescription` would make every slice a prescription under reasoning.
- **Substances outside RxNorm**: RxNorm covers US drugs, so 12 of the 47 substances (teneligliptin,
  ipragliflozin, imeglimin, ...) are looked up in UMLS (exact name, ATC from the UMLS ATC source) and
  matched with `https://identifiers.org/umls:` IRIs; Wikidata labels are found by UMLS CUI (P2892).
  The SHACL rule became "RxNorm, or UMLS when RxNorm does not have it".
- **Classification fallbacks**, in order: several ATC classes -> their common broader class (human
  insulin, lispro and aspart are "insulins and analogues": the formulation, not the substance, makes
  them fast-acting or premixed); ATC level-5 member codes of a project class; FDA EPC; a MeSH
  pharmacological action held by one class only (anagliptin); a curated fallback with a reason
  (glyclopyramide, tofogliflozin, trelagliptin, omarigliptin have no ATC code and no usable MeSH action).
- **Two project classes from A10BX** (other): glinides (repaglinide, nateglinide, mitiglinide; label
  from the FDA EPC "Glinide") and glimins (imeglimin; curated label). Japan treats both as classes;
  ATC does not. Four ATC classes added: A10AB, A10AC, A10AD, A10BF. US results do not change: no US
  substance changed class (checked by diffing scripts/substances.csv).
- **Crosswalk 薬効分類 <-> ATC computed, not curated** (`vocab/jp-drug-class.ttl`, rule in
  `scripts/build_ndb.py`): 396 narrowMatch every oral class, relatedMatch GLP-1 and long-acting
  insulin (the two insulin/GLP-1 combination pens are 396), broadMatch A10B; 249 narrowMatch
  fast-acting insulin and GIP/GLP-1, relatedMatch GLP-1 and long-acting insulin. Nothing is claimed
  about all of 249, which is only partly in scope.
- **Products are strength-level** (one per receipt code), as NDB counts them; US products are
  brand-level. Compare through substances and classes. Value = quantity x NHI price; the 11th
  release carries the 2026-09-02 prices, so it is FY2024 volume at current prices.
- **Marketing authorization holders** from the NHI price list (the 2026-10-14 list, the 2025-03-19
  list for 92 products delisted since). 203 unified-name generics (統一名収載) have no holder.
  Japanese subsidiaries of the seven groups already in the US graph link to them with
  `dm:partOfCorporateGroup`; English names are curated (`vocab/src/jp_manufacturers.csv`).
- **Indications** per YJ ingredient (`vocab/src/ndb_ingredients.csv`, diabetes indications only) with
  a product-level override for Wegovy (obesity), which shares Ozempic's YJ ingredient code. Japan-only
  indications (CHF and CKD for empagliflozin and dapagliflozin, type 1 add-on for some SGLT2
  inhibitors) are not modelled yet.
- **Checks proven on the data before writing the shapes**: every slice without masked cells sums
  exactly to its national total (1,378 of 1,378), no sum exceeds its total, and every unmasked cell
  is 0 or at least the masking threshold (1,000 oral, 400 injection).
- Ontology 0.5.0, shapes 0.3.0 (both additive except the RxNorm rule and the CMS generic name rule,
  which became "CMS generic name XOR YJ code").

## 2026-10-25: Local checks first; AllegroGraph Cloud as second target

- **Check locally, publish once.** The Stardog Cloud Free database was corrupted after its disk filled
  (repeated full reloads, reasoning-on validations). `scripts/check_local.py` now runs budget, SHACL
  (pyshacl), rule coverage, OWL 2 RL closure + SHACL and all queries (pyoxigraph) locally;
  `load_stardog.py` and `load_allegrograph.py` refuse files it has not passed and rewrite only graphs
  whose content hash differs from the server's provenance graph.
- **AllegroGraph Cloud 9.1.0** while Stardog Cloud is recreated: repository `glp` in the root catalog,
  user `glp_loader` (read + write on `glp` only), `glp_reader` (read only); `scripts/setup_allegrograph.py`.
  Same named graphs and IRIs (including the schema graph `tag:stardog:api:context:schema`, kept for
  query portability). Loaded in one session (autoCommit off): 734,106 triples in 1 min 50 s.
- **Portable SPARQL, three engine quirks found by running the same 14 queries on three engines:**
  Oxigraph's fixed-point xsd:decimal overflows on quantity x price (cast to xsd:double) and errors on
  0 / decimal; AllegroGraph 9.1 fails on ROUND over aggregates of IF() values (three share queries now
  return unrounded percentages, rounded for display) and rejects non-ASCII variable names such as
  `?専門分野` (the runner substitutes ASCII names and maps the columns back). After that, all 14 give
  identical results locally and on AllegroGraph, and the same as Stardog up to rounding.
- Not done yet on AllegroGraph: reasoning (RDFS++ only at query time; the defined classes need OWL
  restrictions and property chains) and the MCP server's backend.
- **2026-10-26: AllegroGraph dropped.** The server was removed; `setup_allegrograph.py`,
  `load_allegrograph.py` and `run_queries.py --ag` are deleted, and the three share queries have their
  `ROUND` back (Stardog and Oxigraph handle it). The Oxigraph `xsd:double` casts stay.

## 2026-10-31: Japan in Snowflake; Snowflake as the presentation layer of article 2
- Article 2 shows the data through Snowflake (worksheets, semantic view, Cortex Analyst) instead of Stardog
  Studio. The RDF graph stays the source of truth, built and checked locally; Stardog stays the SPARQL endpoint
  of the MCP server.
- **JP schema** from the NDB graphs (`export_snowflake.py`): PRODUCT, PRODUCT_SUBSTANCE, PRODUCT_CLASS,
  ORGANIZATION (CORPORATE_GROUP_ID -> US.ORGANIZATION, i.e. dm:partOfCorporateGroup), NATIONAL_TOTAL (equal in
  all three breakdowns, checked), QUANTITY (the Data Cube as one row per cell; masked cells kept with
  IS_MASKED). VOCAB gains JP_DRUG_CLASS, JP_CLASS_MATCH (the crosswalk with its evidence), PREFECTURE,
  CARE_SETTING, SEX_AGE_GROUP. Each table now reads only its source graphs (pyoxigraph `default_graph`), so the
  NDB products cannot leak into US tables.
- Quantities are NUMBER(18,5): NDB has up to five decimals. NUMBER(18,2) passed the rounded parity checks but
  failed the loader's exact total (0.88 units), which is why the loader now checks JP totals too.
- **JAPAN_MARKET semantic view** from the same generator: one fact dataset per Data Cube breakdown
  (qb:sliceStructure becomes the schema, so breakdowns are never added together), at the grain product x
  setting [x cell] x class; all-drug metrics read the top class, which every product reaches once (checked by
  the export). Share metrics divide by a class or market total precomputed in the view, so a company filter
  cannot shrink the denominator (Analyst computed Boehringer's SGLT2 share as 78% of its own sales before).
- Cross-country questions are plain SQL (`queries/snowflake/`), because a semantic view holds one model; the
  deploy checks them and all seven Japan verified queries against the graph's SPARQL answers (225 rows).
- The generator now reports labels that two ontology terms share. It found dm:TherapeuticClass and
  dm:JapaneseDrugClass both labelled 「薬効分類」@ja, so in the Japan view the synonym went to the ATC-based class
  tree. Ontology 0.5.2: 薬効分類 stays with dm:JapaneseDrugClass (it is the name of the 日本標準商品分類
  categories); dm:TherapeuticClass becomes 薬効群 with skos:altLabel ATC分類 (not the prefLabel: glinides and
  glimins are project classes, so the tree is ATC-based, not pure ATC). The generator reads skos:altLabel too.
