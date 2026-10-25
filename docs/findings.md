# Findings

## 1. SGLT2 vs GLP-1 by prescriber specialty

*Connecticut, Medicare Part D, data year 2024. Computed 2026-10-14 with
[queries/sglt2-vs-glp1-by-specialty.rq](../queries/sglt2-vs-glp1-by-specialty.rq).*

**Question:** for each kind of doctor, what share of their SGLT2 + GLP-1 claims are SGLT2?

| Primary specialty | Prescribers | SGLT2 claims | GLP-1 claims | SGLT2 share |
|---|---:|---:|---:|---:|
| Internal Medicine | 910 | 62,651 | 76,487 | 45% |
| Endocrinology, Diabetes & Metabolism | 136 | 23,186 | 52,729 | **31%** |
| Family Medicine | 444 | 24,069 | 31,130 | 44% |
| Family Nurse Practitioner | 453 | 17,740 | 29,970 | 37% |
| Cardiovascular Disease (cardiology) | 250 | 20,536 | 2,166 | **90%** |
| Physician Assistant | 166 | 6,715 | 9,249 | 42% |
| Medical Physician Assistant | 118 | 5,833 | 8,992 | 39% |
| Adult Health Nurse Practitioner | 116 | 5,514 | 5,981 | 48% |
| Nurse Practitioner | 97 | 5,009 | 5,267 | 49% |
| Nephrology | 74 | 6,098 | 566 | **92%** |
| Primary Care Nurse Practitioner | 42 | 2,468 | 2,974 | 45% |
| Geriatric Medicine (Internal Medicine) | 37 | 3,256 | 1,399 | 70% |
| **All 72 specialties** | | **198,279** | **238,340** | **45%** |

The top 12 specialties by claim volume are shown. "Prescribers" counts those who wrote at least
one SGLT2 or GLP-1 claim. Specialty names are shortened from the NUCC labels the query returns
(e.g. "Cardiovascular Disease Physician"); the verbatim output is in
[query-results.md](query-results.md).

### What it shows

- **Heart and kidney doctors prescribe SGLT2 drugs almost exclusively** (cardiology 90%,
  nephrology 92%). A likely reason is that SGLT2 inhibitors such as Jardiance (Boehringer
  Ingelheim) and Farxiga are also approved for heart failure and chronic kidney disease, so
  these specialists prescribe them for reasons beyond blood sugar.
- **Diabetes specialists lean the other way.** Endocrinologists write more than twice as many
  GLP-1 as SGLT2 claims (31% SGLT2).
- **Primary care sits in the middle** (internal medicine, family medicine, nurse practitioners
  and physician assistants: 37–49%), and writes most of the volume.

For Boehringer, the SGLT2-heavy specialties (cardiology, nephrology) are a natural audience for
Jardiance, while GLP-1 drugs dominate where diabetes is treated most intensively.

### How the knowledge graph made this easy

- **Roll-up through the drug family tree:** the query asks for the class "GLP-1 receptor agonists"
  and `skos:broader*` pulls in tirzepatide (Mounjaro), which sits in the narrower class "dual
  GIP/GLP-1 agonists". No list of drug names appears in the query.
- **Combination pills count automatically:** Synjardy (empagliflozin + metformin) counts as
  SGLT2 because the product is linked to each of its substances.
- **Specialty comes from a different source** (the NPI Registry graph) than the claims
  (the CMS graph), joined through the pseudonymous prescriber.

### Caveats

- **Medicare only:** Part D covers mostly people aged 65+, so the mix differs from the whole
  market.
- **Claims, not patients:** a claim is one fill or refill. A 90-day fill counts once, like a
  30-day one.
- **Indication is unknown:** the data cannot say why a drug was prescribed. Cardiologists'
  SGLT2 claims may be for heart failure, not diabetes.
- **Wegovy is included** in GLP-1 (1,178 claims, under 0.5% of GLP-1 claims). Its FDA label states
  obesity, not diabetes (indication `Obesity`, MeSH D009765); excluding it would barely change the
  shares.
- **Combination products count fully** for each class they contain; no product combines
  SGLT2 and GLP-1, so no claim is counted twice in this table.
- **Primary specialty** is the NPI Registry taxonomy flagged primary. 13 prescribers without a
  registry record are not in the table.
- **Small cells:** CMS publishes a prescriber/drug row only with 11 or more claims, so
  low-volume prescribing is missing.

## 2. Cost per claim by drug class

*[queries/cost-per-claim-by-class.rq](../queries/cost-per-claim-by-class.rq). Single-ingredient products only.*

| Drug class | Claims | Total cost (USD) | Cost per claim | Cost per 30-day fill |
|---|---:|---:|---:|---:|
| GLP-1 receptor agonists | 237,719 | 318.4 M | $1,339 | **$970** |
| SGLT2 inhibitors | 194,304 | 213.1 M | $1,097 | **$559** |
| DPP-4 inhibitors | 76,159 | 70.0 M | $919 | $499 |
| Long-acting insulins | 82,368 | 20.0 M | $242 | $127 |
| Thiazolidinediones | 20,136 | 0.24 M | $12 | $5 |
| Sulfonylureas | 74,120 | 0.69 M | $9 | $4 |
| Biguanides (metformin) | 346,597 | 3.1 M | $9 | $4 |

- **The money is in the branded classes.** GLP-1, SGLT2 and DPP-4 drugs make up about half of these
  claims (49%) but 96% of the cost.
- **Metformin is the volume leader** (346,597 claims) at $3.74 per month's supply.
- **A month of GLP-1 costs about 1.7 times a month of SGLT2** ($970 vs $559) and about 260 times
  a month of metformin.
- Per 30-day fill is the fairer comparison: a 90-day fill counts as one claim but three fills,
  and cheap generics are often filled for 90 days.
- Costs are gross Part D drug costs before manufacturer rebates, which are not public.

## 3. Asking in Japanese: who prescribes SGLT2阻害薬?

*[queries/sglt2-by-japanese-label.rq](../queries/sglt2-by-japanese-label.rq)*

| 専門分野 (specialty) | 処方件数 (claims) | 処方医数 (prescribers) |
|---|---:|---:|
| 内科医 | 62,651 | 776 |
| 家庭医 | 24,069 | 369 |
| 内分泌・糖尿病・代謝内科医 | 23,186 | 121 |
| 循環器内科医 | 20,536 | 245 |
| 家庭医療ナースプラクティショナー | 17,740 | 353 |
| フィジシャン・アシスタント | 6,715 | 129 |
| 腎臓内科医 | 6,098 | 73 |

The top 7 of the query's 10 rows are shown.

- The query names the drug class only by its Japanese label, `"SGLT2阻害薬"@ja`. The SKOS labels
  turn that into the class, the substances, the products and the claims. No English drug name
  appears in the query, and specialties come back with their Japanese labels.
- Even the result columns have Japanese names (`?専門分野`); SPARQL allows Unicode variable names.
- The claim counts are identical to the SGLT2 column of finding 1, which was computed from the
  English labels: the multilingual layer changes the words, not the answer.
- This is the term-normalization layer the chatbot will use.

## 4. Market share by manufacturer: SGLT2 and GLP-1

*[queries/market-share-by-manufacturer.rq](../queries/market-share-by-manufacturer.rq).
Manufacturer = application holder in Drugs@FDA, grouped by its GLEIF ultimate parent. The graph
labels companies with their GLEIF legal names (e.g. "C.H. Boehringer Sohn AG & Co. KG"); the tables
below use common names.*

**SGLT2 inhibitors** (198,686 claims)

| Company | Claims | Share | Products |
|---|---:|---:|---|
| **Boehringer Ingelheim** | 135,954 | **68%** | Jardiance, Synjardy (XR), Glyxambi, Trijardy XR |
| AstraZeneca | 59,896 | 30% | Farxiga, Xigduo XR |
| Generic | 1,857 | 1% | Dapagliflozin (unbranded) |
| Johnson & Johnson (Janssen) | 966 | 0.5% | Invokana, Invokamet |
| Merck (MSD) | 13 | <0.1% | Steglatro |

**GLP-1 receptor agonists** (238,845 claims)

| Company | Claims | Share | Products |
|---|---:|---:|---|
| Novo Nordisk | 142,643 | 60% | Ozempic, Rybelsus, Victoza, Xultophy, Wegovy |
| Eli Lilly | 94,444 | 40% | Mounjaro, Trulicity |
| AstraZeneca, Sanofi, others | 1,758 | 1% | Bydureon BCise, Byetta, Soliqua |

- **Boehringer leads SGLT2 in Connecticut Medicare with about two thirds of claims**, roughly
  2.3 times AstraZeneca. Empagliflozin combinations (Synjardy, Glyxambi, Trijardy) count because
  each product is linked to all its substances.
- GLP-1 is a two-company market. Lilly's 40% comes from Mounjaro (tirzepatide) and Trulicity;
  Mounjaro counts as GLP-1 through the SKOS hierarchy.
- Byetta's 12 claims appear under both of its application holders (Amylin and AstraZeneca),
  so the GLP-1 rows add up to 12 more than the class total.
- Share of Medicare claims, not of sales or patients.

## 5. Prescriber overlap, inferred by the reasoner

*[queries/prescriber-overlap-reasoning.rq](../queries/prescriber-overlap-reasoning.rq), run with reasoning off and on.*

| Group | Reasoning off | Reasoning on |
|---|---:|---:|
| All prescribers | 3,896 | 3,896 |
| SGLT2 prescribers | 0 | 2,701 |
| GLP-1 prescribers | 0 | 2,362 |
| Both | 0 | 1,813 |

- `dm:SGLT2Prescriber` and `dm:GLP1Prescriber` are never stored. Stardog infers them at query time
  from the OWL definitions (prescriber → prescription → product → substance → class, with the
  SKOS roll-up). With reasoning off the counts are 0; with it on, 1.2 seconds.
- **Two thirds of SGLT2 prescribers (1,813 of 2,701) also prescribe a GLP-1 drug**, and 77% of
  GLP-1 prescribers also prescribe an SGLT2 inhibitor. The two classes are mostly used side by
  side by the same doctors, not by separate camps.
- Changing what "SGLT2 prescriber" means (for example, at least 50 claims) is an edit to one OWL
  definition, not to every query that uses it.

## 6. Japan: where the diabetes drug money goes

*All of Japan, NDB Open Data FY2024 (April 2024 - March 2025, 11th release), value = dispensed quantity x
NHI price (price list of 2026-09-02). Computed 2026-10-25 with
[queries/jp-class-share-yen.rq](../queries/jp-class-share-yen.rq) and
[queries/jp-vs-connecticut-class-mix.rq](../queries/jp-vs-connecticut-class-mix.rq).*

Single-ingredient products, share of each country's diabetes drug value:

| Class | Japan | Connecticut |
|---|---:|---:|
| SGLT2 inhibitors | 39.3% | 34.1% |
| DPP-4 inhibitors | **23.9%** | 11.2% |
| GLP-1 receptor agonists (incl. GIP/GLP-1) | **20.7%** | 50.9% |
| Insulins | 7.0% | 3.2% (glargine only in the CT subset) |
| Biguanides | 4.4% | 0.5% |
| α-glucosidase inhibitors, glimins, glinides | 3.5% | — (not used in the US) |
| Sulfonylureas, thiazolidinediones | 1.2% | 0.1% |

Japan spends 2.1x the US share on DPP-4 inhibitors and less than half on GLP-1 drugs. Three classes exist
only in Japan's market. Combination products (not in the table) are 15.7% of Japan's value. Caveats:
shares, not amounts (yen at list price vs gross USD); Part D is mostly people 65+, NDB all ages.

## 7. Japan: Boehringer Ingelheim's position

*[queries/jp-boehringer-share-by-class.rq](../queries/jp-boehringer-share-by-class.rq). Products in
combination count in each of their classes (Tradiance in SGLT2 and DPP-4).*

| Class | Boehringer group | Next |
|---|---:|---|
| SGLT2 inhibitors | **37.5%** (¥116.4bn) | AstraZeneca 32.2%, Tanabe 10.5% |
| DPP-4 inhibitors | **27.0%** (¥67.3bn) | MSD 22.2%, Tanabe 16.1%, Novartis 12.1% |

The Japanese holder 日本ベーリンガーインゲルハイム links to the same GLEIF group as the US application
holder, so one IRI finds the company in both countries. Not visible in the data: the Lilly co-promotion.

## 8. Japan: SGLT2 share by prefecture

*[queries/jp-sglt2-share-by-prefecture.rq](../queries/jp-sglt2-share-by-prefecture.rq); masked cells
left out.* SGLT2 share of diabetes drug value ranges from 39.3% (Kyoto) and 39.6% (Osaka) to 45.1% (Nara)
and 44.4% (Okinawa); Tokyo 42.1%. A narrow band: the regional story is weak, the class story strong.

## 9. Japan: age profile and GLP-1 uptake

*[queries/jp-age-profile-by-class.rq](../queries/jp-age-profile-by-class.rq),
[queries/jp-glp1-monthly-uptake.rq](../queries/jp-glp1-monthly-uptake.rq).*

- Share of value dispensed to patients aged 75+: glinides 48%, α-GI 48%, DPP-4 46%, sulfonylureas 45%,
  SGLT2 36%, metformin 33%, GLP-1 20%. The older the patient, the more likely a DPP-4 inhibitor.
- Tirzepatide (Mounjaro) went from ¥1.1bn in April 2024 to ¥4.5bn in March 2025 per month (4x);
  semaglutide (Ozempic, Wegovy, Rybelsus together) stayed at about ¥6.3bn.

## 10. Japan: generic share before and after October 2024

*[queries/jp-generic-share-by-month.rq](../queries/jp-generic-share-by-month.rq); tablets, outpatient
(community pharmacy), single-ingredient products.* From October 2024 patients pay part of the price gap
when they choose an off-patent brand that has a generic (長期収載品の選定療養). The generic share steps up
that month in every class with established generics:

| Class | Apr 2024 | Sep 2024 | Oct 2024 | Mar 2025 |
|---|---:|---:|---:|---:|
| α-glucosidase inhibitors | 90.4% | 91.3% | **94.0%** | 94.8% |
| Glinides | 75.3% | 77.2% | **81.5%** | 87.5% |
| Sulfonylureas | 86.7% | 87.4% | **90.6%** | 90.0% |
| Thiazolidinediones | 91.0% | 92.0% | **94.4%** | 95.1% |
| DPP-4 inhibitors | 0% | 0% | 0% | 12.8% (vildagliptin and saxagliptin generics, from December 2024) |

Biguanides show 0.2%: NDB's generic flag is the reimbursement definition, which leaves out generics
priced like their originator (the metformin "MT" generics, priced like Metgluco). A data-definition
trap worth a paragraph in the article.
