# Diabetes prescription knowledge graph in RDF

An RDF knowledge graph of 2024 Medicare Part D prescribing of type 2 diabetes drugs in Connecticut,
built with SKOS, OWL and SHACL and served from Stardog. It is the code behind the Medium article
in [docs/article.md](docs/article.md).

- **Data:** 22,034 prescriber × drug records for 32 diabetes medicines (GLP-1, SGLT2, DPP-4,
  metformin, sulfonylureas, pioglitazone, long-acting insulins) from 3,896 prescribers, about a
  quarter of a million triples.
- **SKOS:** drug class tree (ATC), substances, indications (MeSH) and the NUCC specialty taxonomy,
  with English, Japanese and Chinese labels and `skos:exactMatch` links to ATC, RxNorm, MeSH and
  Wikidata.
- **OWL:** a small ontology aligned with [IDMP-O](https://github.com/edmcouncil/idmp) 1.4.0,
  including defined classes such as `GLP1Prescriber` that only exist with reasoning on.
- **SHACL:** 38 rules that run inside the load transaction; one violation rolls back the load.
- **Governance:** one named graph per source, PROV-O provenance with source releases and content
  hashes, versioned ontology and shapes.
- **MCP server:** lets Claude or any MCP client query the graph in plain language, in any of the
  three languages.

## Privacy

The CMS data contains real prescriber names and NPIs. The pipeline replaces every NPI with a keyed
HMAC pseudonym and loads no names into the graph. Raw downloads, cleaned data and the generated
RDF are git-ignored and **not published**: the pseudonymized graph could still be re-identified by
joining it with the public CMS file. To get the graph, run the pipeline yourself.

## Repository layout

| Folder | Contents |
|---|---|
| [ontology/](ontology/) | OWL ontology (`diabetes-market.ttl`) and the IDMP-O extract it imports |
| [vocab/](vocab/) | SKOS concept schemes (therapeutic classes, substances, indications) and their curated sources |
| [shapes/](shapes/) | SHACL shapes, the modelling contract |
| [scripts/](scripts/) | The pipeline, plus curated and generated lookup tables (`*.csv`) |
| [queries/](queries/) | Business questions as SPARQL; results in [docs/query-results.md](docs/query-results.md) |
| [mcp_server/](mcp_server/) | The `glp-stardog` MCP server, see its [README](mcp_server/README.md) |
| [tests/](tests/) | Reasoning, SHACL, load-gate and MCP tests; deliberately broken records in `tests/shacl/` |
| [docs/](docs/) | Article, design decisions, findings, governance, validation report, Voicebox comparison |

## Requirements

- Python 3.11 or later
- A [Stardog Cloud](https://cloud.stardog.com) database (the free tier is enough) named `glp`
- A [UMLS API key](https://uts.nlm.nih.gov/uts/profile) (free with a UMLS licence), used for MeSH
  and ATC lookups

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in the key, Stardog credentials and UMLS key
```

## Build and load

Run the scripts in this order. Every script caches its API responses in `data/raw/`, so reruns are
fast and repeatable. The CMS API is slow, about 5 s per call.

```sh
.venv/bin/python scripts/download_partd.py          # CMS Part D rows for Connecticut
.venv/bin/python scripts/resolve_drugs.py           # substances, ATC codes, drug classes (RxNorm, FDA)
.venv/bin/python scripts/resolve_vocab.py           # class tree and indications (RxClass, UMLS, MeSH)
.venv/bin/python scripts/resolve_products.py        # brands and indications (RxNorm, openFDA)
.venv/bin/python scripts/resolve_organizations.py   # manufacturers and parent companies (GLEIF)
.venv/bin/python scripts/fetch_wikidata_labels.py   # Japanese and Chinese labels
.venv/bin/python scripts/fetch_npi.py               # prescriber specialties (NPI Registry)
.venv/bin/python scripts/download_nucc.py           # NUCC specialty taxonomy
.venv/bin/python scripts/clean_data.py
.venv/bin/python scripts/build_skos.py
.venv/bin/python scripts/build_rdf.py
.venv/bin/python scripts/load_stardog.py            # one transaction, SHACL gate before commit
.venv/bin/python scripts/validate.py                # writes docs/validation-report.md
.venv/bin/python scripts/run_queries.py             # writes docs/query-results.md
```

## Querying

The data lives in named graphs, so queries in Stardog need
`FROM <tag:stardog:api:context:all>`. The defined classes `dm:GLP1Prescriber` and
`dm:SGLT2Prescriber` appear only with reasoning on. Example queries are in [queries/](queries/),
for instance SGLT2 vs GLP-1 share by specialty and Boehringer Ingelheim's share of SGLT2 claims.

To ask questions in plain language, set up the MCP server as described in
[mcp_server/README.md](mcp_server/README.md).

## Tests

```sh
.venv/bin/python tests/test_ontology_reasoning.py   # OWL inferences, local reasoner
.venv/bin/python tests/test_shapes_reasoning.py     # SHACL gives the same result with reasoning off and on
.venv/bin/python tests/test_shapes_stardog.py       # every SHACL rule fires on the broken examples
.venv/bin/python tests/test_load_gate.py            # a violation rolls back the load
.venv/bin/python tests/test_mcp_server.py           # MCP tools through a real MCP client
```

## Data caveats

Medicare Part D only, so mostly people aged 65 and over. Counts are claims, including refills, not
patients. CMS leaves out prescriber-and-drug rows with fewer than 11 claims. Costs are gross, before
rebates. The data shows what was prescribed, not why.

## Sources

CMS Medicare Part D Prescribers by Provider and Drug (2024), NPI Registry, NUCC Health Care
Provider Taxonomy, RxNorm and RxClass, UMLS, MeSH, openFDA and Drugs@FDA, GLEIF, Wikidata and
IDMP-O. All are public; check each source's terms before reusing derived data. The NUCC taxonomy
file is downloaded by the pipeline and not redistributed here.
