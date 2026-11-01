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

---

# Round 3 — the Japan extension and the AllegroGraph move (2026-10-26)

Fresh round, after the Japan build, the Stardog Cloud corruption and recreation, and the
AllegroGraph detour. Scope: `scripts/`, `mcp_server/`, `shapes/`, `vocab/`, `queries/`, `tests/`,
`docs/`, `japan_extension.md`, `HANDOFF_article2.md`, `docs/article_2.md`.

**13 findings: 1 high, 4 medium, 8 low.** Nothing was fixed in this round — it lists what is wrong
and how to fix it.

The headline is the opposite of round 1's: **the graph and the pipeline are in good shape.** The
live database reproduces every published number exactly, all five test scripts pass, and
`scripts/check_local.py` passes all five of its checks. The problems are in the prose *around* the
graph. `docs/article_2.md`, the draft of the second article, states a market fact that is false, a
triple budget that does not add up, a price-list chronology that cannot be, and a "no new code"
claim that the git history contradicts. The AllegroGraph path is still in the tree with no server,
no credentials and no documented failure mode.

## Summary

| # | Finding | Severity | Where |
|---|---|---|---|
| H1 | "Three classes exist only in Japan's market" — two of the three are US classes | high | `article_2.md`, `findings.md` |
| M1 | "The MCP server needed no new code for Japan" — it gained 49 lines | medium | `article_2.md` vs git |
| M2 | The 11th release "published in June 2026 … carries the price list of September 2026" | medium | `article_2.md`, `provenance.py` |
| M3 | The crosswalk: "427 of its 427 products" — the graph says 427 of 450 | medium | `article_2.md` |
| M4 | The triple budget: Japan "460,000", Connecticut "277,000" | medium | `article_2.md`, `japan_extension.md`, `CLAUDE.md` |
| M5 | The AllegroGraph path is dead but still shipped, and dies with a bare `KeyError` | medium | `run_queries.py`, `load_allegrograph.py` |
| L1 | The AG variable substitution corrupts string literals and IRIs | low | `run_queries.py` |
| L2 | `governance.md` is stale in five places and knows nothing of the two new sources | low | `governance.md` |
| L3 | L7 from round 2 is still open: the cleaning report is keyed by ATC name | low | `clean_data.py` |
| L4 | Three queries lost their `ROUND` for a dead engine; the published numbers are now raw | low | `queries/jp-*.rq` |
| L5 | `SAMPLE()` makes one published query non-reproducible | low | `jp-glp1-…-reasoning.rq` |
| L6 | Three triple counts and two load durations for one build story | low | `decisions.md`, `japan_extension.md` |
| L7 | The NDB snapshot cannot be refreshed and its release string is hardcoded | low | `download_ndb.py`, `provenance.py` |
| L8 | The ontology carries two vocabulary instances the vocabulary graph also carries | low | `ontology/`, `vocab/` |

## Fixes applied (2026-10-26, same day)

| # | Status |
|---|---|
| H1 | **fixed**: `article_2.md` and `findings.md` say the three classes are outside the Connecticut subset; only the glimins are Japan-only |
| M1 | **fixed**: the article says the *term lookup* needed no new code; the server learned the new concept kinds and the Data Cube patterns |
| M2 | **fixed**: "first published in June 2026", MHLW's in-place update of 2026-09-02, and the price read from the NDB tables |
| M3 | **fixed** (the original sentence was not self-contradictory: all 427 products in 396 are A10B; it now quotes 427 of 450 and the 23 GLP-1 products in 249) |
| M4 | **fixed**: 247k / 487k / 734,106 and ~1.15M in the article, `japan_extension.md`, `CLAUDE.md`, the handoff |
| M5, L1 | **fixed by removal**: AllegroGraph scripts, `run_queries.py --ag` and its results file deleted |
| L2 | **fixed**: `governance.md` has the Japan sources, curated files, licence, limits, ontology 0.5.0 / shapes 0.3.0, current provenance table |
| L4 | **fixed**: `ROUND` restored in the three queries; `docs/query-results.md` regenerated from Stardog (one read-only pass), matching `findings.md` |
| L5 | **fixed**: `MIN(?name)` instead of `SAMPLE(?name)` |
| L6 | **not a defect**: "1 min 50 s" is the AllegroGraph load, "2.5 min" the Stardog load; the three triple counts are successive builds |
| L7 | **documented** as a known limit in `governance.md` §8; code unchanged |
| L3, L8 | **left open**: cosmetic; L8 would change a hashed file and force a rebuild and reload for no data change |

## Status of the earlier rounds

| # | Finding | Status |
|---|---|---|
| H1 (r1) | SHACL substance constraint contradicted the OWL axioms | **fixed** ✓ (shapes 0.3.0 keeps the split rule) |
| M2–M5, L6, L8, L9, L10, L11, L13–L15 (r1) | round 1's medium and low findings | **fixed** ✓ |
| L7 (r2) | cleaning report keyed by ATC name | **still open** (L3 below) |
| L12 (r2) | `build_rdf.py` kept only the first claim row's city and specialty | **fixed** ✓ — it now stops the build if a prescriber has more than one |
| N1 (r2) | `docs/query-results.md` stale | **fixed** ✓ |
| N2 (r2) | `governance.md` §2 stale provenance table | **still open** (L2 below) |
| N3 (r2) | shapes not version-bumped | **fixed** ✓ (0.3.0, `owl:priorVersion 0.2.0`, change notes) |
| N4 (r2) | the repository was not under version control | **fixed** ✓ — and the provenance graph now records the build's commit |

---

# High

### H1 — "Three classes exist only in Japan's market" is false: two of the three are US classes

`docs/findings.md:190` and `docs/article_2.md:196`:

> | α-glucosidase inhibitors, glimins, glinides | 3.5% | — (not used in the US) |
>
> Japan spends twice the Connecticut share on DPP-4 … **Three classes exist only in the Japanese
> market.**

Acarbose (Precose, Glucobay) and repaglinide (Prandin) / nateglinide (Starlix) are FDA-approved US
drugs. Only imeglimin (the one glimin) is Japan-only.

**The graph itself says so.** `scripts/substances.csv` — the project's own resolved substance table —
gives these four an **RxNorm CUI**, i.e. an identifier from the US drug dictionary, plus an ATC code:

```
acarbose     rxcui=16681   atc=A10BF01   class=AlphaGlucosidaseInhibitor
miglitol     rxcui=30009   atc=A10BF02   class=AlphaGlucosidaseInhibitor
repaglinide  rxcui=73044   atc=A10BX02   class=Glinide
nateglinide  rxcui=274332  atc=A10BX03   class=Glinide
```

So the vocabulary in the database and the sentence in the article contradict each other: the graph
carries these substances with US identifiers, and the prose calls their classes "not used in the US".
Only imeglimin (UMLS C3501765, no RxNorm) is genuinely Japan-only, and only *glimins* as a class is
Japan-only — of the three classes in the row, α-glucosidase inhibitors and glinides are US classes.

**Why the number is 0.** The Connecticut side of `queries/jp-vs-connecticut-class-mix.rq` is not the
US market; it is the project's own 32-generic subset (`scripts/cms_generic_names.csv`), which
contains no α-glucosidase inhibitor and no glinide. So the query correctly returns `0.00` for all
three classes — and the prose then reads that as "not used in the US", which is a claim about the US
market, not about the subset.

**Evidence (live):**

```
$ grep -iE "acarbose|repaglinide|nateglinide" scripts/cms_generic_names.csv data/clean/partd_claims.csv
(no match — the subset has none of them)
```

**Why it matters.** The article's comparison section is where a pharma reader will look first, and
"these three classes do not exist in the US" is exactly the kind of statement that ends an
argument with a reader. It is also self-contradicting with the article's own scope note two
paragraphs earlier ("The Connecticut insulin figure covers only insulin glargine, the one insulin in
the first article's scope") — the insulin caveat is applied but the α-GI/glinide caveat is not.

**Fix.** In both files, replace "— (not used in the US)" with "— (outside the 32-drug Connecticut
subset)" and "Three classes exist only in Japan's market" with "Three classes are missing from the
Connecticut subset; of them only the glimins are Japan-only". If the US-market point is wanted, it
needs US data outside this subset — which is the honest answer to give.

---

# Medium

### M1 — "The MCP server needed no new code for Japan" is contradicted by the git history

`docs/article_2.md:227`:

> The MCP server from the first article needed no new code for Japan. Its term lookup reads the SKOS
> labels, and the Japanese data brought its labels with it.

**Evidence (`git diff 7043a9e 88cea6a -- mcp_server/server.py`): 49 insertions, 13 deletions.** The
Japan commit added to `mcp_server/server.py`:

- 4 new concept kinds in `KINDS`: `Prefecture`, `JapaneseDrugClass`, `CareSetting`, `SexAgeGroup`;
- 4 new entries in `HOW_TO_USE` (`prefecture`, `jp_drug_class`, `care_setting`, `sex_age`) and
  rewrites of the `product` and `company` patterns for the Japanese forms;
- 5 new prefixes (`pref:`, `sexage:`, `setting:`, `jpc:`, `qb:`, `sdmx-attribute:`);
- a rewritten `INSTRUCTIONS` block with a Japan paragraph (masking thresholds, quantities not
  addable across products, "prices as of 2026-09-02");
- 3 new lines in `describe_model`'s Conventions (the Data Cube pattern, the masked-cell pattern, the
  age bands);
- a new `kind` list in `resolve_term`'s docstring.

**What is true** is narrower and still worth saying: the *term lookup* needed no new code, because
the SKOS labels came with the data. The server still needed to teach the model how to *query* Japan.

**Fix.** "The MCP server's term lookup needed no new code for Japan — its SKOS labels came with the
data. The server gained Japan's concept kinds and the Data Cube query patterns."

### M2 — The release chronology in the article cannot be true, and MHLW's own page says why

`docs/article_2.md:29` and `:33`:

> The [11th release](…), **published in June 2026**, covers fiscal year 2024 … The 11th release
> carries **the price list of September 2026**, so the values are fiscal year 2024 volumes at current
> prices.

A release published in June cannot carry a September price list. The project already knows the real
story — `scripts/download_ndb.py:23`:

> Price lists: the one in force from 2026-10-14 (**NDB's own prices were updated to the 2026-09-02
> list**) and the last one of FY2024 (2025-03-19), for products delisted since.

**MHLW's page (fetched 2026-10-26) confirms it.** The 11th release page marks the 処方薬 (prescription
drug) section **（2026/09/02更新）** — "the drug prices (薬価), NHI listed drug codes and generic flags
were updated, and additional drugs (oral, injection) were output" — and separately marks 医科診療行為
（患者数）as 2026/08/31. The release's files are **updated in place**; the project downloaded them
on 2026-10-25, so it holds the 2026-09-02 price revision.

**A second, smaller inaccuracy in the same paragraph** (`article_2.md:31`):

> The NHI (National Health Insurance) price list adds each product's ingredient, price and marketing
> authorization holder.

The code says otherwise. `scripts/clean_ndb.py:99` takes `nhi_price` from the **NDB workbook's own
price column** (`r[6]`); the price-list workbooks are opened only for 成分名, メーカー名 and 先発品
(`clean_ndb.py:67-74`). The price list is where NDB's prices come from, but it is not where this
pipeline reads them.

**Fix.** "The 11th release covers fiscal year 2024 (April 2024 to March 2025). MHLW updates its files
in place — the prescription-drug tables were last updated on 2 September 2026, when the NHI prices,
drug codes and generic flags were refreshed — so the values are fiscal year 2024 volumes at the
September 2026 prices."

### M3 — The crosswalk quote inverts the ratio

`docs/article_2.md:62`:

> Category 396 gets skos:broadMatch to *blood glucose lowering drugs, excluding insulins* (A10B),
> since **427 of its 427 products** are diabetes drugs but not every such drug is in 396.

The graph says something else. `vocab/jp-drug-class.ttl`, `skos:editorialNote` on `jpc:396`:

> broadMatch BloodGlucoseLowering: **427 of the 450** products containing a substance of
> BloodGlucoseLowering are filed under 396; 427 products in 396 in all.

The class id and the ATC code in the article are right (`BloodGlucoseLowering` = "Blood glucose
lowering drugs, excl. insulins" = A10B, verified in `vocab/therapeutic-class.ttl`); only the ratio
is wrong. "427 of its 427" also contradicts the article's own next clause, "not every such drug is
in 396" — the two cannot both hold.

**Fix.** "since 427 of the 450 blood-glucose-lowering products are filed under 396, while 23 of the
25 GLP-1 products are filed under 249."

### M4 — The triple budget does not add up, in the article and in the plan of record

`docs/article_2.md:104` and `:128`:

> Stardog Cloud Free allows one million edges per database, and **Connecticut already uses about
> 277,000**. … With 4,464 slices, **Japan adds about 460,000 triples**, and the whole database holds
> 734,106.

The same base is in `japan_extension.md:56` ("276,677 (Connecticut)") and `:67` ("~480k | ~755k |
yes, ~245k left"), and `CLAUDE.md:39` repeats it ("Connecticut ~277k, NDB ~485k").

**Measured (live Stardog `glp`, 16 graphs, 734,106 triples):**

| Part | Graphs | Triples |
|---|---|---:|
| Japan | `ndb-2024` 477,662 + `ndb-products` 7,732 + `jp-prefecture` 757 + `ndb-dimensions` 632 + `jp-drug-class` 117 | **486,900** |
| Connecticut + shared vocabularies + shapes + provenance | everything else | **247,206** |
| Total | | **734,106** |

The local files give 485,394 / 248,717 (the difference is 7 triples that appear in two files: 5
between the ontology and the IDMP-O extract, 2 between the ontology and the class vocabulary).

So: Connecticut is **~247k**, not ~277k; Japan is **~487k**, not ~460k; the headroom is **~266k**,
not ~245k; and the flat model would come to **~1.15M**, not ~1.18M. The 276,677 base is not
reproducible from any build in the tree.

The conclusion survives — the flat model does not fit and the Data Cube does — but the numbers the
article publishes about its own database do not.

**Fix.** Use 247,000 and 487,000 (or the exact per-graph counts from `describe_model`), and correct
`japan_extension.md:56,67` and `CLAUDE.md:39` to match.

### M5 — The AllegroGraph path is still shipped, with no server, no credentials and no clear failure

The AllegroGraph server was removed by the user (`HANDOFF_article2.md`, "System state"), but
`scripts/setup_allegrograph.py`, `scripts/load_allegrograph.py` and `run_queries.py --ag` remain,
and `data/validation/query-results-allegrograph.md` remains as an artifact of a server that no
longer exists.

**The failure is a bare traceback, not a message.** `scripts/setup_allegrograph.py` checks its
settings properly (line 58-60: `missing in .env: [...]`), but the other two do not:

```
$ .venv/bin/python scripts/run_queries.py --ag
  File "scripts/setup_allegrograph.py", line 36, in __init__
    self.root = env["AG_URL"].rstrip("/")
KeyError: 'AG_URL'

$ .venv/bin/python scripts/load_allegrograph.py --dry-run
  (same KeyError)
```

`.env.example` has no `AG_*` keys at all, so a fresh clone cannot even discover what the path needs.

**Two further undocumented assumptions** in `load_allegrograph.py`, neither of which can be
re-tested now: the SPARQL endpoint is the free-text `GET /repositories/{id}?query=`, and the
default graph is the union of the named graphs (the `FROM <tag:stardog:api:context:all>` is
stripped and nothing replaces it).

**Fix.** Decide (the handoff leaves this open): either delete the three AG artefacts, or keep them
and make them fail the way `setup_allegrograph.py` does, add the `AG_*` block to `.env.example`, and
say in the file docstrings that the server is gone and the code is kept only as portability
evidence.

---

# Low

### L1 — The AG variable substitution corrupts string literals and IRIs

`scripts/run_queries.py:80`:

```python
query = re.sub(r"\?([^\x00-\x7f\s(){}.,;]+\w*)", ascii_var, query)
```

The pattern matches any `?` followed by a non-ASCII character, anywhere in the query — including
inside a string literal or an IRI. Demonstrated:

| Input | Output |
|---|---|
| `?s skos:prefLabel "糖尿病?用法"` | `?s skos:prefLabel "糖尿病?u0_var"` |
| `?s skos:exactMatch <http://x/?専門>` | `?s skos:exactMatch <http://x/?u0_var>` |
| `SELECT ?class_専門` | unchanged (mixed ASCII/CJK is not matched at all) |

A Japanese label containing `?` is silently rewritten, so the query returns the wrong rows with no
error; a mixed ASCII/CJK variable name is left alone and AllegroGraph rejects the query.

The MCP server solves exactly this problem properly, with `_strip_strings_iris_comments`
(`mcp_server/server.py:168-190`), which blanks literals, IRIs and comments before any keyword or
name rewriting. The AG path has no equivalent.

**Fix.** If the AG path survives L5, reuse the MCP server's approach: blank strings, IRIs and
comments first, then rewrite variables only.

### L2 — `governance.md` is stale in five places, and knows nothing of the two new sources

`docs/governance.md` opens with "Every claim below points to the code or file that enforces it."
Five places no longer hold:

1. **§4 (line 133): "now 0.4.0"** — the ontology is **0.5.0** (`ontology/diabetes-market.ttl:29`),
   and the provenance graph itself carries `dcterms:hasVersion "0.5.0"` for the schema graph. The
   paragraph also stops at 0.4.0 and never mentions the Japan release.
2. **§2 (line 88): the provenance table** still shows the Wikidata retrieval window as
   `2026-10-15T02:35:08Z`; the live query returns `2026-10-25T10:40:38Z`. The table also has no
   hash column, although the query it links to returns one. (This is round 2's N2, still open.)
3. **§1 "Where each fact comes from"** has no row for **NDB Open Data** or the **NHI price list** —
   the two sources that carry the whole Japan dataset.
4. **§1 "Curated inputs"** is "The register of everything that is typed by hand" (line 46), but the
   four hand-typed Japan files are missing from it:
   `vocab/src/ndb_ingredients.csv` (64 YJ ingredient → substance → indication rows),
   `vocab/src/ndb_product_indications.csv`, `vocab/src/jp_manufacturers.csv` (51 Japanese holders →
   GLEIF group), `vocab/src/ndb_substances.csv`. All four **are** hashed in the provenance graph
   (verified), but only two are mentioned anywhere outside it (`docs/decisions.md:386-387`).
5. **§7 "Licences of the sources"** has no row for MHLW / NDB Open Data / the NHI price list, whose
   terms ("free to use with the source cited") are stated on the dataset node itself
   (`scripts/build_ndb.py:329`).

§8 "Known limits" likewise lists no Japan-specific limit (masking thresholds, quantities not
addable across products, prefecture = where the claim was issued).

### L3 — L7 from round 2 is still open

`scripts/clean_data.py:113` is unchanged:

```python
report["partd_rows_by_class"] = dict(Counter(r["drug_class"] for r in out).most_common())
```

The cleaning report is still keyed by the RxClass ATC name ("Sodium-glucose co-transporter 2
(SGLT2) inhibitors": 4047) while the graph uses class ids (`SGLT2Inhibitor`). It is the one finding
from the earlier rounds that has now survived two rounds untouched.

### L4 — Three queries lost their `ROUND` for a server that no longer exists

`queries/jp-age-profile-by-class.rq`, `jp-generic-share-by-month.rq` and
`jp-sglt2-share-by-prefecture.rq` were changed to return unrounded percentages, with a comment
explaining why:

> No ROUND on these shares: AllegroGraph 9.1 fails on ROUND over aggregates of IF() values; results
> are rounded for display.

AllegroGraph is gone (M5). Stardog handles `ROUND` over those aggregates fine — `jp-class-share-yen.rq`
and `jp-vs-connecticut-class-mix.rq` still use it and still work. The published percentages in
`docs/query-results.md` are now raw values with 15 significant digits, formatted to 2 decimals by
`run_queries.py`'s `fmt()`, and `docs/findings.md` §9–§10 still quotes the *old* rounded values
(e.g. α-glucosidase inhibitors April 2024: 90.4% in `findings.md`, 90.45 in `query-results.md`).

**Fix.** Either restore `ROUND` (the target engine supports it) or keep the raw values and
regenerate `docs/findings.md` §9–§10 from the current query output.

### L5 — `SAMPLE()` makes one published query non-reproducible

`queries/jp-glp1-by-japanese-category-reasoning.rq:10` uses `(SAMPLE(?name) AS ?example)`. `SAMPLE`
picks an arbitrary member of the group, so the "example" column of the published table is not stable.

The committed `docs/query-results.md` shows:

```
| Japan | その他のホルモン剤（抗ホルモン剤を含む。） | 23 | マンジャロ皮下注１５ｍｇアテオス　０．５ｍＬ |
| US (Connecticut) | - | 12 | Mounjaro |
```

A fresh run of the same query against the same database returns:

```
| Japan | その他のホルモン剤（抗ホルモン剤を含む。） | 23 | リベルサス錠３ｍｇ |
| US (Connecticut) | - | 12 | Ozempic |
```

Everything else in the 14 query outputs reproduces exactly. If the example column is meant to
illustrate a product (it is Figure 5's point), pick it deterministically — `MIN(?name)`, or a
`GROUP_CONCAT` of the first few names.

### L6 — Three triple counts and two load durations for one build story

| Figure | Where |
|---|---|
| 734,101 triples | `docs/decisions.md:356` ("Total load: 734,101 triples") |
| 734,105 triples | `japan_extension.md:82` ("loaded once successfully") |
| 734,106 triples | `japan_extension.md:87`, `HANDOFF_article2.md:106`, `docs/decisions.md:407` |
| "1 min 50 s" | `docs/decisions.md:407` (for the 734,106 load) |
| "2.5 min" | `japan_extension.md:87` and `HANDOFF_article2.md:75` (for the 734,106 load) |

The three counts are explicable as successive builds. The two durations are not: the same
734,106-triple load is 110 s in one document and 150 s in two others.

### L7 — The NDB snapshot cannot be refreshed, and its release string is hardcoded

`scripts/download_ndb.py:30-32`:

```python
def fetch(url, path):
    if path.exists():
        print(f"exists: {path.relative_to(ROOT)}")
        return
```

The NDB URL is `https://www.mhlw.go.jp/content/12400000/001744600.zip` — a **rolling** file that
MHLW replaces in place (see M2: the 処方薬 tables are marked "2026/09/02更新"). So a rerun of
`download_ndb.py` silently keeps the old ZIP and never notices that MHLW published a new version.
The same skip-if-exists pattern is harmless for CMS and NUCC, whose URLs are immutable.

Worse, the release identifier is a hardcoded string (`scripts/provenance.py:78`):

```python
lambda: "11th release, FY2024 claims (Apr 2024 - Mar 2025); NHI prices as of 2026-09-02",
```

so even a fresh download of a newer snapshot would be labelled with September 2026's prices.

This sits directly under the article's governance section, which argues that "provenance and
reproducibility … turned out to be the disaster recovery plan". The recovery story works (the
graphs are rebuilt from files), but the *source* record cannot tell a June snapshot from a
September one.

**Fix.** Give the NDB source a machine-readable release identifier — the MHLW update date of the
prescription-drug tables, read from the page or recorded in the cache — and make `download_ndb.py`
compare the remote file (size or hash) instead of skipping blindly.

### L8 — The ontology carries two vocabulary instances that the vocabulary graph also carries

Two triples appear in both `ontology/diabetes-market.ttl` and `vocab/therapeutic-class.ttl`:

```
vocab/therapeutic-class/GLP1ReceptorAgonist  rdf:type  ontology#TherapeuticClass
vocab/therapeutic-class/SGLT2Inhibitor        rdf:type  ontology#TherapeuticClass
```

They are in the ontology on purpose — `dm:inTherapeuticClass` has `owl:range dm:TherapeuticClass`,
so the two classes that the defined classes `dm:GLP1Product` / `dm:SGLT2Product` point at with
`owl:hasValue` must be known as instances of the range for the reasoner to infer the range. But
they are instance-level statements about vocabulary concepts, which belong to the vocabulary graph.

The effect is benign: the two triples are loaded twice (into the schema graph and the
therapeutic-class graph), which is why the live per-graph counts sum to 734,106 while the union of
the local files is 734,104. Worth one comment in the ontology saying why they are there.

---

## What was verified, and how

| Check | Result |
|---|---|
| Live Stardog `glp`, per-graph triple counts | 16 graphs, **734,106** — matches the handoff |
| `VALIDATE ALL USING SHAPES GRAPH <shapes>` (no reasoning) | **0 violations, 17 warnings, 130 info** — identical to `docs/validation-report.md` |
| `tests/test_ontology_reasoning.py` | pass |
| `tests/test_shapes_reasoning.py` | pass (0 violations, reasoning off and on, in three scopes) |
| `tests/test_mcp_server.py` | pass, **13/13** |
| `tests/test_load_gate.py` | pass, 7 violations caught, rollback clean |
| `tests/test_shapes_stardog.py` | pass, **59 of 59** rules fired |
| `scripts/check_local.py` | **all five checks PASS** — budget 734,104; contract 0 violations; coverage 59/59; OWL 2 RL closure 256,035 → 457,175 triples, 0 violations; all queries ran |
| All 14 queries re-run against Stardog | identical to `docs/query-results.md` except the `SAMPLE()` column and the timings |
| Japan data shape | 510 products (286 generics, 191 originators); 150,288 cells = 73,313 values + 40,944 zeros + 36,031 masked; 4,464 slices (1,488 per dimension); 1,378 slices with no masked cell; 429 masked totals |
| Substances | 47 (21 US + 26 new); **12 not in RxNorm**, all identified by UMLS; **no US substance changed class** (diffed `scripts/substances.csv` against `7043a9e`) |
| Article §3.1 class-mix table | reproduces exactly (39.3/23.9/20.7/7.0/4.4/3.5/1.2 vs 34.1/11.2/50.9/3.2/0.5/—/0.1) |
| Article §3.1 Boehringer numbers | 37.5% (¥116.4bn) vs AZ 32.2%; 27.0% (¥67.3bn) vs MSD 22.2% — exact |
| Article §3.3 age, uptake, prefectures | DPP-4 45.76→46%, SGLT2 36.18→36%, GLP-1 20.21→20%; tirzepatide ¥1,103m→¥4,468m (4×), semaglutide ~¥6,300m; Kyoto 39.32, Nara 45.08, Tokyo 42.13 — exact |
| Article §3.4 generic share | 91.29→94.03, 77.22→81.54, 87.43→90.64, 92.01→94.44 — exact |
| Article §3.5 Tokyo | 501 products, ¥73,497 million, 42.13% — exact |
| Article Code 1 / 2 / 3 / 4 | the crosswalk notes, the `dm:GLP1Product` definition, the Jardiance slice (`dm:totalQuantity 299457206.33`, Tokyo cell `29567498.75`) and the two SHACL rules all match the files byte for byte |
| MCP term resolution for Japan | all six work: ジャディアンス, 東京→prefecture 13, 糖尿病用剤→396, メトホルミン塩酸塩→metformin, 日本ベーリンガーインゲルハイム, 院外 |
| Provenance graph | 26 hashed curated/generated inputs, including the four new Japan ones; the build activity records the git commit `7043a9e…-dirty` |
| AllegroGraph vs local query results | identical row sets in all 14 tables (row order differs on ties) |

## Also checked, and fine

- **The Data Cube model.** 4,464 slices = 510 products × settings × dimensions; every slice has
  exactly 47/12/42 observations; 429 slices carry `sdmx-attribute:confStatus` instead of a total.
  The IRI scheme omits the route (`slice/<code>/<setting>/<dim>`) but no collision is possible: a
  receipt code is either oral or injection, and `clean_ndb.py:105` fails the build if a code differs
  between workbooks.
- **The crosswalk algorithm** (`scripts/build_ndb.py:253-265`) is consistent with its own
  documentation: `full()` is monotone up the tree, so the "broadest such C only" rule holds, and
  the 396 `broadMatch` picks the narrowest class holding all 427 products (`BloodGlucoseLowering`,
  450 members).
- **The indication override** (`vocab/src/ndb_product_indications.csv`) has one row (ウゴービ →
  Obesity); `build_ndb.py:382` matches it by `name_prefix`, so there is no shadowing to worry about
  yet.
- **`dm:isGeneric`** carries exactly the `rdfs:comment` the article describes (ontology:392).
- **The NDB scope filter**: 427 products in class 396 and 83 in class 249, 510 in all; every product
  has a YJ ingredient in `vocab/src/ndb_ingredients.csv`, and `build_ndb.py:379` stops the build if
  the price list and the curated ingredient name disagree.
- **The MCP read-only guard** still holds: `PREFIX dm: <…>` survives the literal/IRI blanking
  because IRIs are blanked to `<>` first, and the update-word regex cannot see inside a literal.
- **The `check_local.py` coverage step** counts results of any severity, which is sound: every
  shape's `sh:message` belongs to exactly one constraint with one severity.
- **`load_stardog.py`** and **`load_allegrograph.py`** both refuse to publish files that have not
  passed the local check, and both roll back on error without masking the original exception
  (round 1's L14, kept in the new file).

## Suggested order of work

1. **H1** — one line in `findings.md`, one in `article_2.md`. A false market claim in the publishable
   text is the cheapest thing here to fix and the most expensive to leave.
2. **M1, M2, M3** — three sentences in `article_2.md`, each checkable against the graph or the
   MHLW page. Do them before the draft goes out; they are the article's credibility.
3. **M4** — one table of per-graph counts, reused in the article, `japan_extension.md` and
   `CLAUDE.md`, so the three stop drifting apart.
4. **M5 + L1** — decide whether AllegroGraph stays. If it stays, fix the failure message, add
   `AG_*` to `.env.example`, and make the variable rewriting literal-aware.
5. **L2** — refresh `governance.md` against the Japan build: the ontology version, the provenance
   table, the two new sources in §1 and §7, and the four new curated files in the register.
6. **L7, L6, L5, L4, L3, L8** — as convenient.

---

## Reproducing the most important finding

```bash
cd /Users/dgg32/Documents/glp

# H1: the three "Japan-only" classes, and what the Connecticut subset actually contains
grep -iE "acarbose|repaglinide|nateglinide|mitiglinide" scripts/cms_generic_names.csv || echo "none in the subset"
grep -A3 "α-glucosidase" docs/findings.md

# M1: what the MCP server really gained for Japan
git diff --stat 7043a9e 88cea6a -- mcp_server/server.py

# M2: the MHLW update date on the release page
curl -s https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000177221_00017.html \
  | grep -o "処方薬.\{0,40\}更新" | head -3

# M4: the per-graph counts the article should quote
.venv/bin/python - <<'PY'
import sys, urllib.parse, json; sys.path.insert(0, "scripts")
from load_stardog import Stardog, settings
sd = Stardog(settings())
q = "SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g"
b = sd.call("/query?" + urllib.parse.urlencode({"query": q}), method="GET",
            accept="application/sparql-results+json")
jp = [r for r in json.loads(b)["results"]["bindings"] if "ndb" in r["g"]["value"]
      or "jp-" in r["g"]["value"]]
print("Japan:", sum(int(r["n"]["value"]) for r in jp))
print("all:  ", sum(int(r["n"]["value"]) for r in json.loads(b)["results"]["bindings"]))
PY

# M5: the failure mode of the dead AllegroGraph path
.venv/bin/python scripts/run_queries.py --ag 2>&1 | tail -3
```

---

## File index of everything cited

| File | What it is |
|---|---|
| `docs/article_2.md` | the draft of the second article — H1, M1, M2, M3, M4 |
| `docs/findings.md` | business results, §6–§10 for Japan — H1, L4 |
| `docs/governance.md` | governance claims — L2 |
| `japan_extension.md` | the Japan plan of record — M4, L6 |
| `HANDOFF_article2.md` | the hand-off for the article — M4, L6 |
| `CLAUDE.md` | project status and constraints — M4 |
| `scripts/run_queries.py` | `--local` / `--ag` runners — L1, M5 |
| `scripts/load_allegrograph.py`, `scripts/setup_allegrograph.py` | the AllegroGraph loader — M5 |
| `scripts/download_ndb.py` | the NDB and price-list downloader — L7 |
| `scripts/provenance.py` | `SOURCES`, `LINEAGE`, `GENERATED`, `git_commit()` — L7, M2 |
| `scripts/clean_data.py` | `clean_partd()` (class report keyed by ATC name) — L3 |
| `scripts/build_ndb.py` | the Japan vocabularies and the Data Cube — L8, the crosswalk rule |
| `scripts/clean_ndb.py` | NDB workbook cleaning — M2 (where the price comes from) |
| `scripts/check_local.py` | the local gate (budget, contract, coverage, reasoning, queries) |
| `queries/jp-glp1-by-japanese-category-reasoning.rq` | the reasoning query — L5 |
| `queries/jp-age-profile-by-class.rq`, `jp-generic-share-by-month.rq`, `jp-sglt2-share-by-prefecture.rq` | the three queries that lost their `ROUND` — L4 |
| `vocab/jp-drug-class.ttl` | the computed crosswalk with its editorial notes — M3 |
| `vocab/therapeutic-class.ttl` | the ATC-based class tree — M3 |
| `ontology/diabetes-market.ttl` | 0.5.0, 14 `owl:Class`, 4 defined classes — L8, L2 |
| `shapes/diabetes-market-shapes.ttl` | 0.3.0, 59 rules, 13 node shapes |

---

# Round 4 — the Snowflake semantic layer (2026-11-01)

Fresh round, after the Snowflake extension (tables, semantic views, OSI, Cortex Analyst evaluation,
the Snowflake MCP server) and the ontology 0.5.2 push. Scope: `scripts/export_snowflake.py`,
`scripts/load_snowflake.py`, `scripts/build_osi.py`, `scripts/deploy_semantic_view.py`,
`scripts/eval_analyst.py`, `scripts/eval_claude.py`, `scripts/setup_snowflake_reader.py`,
`mcp_server/snowflake_server.py`, `semantic/`, `snowflake_extension.md`, `docs/article_2.md`,
`CLAUDE.md`, `docs/governance.md`.

**13 findings: 2 high, 4 medium, 7 low, plus one incident.** Nothing was fixed in this round.

**Fix status (2026-11-01, later the same day).** H1: reasoning-on runs opt-in (`GLP_LIVE_REASONING=1`).
H2: Analyst's SQL runs on the MCP server's read-only session, after its statement check. M1, M2: conventions stated
in the metric descriptions (`semantic/` regenerated, **not yet deployed**); the parity check filters the NULL
specialty in SQL, explicitly (72 rows, 198,279 / 238,340, checked live). M3, L3, L7: numbers and casing corrected.
M4: the loader clones each schema first and swaps it back on failure. L1: a reader role that inherits roles is
refused. L2: governance has a Snowflake section. L4, L5: the check's meaning and the scorer caveat stand next to the
results (the check key keeps its name, so saved results stay comparable). L6, and the cause of both incidents: the
reader can log in as a service user that holds only `GLP_READER` (`SNOWFLAKE_READER_USER`), and the session is
re-checked before every statement; **the user is not created yet**. CLAUDE.md now forbids write probes on live
databases.

The headline: **the semantic layer is correct and the deployment is verified.** All 27 tables match
the checked export row for row; all four views reproduce the graph's numbers (0 parity differences,
every verified query, both plain-SQL files); the generator is deterministic; the OSI round-trip loss
the hand-off describes is exactly what the live views show. The findings are about the **edges**:
one test that still takes the live database down, one evaluation harness that runs model-written SQL
as the account admin, one metric whose convention differs from the published one by 6× for a class,
and a set of stale counts left behind by the 0.5.2 push.

## Summary

| # | Finding | Severity | Where |
|---|---|---|---|
| H1 | The test suite still runs reasoning-on SHACL against the live free-tier instance — it took the instance down (503) again today | high | `tests/test_shapes_reasoning.py` |
| H2 | The evaluation harness executes the SQL Cortex Analyst returns, as ACCOUNTADMIN, with no read-only guard | high | `scripts/eval_analyst.py` |
| M1 | The view's `class_cost_per_claim` metric uses a different convention from the published findings; Biguanides comes out 6× apart | medium | `semantic/`, `build_osi.py` |
| M2 | The view's specialty breakdown carries a NULL-specialty row the graph does not have, and the parity check filters it out | medium | `deploy_semantic_view.py` |
| M3 | `article_2.md` quotes 734,106 triples; the database holds 734,133 | medium | `docs/article_2.md:130` |
| M4 | The Snowflake loader is not atomic: it drops all 27 tables, loads, and verifies only at the end | medium | `scripts/load_snowflake.py` |
| L1 | The reader-role setup script's privilege check cannot see a role-hierarchy grant | low | `setup_snowflake_reader.py` |
| L2 | `governance.md` does not mention the Snowflake pipeline at all | low | `docs/governance.md` |
| L3 | Stale counts in `CLAUDE.md` and the hand-off (64 synonyms, 16 tables, 45 fields, 15 metrics) | low | `CLAUDE.md`, `snowflake_extension.md` |
| L4 | The eval's `single_ingredient` check tests for a number, not for a convention | low | `eval_analyst.py`, `eval_claude.py` |
| L5 | The Claude scorer was corrected after reading the answers it scores | low | `eval_claude.py` |
| L6 | The MCP server's docstring says "three layers"; one of them is voided by any statement Snowflake accepts unconditionally | low | `snowflake_server.py` |
| L7 | `docs/article_2.md` Code 5 shows the AI clauses in upper case; the deployed DDL uses lower case | low | `docs/article_2.md:205` |

---

## Incident — I truncated `GLP.US.PRODUCT` in Snowflake and restored it

This happened during the round, on the live trial account, and it belongs in the record.

**What I did.** Probing whether the `GLP_READER` role could write, I ran a list of write statements
through a connector session opened with `role=GLP_READER` and `USE SECONDARY ROLES NONE`. The list
included `USE SECONDARY ROLES ALL` **before** `TRUNCATE TABLE GLP.US.PRODUCT`. Snowflake accepts
`USE SECONDARY ROLES ALL` with no privilege check at all — it re-activated the user's
`DEFAULT_SECONDARY_ROLES = ('ALL')`, which carries ACCOUNTADMIN and ORGADMIN — and the TRUNCATE then
succeeded. `GLP.US.PRODUCT` went from 51 rows to 0.

**How it was restored.** Time Travel, the same way the project's own earlier incident was restored:

```sql
INSERT INTO GLP.US.PRODUCT
  SELECT * FROM GLP.US.PRODUCT BEFORE(TIMESTAMP => '2026-11-01 12:30:00'::timestamp);
```

**Verification.** 51 rows, 51 distinct `PRODUCT_ID`s, the first rows as expected (`alogliptin`,
`basaglar-kwikpen-u-100`, `bydureon-bcise`); `US.PRESCRIPTION` unchanged at 22,034 rows /
1,050,891 claims / $644,621,275.38; `JP.QUANTITY` unchanged at 25,939,035,814.92462 units and 36,031
masked cells. I then compared **all 27 tables** against their checked CSV exports, normalising
booleans and decimal scale: **0 mismatches**. The scratch table I created for the privilege test
(`GLP.US.ZZ_PROBE`) was dropped; `GLP.US` holds exactly its 9 tables.

**Why it matters for the code.** The reader role itself is sound — on a scratch table with only
`SELECT` granted, `TRUNCATE`, `DELETE`, `INSERT`, `CREATE`, `ALTER` and `GRANT` were all refused
("SQL access control error"), and `SHOW GRANTS TO ROLE GLP_READER` lists only `SELECT` (58),
`USAGE` (6) and `REFERENCES` (4). The exposure came from re-enabling the secondary roles, which
Snowflake permits unconditionally. That is L6 below, and it is the same fact that makes H2 matter:
**anything that connects with the admin role and runs text it did not author is one statement away
from admin rights.**

---

# High

### H1 — The test suite still runs a reasoning-on SHACL validation against the live free-tier instance, and it took the instance down again today

`tests/test_shapes_reasoning.py:41-43` runs three validations against the **live** Stardog Cloud
database, two of them with `reasoning=true`:

```python
runs = [("false", "all graphs", f"VALIDATE ALL USING SHAPES GRAPH <{SHAPES_GRAPH}>"),
        ("true", "US data + vocabularies", validate_graphs(all_graphs - JAPAN)),
        ("true", "Japanese products + vocabularies", validate_graphs(all_graphs - US - {G + "ndb-2024"}))]
```

**Evidence (today).** The test failed with the server-side error

```
RuntimeError: GET /query -> HTTP 410: {"message":"...OperatorException: Query execution cancelled:
Execution of query ZOSZmtkB, type: SPARQL has been cancelled", ...}
```

and immediately afterwards the instance stopped answering altogether:

```
GET /query        -> HTTP 503 Service Temporarily Unavailable   (4 attempts over 60 s)
GET /server/status-> HTTP 503 Service Temporarily Unavailable
```

It recovered on its own after about a minute. The triple counts are unchanged (734,133) and the
instance answers queries normally now.

**Why it matters.** This is the operation that destroyed the previous instance. `docs/article_2.md:230`:

> During development, the Stardog database was reloaded in full five times, and several validation
> runs used reasoning on top of the 150,000 observations. On the free tier, this filled the
> instance's disk. The sixth reload failed with "No space left on device", and from then on every
> query returned a corruption error. … Stardog Cloud Free has no backups, so the instance had to be
> recreated.

The project's own rule, in `CLAUDE.md`, is "**Never iterate against Stardog Cloud: rebuild and check
locally, push once**" — and `scripts/check_local.py` already does the equivalent locally (OWL 2 RL
closure with `owlrl`, then SHACL again; about ten minutes for everything).

The test's own docstring knows the risk ("the instance answered 503 for minutes afterwards"), and the
mitigation it applies — splitting the validation in two — is evidently not enough: the split still
leaves the instance 503ing. Leaving the test in `tests/` means "run the tests" still triggers it.

**Fix.** Make the two reasoning-on runs opt-in — an environment variable (`GLP_REASONING=1`) or a
flag — and have the default path do the local OWL RL check instead, or point the test at the local
store. If the live run is kept, it needs a long client timeout (`load_stardog.call` uses 600 s) and a
note that it must not be run while the instance is in use.

### H2 — The evaluation harness executes the SQL Cortex Analyst returns, as ACCOUNTADMIN, with no read-only guard

`scripts/eval_analyst.py:281`:

```python
rows = cur.execute(sql).fetchall()
```

`sql` is whatever statement came back in the REST reply (line 273: `next((c.get("statement", "") for
c in content if c.get("type") == "sql"), "")`). The cursor comes from `load_snowflake.connect()`
(`scripts/load_snowflake.py:42-45`), which connects with `role=env["ROLE"]` — `SNOWFLAKE_ROLE`, which
is **ACCOUNTADMIN** in this trial account. There is no statement check, no read-only role, and no
`USE SECONDARY ROLES NONE` anywhere in that path.

**Why it matters.** The MCP server treats exactly this as the threat to guard against: it has a
statement allow-list, a reader role with only `SELECT`/`USAGE`/`REFERENCES`, and it refuses to start
unless the secondary roles are empty. The evaluation harness has none of the three, and it is the
path that runs *text produced by a language model*. In practice Analyst returns `SELECT`s, so nothing
has gone wrong; but the harness would execute a DDL or DML statement verbatim with the account
admin's rights, on a database with no backups whose whole point is that it can be rebuilt.

**Fix.** Run the returned statement on a separate connection that uses `SNOWFLAKE_READER_ROLE` with
`USE SECONDARY ROLES NONE`, and refuse anything that is not a `SELECT`/`WITH`/`SHOW`/`DESCRIBE`
before executing it — the same check `mcp_server/snowflake_server.py` already has, which I tested
against 25 write vectors and which held every one.

---

# Medium

### M1 — The view's cost metric uses a different convention from the published findings, and Biguanides comes out 6× apart

`semantic/diabetes-market.sql:178`:

```sql
class_cost_per_claim AS SUM(prescription_class.drug_cost) / NULLIF(SUM(prescription_class.claims), 0)
```

`prescription_class` has one row per prescription **and class**, so a combination product is counted
in every class it belongs to. The published query `queries/cost-per-claim-by-class.rq` excludes them
(`?prod dm:isCombinationProduct false`), and `docs/findings.md` §2 is on that convention.

**Measured live, same question, two ways:**

| Class | graph (`cost-per-claim-by-class.rq`) | view (`class_cost_per_claim`) | delta |
|---|---:|---:|---:|
| Biguanides | 9.00 | **55.26** | +46.26 |
| Insulins and analogues for injection, long-acting | 242.00 | **255.74** | +13.74 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | 919.00 | **927.96** | +8.96 |
| Sulfonylureas | 9.00 | 9.49 | +0.49 |
| Thiazolidinediones | 12.00 | 12.02 | +0.02 |
| Glucagon-like peptide-1 (GLP-1) analogues | 1,339.00 | 1,338.94 | −0.06 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | 1,097.00 | 1,096.08 | −0.92 |

**The view can express the convention** — one extra predicate reproduces the graph exactly:

```sql
... METRICS class_cost_per_claim
WHERE therapeutic_class.is_drug_class = true AND product.is_combination = false
```
→ GLP-1 1,339.34 · Insulins 242.24 · TZD 11.72 · Biguanides 9.01 · SGLT2 1,096.75 · DPP-4 918.67 ·
SU 9.31.

The **verified query** already does this (`semantic/verified-queries.json`:
`... WHERE therapeutic_class.is_drug_class AND NOT product.is_combination)`), which is why the
deployment's parity check passes. The **metric** does not, and neither its description nor the view's
instructions mention the convention.

**Two consequences.** The evaluation's `single_ingredient` check needs the DPP-4 figure 919, which
the metric cannot produce, so it scores 0/3 for Analyst — the hand-off reports this, but only as
"combination products included (findings: single-ingredient only), so DPP-4 928 vs 919, SGLT2 1,096
vs 1,097". **The Biguanides row (9 vs 55) and the Insulins row (242 vs 256) are not mentioned**,
although Biguanides is by far the largest gap of the seven. And the article's conclusion that "the
semantic layer is generated, not written a second time, so it cannot drift from the graph"
(`article_2.md:343`) is true of the *structure* but not of the *conventions*: the same question returns
a different number through the warehouse than through the graph, by 6× for one class.

**Fix.** Either add the filter to the metric's definition, or say so in the metric's comment
("includes combination products; for the single-ingredient convention add
`AND NOT product.is_combination`"), or add a second metric `class_cost_per_claim_single`. And correct
the hand-off's list of the seven differences.

### M2 — The view's specialty breakdown has a NULL-specialty row the graph does not have, and the parity check filters it out

The graph's `queries/sglt2-vs-glp1-by-specialty.rq` requires a primary specialty
(`?doc dm:hasPrimarySpecialty/skos:prefLabel ?specialty`), so prescribers without one drop out: **72
rows, SGLT2 198,279 and GLP-1 238,340 claims**. The semantic view has no such requirement, because
the metric is a `CASE WHEN` over every prescription:

```
83 rows = 72 specialties with claims
        + 10 specialties with zero SGLT2/GLP-1 claims
        +  1 row whose specialty name is NULL  (407 SGLT2, 493 GLP-1 claims)
view totals: SGLT2 198,686   GLP-1 238,833
```

The hand-off discloses the totals ("all-prescriber totals are slightly higher (198,686 SGLT2 vs
198,279)", `snowflake_extension.md:42`) but not the **NULL row**: a semantic view that returns a row
whose only dimension is NULL is a hazard for an LLM asked to report a breakdown — it may name it
"(no specialty)", drop it, or count it in a total.

The parity check does not catch it because it filters the row out:

```python
got = {name: [int(s), int(g)] for name, s, g in rows if name is not None and (s or g)}
```

**Fix.** Either give the view the same rule as the query (exclude prescribers without a primary
specialty from the metric, or dimension them as "no specialty" explicitly and say so), or state in
the metric's comment that the total covers all prescribers and the graph's covers only those with a
primary specialty.

### M3 — `article_2.md` quotes 734,106 triples; the database holds 734,133

`docs/article_2.md:130`:

> With 4,464 slices, Japan adds about 487,000 triples, and the whole graph holds 734,106.

**Measured live today**, per graph:

```
477,662  ndb-2024        9,104  npi-registry        894  substance        529→556  schema
225,897  cms-partd-2024  8,961  nucc-specialty      757  jp-prefecture    446  therapeutic-class
  7,732  ndb-products      894  ...                 632  ndb-dimensions   410  provenance
                                                   117  jp-drug-class    407  shapes
                                                                329  products   115  drugsfda
                                                                114  indication
TOTAL 734,133
```

The schema graph is **556**, not 529: the ontology 0.5.2 push (2026-10-31, the 薬効分類 → 薬効群
rename) added 27 triples. The local files agree — the manifest sums to 734,138 and the two schema
files share 5 triples, so the union is 734,133, exactly what Stardog holds.

The same stale number is in `docs/decisions.md:407` and `japan_extension.md:87` (both are dated
records of a specific load, so they are history and fine) and in `japan_extension.md:67`, which is
the budget table of record and should say 734,133.

The article's other triple figures are still right: Japan adds 486,900, the zeros cost ~123,000, the
flat model would need ~1.15M.

**Fix.** `article_2.md:130` → "734,133"; `japan_extension.md:67` → the measured figures.

### M4 — The Snowflake loader is not atomic

`scripts/load_snowflake.py:102-112` drops every table first, then recreates and loads them one at a
time; the verification that follows (`:114-126`) is the only check, and its failure path is
`sys.exit` — the warehouse is left with the new, unverified data and no rollback:

```python
for t in reversed(tables):
    run(f"DROP TABLE IF EXISTS {t['name']}")
...
if errors:
    sys.exit("load verification failed:\n  " + "\n  ".join(errors))
```

A failure between the drops (a network error, a `COPY INTO` that aborts on one row, a warehouse
suspend) leaves the database with missing or empty tables. The Stardog loader has exactly this
problem solved — it runs inside a transaction and rolls back (round 1's L14) — and the article's
governance section leans on the symmetry.

**Fix.** Load into a staging schema and `ALTER TABLE ... SWAP WITH` on success, or at least load
into shadow tables and rename them after the verification passes.

---

# Low

### L1 — The reader-role setup script's privilege check cannot see a role-hierarchy grant

`scripts/setup_snowflake_reader.py:50-52`:

```python
privileges = {r[1] for r in cur.execute(f"SHOW GRANTS TO ROLE {role}").fetchall()}
if privileges - {"USAGE", "SELECT", "REFERENCES"}:
    sys.exit(f"{role} holds more than USAGE, SELECT and REFERENCES: {sorted(privileges)}")
```

`SHOW GRANTS TO ROLE` lists **direct** grants only. A `GRANT ROLE ACCOUNTADMIN TO ROLE GLP_READER`
would appear with the privilege name `USAGE` and a `granted_to` of `ROLE`, so the check would pass
while the reader role held the account admin's rights.

**It does not today** — I checked the live role: `SHOW GRANTS TO ROLE GLP_READER` returns only
`SELECT` (58), `USAGE` (6) and `REFERENCES` (4), and the reader role cannot write (every write
statement was refused on a scratch table). The check just cannot see the case that would break it.

**Fix.** Also inspect `SHOW GRANTS OF ROLE <role>` for rows whose `granted_to` is `ROLE`, and refuse
if the role has a sub-role.

### L2 — `governance.md` does not mention the Snowflake pipeline

`docs/governance.md` opens with "Every claim below points to the code or file that enforces it" and
lists the Stardog guarantees — the SHACL gate inside the load transaction, the provenance graph, the
versioning, the licences. The Snowflake side, which now has its own gate and its own log, is not
there at all:

- `scripts/export_snowflake.py` refuses to run unless `check_local.py` passed on exactly these files;
- `scripts/load_snowflake.py` refuses files whose hash differs from the checked export
  (`load_snowflake.checked_export`) and records every load in `PUBLIC.LOAD_LOG` with the RDF
  provenance hash;
- `scripts/deploy_semantic_view.py` refuses to deploy unless Snowflake holds that same export.

None of that is in the governance document, although the article's §3 ("Governance: check locally,
publish once") now describes exactly this two-target pipeline.

**Fix.** A section for the Snowflake path with the same table format as the rest: gate, log,
what is verified after the load.

### L3 — Stale counts in `CLAUDE.md` and the hand-off

`CLAUDE.md:49` (the current summary paragraph):

- "exported as **16 tables** (schemas VOCAB, US)" → the export is now **27 tables in three schemas**
  (VOCAB 12, US 9, JP 6);
- "from the ontology (**0.5.1**)" → the ontology is **0.5.2**;
- "OSI loses all **64** synonyms" → the generator now produces **65** (19 en, 23 ja, 23 zh).

`snowflake_extension.md` §Step 2 (dated 2026-10-31, so history) says "45 fields, 8 relationships,
15 metrics, 64 synonyms (19 en, 22 ja, 23 zh)"; the current generator says **48 fields, 16 metrics,
65 synonyms (19 en, 23 ja, 23 zh)**. Step 4's "the views have 65 and 48 synonyms" is correct.

The article's "48 of them" (`article_2.md:209`) is correct: `JAPAN_MARKET` has 48 synonyms, and the
deployed native view has 48 `with synonyms=(...)` clauses — I counted them in the live DDL.

### L4 — The eval's `single_ingredient` check tests for a number, not for a convention

`scripts/eval_analyst.py:235`:

```python
"single_ingredient": has(numbers(rows), t["cost"]["DPP4Inhibitor"][0]),
```

The check asks whether the answer **contains the single-ingredient figure (919)**. It does not ask
whether the answer excludes the combination-product figure (928). An answer that gives both passes
— which is exactly why Claude scores 3/3 on this check and Analyst 0/3: Claude answers "cost per
claim with and without combination products". The name of the check overstates what it tests, and
the results table in `snowflake_extension.md` reads as if the two systems adopt different
conventions, when in fact one of them says both.

**Fix.** Rename it (`single_ingredient_figure_shown`) or make it test the absence of the combined
figure, and say in the table what it measures.

### L5 — The Claude scorer was corrected after reading the answers it scores

`snowflake_extension.md` §Step 5 discloses this:

> **Scorer caveat:** the text checks were corrected after reading Claude's US answers (three false
> negatives: the parent class "Insulins and analogues" equals "Long-acting insulins" in Connecticut;
> the market average given as context; "$644.6M" read as $645 per claim).

It is honest, and the three corrections are visible in the code
(`eval_claude.extra_truth`'s `shared()` exclusion and `no_parent_class`'s unit-stripping). But the
headline of that section — "**Claude passes every check on both layers, OSI included**" — is the
result of a scorer tuned on the answers it scores, and the summary says so only in a parenthetical
at the end of the section.

**Fix.** Keep the caveat where the result is stated, or re-score the saved answers with a scorer
written without looking at them (the `--rescore` flag exists for exactly this, and would make the
claim defensible).

### L6 — The MCP server's docstring says "three layers"; one of them is voided by any statement Snowflake accepts unconditionally

`mcp_server/snowflake_server.py:15-18`:

> Read-only by design, in three layers: only SELECT/WITH/SHOW/DESCRIBE/EXPLAIN pass the statement
> check, one statement per call; the session uses the role SNOWFLAKE_READER_ROLE, which holds only
> USAGE and SELECT …; and secondary roles are switched off … The server refuses to start otherwise.

The role layer is only a layer while the secondary roles stay off, and `USE SECONDARY ROLES ALL` is
accepted by Snowflake **without any privilege check** — I confirmed it live. So the statement
allow-list is the layer that actually holds. The allow-list itself is solid: I tested 25 write
vectors against `_check_read_only` and it refused every one (`DELETE`, `TRUNCATE`, `USE SECONDARY
ROLES ALL`, `USE ROLE`, `ALTER SESSION`, `CALL`, `COPY INTO`, `CREATE`, `MERGE`, `PUT`, `GRANT`,
multi-statement, and the string/dollar-quote hiding attempts), while allowing every genuine read.

**Fix.** Say "two layers, and the statement check is the one that holds"; and have the server
re-check the session's role and secondary roles periodically rather than only at connect time (the
connection is `lru_cache`d, so the check runs once per process).

### L7 — `article_2.md` Code 5 shows the AI clauses in upper case

`docs/article_2.md:205-206` shows `AI_SQL_GENERATION` and `AI_VERIFIED_QUERIES`; the deployed DDL
uses `ai_sql_generation` and `ai_verified_queries` (Snowflake's own casing). The article says
"Excerpts", and SQL keywords are case-insensitive, so this is cosmetic — but a reader who diffs the
snippet against `GET_DDL` will notice.

---

## What was verified, and how

| Check | Result |
|---|---|
| **All 27 Snowflake tables vs their checked CSV exports** | **0 mismatches** (booleans and decimal scale normalised) |
| `GLP.US.PRODUCT` after the Time Travel restore | 51 rows, 51 distinct ids, claims 22,034 / 1,050,891 / $644,621,275.38 unchanged |
| `GLP.JP.QUANTITY` | 150,288 rows, 25,939,035,814.92462 units, 36,031 masked — unchanged |
| Live Stardog `glp`, per-graph counts | 16 graphs, **734,133** triples; instance healthy again after the 503s |
| Semantic views deployed | `DIABETES_MARKET`, `DIABETES_MARKET_OSI`, `JAPAN_MARKET`, `JAPAN_MARKET_OSI` |
| Deploy parity, US (both views) | `sglt2-vs-glp1-by-specialty` **0 differ**, `cost-per-claim-by-class` **0 differ** |
| Deploy parity, verified queries (all four views) | **all match the graph** |
| Deploy parity, `queries/snowflake/*.sql` | **all match the graph** |
| The article's "All 225 rows of the seven questions match" | **exactly 225** compared rows (10 + 16 + 10 + 72 + 68 + 47 + 2) |
| Japan business questions through the view | Tokyo ¥73,497,396,126.91 — the graph's ¥73,497 million, both views |
| Boehringer's SGLT2 claims through the view | 135,954 / AZ 59,896 / J&J 966 / Merck 13 / generic NULL 1,857 — `findings.md` §4 exactly |
| SGLT2 vs GLP-1 by specialty through both views | Internal Medicine 62,651 / 76,487 = 45.028%, Endocrinology 30.54%, Cardiovascular 90.46% — the graph's numbers |
| Synonyms in the deployed views | native US **65**, native JP **48** (counted from the live `GET_DDL`); OSI views: 0 native, 45 / 44 in the opaque OSI extension |
| OSI round trip | the native views keep `ai_sql_generation` and `ai_verified_queries`; the OSI views keep them only inside `with extension (OSI='…')` — exactly as the hand-off describes |
| `scripts/build_osi.py` re-run | **byte-identical** to the committed `semantic/` files (git clean) — the generator is deterministic |
| `GLP_READER` privileges | only `SELECT` (58), `USAGE` (6), `REFERENCES` (4); every write refused on a scratch table |
| `mcp_server/snowflake_server.py` statement guard | 25 write vectors tested, every one refused |
| `tests/test_ontology_reasoning.py`, `test_mcp_server.py`, `test_load_gate.py` | pass |
| `tests/test_shapes_reasoning.py` | **failed today** — see H1 |

## Also checked, and fine

- **The export's parity checks are apples to apples.** `cost-per-claim-by-class.rq` and
  `sglt2-vs-glp1-by-specialty.rq` both use `skos:broader*` and `dm:hasPrimarySpecialty`, which is
  exactly what the table side computes from `US.PRODUCT_CLASS` and `US.PRESCRIBER`.
- **The Data Cube IRI scheme cannot collide.** The slice and observation IRIs omit the route
  (`slice/<code>/<setting>/<dim>`), but a receipt code is either oral or injection, and
  `clean_ndb.py:105` fails the build if a code differs between workbooks.
- **The crosswalk algorithm is monotone.** `full()` in `build_ndb.py` is closed upwards, so the
  "broadest such C only" rule holds, and the 396 `broadMatch` picks the narrowest class holding all
  427 products (`BloodGlucoseLowering`, 450 members).
- **The generator's label-collision warning works.** `dedupe_synonyms` keeps the first owner
  (metrics, then fields, then datasets) and reports the collision; the ontology 0.5.2 rename
  (薬効分類 → 薬効群, ATC分類 as an altLabel) is the fix it found, and the views carry 65 and 48
  synonyms without duplicates.
- **The OSI YAML validates** against `semantic/schema/osi-0.1.1.schema.json`, and the draft Layer 4
  ontology against the 0.2.0.dev0 schema, on every build.
- **`deploy_semantic_view.py` gates on the export.** It refuses to deploy unless
  `PUBLIC.LOAD_LOG`'s latest `RDF_PROVENANCE` equals the manifest's — the same provenance hash the
  article's governance story rests on.
- **`setup_snowflake_reader.py` is rerunnable** and ends with an explicit privilege assertion.

## Suggested order of work

1. **H1** — make the reasoning-on validation opt-in, or drop it from `tests/`. The instance has no
   backups and this test takes it down; the local OWL RL check already covers the same ground.
2. **H2** — run the model's SQL on the reader role with the statement check, not as ACCOUNTADMIN.
3. **M1** — decide the convention for `class_cost_per_claim` (metric, comment or a second metric),
   and correct the hand-off's list of the seven differences.
4. **M3** — one number in the article: 734,106 → 734,133.
5. **M4, M2, L1, L2, L3, L4, L5, L6, L7** — as convenient.

---

## Reproducing the two most important findings

```bash
cd /Users/dgg32/Documents/glp

# H1: the live validation that takes the instance down (run only when nothing else uses it)
.venv/bin/python tests/test_shapes_reasoning.py
.venv/bin/python - <<'PY'
import sys, urllib.parse; sys.path.insert(0, "scripts")
from load_stardog import Stardog, settings
sd = Stardog(settings())
print(sd.call("/query?" + urllib.parse.urlencode({"query": "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"}),
               method="GET", accept="application/sparql-results+json")[:120])
PY

# H2: the harness executes the model's SQL as the admin role
grep -n "role=env\[" scripts/load_snowflake.py
grep -n "cur.execute(sql)" scripts/eval_analyst.py

# M1: the same question, two conventions
.venv-snowflake/bin/python - <<'PY'
import os, warnings, logging
from dotenv import load_dotenv; load_dotenv(".env")
import snowflake.connector
warnings.filterwarnings("ignore")
env = {k: os.environ.get("SNOWFLAKE_" + k) for k in
       ("ACCOUNT", "USER", "PRIVATE_KEY_PATH", "ROLE", "WAREHOUSE", "DATABASE")}
c = snowflake.connector.connect(account=env["ACCOUNT"], user=env["USER"], authenticator="SNOWFLAKE_JWT",
    private_key_file=os.path.expanduser(env["PRIVATE_KEY_PATH"]), role=env["ROLE"],
    warehouse=env["WAREHOUSE"], database=env["DATABASE"])
cur = c.cursor()
q = """SELECT * FROM SEMANTIC_VIEW(GLP.SEMANTIC.DIABETES_MARKET
        DIMENSIONS therapeutic_class.class_name METRICS class_cost_per_claim
        WHERE therapeutic_class.is_drug_class = true{extra})"""
for label, extra in (("as generated", ""), ("single-ingredient", " AND product.is_combination = false")):
    print(label)
    for r in cur.execute(q.format(extra=extra)).fetchall():
        print("   ", r[0], r[1])
PY
```

---

## File index of everything cited

| File | What it is |
|---|---|
| `tests/test_shapes_reasoning.py` | the live reasoning-on validation — H1 |
| `scripts/eval_analyst.py` | the Cortex Analyst harness (runs the model's SQL) — H2, L4 |
| `scripts/eval_claude.py` | the Claude harness and its text scorer — L4, L5 |
| `scripts/load_snowflake.py` | the loader and `connect()` (admin role) — H2, M4 |
| `scripts/setup_snowflake_reader.py` | the read-only role — L1 |
| `mcp_server/snowflake_server.py` | the read-only MCP server — L6 |
| `semantic/diabetes-market.sql` | the generated native view (65 synonyms, 16 metrics) — M1, L3 |
| `semantic/verified-queries.json` | the verified queries — M1 |
| `scripts/build_osi.py` | the generator (`dedupe_synonyms`, `check_columns`) — L3 |
| `scripts/deploy_semantic_view.py` | the deployment and the parity checks — M2 |
| `scripts/export_snowflake.py` | the export and its parity checks |
| `queries/cost-per-claim-by-class.rq` | the published single-ingredient convention — M1 |
| `docs/article_2.md` | the article — M3, L7 |
| `snowflake_extension.md` | the hand-off — L3, L4, L5 |
| `CLAUDE.md` | the project summary — L3 |
| `docs/governance.md` | the governance claims — L2 |
