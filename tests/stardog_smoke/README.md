# Stardog Cloud Free smoke test (about 5 minutes)

Checks three things before we build on them:

1. Stardog's reasoner understands our ontology (the SGLT2/GLP-1 prescriber classes).
2. The SKOS roll-up property chain works.
3. SHACL validation works on the Free plan.

Everything is toy data (four made-up doctors); nothing real is uploaded.

## 0. Rebuild the load file (only if the ontology changed)

```bash
.venv/bin/python tests/stardog_smoke/build_load_update.py
```

## 1. Create a test database

1. Log in to Stardog Cloud and open **Stardog Studio** for your Free endpoint.
2. In the **Databases** section, create a new database named `glp_smoke`. Keep the default settings (reasoning level SL).

Cloud Free allows 3 databases, so delete this one when you're done.

## 2. Load everything with one query

1. Open the **Workspace** (the query editor) and select `glp_smoke` as the database.
2. Open `tests/stardog_smoke/load-all.rq` in VS Code, copy all of it, paste it into the editor and **run** it.

It puts:
- the ontology and IDMP-O extract into `tag:stardog:api:context:schema`, which is the graph Stardog reads the ontology from (anywhere else and the reasoner ignores it)
- the toy data into the default graph
- two SHACL shapes into `https://dgg32.github.io/glp/graph/smoke-shapes`

## 3. Test 1: inferred prescriber classes

```sparql
PREFIX dm: <https://dgg32.github.io/glp/ontology#>
SELECT ?doctor ?type WHERE {
  VALUES ?type { dm:SGLT2Prescriber dm:GLP1Prescriber }
  ?doctor a ?type .
}
```

Run it twice:

| Reasoning switch | Expected result |
|---|---|
| **Off** | No rows (nobody was labelled a prescriber type) |
| **On** | `d:drA` → SGLT2Prescriber, `d:drB` → GLP1Prescriber |

## 4. Test 2: drug-family roll-up

```sparql
PREFIX dm: <https://dgg32.github.io/glp/ontology#>
PREFIX d:  <https://dgg32.github.io/glp/data/>
SELECT ?class WHERE { d:tirzepatide dm:inTherapeuticClass ?class }
```

| Reasoning switch | Expected result |
|---|---|
| **Off** | 1 row: `GIPGLP1Agonist` |
| **On** | 3 rows: `GIPGLP1Agonist`, `GLP1ReceptorAgonist`, `BloodGlucoseLowering` |

## 5. Test 3: SHACL validation

Run with reasoning **off**:

```sparql
VALIDATE ALL USING SHAPES GRAPH <https://dgg32.github.io/glp/graph/smoke-shapes>
```

Expected: a report with **2 violations**:
- `d:drD`: "NPI must be exactly 10 digits." (value `12345`)
- `d:rx4`: "Claim counts cannot be negative." (value `-3`)

## 6. Clean up

Delete the `glp_smoke` database.

## What to report back

For each test: did you get the expected result? If not, copy the result or error message.

| If this happens | It probably means |
|---|---|
| Test 1 with reasoning on still gives no rows, but test 2 works | `owl:hasValue` isn't supported in that position. Fix: rewrite the two classes as Stardog rules |
| Tests 1 and 2 both give no rows with reasoning on | The ontology didn't land in the schema graph, or reasoning is off for the database |
| Test 3 gives a syntax error | Try plain `VALIDATE ALL` (Stardog then uses shapes from any named graph) |
| Test 3 is refused or "not licensed" | SHACL isn't included in Cloud Free; validation would then run locally with pySHACL instead |
