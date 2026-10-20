# Bug hunt — Diabetes Drug Market graph

Round of static review + live verification against the Stardog Cloud database `glp`.
Date: 2026-10-20. Scope: `scripts/`, `ontology/`, `shapes/`, `vocab/`, `queries/`, `mcp_server/`,
`tests/`, `docs/`.

**14 findings: 1 high, 4 medium, 9 low.** Nothing was fixed in this round — it lists what was
wrong and how to fix it. The status of each finding after the fixes is in
[Round 2](#round-2--fix-verification-2026-10-20-later-the-same-day) above; everything below is the
original round, kept as the record of what was found.

The headline: the published numbers in `docs/findings.md`, `docs/query-results.md` and
`docs/validation-report.md` all **reproduce exactly** (I re-ran every query and the SHACL
validation against the live database). The problems are in the parts of the project that the
published numbers never touch: the modelling contract under reasoning, the MCP tool guidance, and
several governance claims in the docs that no code actually enforces.

---

# Round 2 — fix verification (2026-10-20, later the same day)

Re-checked every finding against the updated tree and the reloaded database. **12 of 14 fixed,
2 still open, plus 4 new loose ends the fixes introduced or left behind.**

| # | Finding | Status |
|---|---|---|
| H1 | SHACL substance constraint contradicted the OWL axioms (21 false violations with reasoning on) | **fixed** ✓ |
| M2 | MCP server told the model to use `dm:hasPrimarySpecialty` for specialties | **fixed** ✓ |
| M3 | `governance.md` claimed the git commit is in the provenance graph | **fixed** (claim made conditional) ✓ |
| M4 | Provenance chain never covered the generated intermediate CSVs | **fixed** ✓ |
| M5 | Source snapshots had no content hash; the article implied they did | **fixed** (wording made accurate) ✓ |
| L6 | Duplicate `rdfs:label` on the five external IDMP-O terms | **fixed** ✓ |
| L7 | `clean_data.py` reports rows per class in ATC names, not class ids | **still open** |
| L8 | `decisions.md` said "Three schemes"; there are four | **fixed** ✓ |
| L9 | `decisions.md` referred to the removed `fda_label_pattern` column | **fixed** ✓ |
| L10 | `findings.md` specialty names did not match the query output | **fixed** ✓ |
| L11 | `findings.md` §3 silently truncated the Japanese table to 7 of 10 rows | **fixed** ✓ |
| L12 | `build_rdf.py` keeps only the first claim row's city and CMS specialty | **still open** |
| L13 | `resolve_organizations.gleif()` only retried on HTTP errors | **fixed** ✓ |
| L14 | `load_stardog.py` rollback could mask the original error | **fixed** ✓ |
| L15 | `GRAPH ?g { ?g ?p ?o }` returns nothing in Stardog (undocumented) | **fixed** ✓ |

**New in round 2 (all minor):**

| # | Finding | Severity |
|---|---|---|
| N1 | `docs/query-results.md` is stale — its provenance table shows 5 rows, the live query now returns 7 | low |
| N2 | `docs/governance.md` §2 shows the same stale 5-row provenance table | low |
| N3 | `shapes/diabetes-market-shapes.ttl` still declares `owl:versionInfo "0.1.0"` after a breaking rule change | low |
| N4 | The repository is still not under version control, so the provenance graph has no commit to record | low (publishing blocker) |

## What was verified, and how

**H1 — fixed and confirmed live.** The constraint is now a SPARQL rule that counts only the
*most specific* classes of a substance, so the property chain cannot inflate it:

```turtle
sh:sparql [ sh:message "A substance is in exactly one most specific therapeutic class." ;
  sh:select """SELECT $this WHERE {
    { SELECT $this (COUNT(DISTINCT ?c) AS ?n) WHERE {
        $this dm:inTherapeuticClass ?c .
        FILTER NOT EXISTS { $this dm:inTherapeuticClass ?narrower . ?narrower skos:broader+ ?c }
      } GROUP BY $this }
    FILTER (?n > 1) }""" ] ;
```

`VALIDATE ALL USING SHAPES GRAPH <shapes>` on the reloaded database now gives the same answer in
both modes, where before it gave 21 violations with reasoning on:

```
reasoning=false: {'Warning': 17, 'Info': 130}   violations={}
reasoning=true:  {'Warning': 17, 'Info': 130}   violations={}
```

I also checked the rule from the other side — it is not a rule that can never fire. A substance
asserted in two sibling classes (`SGLT2Inhibitor` + `DPP4Inhibitor`), added in a transaction, is
reported in both modes:

```
reasoning=false: violations=6  new-rule-fired=True
reasoning=true:  violations=6  new-rule-fired=True
  - A substance is in exactly one most specific therapeutic class.
```

`tests/test_shapes_reasoning.py` is new and passes; it is the regression test H1 asked for, and
`docs/governance.md` §3 now lists it in the guarantee table.

**M2 — fixed.** `HOW_TO_USE["specialty"]` now reads
`?doc dm:hasSpecialty/skos:broader* <iri> .` with a note to use `dm:hasPrimarySpecialty` for
shares, and the `describe_model` conventions explain the difference ("lists every NPI Registry
specialty of a prescriber … `dm:hasPrimarySpecialty` is the one flagged primary").

**M4 — fixed.** `scripts/provenance.py` gained a `GENERATED` map, and the provenance graph now
carries a hashed `prov:Entity` for each generated intermediate
(`scripts/drugs.csv`, `scripts/products.csv`, `scripts/substances.csv`, `scripts/organizations.csv`,
`scripts/therapeutic_classes.csv`, `scripts/indications.csv`, `scripts/labels_ja_zh.csv`,
`data/clean/partd_claims.csv`, `data/clean/npi_taxonomies.csv`). The graph grew 251 → 299 triples
and the provenance query now returns 7 rows instead of 5.

**M5 — fixed by making the claim true.** `article.md` §2 now says "lists the source releases and
retrieval times it was built from, along with a content hash of the graph itself", and
`governance.md` §2 says the same. That is what the graph actually contains: the hash is on the
graph node, not on the API snapshots. (Hashing the cached API responses is still possible — the
files are in `data/raw/` — but it is no longer claimed.)

**M3 — fixed by making the claim true.** `governance.md` now says "when built from a git checkout,
the build's git commit" and "(`provenance.py` omits it otherwise)". The code is unchanged, which is
correct: it already omits it, silently. See N4 for the remaining action.

**L6 — fixed.** `scripts/extract_idmp_terms.py` no longer copies IDMP-O's label for a term whose
label our own MIREOT declaration already provides ("a second, untagged copy would duplicate it").
The extract went 31 → 26 triples and the schema graph 314 → 309. Live check — the five external
terms now carry exactly one label each, all `@en`:

```
MedicinalProduct | 'medicinal product' | lang: en
Substance        | 'substance'          | lang: en
TherapeuticIndication | 'therapeutic indication' | lang: en
hasActiveIngredient   | 'has active ingredient'   | lang: en
hasTherapeuticIndication | 'has therapeutic indication' | lang: en
```

**L13, L14 — fixed in code.** `gleif()` now also catches `OSError` (URLError, timeouts, DNS) and
retries; `HTTPError` is still matched first because it subclasses `OSError`.
`load_stardog.py`'s rollback is now inside its own `try/except`, so a failing rollback prints a
warning instead of replacing the original exception.

**L15 — fixed.** The `describe_model` conventions now carry the warning: "In Stardog,
`GRAPH ?g { ?g ?p ?o }` (the graph variable as subject inside its own `GRAPH` block) returns no
rows; bind the subject to a separate variable."

**Article scope — fixed.** "covering 2024 Medicare Part D claims for 32 diabetes medicines in
Connecticut" replaces the old overstatement, and `article.md` §1.4 now says 38 rules.

## Regression check after the fixes

| Check | Result |
|---|---|
| `tests/test_ontology_reasoning.py` | pass |
| `tests/test_load_gate.py` | pass, 7 violations caught, rollback clean |
| `tests/test_shapes_stardog.py` | pass, **38 of 38** rules fired |
| `tests/test_shapes_reasoning.py` (new) | pass, 0 violations with reasoning off **and** on |
| `tests/test_mcp_server.py` | pass, 13/13 |
| All 6 business queries re-run | identical numbers to `docs/query-results.md` (cost-per-claim table cell-by-cell, specialty totals 198,279 / 238,340, Wegovy 1,178) |
| Per-graph triple counts | all 11 graphs match the local files; 246,086 triples |
| Database state after the test suite | 11 graphs, no leftover test graphs |

## Still open

### L7 — `clean_data.py` still reports rows per class in ATC names

`scripts/clean_data.py` is unchanged (`partd_rows_by_class` is still keyed by the RxClass ATC
name, e.g. `"Sodium-glucose co-transporter 2 (SGLT2) inhibitors": 4047`), so the cleaning report
still cannot be joined to the graph's class ids (`SGLT2Inhibitor`). Low severity — it is an
internal report — but it is the one original finding that was not touched.

### L12 — `build_rdf.py` still keeps only the first claim row's city and CMS specialty

`scripts/build_rdf.py` is unchanged in `build_claims()`:

```python
g.add((doctor, DM.cmsPrescriberType, Literal(r["prscrbr_type"])))
g.add((doctor, DM.city, Literal(r["prscrbr_city"])))
```

Still latent, not live: the cleaning report has no `inconsistent_prscrbr_*` key, so all 3,896
NPIs still have a single city and a single CMS specialty, and the SHACL shape (exactly one value)
still holds. It is a trap for the next data year rather than a defect in today's graph.

## New loose ends

### N1 — `docs/query-results.md` is stale

The file still carries the 2026-10-15 header and its provenance section shows 5 rows, while the
live query now returns 7 (the two generated intermediates appear in it). Everything else in the
file still matches. Fix: `.venv/bin/python scripts/run_queries.py`.

### N2 — `docs/governance.md` §2 shows the same stale table

The provenance table in §2 mirrors the query output and still lists 5 inputs. It should list the
7 the query now returns, or be replaced with a pointer to the regenerated
`docs/query-results.md`.

### N3 — The shapes file was changed but not version-bumped

`shapes/diabetes-market-shapes.ttl` still declares `owl:versionInfo "0.1.0"`, although a rule was
removed (`sh:maxCount 1`), a rule added (the SPARQL constraint), and the semantics of another
changed. The shapes graph is hashed in the provenance graph, so the change is traceable, but the
version string now understates a breaking change to the contract. Suggest `0.2.0` with a
`skos:changeNote`, matching how the ontology is versioned. `decisions.md` already records the
change ("37 constraints; 38 since 2026-10-20").

### N4 — The repository is still not under version control

`git rev-parse HEAD` still fails: `fatal: not a git repository`. The docs no longer claim a commit
is recorded, so nothing is wrong — but `CLAUDE.md` says the code is to be published on GitHub, and
until `git init` + first commit happen, the provenance graph will keep carrying no commit and the
`git_commit()` branch in `scripts/provenance.py` will stay dead. One command, and it activates a
feature that is already written and documented.

### Minor: `docs/article-notes.md` still says "37 of 37"

That file is a dated narrative of the 2026-10-14 run ("The first attempt showed 34 of 37 rules
firing"), so it is correct as history. A reader who compares it with the article's "38 rules" may
wonder; one clause — "37 at the time, 38 since 2026-10-20" — would settle it.

---

## Verification performed

| Check | Result |
|---|---|
| `tests/test_ontology_reasoning.py` (local OWL RL) | pass |
| `tests/test_load_gate.py` (SHACL gate blocks, rollback clean) | pass, 7 violations caught |
| `tests/test_shapes_stardog.py` (every rule can fire) | pass, **37 of 37** rules fired |
| `tests/test_mcp_server.py` (real MCP stdio client) | pass, 13/13 checks |
| All 6 queries in `queries/` re-run against Stardog | identical to `docs/query-results.md` |
| `VALIDATE ALL USING SHAPES GRAPH <shapes>` re-run | 0 violations / 17 warnings / 130 info — identical to `docs/validation-report.md` |
| Per-graph triple count: local files vs Stardog | all 11 graphs match |
| `ontology/diabetes-market.ttl` vs `.rdf` isomorphism | isomorphic (288 triples each) |
| CSV ↔ graph consistency (51 products, 21 substances, 32 generics, 9 organizations, ja/zh label coverage) | all consistent |
| Brand→generic, slug collision, rx-IRI collision checks over 22,034 claim rows | no collisions |

No file in the repository was modified. `docs/` is byte-identical to its state before the hunt.
The two temp graphs used by the test suite were cleaned up by the tests themselves; the graph list
afterwards is unchanged (11 graphs, no residue).

---

## High

### H1 — The SHACL contract contradicts the OWL axioms: 21 false violations as soon as reasoning is on

`shapes/diabetes-market-shapes.ttl` (`dms:SubstanceShape`):

```turtle
sh:property [ sh:path dm:inTherapeuticClass ; sh:minCount 1 ; sh:maxCount 1 ;
               sh:class dm:TherapeuticClass ;
               sh:message "A substance is asserted in exactly one (most specific) therapeutic class." ]
```

`ontology/diabetes-market.ttl` rolls class membership up the SKOS tree with a property chain:

```turtle
dm:inTherapeuticClass owl:propertyChainAxiom ( dm:inTherapeuticClass skos:broaderTransitive ) .
```

With the reasoner on, every substance gains its ancestor classes, so `sh:maxCount 1` is violated
for all 21 substances. The shape's intent — "exactly one **asserted** class" — is not expressible
with a plain `sh:maxCount`, because SHACL in Stardog counts inferred triples.

**Evidence (live, database `glp`):**

```
VALIDATE ALL USING SHAPES GRAPH <https://dgg32.github.io/glp/graph/shapes>
  default (no reasoning param): {'Warning': 17, 'Info': 130}
  reasoning=true:               {'Warning': 17, 'Violation': 21, 'Info': 130}
    21  A substance is asserted in exactly one (most specific) therapeutic class.
```

Supporting query: `?s dm:inTherapeuticClass ?c` returns **1** value per substance with reasoning
off and **3** with it on (e.g. empagliflozin → SGLT2Inhibitor + BloodGlucoseLowering +
DrugsUsedInDiabetes).

**Why it matters.** Both callers validate *without* reasoning, so the bug is latent and the green
"0 violations" is real — but it is real for the wrong reason. The project explicitly markets
reasoning as a feature (the MCP server exposes a `reasoning` switch, the article's selling point
is that OWL adds facts), so the natural thing for a reviewer, a reader or a future maintainer to
do is validate with reasoning on and see 21 violations. The article's own argument is that OWL and
SHACL are complementary; here they silently contradict each other.

**Fix.** Scope the constraint to the asserted graph, which I verified returns only asserted triples
even with reasoning on:

```sparql
SELECT $this WHERE {
  GRAPH <https://dgg32.github.io/glp/graph/vocab/substance> { $this dm:inTherapeuticClass ?c }
  FILTER NOT EXISTS {
    GRAPH <https://dgg32.github.io/glp/graph/vocab/substance> { $this dm:inTherapeuticClass ?c2 }
    FILTER(?c2 != ?c)
  }
}
```

Verification: `GRAPH <…/vocab/substance> { ?s dm:inTherapeuticClass ?c }` → 1 value per substance
with `reasoning=true`. The same reasoning should be applied to the other `sh:maxCount` /
`sh:minCount` constraints on properties that a chain or inverse can expand
(`dm:hasSpecialty`, `dm:prescribedBy`, `dm:forProduct` are safe today, but they are one axiom away
from the same trap).

**Also worth adding:** a test that runs `VALIDATE` with reasoning on and asserts 0 violations, so
the two layers can never drift apart again.

---

## Medium

### M2 — The MCP server tells the model to use the wrong specialty property

`mcp_server/server.py`:

```python
HOW_TO_USE = {
    ...
    "specialty": "?doc dm:hasPrimarySpecialty/skos:broader* <{iri}> .",
```

`dm:hasPrimarySpecialty` is the NPI Registry *primary* taxonomy only. 3,881 of 3,896 prescribers
have a primary specialty, but many carry a specialty only as a secondary one.

**Evidence (live):**

| Query | Family Medicine (207Q00000X) |
|---|---:|
| `?d dm:hasSpecialty dmsp:207Q00000X` | 552 prescribers |
| `?d dm:hasPrimarySpecialty dmsp:207Q00000X` | 517 prescribers |
| `?d dm:hasSpecialty/skos:broader* dmsp:207Q00000X` | 571 prescribers |
| `?d dm:hasPrimarySpecialty/skos:broader* dmsp:207Q00000X` | 542 prescribers |

The guidance loses 29 prescribers for a common specialty, and returns **zero** for any NUCC
*specialization* code (e.g. `207QS0010X` "Sports Medicine (Family Medicine) Physician"), which is
exactly what `resolve_term` hands back for a specialty lookup. `describe_model`'s Conventions
section repeats the same advice (`?doc dm:hasPrimarySpecialty ?sp`).

**Impact.** This is the GenAI layer the article showcases. The model is told to use a pattern that
systematically under-reports, and it will use it verbatim.

**Fix.** `?doc dm:hasSpecialty/skos:broader* <iri> .` and add a second line for the primary-only
case. Same in the Conventions text in `describe_model`.

### M3 — `governance.md` claims the git commit is in the provenance graph; it is not

`governance.md` §4:

> **Data and vocabularies:** identified by their content hash and the build's git commit in the
> provenance graph

`scripts/provenance.py`:

```python
def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, ...).stdout.strip()
    except Exception:
        return None
...
if commit := git_commit():
    g.add((build_act, DCTERMS.hasVersion, Literal(commit)))
```

The project directory is **not a git repository** (`git rev-parse HEAD` → `fatal: not a git
repository`), so `git_commit()` returns `None` and the triple is silently omitted.

**Evidence (live, provenance graph):** the build activity
`data/activity/build/2026-10-15T04:34:03+00:00` has a label, `prov:endedAtTime` and
`prov:wasAssociatedWith`, but **no** `dcterms:hasVersion`. The 11 activity rows in the graph carry
zero `hasVersion` values.

The same doc opens with "Every claim below points to the code or file that enforces it." This one
does not.

**Fix.** Either `git init` the repo and push (the `.gitignore` is already written for a repo, so
this looks like an unfinished step), or record the absence explicitly
(`prov:wasGeneratedBy` an activity with `rdfs:comment "no git commit: not a version-controlled
build"`) and soften the doc.

### M4 — The provenance chain never covers the *generated* intermediate CSVs

`LINEAGE` in `scripts/provenance.py` records, per graph, the curated files that fed it. But the
graphs are built from **generated** CSVs that are not recorded anywhere:

| Graph | Built from | Curated input recorded | Generated input **not** recorded |
|---|---|---|---|
| `vocab/indication` | `scripts/indications.csv`, `scripts/labels_ja_zh.csv` | `vocab/src/indications.csv` | both generated files |
| `vocab/substance` | `scripts/substances.csv`, `scripts/labels_ja_zh.csv` | `vocab/src/therapeutic_classes.csv`, `vocab/src/substance_labels_ja_zh.csv` | `scripts/substances.csv` |
| `vocab/therapeutic-class` | `scripts/therapeutic_classes.csv` | `vocab/src/therapeutic_classes.csv` | `scripts/therapeutic_classes.csv` |
| `products` | `scripts/products.csv`, `scripts/drugs.csv` | `scripts/cms_generic_names.csv`, `vocab/src/indications.csv` | `scripts/products.csv`, `scripts/drugs.csv` |
| `drugsfda` | `scripts/organizations.csv`, `scripts/labels_ja_zh.csv` | `vocab/src/sponsor_lei.csv`, `vocab/src/organization_labels_ja_zh.csv` | `scripts/organizations.csv` |

So a change in a generated intermediate (a new MeSH entry term from a refreshed MeSH release, a new
indication resolved from a changed openFDA label) is invisible in the provenance chain. Only the
final graph hash moves.

**Fix.** Add the generated inputs to `LINEAGE` (or add a second `curated`/intermediate list) so
the chain is graph ← generated CSV ← curated file ← API snapshot. The graph's own content hash
still protects the end state, but the *why* is lost.

### M5 — Source snapshots carry no content hash, and the article implies they do

`article.md` §2:

> Each source lives in its own named graph, and a PROV-O record for every graph lists the source
> release, the retrieval time and a content hash.

In the graph, the **source** entities (`data/source/cms-partd`, `…/rxnorm`, `…/umls`, `…/mesh`,
`…/gleif`, `…/wikidata`, `…/drugsfda`, `…/openfda-label`, `…/nucc`, `…/npi-registry`, `…/idmp-o`)
have a release (`dcterms:hasVersion`) and a retrieval window, but **no content hash**. The only
`dcterms:identifier` values on those rows are the *curated file* hashes.

**Evidence (live, `queries/provenance-of-a-graph.rq`):** the hash column is empty for all three
API sources and populated only for the two curated CSVs:

| input | release | retrieved | hash |
|---|---|---|---|
| GLEIF LEI records | 2026-10-14T16:00:00Z | 2026-10-15T02:14:42Z | *(empty)* |
| Wikidata (CC0), labels by identifier | | 2026-10-15T02:35:08Z | *(empty)* |
| openFDA Drugs@FDA | 2026-10-14 | 2026-10-15T01:43:35Z | *(empty)* |
| vocab/src/organization_labels_ja_zh.csv | | | sha256:b4d1503e… |
| vocab/src/sponsor_lei.csv | | | sha256:6904aec6… |

The cached API responses are on disk in `data/raw/`, so they *can* be hashed. Without a hash you
cannot prove that a rebuild talked to the same bytes — the retrieval window is only a timestamp of
a file's mtime, which `governance.md` §8 already concedes is fragile.

**Fix.** Hash the cached responses per source (e.g. sha256 over the sorted canonical JSON in
`data/raw/<source>/`) and add `dcterms:identifier` to the source entity. Then the article sentence
is true.

---

## Low

### L6 — Duplicate `rdfs:label` on all five external IDMP-O terms

`ontology/diabetes-market.ttl` declares the MIREOT-style external terms with language-tagged
labels (`rdfs:label "medicinal product"@en`); `ontology/imports/idmp-o-1.4.0-extract.ttl` declares
the same terms with plain literals (`rdfs:label "medicinal product"`). Both files are loaded into
the schema graph, so every one of the five terms ends up with **two** label values.

**Evidence (live, schema graph):**

```
MedicinalProduct        | medicinal product | lang: en
MedicinalProduct        | medicinal product | lang:
Substance               | substance          | lang: en
Substance               | substance          | lang:
TherapeuticIndication   | therapeutic indication | lang: en
TherapeuticIndication   | therapeutic indication | lang:
hasActiveIngredient     | has active ingredient | lang: en
hasActiveIngredient     | has active ingredient | lang:
hasTherapeuticIndication| has therapeutic indication | lang: en
hasTherapeuticIndication| has therapeutic indication | lang:
```

Consequences: entity lookup / `stardog:label` sees two spellings of the same label; the SHACL
`sh:uniqueLang` rule does not apply (it targets `skos:prefLabel`), so nothing catches it. The
overlap also means the two files share 5 triples and can drift silently.

**Fix.** Pick one literal form. Either drop the five external-term declarations from
`ontology/diabetes-market.ttl` (the extract already carries type, label, definition,
`isDefinedBy` and `subClassOf`) or make the two files agree on `@en` vs plain.

### L7 — `clean_data.py` reports rows per class in names that do not exist in the vocabulary

`data/clean/cleaning_report.json` → `partd_rows_by_class` is keyed by the RxClass ATC name:

```json
"Sodium-glucose co-transporter 2 (SGLT2) inhibitors": 4047
"Biguanides + Dipeptidyl peptidase 4 (DPP-4) inhibitors": 606
```

while the SKOS scheme uses stable ids: `SGLT2Inhibitor`, `Biguanide`, `DPP4Inhibitor`. The class
*ids* live in `scripts/substances.csv` (`therapeutic_class` column) and in
`vocab/src/therapeutic_classes.csv`; `scripts/drugs.csv` only carries the human-readable ATC name
in `drug_class`. A reader cannot join the cleaning report to the graph without a lookup table.

**Fix.** Have `clean_data.py` report both the id and the label, or join `drug_class` to the
`therapeutic_class` id in `drugs.csv` so the report is keyed the same way as the graph.

### L8 — `decisions.md` says "Three schemes"; there are four

`docs/decisions.md` §"SKOS vocabularies":

> **Three schemes**: therapeutic classes (`vocab/therapeutic-class.ttl`), active substances
> (`vocab/substance.ttl`) and NUCC specialties (`vocab/nucc-specialty.ttl`)

`scripts/build_skos.py` builds four: `therapeutic-class.ttl`, `substance.ttl`, `indication.ttl`,
`nucc-specialty.ttl`. The indication scheme (T2DM / T1DM / Obesity) is missing from the list, and
so is its `scripts/indications.csv` input. (`CLAUDE.md` says "Two SKOS vocabularies", which is
also out of date.) All four exist and load correctly — this is documentation drift only.

### L9 — `decisions.md` refers to a column that no longer exists

`docs/decisions.md`:

> matched against `fda_label_pattern` in `vocab/src/indications.csv`

`vocab/src/indications.csv` has columns `id, mesh_id, pref_ja, pref_zh, scope_note_en`. The terms
actually matched against FDA labels are `match_terms` and `implied_by_terms`, which live in the
**generated** `scripts/indications.csv`. The paragraph describing the pipeline is otherwise
accurate; only the column name is stale.

### L10 — `findings.md` specialty names no longer match the query output

`docs/findings.md` §1 shows "Internal Medicine", "Endocrinology, Diabetes & Metabolism",
"Cardiovascular Disease (cardiology)", "Nephrology". The query returns "Internal Medicine
Physician", "Endocrinology, Diabetes & Metabolism Physician", "Cardiovascular Disease Physician",
"Nephrology Physician" (`docs/query-results.md` has the verbatim output). The "Primary specialty"
column is therefore an edited label, not the value in the graph — and "(cardiology)" is an
editorial addition with no counterpart in the NUCC data.

The numbers all check out (I re-summed all 72 rows: SGLT2 198,279, GLP-1 238,340, matching the
"All 72 specialties" row; every percentage in the table is correct). Only the row labels drift.

**Fix.** Either use the verbatim NUCC names or add one line saying the names were shortened for
the table.

### L11 — `findings.md` §3 shows 7 of the query's 10 rows without saying so

The Japanese-label query has `LIMIT 10` and returns 10 rows; the table in `docs/findings.md` §3
lists 7. The three omitted rows are the smallest by claim volume, so nothing is misleading, but the
table is silently truncated. The English query in §1 shows 12 of 72 and says so ("The top 12
specialties by claim volume are shown"). The Japanese table should say the same.

### L12 — `build_rdf.py` keeps only the first claim row's city and CMS specialty per prescriber

`scripts/build_rdf.py`, `build_claims()`:

```python
if doctor not in seen_hcp:
    seen_hcp.add(doctor)
    ...
    g.add((doctor, DM.cmsPrescriberType, Literal(r["prscrbr_type"])))
    g.add((doctor, DM.city, Literal(r["prscrbr_city"])))
```

`data/clean/prescribers.csv` deliberately joins inconsistent values with `" | "` (e.g.
`Hartford | New Haven`). The RDF keeps whichever value the first claim row carried, so the two
representations disagree and the graph silently discards one.

**Today this is latent**: the cleaning report has no `inconsistent_prscrbr_*` keys, so all 3,896
NPIs have a single city and a single CMS specialty. It is a trap for the next data year, and it
would not be caught by SHACL (the shape asks for exactly one value, which the RDF satisfies).

**Fix.** Build the prescriber attributes from `data/clean/prescribers.csv` (the already-reconciled
table) instead of from the first claim row, or assert the joined value.

### L13 — `resolve_organizations.gleif()` only retries on HTTP errors

Every other fetch helper in the project catches `Exception` and retries
(`build_skos.cached_json`, `download_partd.get_json`, `fetch_npi.fetch`,
`resolve_products.openfda_labels`). `scripts/resolve_organizations.py` catches only
`urllib.error.HTTPError`:

```python
except urllib.error.HTTPError as exc:
    if exc.code == 404: ...
    time.sleep(10 * (attempt + 1))
```

A `URLError`, a socket timeout or a DNS failure escapes the retry loop entirely and aborts the
build. Same class of problem in `build_rdf.drugsfda_sponsors`, which also catches only
`HTTPError`.

### L14 — `load_stardog.py`: the rollback in the `except` handler can mask the original error

```python
except Exception:
    sd.call(f"/transaction/rollback/{tx}")
    print("rolled back; database unchanged", file=sys.stderr)
    raise
```

If the rollback call itself fails (network, or a transaction that was already committed), the new
exception replaces the original one and the operator sees the rollback failure instead of the
cause. Wrap the rollback in its own `try/except`.

The `sys.exit(1)` in the violation branch is safe — `SystemExit` is not caught by
`except Exception` — so there is no double rollback there.

### L15 — Stardog quirk worth documenting for MCP users: `GRAPH ?g { ?g ?p ?o }` returns nothing

In Stardog 12.1.4, using the graph variable as a subject inside its own `GRAPH` block silently
returns 0 rows:

| Query | Rows |
|---|---:|
| `SELECT ?g ?id WHERE { GRAPH ?g { ?g dcterms:identifier ?id } }` | **0** |
| `SELECT ?g ?id WHERE { GRAPH ?g { ?s dcterms:identifier ?id } }` | **28** |

The project's own queries avoid the pattern (`load_stardog.count_per_graph` and the MCP
`describe_model` both use `?s ?p ?o`), so nothing is broken today. But any MCP client that writes
`GRAPH ?g { ?g ... }` gets an empty result with no error. Worth one line in the `describe_model`
Conventions block, since the article invites people to write their own SPARQL against this
database.

---

## Also checked, and fine

- **Claim dedup and IRI safety.** 22,034 rows, no duplicate `(NPI, brand, generic)`; no brand
  appears with two generic names; no two brands slug to the same IRI; no `(NPI, brand)` pair maps
  to two rx IRIs. `build_rdf`'s pseudonym-collision guard is correct.
- **CMS pagination.** `download_partd.py` uses `offset=0, 5000, 10000…`; I probed the live API
  and `offset` is **0-based** (`size=3&offset=0` → rows 1–3, `offset=1` → rows 2–4,
  `offset=2` → rows 3–4), so the loop and the row-count guard are right. The 1-based reading would
  have been a serious off-by-one; it is not.
- **rxNorm cache keys.** `resolve_drugs.resolve_rxcui` and `resolve_products.find_brand` both
  write `rxcui2_<slug>.json` — but they request the *same* URL (`rxcui.json?name=…&search=2`), so
  the shared cache file is correct, not a collision. `openfda_labels` batch order is stable
  (always a sorted list), so its cache keys do not churn.
- **Class hierarchy.** `skos:broader`/`narrower` in `vocab/therapeutic-class.ttl` is a proper tree:
  DrugsUsedInDiabetes → {Insulin → LongActingInsulin, BloodGlucoseLowering → {Biguanide,
  Sulfonylurea, Thiazolidinedione, DPP4Inhibitor, GLP1ReceptorAgonist → GIPGLP1Agonist,
  SGLT2Inhibitor}}. `skos:broader*` roll-up is correct in every business query.
- **Combination-product handling.** `dm:isCombinationProduct` matches the number of active
  substances for all 51 products (the SPARQL constraint fires on 0 nodes), and
  `cost-per-claim-by-class.rq` correctly excludes combination products, so no claim is double
  counted there. `market-share-by-manufacturer.rq` does count combination products in each class
  they belong to, as its comment says, and Byetta's 12 claims appear under both holders — already
  disclosed in `findings.md` §4.
- **ja/zh label coverage.** 20 specialty codes + 3 groupings have Japanese labels; 3,683 of 3,896
  prescribers (94.5%) have a primary specialty with a Japanese label — exactly the figure
  `decisions.md` claims. 11 classes, 21 substances, 3 indications and 9 organizations all have
  complete en/ja/zh label sets, and every concept has a matching row in
  `scripts/labels_ja_zh.csv`.
- **The five external IDMP-O terms** are all present, declared with `rdfs:isDefinedBy`, and the
  extract carries the MIT notice.
- **Counts and figures.** Every number in `docs/findings.md` §1, §2, §4 and §5 reproduces; the
  Wegovy figure (1,178 claims) is right; 33 of 51 products have a manufacturer; 6 NUCC
  classification concepts are minted; 24 label-review disagreements; 37 SHACL rules; 10 owl:Class
  declarations.

---

## Suggested order of work

*As proposed in round 1. H1, M2, M3, M4, M5 and the article scope wording are done; the order below
is the original proposal, kept for the record. The current outstanding list is
[Round 2 § Still open](#still-open).*

1. **H1** — rewrite the substance class constraint as a graph-scoped SPARQL constraint and add a
   "validate with reasoning on" test. This is the one that could embarrass the article.
2. **M2** — one-line change in `mcp_server/server.py` (`hasSpecialty` instead of
   `hasPrimarySpecialty`), plus the same fix in the `describe_model` conventions.
3. **M3 / M4 / M5** — the governance story is the article's second half, and three of its
   guarantees are currently unbacked. `git init` + push, hash the cached API responses, and add the
   generated CSVs to `LINEAGE`.
4. **M7 (see BUG.md §"Scope accuracy" below)** — tighten the article's scope sentence before
   publication.
5. The low-severity items as convenient.

---

## Scope accuracy (not a code bug, but the article is about to be published)

`docs/article.md` §1:

> This article builds such an RDF graph from public data, covering **every 2024 Medicare Part D
> prescription of type 2 diabetes drugs in Connecticut**

`docs/project_explained.md` says the same thing ("only type 2 diabetes drugs"). Three things are
inaccurate, and a reader with the CMS data in front of them could check each one:

1. **"every … type 2 diabetes drug"** — the subset is 32 CMS generic names, a subset of ATC A10.
   Missing: meglitinides (repaglinide), alpha-glucosidase inhibitors (acarbose), bromocriptine,
   pramlintide. The project itself calls it "an ATC A10 subset" in `docs/decisions.md`.
2. **"type 2 diabetes"** — 2,406 of the 22,034 rows (10.9%) are for products whose indication is
   **type 1** diabetes (the insulins; `dm:hasIndication dmind:T1DM`), and 53 rows are **Wegovy**,
   whose label states obesity and no diabetes indication. The graph records all of this correctly
   (`dms:ProductShape` requires at least one indication; the `dm:hasIndication` counts are T2DM
   21,981 / T1DM 2,406 / Obesity 53); it is the prose that overstates.
3. **"every … prescription"** — the rows are *claim aggregates*, not prescriptions: one row per
   prescriber × product per year, totalling 1,031,403 claims in the seven single-ingredient
   classes. 13,923 of 22,034 rows (63%) have a suppressed beneficiary count, and CMS omits every
   prescriber/drug row with fewer than 11 claims.

Suggested wording: *"covering all 22,034 2024 Medicare Part D claim aggregates for a 32-drug subset
of type 2 diabetes medicines in Connecticut, with all prescribers pseudonymized."* — the second
half of the sentence is already accurate and is the stronger claim anyway.

Note also `docs/article.md` §1.4: *"SHACL checks the closed world with 37 rules"* — that is
correct (37 distinct `sh:message` values, 37 of 37 proven to fire), and the claim that the
first run *"found no bad data but two bugs in the pipeline"* matches `docs/article-notes.md`.

---

## Reproducing the two most important findings

```bash
cd /Users/dgg32/Documents/glp

# H1: 21 false violations once reasoning is on
.venv/bin/python - <<'PY'
import sys, urllib.parse; sys.path.insert(0, "scripts")
from load_stardog import Stardog, settings
from rdflib import Graph, Namespace
SH = Namespace("http://www.w3.org/ns/shacl#")
sd = Stardog(settings())
q = "VALIDATE ALL USING SHAPES GRAPH <https://dgg32.github.io/glp/graph/shapes>"
for extra in ({}, {"reasoning": "true"}):
    p = {"query": q, "timeout": 600000, **extra}
    body = sd.call("/query?" + urllib.parse.urlencode(p), method="GET", accept="text/turtle")
    g = Graph().parse(data=body, format="turtle")
    v = [r for r in g.subjects(SH.resultSeverity, SH.Violation)]
    print(extra or "no reasoning", "->", len(v), "violations")
PY

# M2: the specialty property the MCP server recommends loses prescribers
.venv/bin/python - <<'PY'
import sys, urllib.parse; sys.path.insert(0, "scripts")
from load_stardog import Stardog, settings
import json
sd = Stardog(settings())
q = """PREFIX dm: <https://dgg32.github.io/glp/ontology#>
PREFIX dmsp: <https://dgg32.github.io/glp/vocab/specialty/>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?prop (COUNT(DISTINCT ?d) AS ?n) WHERE {
  { ?d dm:hasSpecialty ?s . ?s skos:broader* dmsp:207Q00000X BIND("hasSpecialty" AS ?prop) }
  UNION
  { ?d dm:hasPrimarySpecialty ?s . ?s skos:broader* dmsp:207Q00000X BIND("hasPrimarySpecialty" AS ?prop) }
} GROUP BY ?prop"""
body = sd.call("/query?" + urllib.parse.urlencode({"query": q, "timeout": 300000}),
               method="GET", accept="application/sparql-results+json")
for b in json.loads(body)["results"]["bindings"]:
    print(b["prop"]["value"], b["n"]["value"])
PY
```

---

## File index of everything cited

| File | What it is |
|---|---|
| `shapes/diabetes-market-shapes.ttl` | 37 rules, 7 node shapes, 34 property shapes, 2 SPARQL constraints |
| `ontology/diabetes-market.ttl` | 288 triples, 10 `owl:Class`, 2 property chains, 2 defined classes |
| `ontology/diabetes-market.rdf` | isomorphic RDF/XML twin (288 triples) |
| `ontology/imports/idmp-o-1.4.0-extract.ttl` | 31 triples, 5 external terms, MIT notice |
| `scripts/provenance.py` | `LINEAGE` (11 graphs), `SOURCES` (11 sources), `git_commit()` |
| `scripts/load_stardog.py` | `gate()` (VALIDATE, no reasoning), `count_per_graph()` |
| `scripts/validate.py` | VALIDATE, no reasoning; writes `docs/validation-report.md` |
| `scripts/build_rdf.py` | `build_claims()` (first-row attributes), `build_manufacturers()` |
| `scripts/clean_data.py` | `clean_partd()` (class report keyed by ATC name) |
| `scripts/resolve_organizations.py` | `gleif()` (HTTPError-only retry) |
| `mcp_server/server.py` | `HOW_TO_USE["specialty"]`, `describe_model` conventions, `_check_read_only` |
| `docs/article.md`, `docs/findings.md`, `docs/governance.md`, `docs/decisions.md` | published claims |
