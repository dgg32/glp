---
title: "Adding Japan to a Diabetes Drug Knowledge Graph in RDF"
subtitle: "One graph, two countries: a computed 薬効分類–ATC crosswalk, masked cells as data, and a defined class that finds every GLP-1 drug"
status: draft
---
<!-- Draft of article 2, written 2026-10-26 from HANDOFF_article2.md, docs/findings.md §6–10, docs/decisions.md (2026-10-25) and docs/query-results.md. Every number below is taken from those files. Lines in HTML comments are notes for the author and are not part of the article. -->

# Adding Japan to a Diabetes Drug Knowledge Graph in RDF

## One graph, two countries: a computed 薬効分類–ATC crosswalk, masked cells as data, and a defined class that finds every GLP-1 drug

<!-- Figure 1: Stardog Explorer around ジャディアンス錠10mg → empagliflozin → SGLT2 inhibitors → 糖尿病用剤 (396) and A10BK, plus 日本ベーリンガーインゲルハイム → the Boehringer group. -->
![](figure1.png)

Figure 1. ジャディアンス錠10mg (Jardiance 10 mg) and its neighbors in Stardog Explorer. Image by author.

The [previous article](https://medium.com/@dgg32/building-a-governed-diabetes-prescription-knowledge-graph-in-rdf-75667d126ee2) built an RDF knowledge graph from Medicare Part D claims for diabetes drugs in Connecticut. SKOS named the drugs in English, Japanese and Chinese, an OWL ontology aligned to IDMP-O defined the concepts and rules, and SHACL checked the data before it entered the database. That article explained the three standards. This one puts them to the test that matters most: a second dataset from another country.

Shared vocabularies earn their keep only when a second source arrives. With one dataset, a drug class tree is a convenience. With two, it is the only thing that makes the datasets comparable, and Japan stretches it in every direction. Japan files its drugs under its own classification, the 薬効分類 (therapeutic category) of the Japan Standard Commodity Classification, not under the WHO's ATC. Most GLP-1 (glucagon-like peptide-1) drugs, for example, are filed as "other hormone preparations" rather than as antidiabetics. Japan's national claims data counts dispensed tablets and pens, not claims or patients. It masks small numbers in a different way than CMS does. Several of its diabetes drugs are not sold in the US and are missing from RxNorm, the US drug dictionary. And it has no prescribers at all.

This article adds Japan's NDB Open Data for fiscal year 2024 to the same Stardog database as the Connecticut data. Both countries share one substance and drug class vocabulary, so a single SPARQL query can compare the two markets. A computed crosswalk links Japan's classification to ATC, an RDF Data Cube keeps 150,288 table cells within the free tier's one-million-edge limit, and 59 SHACL rules check the result. The code is in the same GitHub repository as before.

## [GitHub - dgg32/glp](https://github.com/dgg32/glp)

## 1. Building the Japanese part of the graph

### 1.1 Data

The Ministry of Health, Labour and Welfare (MHLW) publishes [NDB Open Data](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000177182.html), aggregate tables from the National Database of Health Insurance Claims. NDB covers almost every insured patient in Japan, whatever their age. The [11th release](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000177221_00017.html), first published in June 2026, covers fiscal year 2024 (April 2024 to March 2025). It is the first release without a cap on the number of products per class, so every product appears. The data is free to use with the source cited.

The prescription tables list each product at strength level, such as ジャディアンス錠10mg and ジャディアンス錠25mg as separate rows. For each product they give the dispensed quantity by prefecture, by month or by sex and five-year age band, in three care settings: outpatient prescriptions filled at a community pharmacy (院外), outpatient drugs dispensed at the clinic or hospital (院内) and inpatient use (入院). The three breakdowns are never crossed, so there is no prefecture by age table. This project takes every antidiabetic in category 396, every insulin and the GLP-1 and dual GIP/GLP-1 drugs filed under category 249: 510 products, 286 of them generics. The tables carry each product's NHI (National Health Insurance) price, and the NHI price list adds its ingredient and marketing authorization holder.

NDB also lacks several things that the Connecticut graph relies on. It has no prescribers, no specialties, no claims and no patient counts. The story of the first article, such as cardiologists writing 91% of their SGLT2 and GLP-1 claims for an SGLT2 inhibitor, cannot be repeated for Japan. The model shifts from doctors to products and regions. A quantity is also not a prescription. One tablet of metformin and one Ozempic pen, which lasts about four weeks, are both counted as one. Quantities therefore cannot be added across products. This article compares products in yen instead: quantity times the NHI price. MHLW updates the release in place. On 2 September 2026 it refreshed the prices, drug codes and generic flags in the prescription tables, so the values are fiscal year 2024 volumes at September 2026 prices.

### 1.2 SKOS: a crosswalk between two classifications

The 薬効分類 is a tree of three-digit codes. Category 396 (糖尿病用剤, antidiabetic agents) holds the tablets and most insulin combinations. Category 249 (その他のホルモン剤, other hormone preparations) holds the GLP-1 drugs, including the oral semaglutide tablet Rybelsus, and some insulins. Two products cross the line: the insulin and GLP-1 combination pens Xultophy and Soliqua are filed under 396. A query for "GLP-1 drugs" that relies on the Japanese category alone finds only part of them.

SKOS has a set of mapping properties for exactly this situation. skos:exactMatch says that two concepts are interchangeable, skos:narrowMatch that the other concept is narrower, skos:broadMatch that it is broader and skos:relatedMatch that the two overlap without either containing the other. The Japanese category tree becomes its own concept scheme, and every category links to the ATC-based class tree from the first article with these properties (Figure 2).

<!-- Figure 2: diagram of the crosswalk. Left: 3 → 39 → 396, 2 → 24 → 249. Right: A10 → A10B → classes, A10A → insulins. Arrows labelled narrowMatch / relatedMatch / broadMatch. -->
![](figure2.png)

Figure 2. The crosswalk between Japan's 薬効分類 and the ATC-based class tree. Image by author.

The crosswalk is computed, not written by hand. Every Japanese product has both a category and an active substance with an ATC class, so a script counts, for each pair of category and class, how many of the class's products sit in that category. If all of them do, the category gets skos:narrowMatch to the class. If only some do, it gets skos:relatedMatch. Each link carries the count that justifies it (Code 1).

```c
# Code 1. The crosswalk on category 249, shortened
jpc:249 a skos:Concept , dm:JapaneseDrugClass ;
    skos:prefLabel "Other hormone preparations (including antihormones)"@en ,
                   "その他のホルモン剤（抗ホルモン剤を含む。）"@ja ,
                   "其他激素类药物（含抗激素药）"@zh ;
    skos:broader      jpc:24 ;
    skos:narrowMatch  dmtc:FastActingInsulin , dmtc:GIPGLP1Agonist ;
    skos:relatedMatch dmtc:GLP1ReceptorAgonist , dmtc:LongActingInsulin ;
    skos:editorialNote
        "narrowMatch GIPGLP1Agonist: 6 of the 6 products containing a substance of GIPGLP1Agonist are filed under 249."@en ,
        "relatedMatch GLP1ReceptorAgonist: 23 of the 25 products containing a substance of GLP1ReceptorAgonist are filed under 249."@en .
```

The result says that all six tirzepatide products are in 249, while 23 of the 25 GLP-1 products are in 249 and the other two in 396. Nothing is claimed about category 249 as a whole, which also holds other hormone preparations that are out of scope. Category 396 gets skos:broadMatch to *blood glucose lowering drugs, excluding insulins* (A10B), since all 427 products in 396 belong to A10B, but only 427 of the 450 A10B products are in 396. The other 23 are the GLP-1 products in 249. A hand-written crosswalk would be a matter of opinion. A computed one is a fact about the data, and it updates itself when the next release adds products.

The ATC tree itself also needed new branches. Japan uses two classes that ATC lumps together under A10BX (other blood glucose lowering drugs): the glinides (repaglinide, nateglinide and mitiglinide) and the glimins, a class with one member, imeglimin. Both became project classes below A10BX. Four substances have no ATC code at all: glyclopyramide, tofogliflozin, trelagliptin and omarigliptin. Each got a curated class with a recorded reason. No US substance changed class, which a diff of the substance table confirmed, so the Connecticut results stayed the same.

Two more vocabularies arrived with Japan. The 47 prefectures form a SKOS scheme with their JIS codes as skos:notation, Wikidata links and labels in three languages, such as 東京都, Tokyo and 东京都 for prefecture 13. The care settings and the 42 sex and age bands form a third. In a property graph, these would be Prefecture nodes with a name_ja property. In SKOS they use the same properties as the drug classes, so the MCP server from the first article resolves 東京 to the right prefecture with the same lookup code.

### 1.3 Substances that RxNorm does not know

RxNorm is an American dictionary. It lists the drugs approved in the US, so 12 of the 47 substances in the Japanese data are missing from it. These include teneligliptin, ipragliflozin and imeglimin, all developed in Japan. The graph identifies them by their concept ID in the UMLS (Unified Medical Language System) instead, which includes drugs from other countries, and finds their ATC codes through UMLS's ATC source. Their Wikidata entries, and with them extra Japanese and Chinese labels, are found through Wikidata's UMLS property (P2892).

The Japanese names also come in more than one spelling. The NHI price list names the salt, so the price list says テネリグリプチン臭化水素酸塩水和物 where the concept is called テネリグリプチン. The product names in NDB use full-width characters, such as ジャディアンス錠１０ｍｇ. The salt names and the half-width spellings go into skos:hiddenLabel, a SKOS label that search can match but that is never displayed. Name lookup finds the right concept from any of them.

The SHACL rule for substances changed accordingly. It used to say "a substance has an RxNorm link". It now says "a substance has an RxNorm link, or a UMLS link when RxNorm does not have it". The first article argued that SHACL rules are the modeling contract. A second country tests that claim, and the rule changed in one place, with a version note, rather than in scattered application code.

### 1.4 OWL: defined classes and one company in two countries

The ontology moved to version 0.5.0 and gained one new structure, explained in the next section, and two new defined classes. dm:GLP1Product is any medicinal product with an active substance in the GLP-1 class or a narrower one (Code 2). dm:SGLT2Product works the same way for SGLT2 (sodium-glucose co-transporter 2) inhibitors.

```c
# Code 2. OWL definition of the GLP1Product class
dm:GLP1Product a owl:Class ;
    rdfs:label "GLP-1 receptor agonist product"@en , "GLP-1受容体作動薬製剤"@ja , "GLP-1受体激动剂产品"@zh ;
    skos:definition "A medicinal product containing a substance in the GLP-1 receptor agonist class (including dual GIP/GLP-1 agonists), alone or in combination, whatever its Japanese therapeutic category (249 or 396)."@en ;
    owl:equivalentClass [
        a owl:Class ;
        owl:intersectionOf (
            dm:MedicinalProduct
            [ a owl:Restriction ;
              owl:onProperty dm:hasActiveSubstance ;
              owl:someValuesFrom [ a owl:Restriction ;
                  owl:onProperty dm:inTherapeuticClass ;
                  owl:hasValue dmtc:GLP1ReceptorAgonist ] ]
        )
    ] .
```

The definition never mentions 249 or 396. It describes what a GLP-1 product is, and the reasoner works out which products qualify. With reasoning off, a query for dm:GLP1Product returns nothing, because no data file states that type. With reasoning on, it returns 37 products: 23 Japanese products in 249, the 2 combination pens in 396 and 12 US products (Figure 5 in section 3). The same definition serves both countries, although their classifications disagree. In the Neo4j drug_atc graph, the same question is a variable-length match over (:Substance)-[:BELONGS_TO]->(:ATC) relationships, repeated in every query that needs it. Here the rule lives in the ontology once.

Companies needed a link across the border as well. In the US data, a product's manufacturer is the application holder at the FDA, grouped by its GLEIF (Global Legal Entity Identifier Foundation) parent. In Japan, the marketing authorization holder is usually a local subsidiary, such as 日本ベーリンガーインゲルハイム (Nippon Boehringer Ingelheim). The new property dm:partOfCorporateGroup links each Japanese subsidiary of the seven groups already in the graph to the same parent company IRI as the US holder. A query for Boehringer Ingelheim's products therefore finds Jardiance in Connecticut and ジャディアンス錠10mg in Japan through one IRI. The co-promotion agreements between Boehringer Ingelheim and Eli Lilly are a commercial fact that no public dataset records, so the graph does not show them.

### 1.5 An RDF Data Cube to fit the budget

The NDB tables have 150,288 cells for the 510 products: 73,313 values, 40,944 zeros and 36,031 masked cells. Stardog Cloud Free allows one million edges per database, and the Connecticut data with the shared vocabularies already uses about 247,000. A flat model, with every cell a node that names its product, setting, dimension, value and type, needs about six triples per cell. That comes to about 1.15 million triples in total, which does not fit.

The W3C's [RDF Data Cube](https://www.w3.org/TR/vocab-data-cube/) vocabulary solves this with slices. A slice fixes the values that all its cells share: one product, one care setting and one breakdown. Each cell then needs only three triples: the link from the slice, the dimension value and either the quantity or a masking flag. The prefecture breakdown of ジャディアンス錠10mg in community pharmacies, for example, is one slice with 47 cells. Tokyo's cell says that 29,567,498.75 tablets were dispensed there (Code 3).

```c
# Code 3. One slice and one of its 47 observations, shortened
slice:622401201/outpatient-external/prefecture a dm:QuantitySlice ;
    qb:sliceStructure  key:prefecture ;
    dm:aboutProduct    product:622401201 ;     # ジャディアンス錠１０ｍｇ
    dm:careSetting     setting:outpatient-external ;
    dm:totalQuantity   299457206.33 ;
    qb:observation     obs:622401201/outpatient-external/01 , … ,
                       obs:622401201/outpatient-external/47 .

obs:622401201/outpatient-external/13
    dm:prefecture pref:13 ;                   # 東京都
    dm:quantity   29567498.75 .
```

<!-- Figure 3: diagram of one slice: product, setting and key on the slice; 47 observation nodes with prefecture + quantity or confStatus-C. -->
![](figure3.png)

Figure 3. One slice of the RDF Data Cube and its observations. Image by author.

With 4,464 slices, Japan adds about 487,000 triples, and the whole database holds 734,106. The zeros are kept. They cost about 123,000 triples, but they make the graph lossless: every table can be rebuilt from the graph, and SHACL can check that a prefecture slice has exactly 47 cells. A property graph would face the same size trade-off, and the usual answer there is a list property on the slice node. That saves even more space, but individual cells then can no longer carry a masking flag or be checked one by one.

The Data Cube also forced a small ontology decision. The first article's dm:forProduct links a prescription to its product, and its domain is dm:Prescription. Reusing it on slices would have made every slice a prescription under reasoning, since OWL treats a domain as an inference, not as a check. The slices got their own property, dm:aboutProduct, instead.

### 1.6 SHACL: masked cells and totals

NDB masks every cell below 1,000 in the oral tables and below 400 in the injection tables, and shows a dash instead. When a single cell in a row is masked, the next smallest cells are masked as well, so that the masked value cannot be recovered by subtraction. The CMS data in the first article had a similar rule, and the graph handled it with a suppression flag. For Japan, the graph uses an existing standard: the SDMX confidentiality attribute sdmx-attribute:confStatus with the value sdmx-code:confStatus-C, the code for confidential data used by statistical offices. The files do not say whether a cell was masked as small or to protect another cell, so the general code is the honest choice.

Before writing the rules, the masking logic was checked against the data. Every one of the 1,378 slices without a masked cell sums exactly to its national total. No slice sums to more than its total. And every unmasked cell is either zero or at least the masking threshold. These facts became SHACL rules (Code 4).

```c
# Code 4. SHACL rules for the NDB observations and slices, shortened
dms:ObservationShape a sh:NodeShape ;
    sh:targetObjectsOf qb:observation ;
    # A value is present OR the cell is flagged masked, never both, never neither.
    sh:xone (
        [ sh:path dm:quantity ; sh:minCount 1 ]
        [ sh:path sdmx-attribute:confStatus ; sh:hasValue sdmx-code:confStatus-C ]
    ) .

dms:QuantitySliceShape a sh:NodeShape ;
    sh:targetClass dm:QuantitySlice ;
    sh:sparql [
        sh:message "The cells add up to more than the national total, or, with no cell masked, not to the total." ;
        sh:select """
            SELECT $this (?sum AS ?value) WHERE {
              { SELECT $this (SUM(?q) AS ?sum) (COUNT(?m) AS ?masked) WHERE {
                  $this qb:observation ?o .
                  OPTIONAL { ?o dm:quantity ?q } OPTIONAL { ?o sdmx-attribute:confStatus ?m }
                } GROUP BY $this }
              $this dm:totalQuantity ?total .
              FILTER (?sum > ?total + 0.01 || (?masked = 0 && ABS(?sum - ?total) > 0.01))
            }""" ] .
```

The first rule is the Japanese twin of the CMS rule from the first article, with "exactly one of these" expressed by sh:xone. The second compares each slice with its national total. It is a SHACL-SPARQL rule, because core SHACL cannot sum across nodes. Other new rules require 47 cells per prefecture slice, 12 per month slice and 42 per sex and age slice, a YJ code (Japan's 12-digit drug code) for every Japanese product and exactly one country identifier per product: a CMS generic name in the US or a YJ code in Japan. The shapes moved to version 0.3.0 with 59 rules. A test file of deliberately broken records shows that all 59 can fire, and the real data passes with zero violations.

## 2. Governance: check locally, publish once

The governance design from the first article carried over unchanged. The NDB data sits in its own named graphs, graph:ndb-2024 for the cells and graph:ndb-products for the products, each with a PROV-O record of its source release, build time, triple count and content hash. The SHACL rules still run inside the load transaction, so a single violation rolls back the whole load.

The Japanese build also produced an incident, and it changed the process. During development, the database was reloaded in full five times, and several validation runs used reasoning on top of the 150,000 observations. On the free tier, this filled the instance's disk. The sixth reload failed with "No space left on device", and from then on every query returned a corruption error. The database could neither be read nor dropped. Stardog Cloud Free has no backups, so the instance had to be recreated.

Recovery took one load of two and a half minutes, because every graph in the database is rebuilt from files in the repository. Provenance and reproducibility, which sound like paperwork, turned out to be the disaster recovery plan. The development loop changed as well. All checks now run on the local machine first: the triple budget, the full SHACL contract with pySHACL, the test that every rule can fire, an OWL 2 RL closure with owlrl followed by SHACL again, and every business query on the embedded store pyoxigraph. These take about ten minutes. The loader refuses files that have not passed the local check, and it rewrites only the graphs whose content hash differs from the one recorded in the database. A change to one label now replaces one graph instead of 734,000 triples.

## 3. Using the graph

### 3.1 Japan and Connecticut side by side

Because both countries share the class tree, one query compares the two markets (Figure 4). Each class's share is computed within its own country: yen at NHI list prices for Japan and gross US dollars for Connecticut. The comparison uses single-ingredient products, so each product counts in exactly one class.

| Class | Japan | Connecticut |
|---|---:|---:|
| SGLT2 inhibitors | 39.3% | 34.1% |
| DPP-4 inhibitors | 23.9% | 11.2% |
| GLP-1 receptor agonists, incl. GIP/GLP-1 | 20.7% | 50.9% |
| Insulins | 7.0% | 3.2% |
| Biguanides | 4.4% | 0.5% |
| α-glucosidase inhibitors, glimins, glinides | 3.5% | —* |
| Sulfonylureas, thiazolidinediones | 1.2% | 0.1% |

Table 1. Share of diabetes drug value by class, single-ingredient products. Japan: NDB Open Data FY2024. Connecticut: Medicare Part D 2024. *Not in the 32 drugs of the Connecticut subset.

<!-- Figure 4: Stardog Studio with queries/jp-vs-connecticut-class-mix.rq and its result. -->
![](figure4.png)

Figure 4. The query "compare the class mix of Japan and Connecticut" and its result in Stardog. Image by author.

Japan spends twice the Connecticut share on DPP-4 (dipeptidyl peptidase-4) inhibitors and less than half on GLP-1 drugs. Three classes are missing from the Connecticut column. The α-glucosidase inhibitors and glinides are approved in the US but lie outside the 32 drugs of the first article's subset. Only the glimins, with their single member imeglimin, exist in Japan alone. The comparison has further limits. Prices differ between the two systems, the US costs are gross before rebates, and Medicare covers mostly people aged 65 and over, while NDB covers all ages. Shares are comparable, amounts are not. The Connecticut insulin figure covers only insulin glargine, the one insulin in the first article's scope.

Boehringer Ingelheim's position differs, too. In Connecticut, the group held 68% of SGLT2 claims. In Japan it holds 37.5% of SGLT2 value (¥116.4 billion), ahead of AstraZeneca with 32.2%, and 27.0% of DPP-4 value (¥67.3 billion), ahead of MSD with 22.2%. Combination products count in each of their classes, so Tradiance, which combines empagliflozin and linagliptin, counts for both. The query names the company once, and dm:partOfCorporateGroup brings in its Japanese subsidiary.

### 3.2 Reasoning across two classifications

The question "how many GLP-1 products are there, by country and Japanese category" shows what the defined class from section 1.4 does. With reasoning off, the answer is empty. With reasoning on, Stardog returns the 23 products in 249, the 2 in 396 and the 12 US products (Figure 5). The 396 row is the one a category-based query would miss: Xultophy and Soliqua, the insulin and GLP-1 pens.

<!-- Figure 5: queries/jp-glp1-by-japanese-category-reasoning.rq in Stardog Studio, reasoning off (0 rows) and on (3 rows). -->
![](figure5.png)

Figure 5. The same query with reasoning off and on. Image by author.

### 3.3 Age, months and prefectures

The sex and age tables show who receives which drug. Of the value of DPP-4 inhibitors, 46% goes to patients aged 75 and over. For SGLT2 inhibitors the figure is 36%, and for GLP-1 drugs 20%. The older the patient, the more likely a DPP-4 inhibitor. DPP-4 inhibitors are tablets with a low risk of hypoglycemia, which may explain part of the pattern, but the data cannot say why a drug was chosen.

The month tables show the arrival of tirzepatide. Mounjaro rose from ¥1.1 billion in April 2024 to ¥4.5 billion in March 2025 per month, a fourfold increase within one fiscal year. Semaglutide, as Ozempic, Wegovy and Rybelsus together, stayed flat at about ¥6.3 billion per month.

<!-- Optional Figure 6: monthly line chart, tirzepatide vs semaglutide, from queries/jp-glp1-monthly-uptake.rq. -->

The prefecture tables tell the weakest story. The SGLT2 share of diabetes drug value ranges from 39.3% in Kyoto to 45.1% in Nara, with Tokyo at 42.1%. That is a narrow band. The prefecture is also where the claim was issued, not where the patient lives, and masked cells make small products in small prefectures disappear. In Japan's diabetes market, the class tells much more than the region.

### 3.4 A policy change in the data, and a definition trap

From October 2024, patients in Japan pay part of the price difference when they choose an off-patent brand that has a generic. The policy is called 長期収載品の選定療養. The month tables show its effect in the same month. In every class with established generics, the generic share of tablets dispensed at community pharmacies stepped up in October 2024: from 91.3% to 94.0% for α-glucosidase inhibitors, from 77.2% to 81.5% for glinides, from 87.4% to 90.6% for sulfonylureas and from 92.0% to 94.4% for thiazolidinediones.

Metformin seems to defy the trend, with a generic share of 0.2% throughout the year. The cause is a definition, not the market. NDB's generic flag follows the reimbursement definition, and that definition leaves out generics priced at the same level as their originator. Most metformin generics, the "MT" products, are priced like the originator Metgluco and are therefore not flagged. A dashboard built on the flag would report that nobody in Japan takes generic metformin. The graph records the trap where the data lives: the property dm:isGeneric carries an rdfs:comment that explains the reimbursement definition and names metformin as the known case. In a property graph, that warning would sit in a wiki page. In RDF, it travels with the data to every tool and AI assistant that reads the property.

### 3.5 MCP in Japanese

The term lookup of the MCP server from the first article needed no new code for Japan. It reads the SKOS labels, and the Japanese data brought its labels with it. The server only had to learn the new concept kinds and how to query the Data Cube. ジャディアンス resolves to the Jardiance products, 東京 to prefecture 13, 糖尿病用剤 to category 396, メトホルミン塩酸塩, the salt name used in NDB, to metformin, 日本ベーリンガーインゲルハイム to the Japanese holder and 院外 to the community pharmacy setting. Asked in Japanese for the value of diabetes drugs dispensed in Tokyo, Claude answered with ¥73.5 billion across 501 products (Figure 6). <!-- TODO: confirm with the screenshot; the verified figure is 501 products, ¥73,497 million. -->

<!-- Figure 6: Claude Desktop answering a Japanese question via the MCP server. -->
![](figure6.png)

Figure 6. Claude answered a question in Japanese via the MCP server. Image by author.

## Conclusion

This project added a second country to a diabetes drug knowledge graph. Japan's NDB Open Data differs from Medicare in almost every respect: a different classification, a different unit, different masking and no prescribers. Still, the graph absorbed it without a single change to the Connecticut results. The shared substance and class vocabulary made the two markets comparable in one query, a computed SKOS crosswalk bridged the two classifications, a defined OWL class found every GLP-1 product in both countries, and an RDF Data Cube kept the data within the free tier's budget.

In my view, the second dataset is where RDF's standards pay off. With one source, SKOS mappings, defined classes and SHACL rules look like extra work. With two, they are what keeps the sources apart where they differ and joined where they agree. Several pieces came from existing W3C and SDMX vocabularies, so the graph did not need to invent a model for statistical tables or masked cells. The costs from the first article remain. The Data Cube slices and the SHACL-SPARQL rules are hard to read, and the free tier's limits shaped the model more than any modeling principle did. The incident showed that a cloud database is no place for development iterations, and that a graph rebuilt from version-controlled files recovers in minutes.

The Japanese data also has clear limits. It shows what was dispensed, where and to whom, but not who prescribed it or why. Indications that exist only in Japan, such as heart failure and chronic kidney disease for empagliflozin and dapagliflozin, are not modeled yet. They would partly replace the missing specialty story, and the graph is ready for them.
