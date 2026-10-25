# Building a Governed Diabetes Prescription Knowledge Graph in RDF

*A Medicare-based graph that explains itself, checks its own quality and speaks three languages*

Drug names are confusing. Most drugs have two names. The generic name is the active ingredient and stays the same whoever makes it, while the brand name is the trade name the manufacturer puts on the box. The generic semaglutide, for example, is sold under three brands. Ozempic is a diabetes injection, Wegovy a weight-loss injection and Rybelsus a diabetes tablet, yet all three are the same molecule. Many people who know "Ozempic" from the news have never heard the word semaglutide or know that it is a GLP-1 (glucagon-like peptide-1) drug, let alone its Japanese or Chinese names. When an AI model answers questions about drugs, it has to guess which names belong together, and those guesses can lead to hallucinations. A knowledge graph removes the guesswork. Every drug becomes one entity, with its synonyms, its place in a hierarchy and its links to the rest of the data, such as its manufacturer and the doctors who prescribe it. The same structure also makes governance possible, which matters more in medicine than almost anywhere else. Imagine an AI assistant answering a question about Ozempic. That answer should be traceable to its source, the version of the data and the checks it passed.

Mention a knowledge graph, and most people think of a property graph like Neo4j. Property graphs are intuitive and quick to develop with. Their query language Cypher is one of the most readable around and inspired the ISO standard GQL (Graph Query Language). But a property graph's schema mostly lives in application code and in the heads of its developers. One team's "Drug" may be a brand like Ozempic, another team's "Drug" the molecule semaglutide, and nothing in the database records the difference. A rule like "a doctor who prescribes a GLP-1 drug is a GLP-1 prescriber" cannot be stored in the database itself either. It has to be repeated in every query that needs it. And combining graphs from two companies means first agreeing on what every label means. 

The other major kind of knowledge graph, RDF (Resource Description Framework), was designed for exactly these problems. RDF itself is the basic data format. Every fact is a simple statement such as "Ozempic contains semaglutide", and every drug, doctor and drug class gets a unique web address, so two datasets that mention semaglutide point to exactly the same thing. Three standards of the World Wide Web Consortium (W3C), SKOS (Simple Knowledge Organization System), OWL (Web Ontology Language) and SHACL (Shapes Constraint Language), are built on top of RDF and written in RDF themselves, so the meaning sits in the graph right next to the data. SKOS records that semaglutide is called セマグルチド in Japanese and belongs to the GLP-1 class. OWL stores rules such as the definition of a GLP-1 prescriber. SHACL checks that the data is complete and well-formed before anyone uses it. Together they fill the gaps that property graphs leave open. Pharma has already built on this stack. IDMP-O, the Pistoia Alliance's ontology for the ISO standards for the Identification of Medicinal Products (IDMP), is written in OWL and uses SKOS for its definitions and labels.

This article builds such an RDF graph from public data, covering 2024 Medicare Part D claims for 32 diabetes medicines in Connecticut, with all prescribers pseudonymized. SKOS vocabularies name drugs and specialties in English, Japanese and Chinese, an OWL ontology defines the core concepts and links them to IDMP-O, and SHACL rules check the data before it is loaded. The finished graph runs in Stardog, a commercial RDF database with a built-in reasoner. SPARQL (SPARQL Protocol and RDF Query Language) queries there answer market questions such as which medical specialties favour SGLT2 (sodium-glucose co-transporter 2) inhibitors over GLP-1 drugs, and a custom MCP (Model Context Protocol) server lets Claude answer such questions in plain language. The code for this project is hosted on my GitHub repository [here](https://github.com/dgg32/glp).

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
SKOS is the graph's dictionary: it records what each thing is called, in which language, and where it sits in a family tree of broader and narrower terms. This project has two such family trees, which SKOS calls concept schemes: one for drug classes and one for medical specialties. The drug class tree comes from the WHO's Anatomical Therapeutic Chemical (ATC) classification: *drugs used in diabetes* branches into classes such as *SGLT2 inhibitors*, and empagliflozin sits in that class. The specialty tree comes from the US National Uniform Claim Committee (NUCC): *internal medicine* branches into narrower specialties such as *cardiovascular disease*, better known as cardiology.

Every drug class, substance and indication has English, Japanese and Chinese labels (`skos:prefLabel`, `skos:altLabel`) and links to its ATC, RxNorm or MeSH entry. The most common specialties in the data have Japanese and Chinese labels, too. Because SKOS terms are W3C standards with a fixed meaning, anyone who receives the data, whether another team, another company or an off-the-shelf tool, knows what each property means without asking. In a property graph, by contrast, each team invents its own names for these things, such as a `name_ja` property for the Japanese name and an `IS_A` relationship for the tree, and has to document what they mean for everyone else.

### 1.3 OWL
If SKOS is the dictionary, OWL is the blueprint: it defines what kinds of things exist and how they relate. In industry, "ontology" can mean anything from a list of terms to an entire data platform: Palantir calls the whole data layer of its Foundry product the Ontology, and property-graph teams often use the word for their schema. In this project, the ontology is one OWL file (`ontology/diabetes-market.ttl`) with the classes, relationships and rules, while the SKOS vocabularies, the SHACL rules and the data each live in their own files. The ontology declares the graph's node types and edge types. It has ten classes, such as `MedicinalProduct`, `Substance` and `HealthcareProfessional`, and nine relationships between them, such as `prescribedBy` and `hasActiveSubstance`.

Three of the classes, `MedicinalProduct`, `Substance` and `Indication`, are subclasses of their IDMP-O counterparts. IDMP-O's medicinal product class covers medicines of every kind, including veterinary drugs and medicines never sold in the US. Our graph holds only 51 US diabetes products, so our product class is a smaller group inside IDMP-O's. We could also declare the two classes equivalent, but that would mean they have exactly the same members, which is wrong. For example, Jardiance is in both, but a veterinary drug is only in IDMP-O's. The subclass link is still enough to connect the two. When a query asks for IDMP-O's `MedicinalProduct`, Stardog's reasoner follows the link down through ours and finds Jardiance, without a mapping table.

Attaching Jardiance directly to IDMP-O's class would also work, but the subclasses have two advantages. First, subclasses draw a boundary around the project's own products, substances and indications. A query can ask for these alone, even when other IDMP-O data sits in the same database, and the project rules apply only inside that boundary. A SHACL rule (section 1.4), for example, says that every product needs exactly one CMS generic name, a US Medicare detail that IDMP-O lacks. Attached to IDMP-O's class, that rule would flag every European product in a shared database. Second, they shield the project from IDMP-O changes. If IDMP-O renames or moves a class, we only change one subclass line instead of every triple, query and rule.

Unlike a Neo4j constraint, the ontology never rejects data. Instead, Stardog's reasoner reads it and draws conclusions. This lets a rule such as "a doctor who prescribes a GLP-1 drug is a GLP-1 prescriber" live in the database itself, which a property graph cannot do. The class `GLP1Prescriber` states the rule precisely: any healthcare professional who wrote a prescription for a product whose active substance belongs to the GLP-1 class. No data file marks anyone as a GLP-1 prescriber, so with reasoning off Stardog returns none. With reasoning on, it follows the chain prescriber → prescription → product → substance → class and returns 2,362 prescribers. In Neo4j, that chain would have to be spelled out in every Cypher query that needs it, or a job would have to add a `:GLP1Prescriber` label to the nodes and be rerun whenever the data changes.

### 1.4 SHACL
If OWL is the blueprint, SHACL is the building inspector. The two work under opposite assumptions. OWL makes the *open-world assumption*: a fact missing from the graph is unknown, not false. If a product has no active substance on record, OWL assumes the substance exists and simply hasn't been recorded, so it does not complain. That suits the web, where no single dataset can claim to know everything. SHACL makes the *closed-world assumption*: whatever the graph does not say is treated as absent. So under SHACL, that product without a substance breaks the rule "every product has an active substance" and gets reported.

The project has 38 such rules. Their first run found no bad data, but it did expose two bugs in the pipeline. After the fixes, the data passes with zero violations, and a negative test with deliberately broken records shows that every one of the 38 rules can fire. Another test runs the validation with reasoning both off and on, because with reasoning on, SHACL checks the facts OWL infers as well as the stored ones. In comparison, Neo4j constraints cover uniqueness, existence and property types, but a rule like "a count is present or its suppression flag is set" ends up in application code. In SHACL it is a few lines of data:

```turtle
dms:PrescriptionShape a sh:NodeShape ;
    sh:targetClass dm:Prescription ;
    # A count is present OR its suppression flag is set, never both, never neither.
    sh:xone (
        [ sh:path dm:totalBeneficiaries ; sh:minCount 1 ]
        [ sh:path dm:beneficiaryCountSuppressed ; sh:hasValue true ]
    ) ;
    sh:message "Either the beneficiary count is present or it is flagged as suppressed (exactly one of the two)." .
```

CMS hides beneficiary counts below 11 to protect patient privacy, so every prescription record must either carry a count or say that it was hidden. `sh:xone` means "exactly one of these", a condition Neo4j constraints cannot express.

## 2. Governance: provenance, versions and checks

In medicine, as in finance and other regulated industries, data governance is a requirement, not a nice-to-have: an answer should be traceable to its source, the version of the data and the checks it passed. RDF handles the source with named graphs. Despite the name, a named graph is not a separate network of nodes and edges. It is a folder for triples: every triple in the database carries a fourth element, the name of its folder. This project sorts its triples into folders by where they came from, such as `graph:cms-partd-2024` for the CMS claims and `graph:npi-registry` for the specialties. Because a folder's name is itself a web address, the folder can be described with ordinary RDF triples. The description is written in PROV-O, the W3C's provenance ontology. Code 4 shows the description of the CMS claims folder, shortened.

```turtle
graph:cms-partd-2024 a prov:Entity ;
    prov:wasDerivedFrom  <https://dgg32.github.io/glp/data/source/cms-partd> ;
    prov:generatedAtTime "2026-10-20T13:19:44+00:00"^^xsd:dateTime ;
    dcterms:extent       "225897 triples" ;
    dcterms:identifier   "sha256:b0510530…" .
```

It records which source the folder's triples came from, when they were built, how many there are and a content hash, so any change to the data shows up as a different hash. The source has a record of its own that names the release and the retrieval time. A property graph has no named graphs, so the same provenance would have to be copied onto every node and relationship.

Besides the source, governance also has to track the version of the graph and the checks the data passed.

Every rebuild of the graph can change the data, and the ontology and rules change over time too, so an answer can only be reproduced with the exact versions that produced it. The ontology and the SHACL rules carry version numbers, 0.4.0 and 0.2.0, each linked to its previous version, and every build records the git commit of the code that made it.

The checks are the SHACL rules from section 1.4. They run inside the load transaction: a single violation rolls back the whole load, so everything in the database has passed all 38 rules.

## 3. Using the graph

### Query: what the graph says about the market

The finished graph holds about a quarter of a million triples. It was loaded into a database on Stardog Cloud's free tier. Every query in this section runs there. SPARQL queries over the graph answer typical commercial questions. One query compares SGLT2 inhibitors with GLP-1 drugs by specialty. Heart and kidney doctors strongly favour SGLT2: of all the SGLT2 and GLP-1 claims written by cardiologists, 91% are for an SGLT2 inhibitor, and for nephrologists the figure is 92%. Endocrinologists lean the other way, with SGLT2 at only 31% of their claims for the two classes. Another query shows that Boehringer Ingelheim holds 68% of all SGLT2 claims, about two thirds. The queries name only the drug class, and `skos:broader*` pulls in every substance and product below it, including combination pills and Mounjaro's tirzepatide. However, the numbers show what was prescribed, not why.

### Stardog explorer

Similar to Neo4j Bloom, Stardog has an interactive graph interface called Explorer, where users can search for nodes and examine their relationships without writing SPARQL. A search for Jardiance brings up the product, and a few clicks expand it to its active substance empagliflozin, then to its drug class *SGLT2 inhibitors* and up the class tree to *drugs used in diabetes*. Nodes are coloured by class and edges carry the ontology's relationship names, so the model from section 1 is visible at a glance. That makes Explorer a quick way for business users to see what the graph holds before anyone writes a query.

### MCP: Asking the graph in plain language

The MCP server makes the graph usable from Claude or any other MCP client through three tools: `describe_model`, `resolve_term` and `run_sparql`. `resolve_term` matches a name in any language against the SKOS labels, so the Chinese names 勃林格殷格翰 for Boehringer Ingelheim and SGLT2抑制剂 for SGLT2 inhibitors become the exact web addresses of the matching nodes before any SPARQL is written. Asked in Chinese for Boehringer's share of SGLT2 claims, Claude answered correctly with 68.4%.

I compared Stardog's built-in Voicebox with Claude and the MCP server on that Chinese question and three additional English ones, each with an answer verified by a hand-written SPARQL query. Voicebox answered the Chinese question wrongly in every attempt and turned every Chinese character in the conversation into a question mark. On the English questions, Claude answered all three correctly, while Voicebox answered none. Voicebox computed dollars when the question asked for claims, missed tirzepatide because it never walked the class tree, and once hit its limit on query attempts before it could calculate the percentage.

## Conclusion

This project took public Medicare data on diabetes drugs and turned it into an RDF graph that names its drugs in three languages, defines its own rules, checks its own quality and records where every fact came from. It was an interesting way for me to get my hands dirty in the world of RDF from a Neo4j user's perspective, and to see first-hand what SKOS, OWL and SHACL add on top of a graph. What follows is my personal take from this one project, not an objective verdict.

In my view, RDF is not a replacement for property graphs. Neo4j remains the more natural choice for traversals, graph algorithms and quick development. RDF has its niche where meaning has to be shared and trusted: standard vocabularies that other teams and companies can read without asking, rules stored in the database instead of in every query, alignment with industry ontologies such as IDMP-O, and provenance down to the source release, which also gives an AI assistant something reliable to query. A practical setup keeps the model and the SHACL rules in RDF and copies the data into Neo4j, for example with neosemantics, when graph algorithms are needed.

In my experience, RDF also has real costs. Much of the work is editing text files by hand, and Turtle with its long web addresses and prefixes is less forgiving than a few lines of Cypher. The logic takes time to master: a single defined class such as `GLP1Prescriber` needs four nested restrictions, and the open world of OWL and the closed world of SHACL can disagree in ways that only show up when reasoning is switched on. Tools are also scarce compared with the property-graph world, and even the commercial ones have gaps, as the Voicebox test showed.

*Code and data pipeline: [github.com/dgg32/glp](https://github.com/dgg32/glp). Prescribers are pseudonymized; the graph stores no names or NPIs.*
