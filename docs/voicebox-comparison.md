# Voicebox vs the glp-stardog MCP server

Same question to both, scored against the verified answer in [findings.md](findings.md).

## Q1. 勃林格殷格翰在SGLT2抑制剂中的市场份额是多少？ (Boehringer's share of SGLT2 inhibitors)

**Verified answer:** 135,954 of 198,686 SGLT2 claims = **68.4%** (cost share 71.3%).

### MCP server + Claude Code (2026-10-14): correct

`describe_model` → `resolve_term "勃林格殷格翰"` (company, from the Chinese label) →
`resolve_term "SGLT2抑制剂"` (drug class) → one `run_sparql` → answer in Chinese:
68.4% of claims, 70.1% of 30-day fills, 71.3% of cost, with a per-product breakdown and the
right caveats (combination products, Medicare only, claims not patients, gross cost).

### Stardog Voicebox (2026-10-14): wrong, for two reasons

Voicebox translated the question and generated this pattern:

```sparql
?therapeuticClass stardog:label "SGLT2 inhibitors" .
?substance ns2:inTherapeuticClass ?therapeuticClass .
?product ns2:hasActiveSubstance ?substance .
?prescription ns2:forProduct ?product ; ns2:totalClaims ?allClaims ; ns2:totalDrugCost ?allCost .
OPTIONAL {
  ?product ns2:manufacturedBy ?manufacturer .
  ?manufacturer stardog:label "Boehringer Ingelheim" .
  ?prescription ns2:totalClaims ?boehringerClaims ; ns2:totalDrugCost ?boehringerCost .
}
... (SUM(?boehringerClaims) ...) (ROUND(100.0 * SUM(?boehringerClaims) / SUM(?allClaims), 2) ...)
```

1. **Entity lookup missed the drug class (our data, fixed).** `stardog:label` reads only
   `rdfs:label`; the SKOS concepts had only `skos:prefLabel`. Result: every total was 0.
   After mirroring prefLabels to rdfs:label, the class is found and the SGLT2 totals are right
   (198,686 claims, $217.8M).
2. **SUM over an OPTIONAL variable (Voicebox's query, not fixable in the data).** For
   non-Boehringer rows `?boehringerClaims` is unbound; by the SPARQL spec an unbound value makes
   `SUM` an error, so the Boehringer total and both shares come back empty. The same pattern as a
   plain join returns the correct 135,954. A correct query would use
   `SUM(COALESCE(?boehringerClaims, 0))`.

Also note: the query uses `ns2:inTherapeuticClass` without `skos:broader*`. That happens to be
fine for SGLT2 (no narrower classes) but would miss tirzepatide (Mounjaro) for GLP-1.

### Stardog Voicebox, second run after the label fix (2026-10-14): wrong, 0.0273%

```sparql
SELECT DISTINCT ((SUM(?biCost) / SUM(?allCost)) * 100 AS ?marketSharePercent)
WHERE {
  ?org stardog:label "Boehringer Ingelheim" .
  ?substance ns1:inTherapeuticClass ?therapeuticClass .
  ?therapeuticClass stardog:label "SGLT2 inhibitors" .
  ?product ns1:hasActiveSubstance ?substance ; ns1:manufacturedBy ?org .
  ?prescription ns1:forProduct ?product ; ns1:totalDrugCost ?biCost .
  { SELECT (SUM(?cost) AS ?allCost) WHERE { ... all SGLT2 prescriptions ... } }
}
GROUP BY ?allCost
```

- Entity lookup now works (both labels found, thanks to the rdfs:label fix).
- **Aggregation bug:** the subquery returns the SGLT2 total once, but the outer query joins it to
  each of the 2,615 Boehringer prescription rows and then takes `SUM(?allCost)`, multiplying the
  denominator by 2,615. Check: true cost share 71.27% / 2,615 = **0.027255%**, exactly the value
  returned. `?allCost` (or `SAMPLE(?allCost)`) instead of `SUM(?allCost)` would give 71.27%.
- It silently chose cost share rather than claims share (68.4%), took 9.3 s, and returned a bare
  number without explanation, language or caveats.

### Stardog Voicebox, third run (2026-10-25): right number, wrong question

- Results table: one column, `boehringerSGLT2Cost` = **155,210,266.23**. That matches the verified
  Boehringer SGLT2 gross cost exactly (`market-share-by-manufacturer.rq`: 155,210,266), so entity
  lookup, the class filter and the sum are all correct.
- But it computed no share: no SGLT2 total, no percentage. The "1.55" in the Chinese answer is
  1.55亿 (155 million), i.e. the same absolute cost, not a market share.
- **Encoding:** every Chinese character in the conversation, the question included, displayed as a
  literal `?`. Latin text (Boehringer Ingelheim, SGLT2, Synjardy XR, Tradjenta) survived. Literal
  `?` rather than empty boxes means a non-UTF-8 conversion on Voicebox's side, not a missing font.
  The answer text is therefore unreadable; only the results table could be checked.

**Score after three runs:** Voicebox 0/3 correct (two broken aggregations, one answer to a
different question); MCP + Claude 1/1 correct.

## English question set (2026-10-25)

Reference answers verified against Stardog the same day. One run per platform per question.

| Question | Reference | MCP + Claude Code | Voicebox |
|---|---|---|---|
| Q1. What percentage of all SGLT2 inhibitor claims are for Boehringer Ingelheim products? | **68.4%** (135,954 / 198,686 claims) | 68.4%, per-product breakdown, cost share 71.3% as a side note: **correct** | no answer: hit its step limit; had switched to cost ($155.21M / $217.776M, both correct totals) instead of claims: **wrong** |
| Q2. How many prescribers wrote at least one claim for a GLP-1 receptor agonist? | **2,362** of 3,896 | 2,362, checked two ways (reasoning on, and `skos:broader*`): **correct** | 2,288, lists five GLP-1 substances without tirzepatide: the no-roll-up trap, **wrong** |
| Q3. Among cardiovascular disease physicians, what share of their combined SGLT2 inhibitor and GLP-1 receptor agonist claims is for SGLT2 inhibitors? | **90.5%** (20,536 / 22,702 claims) | 90.5%, 250 prescribers, notes subspecialties are separate NUCC codes: **correct** | 92.59%, computed on dollars ($30,458,200 / $32,897,200) that match no figure in the data (cardiology cost is $25,373,559 SGLT2, $2,643,895 GLP-1 incl. tirzepatide, $2,112,239 without): **wrong** |

Trap values for reference: without `skos:broader*`, Q2 gives 2,288 and Q3 gives 92.3% (20,536 /
22,256 claims; GLP-1 1,720 claims without tirzepatide).

**Caveat on fairness:** the first three Claude Code runs were in one conversation after the Chinese
Q1, and the English Q1 answer says it reused the earlier query's numbers instead of running again.

**Rerun in a new Claude Code session (2026-10-25, 12:16–12:17): 3/3 correct, every answer from its
own queries.**

- Q1: `resolve_term` for the class and the company, one `run_sparql` → 68.4% (135,954 / 198,686),
  per-product table that adds up to the reference company totals (AstraZeneca 59,301 + 595 =
  59,896; J&J 954 + 12 = 966), cost share 71.3%, and a sensitivity check without combination
  products (132,179 / 194,304 = 68.0%).
- Q2: two independent queries, `skos:broader*` path and `dm:GLP1Prescriber` with reasoning, both
  2,362; names tirzepatide as the reason the roll-up matters. (The IDE attached an article line as
  context; it did not contain the answer.)
- Q3: resolves the specialty to NUCC 207RC0000X, one query with and without narrower
  specialties, both 20,536 / 2,166 → 90.5%.

**Score, English set:** MCP + Claude 3/3, Voicebox 0/3. **Overall so far:** MCP + Claude 4/4,
Voicebox 0/6.

### Studio gotcha

If text is selected in the query editor, Studio runs only the selection. Running with the
question comment highlighted produced a parse error at line 1, column 1.
