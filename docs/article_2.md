---
title: "Compiling a Diabetes Drug Market Knowledge Graph into a Snowflake Semantic View"
subtitle: "One graph, two countries: the same answers in SPARQL, SQL and plain Japanese"
status: draft
---
<!-- Draft of article 2, rewritten 2026-10-31 with Snowflake as the presentation layer. Sources: HANDOFF_article2.md, docs/findings.md §6–10, docs/decisions.md, snowflake_extension.md, data/snowflake/tables.json (graph results), data/validation/semantic-view-check.json (Snowflake parity) and data/validation/analyst-eval-jp-final.json (Cortex Analyst). Every number below is taken from those files. Lines in HTML comments are notes for the author and are not part of the article. -->

# Compiling a Diabetes Drug Market Knowledge Graph into a Snowflake Semantic View

## One graph, two countries: the same answers in SPARQL, SQL and plain Japanese

<!-- Figure 1: Snowsight, Cortex Analyst on GLP.SEMANTIC.JAPAN_MARKET answering 「日本ベーリンガーインゲルハイムのSGLT2阻害薬シェアは？」 with the company table (C.H. Boehringer Sohn AG & Co. KG 37.5%, AstraZeneca 32.2%, ...). -->
![](figure1.png)

Figure 1. Cortex Analyst in Snowflake answers a Japanese question about Japanese data through a semantic view generated from the ontology. Image by author.

Many governments publish statistics on medicines. Health agencies use them to monitor the nation's health and its drug spending, drug companies analyze them for market trends and competitors, and researchers study how doctors treat a disease. But comparing them across countries is difficult, because every country collects them differently. The US government publishes how many prescriptions each doctor in the Medicare program wrote for each drug. Japan's national health insurance publishes how many tablets, pens and vials of each medicine were dispensed in each prefecture, month and age group. Jardiance, for example, is one product in the US data, but in Japan it appears under its Japanese name, once for each tablet strength. The two countries also group their medicines under completely different classification systems.

It's slow and tedious for data analysts to manually match every name, dose, and metric in every project. The exact same issue trips up AI assistants. Asked to compare Jardiance usage in the US and Japan, an AI has to guess which records belong together. It might miss one of the Japanese doses entirely, or make the fatal flaw of comparing US prescription counts directly against Japanese tablet counts.

This is where an RDF knowledge graph comes in. In RDF, every medicine has a global identifier called an IRI. The US and Japanese records of a medicine link to this one shared entry, with its names in each language attached. A W3C vocabulary called SKOS links that entry to public code systems, such as the WHO's ATC classification and the Japanese therapeutic categories. SKOS also arranges drug classes in a hierarchy, so empagliflozin rolls up to the SGLT2 inhibitors and on to all antidiabetic drugs. Furthermore, it states how closely two classification systems match. Finally, the graph records what each number counts, so no one adds US prescriptions to Japanese tablets.

My previous article built such a graph from Medicare Part D claims for diabetes drugs in Connecticut, with an OWL ontology for the concepts and SHACL rules that check the data, and loaded it into Stardog, an RDF graph database. This article builds on it with a second dataset, Japan’s NDB Open Data for fiscal year 2024. The graph now has to absorb Japan’s own drug codes and classification, and even drugs missing from the US drug dictionary. In addition, the article exports the graph into Snowflake as tables, because pharma analysts usually work in data warehouses like Snowflake and use SQL, not SPARQL. The RDF graph, however, remains the master copy. In Snowflake, the natural-language-to-SQL service Cortex Analyst answers questions in Japanese, and its SQL results match the graph’s numbers row for row. Finally, a Stardog virtual graph reads the Snowflake tables back as the same knowledge graph (Figure 1). The code is in the same GitHub repository as before.

## [GitHub - dgg32/glp](https://github.com/dgg32/glp)

## 1. Building the Japanese part of the graph

### 1.1 Data

The Ministry of Health, Labour and Welfare (MHLW) publishes [NDB Open Data](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000177182.html), aggregate tables from Japan's national database of health insurance claims. NDB covers almost every insured patient in Japan. This article uses the [11th release](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000177221_00017.html), which covers fiscal year 2024 (April 2024 to March 2025).

The tables list each product at strength level, such as Jardiance Tablets 10 mg (ジャディアンス錠10mg). For each product, they give the dispensed quantity by prefecture, by month and by sex and age band. Each breakdown is a separate table. So there are figures for Osaka and for women aged 70–74, but none for women aged 70–74 in Osaka. In total, the project covers 510 diabetes drug products, together with their NHI (National Health Insurance) prices and manufacturers.

NDB also lacks several things that the Connecticut graph relies on. It has no prescribers, no specialties and no patient counts, so the doctor-level analyses of the first article cannot be repeated for Japan. In addition, NDB counts dispensed units, such as tablets and pens, not prescriptions. One metformin tablet covers part of a day, while one Ozempic pen covers about four weeks. Yet NDB counts each as one unit. Quantities therefore cannot be added across products. This article compares products in yen instead, that is, quantity times the NHI price.

### 1.2 SKOS: a crosswalk between two classifications

In the previous article, SKOS provided multilingual labels and the drug class hierarchy. In this project, it also has to bridge two classification systems. Japan does not file its drugs under the WHO's ATC but under its own therapeutic categories (薬効分類). The two systems do not line up. Most GLP-1 drugs, for example, sit in category 249, “other hormone preparations”, together with some insulins. Two GLP-1 combination pens, however, sit in category 396, “antidiabetic agents”. So no Japanese category equals “GLP-1 drugs”.

SKOS has mapping properties for exactly this situation. They state whether a concept in one scheme is the same as, broader than, narrower than or merely related to a concept in another. A script links each Japanese category to the ATC-based classes by counting how many products they share (Figure 2, Code 1). Each link also records the counts behind it. The crosswalk can therefore be checked against the data, and it is recomputed with every new release.

<!-- Figure 2: diagram of the crosswalk. Left: 3 → 39 → 396, 2 → 24 → 249. Right: A10 → A10B → classes, A10A → insulins. Arrows labelled narrowMatch / relatedMatch / broadMatch. -->
![](figure2.png)

Figure 2. The crosswalk between Japan's 薬効分類 and the ATC-based class tree. Image by author.

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

The class tree itself grew as well. Japan treats some drug groups as classes of their own, while ATC lumps them together under “other”. The project therefore added classes for them. In addition, a few substances are sold only in Japan and have no ATC code at all. Each was assigned by hand to an existing class, with the reason recorded.

Three more vocabularies arrived with Japanese data: the 47 prefectures, the care settings and the sex and age bands. Each became a small SKOS scheme with labels in three languages. Because they use the same properties as the drug classes, the same code later turns all of them into Snowflake tables.

### 1.3 OWL: defined classes and one company in two countries

The first article defined GLP-1 and SGLT2 prescribers. Japan has no prescribers, so the ontology now defines the same classes for products: dm:GLP1Product and dm:SGLT2Product. A defined class states the conditions for membership instead of listing its members (Code 2).

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

Code 2 shows one of the real strengths of OWL. The definition never lists a single product. It only says what a GLP-1 product is: a product that contains an active substance from the GLP-1 class. The reasoner finds every product that qualifies, including the two combination pens in category 396, which a category-based query would miss. Moreover, new products are classified as soon as they enter the graph. The rule is written once in the ontology instead of in any query or program, and every query benefits from it. Even Snowflake reuses it, as section 2.2 shows. In a Neo4j graph, in contrast, the rule lives in the application code. It has to be repeated in every query, and each copy can drift from the others.

Companies needed a link across the border as well. In Japan, a drug is usually sold by a local subsidiary, such as 日本ベーリンガーインゲルハイム (Nippon Boehringer Ingelheim). A new property links each subsidiary to its parent company. A query for Boehringer Ingelheim therefore finds its products in both countries.

### 1.4 An RDF Data Cube

The NDB tables have about 150,000 cells. Stored naively, they would push the graph to about 1.15 million triples. That exceeds the one-million-edge limit of Stardog Cloud Free, which also has to hold the Connecticut data.

The W3C’s RDF Data Cube vocabulary solves this with slices. A slice holds what all its cells share, such as the product and the breakdown. Each cell then only needs to store its own prefecture, month or age band, and its quantity (Code 3, Figure 3). With this design, Japan adds about 487,000 triples, and the whole graph fits in Stardog Cloud Free.

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

<!-- Figure 3: diagram of one slice: product, setting and key on the slice; 47 observation nodes with prefecture + quantity or confStatus-C. Next to it, the same slice as 47 rows of JP.QUANTITY (PRODUCT_ID, CARE_SETTING_ID, BREAKDOWN, CELL, QUANTITY, IS_MASKED). -->
![](figure3.png)

Figure 3. One slice of the RDF Data Cube and the same slice as rows of a Snowflake table. Image by author.

## 2. From the graph to Snowflake

### 2.1 Tables as projections of the graph

A script exports the graph to Snowflake. Each of the 27 tables comes from one SPARQL query over the validated graph. The tables sit in three schemas: shared vocabularies, Connecticut and Japan. SPARQL climbs the class hierarchy in one line, while SQL needs a recursive query. The script therefore stores every class with all its ancestors. Finally, a parity check makes sure the copy is faithful. The script answers ten business questions on the graph and saves the results. Snowflake must later return exactly the same numbers for the same questions.

### 2.2 A semantic view generated from the ontology

A Snowflake semantic view describes tables in business terms, such as dimensions, metrics and synonyms. Cortex Analyst relies on it to turn a question into SQL. Here, a script generates the view from the ontology and the vocabularies, so no part of it is written by hand (Code 4).

```c
-- Code 4. Excerpts of the generated semantic view GLP.SEMANTIC.JAPAN_MARKET
CREATE OR REPLACE SEMANTIC VIEW GLP.SEMANTIC.JAPAN_MARKET
  TABLES ( national_value AS GLP.SEMANTIC.SV_JP_NATIONAL_VALUE ..., product AS ..., prefecture AS ... )
  RELATIONSHIPS ( prefecture_value_to_prefecture AS prefecture_value (PREFECTURE_CODE) REFERENCES prefecture (PREFECTURE_CODE), ... )
  DIMENSIONS (
    prefecture.prefecture_name_ja AS prefecture.PREFECTURE_NAME_JA
      WITH SYNONYMS = ('都道府県')                                       -- rdfs:label of dm:Prefecture
      COMMENT = 'Prefecture name in Japanese. Values: 三重県; 京都府; ...',   -- the SKOS scheme
    product.is_glp1_product AS product.IS_GLP1_PRODUCT
      WITH SYNONYMS = ('GLP-1 receptor agonist product', 'GLP-1受容体作動薬製剤', 'GLP-1受体激动剂产品')
      COMMENT = 'A medicinal product containing a substance in the GLP-1 receptor agonist class ...', -- skos:definition
    ... )
  METRICS (
    class_market_share AS SUM(national_value.value_yen) / NULLIF(MAX(national_value.class_total_value_yen), 0)
      COMMENT = 'Share (0 to 1) of the class''s national value, for one class at a time. ...', ... )
  ai_sql_generation 'Answer in yen (value_yen metrics), never by adding quantities across products. ...'
  ai_verified_queries ( jp_class_share_yen AS ( QUESTION 'What share of Japan''s diabetes drug value ...' ... ), ... );
```

Each part of the view comes from a part of the graph. The labels in three languages become synonyms. The SKOS definitions become descriptions. The defined OWL classes become yes/no columns, such as “is this a GLP-1 product”. In addition, the business queries of the graph become reference queries that Cortex Analyst consults. They also serve as tests. After every deployment, a script runs them in Snowflake and compares the results with the graph's answers. All of them must match row for row.

The same model was also deployed through OSI (Open Semantic Interchange), a vendor-neutral format for semantic models. The OSI view gives the same numbers, but it loses the synonyms, the instructions for Cortex Analyst and the verified queries.

### 2.3 Virtual graph: SPARQL over the Snowflake tables

The export copies the graph into tables. A virtual graph goes the other way without ETL: the data stays in Snowflake. Stardog can build a virtual graph from a mapping file that declares how table rows become triples. It then translates each SPARQL query into SQL and runs it in Snowflake with a read-only role, like the MCP server of the first article. The mapping is written in R2RML, the W3C standard for this task. A second R2RML engine, [Morph-KGC](https://github.com/morph-kgc/morph-kgc), confirmed that the mapping turns the Snowflake tables back into the original graph, triple for triple.

Correct triples, however, do not guarantee correct answers. Stardog's translation into SQL has limits of its own. Some queries had to be rewritten, and one returned a wrong count without any error. The mistake only showed up because the results could be compared with the original graph. A virtual graph is therefore only as reliable as its translation into SQL.

<!-- Author notes (2026-11-07/08): virtual graph snowflake_glp in Stardog database `snowflake`, data source `snowflake` (recreated 2026-11-08 with glp.sms; SQL Schemas GLP.VOCAB,GLP.US,GLP.JP; JDBC URL with schema=VOCAB), Snowflake user GLP_STARDOG (LEGACY_SERVICE, password) holding only GLP_READER. Mapping: mapping/glp.r2rml.ttl generated by scripts/build_mapping.py (96 triples maps), mapping/glp.sms generated by scripts/r2rml_to_sms2.py, checked by scripts/check_mapping.py (2026-11-08: identical, 727,728 triples, Morph-KGC ~4 min). The 2026-11-07 proof of concept (vocabulary only, 391 triples, Code 8 query 2 results in 990 ms) used the earlier mapping/vocab.r2rml.ttl. Stardog results 2026-11-08: triple count 727,741 (= 727,728 + 13 NUCC "None" definitions); COUNT(*)/SUM over ?s dm:totalQuantity ?q without ?s → 1,345 (optimizer collapses three maps, Show Plan saved), COUNT(DISTINCT ?s) → 4,035; skos:broader* with two variable ends → "Cannot translate an unconstrained zero-or-more property path"; queries/virtual/jp-class-share-yen.rq (broaderTransitive rewrite) → all 11 rows identical to tables.json, 59.5 s; queries/virtual/sglt2-vs-glp1-by-specialty.rq: UNION version → SQL error, and without the share column 164 rows (GROUP BY pushed per UNION branch); LEFT JOIN rewrite → 72 rows, all claims as in tables.json, 1.96 s, but shares truncated to integers (30 for 30.5; plan: ?sglt2SharePct ^^xsd:integer, 1000.0 → 1000); decimal literals did not help, xsd:double cast did → all 72 rows identical incl. shares, 2.3 s. TODO: (1) rerun the Code 8 query on the full mapping; the other 8 business queries are not yet run on the virtual graph (Table 3 covers two); (2) Show Plan screenshot as a figure (would renumber Figures 5–7); (3) the reasoning queries need the ontology in the `snowflake` database. Caveat not in the text: in the trial account PUBLIC holds SNOWFLAKE_LEARNING_ROLE (CREATE SCHEMA on SNOWFLAKE_LEARNING_DB), so GLP_STARDOG can USE ROLE it; revoke before claiming strict read-only, or qualify the sentence. Studio ignored mappings.syntax=R2RML; whether the HTTP API honours it was not tested. Stardog server version 12.2.1. -->

## 3. Governance: check locally, publish once

The governance design from the first article carried over unchanged. The Japanese data sits in its own named graphs, each with a provenance record of its source release and a hash of its content. The ontology carries a version number, and every generated semantic view states the version it came from.

The SHACL shapes are the data contract. They state what valid data looks like, and the pipeline enforces them. The shapes first run on the local machine, together with an OWL reasoner and every business query. The Stardog loader and the Snowflake export refuse files that have not passed this run. In Stardog, the shapes run once more inside the load transaction, so a single violation rolls back the whole load. The reasoner adds a second check. A disjointness axiom makes it report a contradiction when a link points at the wrong kind of thing, such as an indication link that points at a substance. Stardog and Snowflake therefore only receive valid data (Figure 4).

<!-- Figure 4: pipeline diagram. NDB / CMS / RxNorm / UMLS → build RDF → local checks (pySHACL 59 rules, owlrl, pyoxigraph queries) → (a) Stardog (SPARQL, MCP server) and (b) export → Snowflake VOCAB / US / JP → generated semantic views → Cortex Analyst. Parity checks as dashed arrows back to the graph results. -->
![](figure4.png)

Figure 4. One graph, checked once, published to two places. Image by author.

## 4. Using the data in Snowflake

### 4.1 Japan and Connecticut side by side

Because both countries share the class tree, one SQL query compares them (Figure 5, Table 1). Each class's share is computed within its own country, in yen for Japan and in US dollars for Connecticut.

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

<!-- Figure 5: Snowsight worksheet with queries/snowflake/jp-vs-connecticut-class-mix.sql and its result (CLASS_NAME, CLASS_NAME_JA, JAPAN_PCT, CONNECTICUT_PCT). -->
![](figure5.png)

Figure 5. The query "compare the class mix of Japan and Connecticut" and its result in a Snowflake worksheet. Image by author.

DPP-4 inhibitors take 24% of Japan's diabetes drug spending, twice their 11% share in Connecticut. GLP-1 drugs show the opposite: 21% in Japan against 51% in Connecticut. Some classes are missing in Connecticut, because the first article covered only 32 drugs. The comparison has other limits as well. Prices differ between the two countries, while US costs are counted before rebates. Moreover, Medicare covers mostly people aged 65 and over. The shares can therefore compare how each country splits its spending among the classes, but not which country spends more.

Boehringer Ingelheim's position differs, too. In Connecticut, the group held 68% of SGLT2 claims. In Japan, it holds 37.5% of SGLT2 value, ahead of AstraZeneca with 32.2%. The company link from section 1.3 makes this comparison possible.

### 4.2 A defined class without a reasoner

The question “how many GLP-1 products are there per country” shows the defined class at work. In Stardog, a reasoner answers it. In Snowflake, it is a simple filter on the generated column (Figure 6). Both return the same result, including the two combination pens that a category-based query would miss. A reasoner applies a changed definition immediately. The column, in contrast, changes only when the view is regenerated, but any BI tool can filter on it.

<!-- Figure 6: Snowsight worksheet with queries/snowflake/glp1-products-by-country.sql: Japan その他のホルモン剤 23, Japan 糖尿病用剤 2, US (Connecticut) 12. -->
![](figure6.png)

Figure 6. GLP-1 products by country and Japanese category, from the OWL definition compiled into SQL. Image by author.

### 4.3 Age, months and prefectures

The age tables show who receives which drug. Of the value of DPP-4 inhibitors, 45.8% goes to patients aged 75 and over, compared with 20.2% for GLP-1 drugs. The data, however, cannot say why a drug was chosen. The month tables show the rise of tirzepatide (Mounjaro). Its monthly value grew fourfold within one fiscal year, while semaglutide stayed flat. The prefecture tables, in contrast, show little variation. Across all 47 prefectures, the SGLT2 share stays between 39% and 45%. In Japan, the large differences lie between drug classes and age groups, not between regions.

<!-- Optional Figure 7: Snowsight chart of the verified query jp_glp1_monthly_uptake (month × substance, yen), tirzepatide vs semaglutide. -->

### 4.4 A policy change in the data, and a definition trap

From October 2024, patients in Japan pay extra when they choose an off-patent brand over its generic. Patients reacted at once, and the monthly data captures the reaction. In every class with established generics, the generic share of tablets jumped in October 2024.

Metformin defies the trend because its generics cost the same as the brand. The surcharge is a share of the price gap, so it adds nothing here. Patients therefore have little reason to prefer the generics. Furthermore, the equal price hides these generics in the data. This is because NDB flags a drug as generic only if it costs less than the original. As a result, almost none of metformin's non-originator products are flagged. Only one small product costs less than the brand. A dashboard built on the flag would therefore show a generic share of just 0.2%. In fact, about 71% of metformin tablets are generics that carry no flag because they cost as much as the brand. In a property graph, a warning about such a trap would usually live in a separate wiki page. Here, the ontology records it next to the data as a comment on the generic flag. The generated semantic view carries the same warning for Cortex Analyst.

### 4.5 Cortex Analyst in Japanese

Cortex Analyst answers questions in natural language and shows the SQL it ran. Five Japanese questions went through it three times each, on both the generated view and the OSI view. A script then checked every answer against plain SQL (Table 2).

| Question | Check | Native | OSI |
|---|---|---:|---:|
| 東京都で処方された糖尿病治療薬の金額は？ | ¥73.5 billion | 3/3 | 3/3 |
| 日本ベーリンガーインゲルハイムのSGLT2阻害薬シェアは？ | 37.5% | 3/3 | 3/3 |
| GLP-1受容体作動薬は薬効分類のどこに入っている？ | 249 and 396 named | 3/3 | 3/3 |
| | 23 and 2 products | 3/3 | 0/3 |
| マンジャロの月別の金額の推移は？ | ¥1.1 billion in April, ¥4.5 billion in March | 1/3 | 3/3 |
| 75歳以上の患者への割合が最も高い薬効群は？ | glinides, 48.2% | 3/3 | 3/3 |

Table 2. Correct answers out of three runs per view, after the fixes described below. Native: the generated semantic view. OSI: the same model deployed through OSI YAML.

<!-- Figure 7: Snowsight, Cortex Analyst answering 「マンジャロの月別の金額の推移は？」 with a line chart. -->
![](figure7.png)

Figure 7. Cortex Analyst answers a question about tirzepatide by its Japanese brand name. Image by author.

The first round exposed two gaps, and both had to do with companies. First, Analyst did not recognize 日本ベーリンガーインゲルハイム as part of the Boehringer Ingelheim group. A list of each group's subsidiaries, generated from the company link in the graph, fixed this. Second, Analyst computed Boehringer's share of its own sales instead of its share of the market. A prepared market-share metric fixed that as well. The remaining misses were minor. Still, one lesson stands out: instructions for a language model need tests, just like code.

The MCP server from the first article answers the same kind of question over SPARQL. Cortex Analyst, in contrast, works inside the warehouse and needs no graph database at query time.

## Conclusion

This project added Japan to a diabetes drug knowledge graph and moved its data into Snowflake. Japan's data differs from Medicare in almost every respect: a different classification, a different unit, different masking and no prescribers. Still, the graph absorbed it without changing a single Connecticut result. The shared vocabulary made the two countries comparable in one query. Moreover, a computed SKOS crosswalk bridged the two classifications, and a defined OWL class found every GLP-1 product in both countries.

The second dataset is where RDF's standards pay off. With one source, SKOS mappings, defined classes and SHACL rules look like extra work. With two, they keep the sources apart where they differ and joined where they agree. In Snowflake, the same artifacts do a second job. Labels become synonyms, definitions become descriptions, and OWL classes become columns. Because the semantic view is generated, it cannot drift from the graph. The generator even found a flaw in the ontology. Two classes carried the same Japanese label 薬効分類. One is Japan's own drug category, such as 396 for antidiabetics. The other is the ATC-based class tree. In the semantic view, the synonym 薬効分類 therefore pointed at the ATC tree. A Japanese question about 薬効分類 would have used the wrong classification. Renaming the ATC tree to 薬効群 in the ontology fixed it.

The approach has costs, too. The free tier's limits shaped the model more than any modeling principle did. Every derived table must be regenerated when the graph changes. Moreover, a cloud database turned out to be no place for trial and error. During the Japanese build, repeated reloads filled the disk of the free Stardog instance. The database broke and had to be recreated. Since then, every check runs on the local machine, and the cloud only receives the finished result.

The Japanese data also has clear limits. It shows what was dispensed, where and to whom, but not who prescribed it or why. Japan-only indications, such as heart failure and chronic kidney disease for empagliflozin and dapagliflozin, are not modeled yet. They are the natural next step.
