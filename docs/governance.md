# Governance

How this knowledge graph stays trustworthy: where every fact comes from, what is checked before data
goes live, how changes are versioned, and which rules a contributor follows. Every claim below points
to the code or file that enforces it.

The short version:

1. **Facts are looked up, not typed.** Drug, product, company, class and indication facts come from
   public APIs (RxNorm, MeSH, UMLS, openFDA, GLEIF, Wikidata). What cannot be looked up is kept in
   a few small curated tables, each with the reason and, where possible, evidence the build re-checks.
2. **Every graph says where it came from.** A PROV-O record per named graph lists its source
   snapshots (with release), its curated and generated inputs (each hashed) and a content hash.
3. **Nothing breaks the contract and goes live.** The SHACL shapes are validated inside the load
   transaction; a single violation rolls the whole load back.
4. **Changes are versioned.** The ontology has semantic versions with change notes; data and
   vocabularies are identified by content hashes and, when built from a git checkout, the build's
   git commit.

## 1. Where each fact comes from

| Fact | Source | How | Curated part |
|---|---|---|---|
| Prescriptions (claims, cost, fills) | CMS Part D, data year 2024 | API download, one state | none |
| Prescriber specialty | NPI Registry → NUCC taxonomy | API per NPI | none |
| Generic name → active substances | RxNorm | exact, else approximate match; ingredients (IN) | the 32 CMS spellings to download, 3 search-term overrides |
| Substance → ATC code, synonyms | RxNorm | ATC property, synonyms, salt names | none |
| ATC code → drug class | RxClass ATC tree | level 4 of the code | which classes exist (ids) |
| Tirzepatide's class | FDA EPC via RxClass | ATC files it under "other" | placing dual GIP/GLP-1 agonists under GLP-1 (decision) |
| Class hierarchy, English names | RxClass ATC tree | tree walk | none |
| Class ↔ MeSH link, synonyms, definition | UMLS (NLM editors' relations), MeSH | 1. UMLS, 2. shared pharmacological action, 3. curated | 3 of 10 links (top class, two insulin classes) |
| Brand → RxNorm brand | RxNorm | longest leading run of words that is a brand with the same ingredients | none |
| Product → indications | openFDA drug labels, MeSH | MeSH entry terms in the label's indications, majority vote over labels | which MeSH descriptors are in scope (3) |
| Product → manufacturer | Drugs@FDA | application holder | none |
| Application holder → company | GLEIF | ultimate parent of the holder's LEI | sponsor name → LEI (13 rows, evidence re-checked) |
| Japanese and Chinese labels | Wikidata (CC0), by identifier | RxNorm CUI, LEI, MeSH ID | labels Wikidata lacks or gets wrong; class and specialty labels |

Each lookup was compared with the earlier hand-made tables when it replaced them; all matched
(see [decisions.md](decisions.md), 2026-10-15). The failures are part of the record too: RxNorm's
fuzzy match turns "Dapaglifloz Propaned/Metformin" into *propane*, GLEIF's search turns "SANOFI
AVENTIS US" into a pension trust, and the UMLS ATC→MeSH crosswalk is empty for every diabetes class.
Each is caught by a check, not by luck.

### Curated inputs

The register of everything that is typed by hand, why, and how it is checked. Each file's hash is
recorded in the provenance graph.

| File | Contents | Why it cannot be looked up | Check |
|---|---|---|---|
| `scripts/cms_generic_names.csv` | 32 CMS spellings, 3 RxNorm search overrides | CMS abbreviates beyond what RxNorm matches | every ingredient must land in a diabetes class, or the build stops |
| `vocab/src/therapeutic_classes.csv` | class ids and ATC codes; the dual GIP/GLP-1 class; 3 MeSH ids; ja/zh labels | ids are IRI design; the GIP/GLP-1 placement is a modelling decision | ATC parent must exist; a curated MeSH id that disagrees with an API link stops the build |
| `vocab/src/indications.csv` | 3 in-scope MeSH descriptors, fallback ja/zh labels | scope decision | descriptors must exist in MeSH |
| `vocab/src/sponsor_lei.csv` | Drugs@FDA sponsor → LEI, match type, GLEIF search, note | Drugs@FDA abbreviates names; GLEIF search maps 5 of 13 wrongly | the GLEIF search in each row is re-run on every build |
| `vocab/src/*_ja_zh.csv` | Japanese and Chinese labels | no free API for class or specialty names | compared with Wikidata; disagreements listed in [label-review.md](label-review.md) |
| `ontology/`, `shapes/` | ontology and SHACL shapes | they are the model | tests (section 3) |

## 2. Provenance in the graph

`data/rdf/provenance.ttl` (built by [scripts/provenance.py](../scripts/provenance.py)) describes
every named graph that is loaded, in PROV-O:

- **Source snapshots:** one `prov:Entity` per source as retrieved for this build,
  `prov:specializationOf` the API, with `dcterms:hasVersion` where the source publishes a release
  (RxNorm 05-Oct-2026, UMLS 2026AA, GLEIF golden copy 2026-10-14, openFDA 2026-10-14, NUCC 261,
  IDMP-O 1.4.0) and a retrieval activity whose start and end come from the cached responses.
  MeSH, Wikidata and the NPI Registry publish no release identifier, so only the retrieval window
  is recorded.
- **Graphs:** `prov:wasDerivedFrom` their source snapshots, curated input files and generated
  intermediate files, `prov:wasGeneratedBy` the build (with its git commit when the build runs in a
  git checkout, suffixed `-dirty` if tracked files had uncommitted changes; `provenance.py` omits it
  outside a checkout), a triple count and a content hash
  (`dcterms:identifier`, sha256 of the canonical N-Triples, stable across rebuilds that change
  nothing). The schema graph also carries the ontology version.
- **Curated files:** a `prov:Entity` each, with its sha256 and author.
- **Generated files** (the resolved CSVs in `scripts/` and the cleaned tables in `data/clean/`): a
  `prov:Entity` each, with its sha256, `prov:wasGeneratedBy` the build. A change in an intermediate
  (say, a new indication from a changed openFDA label) shows up here, not only in the final graph
  hash.

All API responses are cached in `data/raw/`, so a rebuild is offline and reproduces the same graphs;
deleting a cache folder refreshes that source. Asking the graph where a graph came from is one query,
[queries/provenance-of-a-graph.rq](../queries/provenance-of-a-graph.rq):

| input | release | retrieved / generated |
|---|---|---|
| GLEIF LEI records | 2026-10-14T16:00:00Z | 2026-10-15T02:14:42Z |
| Wikidata (CC0), labels by identifier | | 2026-10-15T02:35:08Z |
| openFDA Drugs@FDA | 2026-10-14 | 2026-10-15T01:43:35Z |
| scripts/labels_ja_zh.csv (generated, sha256 recorded) | | build time |
| scripts/organizations.csv (generated, sha256 recorded) | | build time |
| vocab/src/organization_labels_ja_zh.csv (curated, sha256 recorded) | | |
| vocab/src/sponsor_lei.csv (curated, sha256 recorded) | | |

The full output, with the hashes, is in [query-results.md](query-results.md).

Inside the vocabularies, provenance goes down to the label: every concept has a `skos:editorialNote`
saying whether its Japanese and Chinese labels come from Wikidata (with the item) or are curated
and pending review, and substances, indications and companies link to their Wikidata items.

## 3. The modelling contract and the quality gate

[shapes/diabetes-market-shapes.ttl](../shapes/diabetes-market-shapes.ttl) is the contract between
the pipeline and everyone who queries the graph: a product has at least one substance, an NPI has 10
digits, every concept has exactly one English prefLabel, counts are non-negative, a beneficiary count
is present or flagged as suppressed, and more.

| Guarantee | Enforced by |
|---|---|
| Live data has no violations | [load_stardog.py](../scripts/load_stardog.py) runs `VALIDATE` on the uncommitted state inside the load transaction and rolls back on any `sh:Violation` |
| The gate really blocks | [tests/test_load_gate.py](../tests/test_load_gate.py) adds an invalid prescription in a transaction; the gate reports 7 violations and the rollback leaves nothing behind |
| Every rule can fire | [tests/test_shapes_stardog.py](../tests/test_shapes_stardog.py): planted errors trigger 38 of 38 rules |
| OWL and SHACL agree | [tests/test_shapes_reasoning.py](../tests/test_shapes_reasoning.py) validates the live data with reasoning off and on; both give 0 violations, so no shape relies on facts the reasoner would contradict |
| Warnings are visible | [validate.py](../scripts/validate.py) writes [validation-report.md](validation-report.md): currently 0 violations, 17 warnings (13 prescribers missing from the NPI Registry, 3 zero-cost rows, Byetta's two application holders), 130 info |
| What was loaded is what was built | the loader compares the triple count of every graph in Stardog with the local files |

Warnings and info results do not block a load: they describe real properties of the source data,
not pipeline errors.

## 4. Versioning

- **Ontology:** semantic versions with `owl:versionIRI`, `owl:versionInfo`, `owl:priorVersion` and
  a `skos:changeNote` per release ([diabetes-market.ttl](../ontology/diabetes-market.ttl), now
  0.4.0). A minor version changes axioms or properties (0.2.0 removed the age 65+ properties, 0.3.0
  added the pseudonym); a definitions-only change is still a release, because definitions are part
  of the contract (0.4.0). The RDF/XML copy is regenerated from the Turtle file and checked to be
  isomorphic.
- **Data and vocabularies:** identified by their content hash and (from a git checkout) the build's
  git commit in the provenance graph, and by the source releases they were derived from. Two builds with the same
  hash are the same graph.
- **Decisions:** [decisions.md](decisions.md) records every non-obvious choice with its date,
  including the rejected alternatives.

## 5. Modelling standards

The conventions a contributor follows when changing the model or adding a source.

**Identifiers**
- IRIs live under `https://dgg32.github.io/glp/`: `ontology#` for classes and properties,
  `vocab/<scheme>/<id>` for SKOS concepts, `data/<type>/<id>` for instances, `graph/<name>` for
  named graphs.
- Concept ids are stable names (`SGLT2Inhibitor`), never labels; renaming one is a breaking change.
- Instances use an authoritative identifier where one exists: companies use their LEI
  (`data/organization/529900P5FAANZASUYL28`), specialties their NUCC code. Prescribers use a keyed
  hash, never the NPI.

**Labels**
- Exactly one `skos:prefLabel` per language per concept (checked by SHACL for English); synonyms are
  `skos:altLabel`; source spellings that should match but never display (CMS's "Metformin Hcl") are
  `skos:hiddenLabel`.
- English labels come from the source of the concept (ATC, MeSH, RxNorm, GLEIF), not from us.
- Every prefLabel is mirrored to `rdfs:label`, because many tools (including Stardog's entity lookup)
  read only that.

**Links to other vocabularies**
- `skos:exactMatch` only when the identifier denotes the same thing (substance ↔ RxNorm ingredient,
  class ↔ ATC code, indication ↔ MeSH descriptor); `skos:closeMatch` when it is related but not the
  same (class ↔ MeSH pharmacological action or chemical group).
- External ontology terms (IDMP-O, OMG Commons) are referenced and declared, not imported (MIREOT);
  `ontology/imports/` holds only the terms used.

**Graphs**
- One named graph per source; the provenance graph describes all of them.
- Data that is derived (inferred class membership, `dm:writes`) is left to the reasoner, not stored.

**Adding a source** (checklist)
1. Fetch it in a script that caches every response in `data/raw/<source>/`.
2. Resolve entities by identifier where possible; if a name match is unavoidable, add a check that
   stops the build on an implausible match.
3. Put anything curated in a small file under `vocab/src/` or `scripts/` with a note per row, and
   compare it with the API result when one exists.
4. Write it to its own named graph; add the source and its curated inputs to `LINEAGE` and `SOURCES`
   in [provenance.py](../scripts/provenance.py).
5. Add SHACL shapes for its invariants and a planted error per shape in `tests/shacl/`.
6. Record the decision in [decisions.md](decisions.md).

## 6. Privacy and access

- **Pseudonymization by design:** the source data names real doctors. NPIs and names never enter the
  RDF; prescribers are `data/hcp/<HMAC-SHA256(key, NPI)[:16]>`, with the key in `.env`.
- **Re-identification risk is acknowledged:** CMS publishes the source file, so a determined reader
  could match claim counts. The generated RDF, the raw downloads and the cleaned tables are therefore
  not published (`.gitignore`); only the code and the curated tables are.
- **Read-only access for AI clients:** the MCP server is read-only in three layers: only
  SELECT/ASK/CONSTRUCT/DESCRIBE pass its query check, queries go to Stardog's read endpoint, and it
  logs in as a separate user with READ permission only. Its test proves the first layer (`DROP ALL`
  is rejected); the other two are configuration.
- **Secrets:** credentials and API keys live only in `.env` (git-ignored). API keys are sent in request
  URLs but never written to the caches.

## 7. Licences of the sources

| Source | Terms | What this project does |
|---|---|---|
| CMS Part D, NPI Registry, openFDA | US government public data | republishes aggregates in pseudonymized form only (and not in the repo) |
| RxNorm, RxClass, MeSH | NLM terms of use, free | publishes RxNorm CUIs and names, MeSH IDs and entry terms |
| UMLS | licence required (free) | uses NLM editors' relations to find MeSH links; publishes only the resulting MeSH IDs |
| ATC (via RxClass) | WHO Collaborating Centre copyright | uses 10 class codes and names; the full WHO index (about EUR 200) was not bought. Check WHOCC terms before commercial reuse |
| NUCC taxonomy | AMA/NUCC permission, US only, no derivative works | builds the SKOS scheme locally; it is not committed |
| GLEIF, Wikidata | CC0 | publishes LEIs, legal names, Wikidata labels |
| IDMP-O 1.4.0 | MIT | includes a 5-term extract with the MIT notice |
| KEGG | academic use only | considered for ATC and rejected |

## 8. Known limits

- Retrieval times come from cache file times; copying `data/raw/` without preserving them changes
  the recorded window (not the data).
- Release identifiers are read at first retrieval and cached with the responses; a partial refresh
  of one cache folder can mix releases within a source.
- Five class → MeSH links rest on judgement rather than an NLM mapping (2 derived by a rule, 3
  curated), and the GIP/GLP-1 placement is a modelling decision; `mesh_source` and the class's scope
  note say so.
- Curated Japanese and Chinese labels without a Wikidata counterpart (most class names, NUCC
  specialties) are still pending native-speaker review.
