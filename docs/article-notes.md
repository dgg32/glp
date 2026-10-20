# Article notes

Story material for the Medium article, collected while building.

## SHACL caught my own pipeline before it caught the data

*Probably the best story for the article. Recorded 2026-10-14.*

### The setup

I wrote 37 SHACL rules as the "modeling contract" for the knowledge graph and ran them in
Stardog against the real Connecticut data (244,482 triples). The first run did not find bad
data. It found two problems in **my own pipeline**.

### Catch 1: the database quietly changed my data types

- The converter wrote every claim count as `xsd:nonNegativeInteger`, matching the ontology.
- Stardog stores integer subtypes in canonical form, so the counts came back as plain
  `xsd:integer`.
- My rule "total claims must be an `xsd:nonNegativeInteger`" therefore failed on **all 22,034
  prescription rows**.
- Nothing else would have noticed: queries, sums and the reasoner all worked fine. Only a
  closed-world check that compared "what I meant to store" with "what the database actually
  holds" exposed the mismatch.
- Fix: write counts as `xsd:integer` and check the range with `sh:minInclusive 0`. This check
  works the same in every triple store.

### Catch 2: a rule that silently did nothing useful

- The rule "every substance has an exactMatch to RxNorm" used `sh:qualifiedValueShape` with
  `sh:pattern` on the link's IRI.
- In Stardog 12 the pattern did not match IRIs in that position, so the rule flagged **all 21
  substances**, though every one has an RxNorm link.
- Fix: rewrite it as a small SHACL-SPARQL constraint (`FILTER NOT EXISTS { ... STRSTARTS(...) }`),
  after a probe confirmed that Stardog runs SPARQL-based constraints.

### The twist: proving the rules can fail

After the fixes the real data showed **0 violations**. That raises a fair question: are the rules
working, or silently passing? So I wrote one deliberately broken record per rule
(`tests/shacl/broken-examples.ttl`) and validated it in a temporary graph. The first attempt
showed **34 of 37** rules firing. The 3 gaps were in my test file, not in the rules. After
adding those cases, **37 of 37** fired.

### What the rules found in the real data

| Severity | Count | Finding |
|---|---:|---|
| Violation | 0 | No real errors |
| Warning | 13 | Prescribers missing from the NPI Registry, so no specialty |
| Warning | 3 | Prescription rows with $0.00 total drug cost (generic glipizide, metformin, glimepiride) |
| Warning | 1 | Byetta has two application holders on record (Amylin, AstraZeneca) |
| Info | 130 | Primary specialty registered as "Student in an Organized Health Care Education/Training Program" |

### The point for a Neo4j audience

- **OWL and SHACL do different jobs.** OWL is open-world: it adds facts and never complains that
  something is missing. SHACL is closed-world: it checks that the data has exactly the shape you
  promised. A property graph schema gives you some of the second and none of the first.
- **The contract protects you from your own tools.** The most valuable catches were mismatches
  between the converter, the ontology and the database, not dirty source data.
- **Test the tests.** "0 violations" means nothing until you have seen every rule fail on
  purpose.
- **Severity matters.** Violation blocks publishing, Warning needs a look, Info marks a known
  quirk analyses should account for. The 130 "students" are not errors, but anyone ranking
  specialties needs to know about them.

### Files to show

- Rules: `shapes/diabetes-market-shapes.ttl`
- Runner and summary: `scripts/validate.py` → `docs/validation-report.md`
- Every-rule-fires test: `tests/test_shapes_stardog.py` with `tests/shacl/broken-examples.ttl`
- Decision log: `docs/decisions.md` (section "SHACL shapes as the modeling contract")

## Knowledge in the query vs knowledge in the model

**The point: Cypher puts the knowledge in the query; OWL puts it in the model, so every query,
person and AI tool gets it for free.**

- **The roll-up itself is not exclusive to RDF.** "All substances in *drugs used in diabetes*" works in
  Cypher with a variable-length path (`-[:IN_THERAPEUTIC_CLASS*1..]->`) and in SPARQL without
  reasoning with a property path (`dm:inTherapeuticClass/skos:broader*`). This project's own
  business queries use the property path.
- **The difference is where the rule lives.** In OWL it is stated once, in the ontology:
  `dm:inTherapeuticClass owl:propertyChainAxiom ( dm:inTherapeuticClass skos:broaderTransitive )`.
  With reasoning on, even a naive query (`?s dm:inTherapeuticClass dmtc:DrugsUsedInDiabetes`)
  finds metformin. Without the axiom, every query writer and every tool has to know the pattern.
- **Real example from this project:** Stardog Voicebox generated `?substance dm:inTherapeuticClass
  ?class` without `skos:broader*` (see `docs/voicebox-comparison.md`). For GLP-1 that misses
  tirzepatide (Mounjaro); with the rule in the model, the same naive query would be right.
- **Inference can create categories, not just paths.** `dm:SGLT2Prescriber` is defined, never
  asserted: Stardog finds 2,701 SGLT2 prescribers with reasoning on and 0 with it off (checked in
  `tests/test_mcp_server.py`). In Neo4j the same set is either a repeated query or a stored label
  that goes stale.
- **Keep membership and hierarchy apart.** A Neo4j sketch often reuses one relationship type for
  "substance is in class" and "class is in class". The RDF model separates membership
  (`dm:inTherapeuticClass`) from hierarchy (`skos:broader`, a W3C standard), and the axiom says
  how they combine.
- **Honest trade-off:** reasoning can slow queries and surprise people who do not know the axioms,
  so say whether it was on (the MCP tool has a `reasoning` switch). Neo4j can approximate some of
  this with the neosemantics (n10s) inference procedures.

## RDF and property graphs are not rivals

*Closing position for the article. Recorded 2026-10-15.*

The two aren't really rivals. RDF is better as the meaning-and-contract layer, and property
graphs are better as the traversal-and-analytics engine. Many pharma setups use both, and
neosemantics (n10s) bridges RDF into Neo4j. For the article, an honest framing is that you'd keep
the semantic model and the SHACL contract in RDF and project into Neo4j or LadybugDB when you need
algorithms. That's a credible position for a Neo4j Ninja applying for a semantic role.
