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

**Score after two runs:** Voicebox 0/2 correct; MCP + Claude 1/1 correct.

**To do:** run the rest of the question set.

### Studio gotcha

If text is selected in the query editor, Studio runs only the selection. Running with the
question comment highlighted produced a parse error at line 1, column 1.
