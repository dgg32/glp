# Building a Governed Diabetes Prescription Knowledge Graph in RDF

*A Medicare-based graph that explains itself, checks its own quality and speaks three languages*

Drug names are confusing. Most drugs have two names. The generic name is the active ingredient and stays the same whoever makes it, while the brand name is the trade name the manufacturer puts on the box. The generic semaglutide, for example, is sold under three brands. Ozempic is a diabetes injection, Wegovy a weight-loss injection and Rybelsus a diabetes tablet, yet all three are the same molecule. Many people who know “Ozempic” from the news have never heard the word semaglutide or know that it is a GLP-1 (glucagon-like peptide-1) drug, let alone its Japanese or Chinese names. When drug data reaches an AI model, the model has to guess which names belong together, and those guesses can lead to hallucinations. A knowledge graph removes the guesswork. Every drug becomes one entity, with its synonyms, its place in a hierarchy and its links to the rest of the data, such as its manufacturer and the doctors who prescribe it. The same structure also makes governance possible, which matters more in medicine than almost anywhere else. Imagine an AI assistant answering a question about Ozempic. That answer should be traceable to its source, the version of the data and the checks it passed.

Mention a knowledge graph, and most people think of a property graph like Neo4j. Property graphs are intuitive and pleasant to develop with. Their query language Cypher is one of the most readable around and inspired GQL (Graph Query Language), the new ISO standard for graph queries. But a property graph's schema mostly lives in application code and in the heads of its developers. One team's "Drug" may be a brand like Ozempic, another team's "Drug" the molecule semaglutide, and nothing in the database records the difference. A rule like "a doctor who prescribes a GLP-1 drug is a GLP-1 prescriber" cannot be stored in the database itself either. It has to be repeated in every query that needs it. And combining graphs from two companies means first agreeing on what every label means. 

The other major kind of knowledge graph, RDF (Resource Description Framework), was designed for exactly these problems. RDF itself is the basic data format. Every fact is a simple statement such as "Ozempic contains semaglutide", and every drug, doctor and drug class gets a unique web address, so two datasets that mention semaglutide point to exactly the same thing. Three standards of the World Wide Web Consortium (W3C), SKOS (Simple Knowledge Organization System), OWL (Web Ontology Language) and SHACL (Shapes Constraint Language), are built on top of RDF and written in RDF themselves, so the meaning sits in the graph right next to the data. SKOS records that semaglutide is called セマグルチド in Japanese and belongs to the GLP-1 class. OWL stores rules such as the definition of a GLP-1 prescriber. SHACL checks that the data is complete and well-formed before anyone uses it. Together they fill the gaps that property graphs leave open. Pharma has already built on this stack. IDMP-O, the Pistoia Alliance's ontology for the ISO standards for the Identification of Medicinal Products (IDMP), is written in OWL and uses SKOS for its definitions and labels.

This article builds such an RDF graph from public data, covering 2024 Medicare Part D claims for 32 diabetes medicines in Connecticut, with all prescribers pseudonymized. SKOS vocabularies name drugs and specialties in English, Japanese and Chinese, an OWL ontology defines the core concepts and links them to IDMP-O, and SHACL rules check the data before it is loaded. The finished graph runs in Stardog, where it answers market questions such as which specialties favour SGLT2 (sodium-glucose co-transporter 2) inhibitors over GLP-1 drugs, and an AI assistant can query it in plain language. The code for this project is hosted on my GitHub repository [here](https://github.com/dgg32/glp).

## 1. Building the RDF graph

The graph is built in four steps: gather the data, name things with SKOS, define the concepts and rules with OWL, and check the result with SHACL. Each step is a Python script that can be rerun from cached API responses.

### 1.1 Data

The core of the graph is the 2024 dataset *Medicare Part D Prescribers by Provider and Drug* from the Centers for Medicare & Medicaid Services (CMS). This project uses its Connecticut rows for 32 diabetes medicines: 22,034 records from 3,896 prescribers, each record summing up one prescriber's claims for one drug over the year. Other public sources fill in the rest:

- The National Provider Identifier (NPI) Registry gives each prescriber's specialty.
- RxNorm (the US drug dictionary) gives each drug's ingredients and classes.
- openFDA gives its indications and manufacturer.
- MeSH (Medical Subject Headings) supplies the standard terms for those indications.
- GLEIF (Global Legal Entity Identifier Foundation) identifies the parent company.

The data covers Medicare only (mostly people aged 65 and over), counts claims rather than patients and leaves out rows with fewer than 11 claims. The graph also pseudonymizes the doctors to protect their privacy.

### 1.2 SKOS
SKOS turns the drug classes and the medical specialties into concept schemes. The drug classes form a tree taken from ATC (Anatomical Therapeutic Chemical), the WHO's drug classification: *drugs used in diabetes* branches into classes such as *SGLT2 inhibitors*, and empagliflozin sits in that class. The specialties form a second tree from the taxonomy of the US National Uniform Claim Committee (NUCC), for example *Internal Medicine* above *Cardiovascular Disease*. Every drug class, substance and indication has labels (`skos:prefLabel`, `skos:altLabel`) in English, Japanese and Chinese and links to its ATC, RxNorm or MeSH entry; the specialties most common in the data have Japanese and Chinese labels too. In a property graph, each team invents its own names for these things, such as a `name_ja` property for the Japanese name and an `IS_A` relationship for the tree, and others have to ask what they mean. `skos:prefLabel` and `skos:broader` are W3C standards, so any SKOS tool reads them the same way.

### 1.3 OWL
The ontology is small, with ten classes such as `MedicinalProduct`, `Substance` and `HealthcareProfessional`, each declared a subclass of its IDMP-O counterpart where one exists. The defined class `GLP1Prescriber` turns the introduction's rule into an axiom: with reasoning off Stardog finds no GLP-1 prescribers, and with reasoning on it finds 2,362, a label that no source file contains. In Cypher, the same rule would have to be repeated in every query or written onto the nodes by a batch job that goes stale.

### 1.4 SHACL
OWL works in an open world: it adds facts but never complains that something is missing, so SHACL checks the closed world with 38 rules such as "every product has an active substance". Its first run found no bad data but two bugs in the pipeline, and after the fixes the data passes with zero violations, while a file of deliberately broken records shows that all 38 rules can fire. A test also validates the data with reasoning both off and on, so the rules never contradict what OWL infers. Neo4j constraints cover uniqueness, existence and property types, but a rule like "a count is present or its suppression flag is set" ends up in application code.

## 2. Governance

The introduction promised that an answer should be traceable to its source, the version of the data and the checks it passed. Each source lives in its own named graph, and a record in PROV-O, the W3C's provenance ontology, for every graph lists the source releases and retrieval times it was built from, along with a content hash of the graph itself. The ontology and the SHACL rules carry versions (0.4.0 and 0.2.0), each linked to its previous version, and every build records the git commit of the code that made it. The SHACL rules also run inside the load transaction, so a single violation rolls back the whole load. A property graph has no named graphs, so the same provenance would have to be copied onto every node and relationship.


## 3. Using the graph

### Query: what the graph says about the market

SPARQL (SPARQL Protocol and RDF Query Language) queries over the graph answer typical commercial questions. Heart and kidney doctors prescribe SGLT2 drugs almost exclusively (90% of their SGLT2 and GLP-1 claims in cardiology, 92% in nephrology), endocrinologists lean towards GLP-1 (31% SGLT2), and Boehringer Ingelheim holds about two thirds of all SGLT2 claims. The queries name only the drug class, and `skos:broader*` pulls in every substance and product below it, including combination pills and Mounjaro's tirzepatide. The data shows patterns, not causes, because it cannot say why a drug was prescribed.

### Stardog explorer

> TODO: what Explorer shows, plus a screenshot.

### MCP: Asking the graph in plain language

An MCP (Model Context Protocol) server makes the graph usable from Claude or any other MCP client through three tools: `describe_model`, `resolve_term` and `run_sparql`. `resolve_term` matches a name in any language against the SKOS labels, so 勃林格殷格翰 (Boehringer Ingelheim) and SGLT2抑制剂 (SGLT2 inhibitors) become exact IRIs (the graph's web addresses) before any SPARQL is written. Asked in Chinese for Boehringer's share of SGLT2 claims, Claude answered correctly with 68.4%, while Stardog's built-in Voicebox got the same question wrong in two runs because of errors in its own queries.

## Conclusion

RDF does not replace property graphs: it is better as the layer that holds meaning and rules (SKOS for names, OWL for definitions, SHACL for checks), while a property graph is better for traversal and graph algorithms. A practical setup keeps the model and the SHACL contract in RDF and copies the data into Neo4j, for example with neosemantics, when it needs algorithms.

*Code and data pipeline: [github.com/dgg32/glp](https://github.com/dgg32/glp). Prescribers are pseudonymized; the graph stores no names or NPIs.*
