# Query results

*Generated 2026-10-26 by `scripts/run_queries.py` against Stardog database `glp`. Interpretation: [findings.md](findings.md).*

## cost-per-claim-by-class

[queries/cost-per-claim-by-class.rq](../queries/cost-per-claim-by-class.rq): Cost per claim and per 30-day fill by therapeutic class (Connecticut, Medicare Part D 2024). Single-ingredient products only, so a combination pill's cost is not counted twice. Per 30-day fill is the fairer comparison: a 90-day fill is one claim but three 30-day fills.

*7 rows, 0.7 s*

| class | claimsTotal | costTotal | costPerClaim | costPer30DayFill |
|---|---|---|---|---|
| Glucagon-like peptide-1 (GLP-1) analogues | 237,719 | 318,386,863 | 1,339 | 970 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | 194,304 | 213,102,233 | 1,097 | 559 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | 76,159 | 69,965,079 | 919 | 499 |
| Insulins and analogues for injection, long-acting | 82,368 | 19,953,188 | 242 | 127 |
| Thiazolidinediones | 20,136 | 235,907 | 12 | 5 |
| Sulfonylureas | 74,120 | 689,841 | 9 | 4 |
| Biguanides | 346,597 | 3,123,420 | 9 | 4 |

## jp-age-profile-by-class

[queries/jp-age-profile-by-class.rq](../queries/jp-age-profile-by-class.rq): Japan, FY2024: share of each class's value (yen) dispensed to patients aged 75 and over (後期高齢者), from the sex-age tables, all care settings, products alone or in combination. Masked cells are left out. xsd:double: quantity x price overflows the fixed-point decimals of some engines (Oxigraph).

*10 rows, 2.9 s*

| class | yenMillion | age75plusPct | femalePct |
|---|---|---|---|
| Glinides | 8,098 | 48.20 | 39 |
| Alpha glucosidase inhibitors | 11,861 | 47.70 | 40.10 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | 248,701 | 45.80 | 39.70 |
| Sulfonylureas | 5,106 | 45.10 | 37.60 |
| Thiazolidinediones | 5,847 | 41.60 | 33.40 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | 310,793 | 36.20 | 35.30 |
| Glimins | 8,291 | 34.20 | 36.70 |
| Biguanides | 58,992 | 32.70 | 38.70 |
| Insulins and analogues | 56,442 | 31.40 | 40.70 |
| Glucagon-like peptide-1 (GLP-1) analogues | 135,989 | 20.20 | 41.30 |

## jp-boehringer-share-by-class

[queries/jp-boehringer-share-by-class.rq](../queries/jp-boehringer-share-by-class.rq): Japan, FY2024: Boehringer Ingelheim's value share (yen) in the classes where it has products, by corporate group of the marketing authorization holder. Nippon Boehringer Ingelheim links to the same GLEIF group as the US application holder (dm:partOfCorporateGroup), so one IRI finds the company in both countries. Products in combination count in each of their classes (Tradiance: SGLT2 and DPP-4). xsd:double: quantity x price overflows the fixed-point decimals of some engines (Oxigraph).

*16 rows, 0.6 s*

| class | company | yenMillion | sharePct |
|---|---|---|---|
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | C.H. Boehringer Sohn AG & Co. KG | 67,273 | 27 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | MERCK & CO., INC. | 55,281 | 22.20 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | Tanabe Pharma Corporation | 40,144 | 16.10 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | Novartis Pharma K.K. | 29,987 | 12.10 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | Teijin Pharma Limited | 24,615 | 9.90 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | Ono Pharmaceutical Co., Ltd. | 21,450 | 8.60 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | Sanwa Kagaku Kenkyusho Co., Ltd. | 4,460 | 1.80 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | Kyowa Kirin Co., Ltd. | 3,468 | 1.40 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | Kissei Pharmaceutical Co., Ltd. | 1,179 | 0.50 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | C.H. Boehringer Sohn AG & Co. KG | 116,449 | 37.50 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | ASTRAZENECA PLC | 100,029 | 32.20 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | Tanabe Pharma Corporation | 32,763 | 10.50 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | Astellas Pharma Inc. | 19,641 | 6.30 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | Kowa Company, Ltd. | 14,597 | 4.70 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | Taisho Pharmaceutical Co., Ltd. | 14,153 | 4.60 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | MERCK & CO., INC. | 13,183 | 4.20 |

## jp-class-share-yen

[queries/jp-class-share-yen.rq](../queries/jp-class-share-yen.rq): Japan, FY2024 (NDB Open Data): value share by therapeutic class, all care settings, in yen (dispensed quantity x NHI price, at the price list of 2026-09-02). Single-ingredient products only, like cost-per-claim-by-class.rq; combination products are shown as their own row. National totals come from the prefecture slices (each product x setting once); masked totals are left out. xsd:double: quantity x price overflows the fixed-point decimals of some engines (Oxigraph).

*11 rows, 0.6 s*

| class | yenMillion | sharePct |
|---|---|---|
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | 245,183 | 33.10 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | 149,180 | 20.20 |
| Glucagon-like peptide-1 (GLP-1) analogues | 128,923 | 17.40 |
| (combination products) | 116,401 | 15.70 |
| Insulins and analogues | 43,710 | 5.90 |
| Biguanides | 27,662 | 3.70 |
| Alpha glucosidase inhibitors | 8,598 | 1.20 |
| Glimins | 8,291 | 1.10 |
| Sulfonylureas | 5,040 | 0.70 |
| Glinides | 4,830 | 0.70 |
| Thiazolidinediones | 2,420 | 0.30 |

## jp-generic-share-by-month

[queries/jp-generic-share-by-month.rq](../queries/jp-generic-share-by-month.rq): Japan, FY2024: generic share of dispensed tablets per month, oral outpatient (community pharmacy) only, by class, for the classes that have generics. From October 2024, patients pay part of the price gap when they choose an off-patent brand that has a generic (長期収載品の選定療養); a rise from 2024-10 would show it. Masked month cells are left out. Tablets are comparable within one class, not across classes. "Generic" is NDB's reimbursement flag: generics priced like their originator (★ in the price list) are not counted, which is why biguanides (metformin "MT" generics, priced like Metgluco) show almost no generics. xsd:double: Oxigraph returns an error, not 0, for 0 divided by a decimal (months without generics).

*72 rows, 1.1 s*

| class | month | genericPct |
|---|---|---|
| Alpha glucosidase inhibitors | 2024-04 | 90.40 |
| Alpha glucosidase inhibitors | 2024-05 | 90.60 |
| Alpha glucosidase inhibitors | 2024-06 | 90.70 |
| Alpha glucosidase inhibitors | 2024-07 | 90.90 |
| Alpha glucosidase inhibitors | 2024-08 | 91.10 |
| Alpha glucosidase inhibitors | 2024-09 | 91.30 |
| Alpha glucosidase inhibitors | 2024-10 | 94 |
| Alpha glucosidase inhibitors | 2024-11 | 94.40 |
| Alpha glucosidase inhibitors | 2024-12 | 94.60 |
| Alpha glucosidase inhibitors | 2025-01 | 94.80 |
| Alpha glucosidase inhibitors | 2025-02 | 94.70 |
| Alpha glucosidase inhibitors | 2025-03 | 94.80 |
| Biguanides | 2024-04 | 0.20 |
| Biguanides | 2024-05 | 0.20 |
| Biguanides | 2024-06 | 0.20 |
| Biguanides | 2024-07 | 0.20 |
| Biguanides | 2024-08 | 0.20 |
| Biguanides | 2024-09 | 0.20 |
| Biguanides | 2024-10 | 0.20 |
| Biguanides | 2024-11 | 0.20 |
| Biguanides | 2024-12 | 0.20 |
| Biguanides | 2025-01 | 0.20 |
| Biguanides | 2025-02 | 0.20 |
| Biguanides | 2025-03 | 0.20 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | 2024-04 | 0 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | 2024-05 | 0 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | 2024-06 | 0 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | 2024-07 | 0 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | 2024-08 | 0 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | 2024-09 | 0 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | 2024-10 | 0 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | 2024-11 | 0 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | 2024-12 | 4.50 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | 2025-01 | 10 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | 2025-02 | 11.90 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | 2025-03 | 12.80 |
| Glinides | 2024-04 | 75.30 |
| Glinides | 2024-05 | 75.60 |
| Glinides | 2024-06 | 75.90 |
| Glinides | 2024-07 | 76.40 |
| Glinides | 2024-08 | 77 |
| Glinides | 2024-09 | 77.20 |
| Glinides | 2024-10 | 81.50 |
| Glinides | 2024-11 | 83.10 |
| Glinides | 2024-12 | 84.40 |
| Glinides | 2025-01 | 85.60 |
| Glinides | 2025-02 | 86.50 |
| Glinides | 2025-03 | 87.50 |
| Sulfonylureas | 2024-04 | 86.70 |
| Sulfonylureas | 2024-05 | 86.90 |
| Sulfonylureas | 2024-06 | 86.90 |
| Sulfonylureas | 2024-07 | 87 |
| Sulfonylureas | 2024-08 | 87.20 |
| Sulfonylureas | 2024-09 | 87.40 |
| Sulfonylureas | 2024-10 | 90.60 |
| Sulfonylureas | 2024-11 | 90.90 |
| Sulfonylureas | 2024-12 | 90.80 |
| Sulfonylureas | 2025-01 | 90.60 |
| Sulfonylureas | 2025-02 | 90.30 |
| Sulfonylureas | 2025-03 | 90 |
| Thiazolidinediones | 2024-04 | 91 |
| Thiazolidinediones | 2024-05 | 91.20 |
| Thiazolidinediones | 2024-06 | 91.40 |
| Thiazolidinediones | 2024-07 | 91.50 |
| Thiazolidinediones | 2024-08 | 91.80 |
| Thiazolidinediones | 2024-09 | 92 |
| Thiazolidinediones | 2024-10 | 94.40 |
| Thiazolidinediones | 2024-11 | 94.70 |
| Thiazolidinediones | 2024-12 | 94.90 |
| Thiazolidinediones | 2025-01 | 95.10 |
| Thiazolidinediones | 2025-02 | 95.10 |
| Thiazolidinediones | 2025-03 | 95.10 |

## jp-glp1-by-japanese-category-reasoning

[queries/jp-glp1-by-japanese-category-reasoning.rq](../queries/jp-glp1-by-japanese-category-reasoning.rq): Products the reasoner classifies as dm:GLP1Product (a defined OWL class: contains a substance in the GLP-1 receptor agonist class or a narrower one), counted by country and Japanese therapeutic category. Japan files most GLP-1 drugs under 249 (other hormones) but the insulin combinations under 396 (antidiabetics); the defined class finds both without knowing either code. Without reasoning, no product has this type.

*reasoning off, 0 rows, 0.6 s*

| country | category | products | example |
|---|---|---|---|

*reasoning on, 3 rows, 0.8 s*

| country | category | products | example |
|---|---|---|---|
| Japan | その他のホルモン剤（抗ホルモン剤を含む。） | 23 | ウゴービ皮下注０．２５ｍｇ　ＳＤ　０．５ｍＬ |
| Japan | 糖尿病用剤 | 2 | ソリクア配合注ソロスター |
| US (Connecticut) | - | 12 | Bydureon Bcise |

## jp-glp1-monthly-uptake

[queries/jp-glp1-monthly-uptake.rq](../queries/jp-glp1-monthly-uptake.rq): Japan, FY2024: monthly value (yen) of GLP-1 and GIP/GLP-1 receptor agonists by substance, all care settings. Quantities are in pens, tablets or kits, which cannot be added across products, so value is the common unit. Masked month cells (small products) are left out. Products alone only (no insulin combinations). xsd:double: quantity x price overflows the fixed-point decimals of some engines (Oxigraph).

*68 rows, 0.8 s*

| month | substance | yenMillion |
|---|---|---|
| 2024-04 | semaglutide | 6,313 |
| 2024-04 | dulaglutide | 1,284 |
| 2024-04 | tirzepatide | 1,103 |
| 2024-04 | liraglutide | 859 |
| 2024-04 | lixisenatide | 8 |
| 2024-04 | exenatide | 6 |
| 2024-05 | semaglutide | 5,996 |
| 2024-05 | dulaglutide | 1,253 |
| 2024-05 | tirzepatide | 1,125 |
| 2024-05 | liraglutide | 776 |
| 2024-05 | lixisenatide | 6 |
| 2024-05 | exenatide | 5 |
| 2024-06 | semaglutide | 5,918 |
| 2024-06 | tirzepatide | 1,439 |
| 2024-06 | dulaglutide | 1,211 |
| 2024-06 | liraglutide | 742 |
| 2024-06 | lixisenatide | 5 |
| 2024-06 | exenatide | 4 |
| 2024-07 | semaglutide | 6,334 |
| 2024-07 | tirzepatide | 1,935 |
| 2024-07 | dulaglutide | 1,307 |
| 2024-07 | liraglutide | 742 |
| 2024-07 | lixisenatide | 5 |
| 2024-08 | semaglutide | 6,107 |
| 2024-08 | tirzepatide | 2,261 |
| 2024-08 | dulaglutide | 1,272 |
| 2024-08 | liraglutide | 693 |
| 2024-08 | lixisenatide | 4 |
| 2024-08 | exenatide | 0 |
| 2024-09 | semaglutide | 5,823 |
| 2024-09 | tirzepatide | 2,439 |
| 2024-09 | dulaglutide | 1,197 |
| 2024-09 | liraglutide | 632 |
| 2024-09 | lixisenatide | 3 |
| 2024-09 | exenatide | 0 |
| 2024-10 | semaglutide | 6,348 |
| 2024-10 | tirzepatide | 2,996 |
| 2024-10 | dulaglutide | 1,303 |
| 2024-10 | liraglutide | 653 |
| 2024-10 | lixisenatide | 3 |
| 2024-10 | exenatide | 0 |
| 2024-11 | semaglutide | 6,099 |
| 2024-11 | tirzepatide | 3,192 |
| 2024-11 | dulaglutide | 1,210 |
| 2024-11 | liraglutide | 591 |
| 2024-11 | lixisenatide | 0 |
| 2024-12 | semaglutide | 6,652 |
| 2024-12 | tirzepatide | 3,768 |
| 2024-12 | dulaglutide | 1,321 |
| 2024-12 | liraglutide | 624 |
| 2024-12 | exenatide | 0 |
| 2025-01 | semaglutide | 6,036 |
| 2025-01 | tirzepatide | 3,746 |
| 2025-01 | dulaglutide | 1,194 |
| 2025-01 | liraglutide | 553 |
| 2025-01 | exenatide | 0 |
| 2025-01 | lixisenatide | 0 |
| 2025-02 | semaglutide | 5,756 |
| 2025-02 | tirzepatide | 3,791 |
| 2025-02 | dulaglutide | 1,121 |
| 2025-02 | liraglutide | 498 |
| 2025-02 | lixisenatide | 0 |
| 2025-02 | exenatide | 0 |
| 2025-03 | semaglutide | 6,340 |
| 2025-03 | tirzepatide | 4,468 |
| 2025-03 | dulaglutide | 1,203 |
| 2025-03 | liraglutide | 512 |
| 2025-03 | exenatide | 0 |

## jp-sglt2-share-by-prefecture

[queries/jp-sglt2-share-by-prefecture.rq](../queries/jp-sglt2-share-by-prefecture.rq): Japan, FY2024: SGLT2 inhibitors' share of diabetes drug value (yen) by prefecture, outpatient and inpatient together, products alone or in combination. Masked prefecture cells are left out, so small products in small prefectures are missing on both sides of the ratio. Top 10 and, by ORDER BY ASC, bottom. The prefecture is where the claim was issued, not where the patient lives. xsd:double: quantity x price overflows the fixed-point decimals of some engines (Oxigraph).

*47 rows, 1.0 s*

| prefecture | en | sglt2YenMillion | allYenMillion | sglt2SharePct |
|---|---|---|---|---|
| 奈良県 | Nara | 3,729 | 8,273 | 45.10 |
| 沖縄県 | Okinawa | 3,059 | 6,889 | 44.40 |
| 山口県 | Yamaguchi | 3,511 | 7,954 | 44.10 |
| 大分県 | Ōita | 3,410 | 7,726 | 44.10 |
| 福島県 | Fukushima | 5,517 | 12,541 | 44 |
| 鹿児島県 | Kagoshima | 4,434 | 10,109 | 43.90 |
| 香川県 | Kagawa | 2,917 | 6,690 | 43.60 |
| 宮崎県 | Miyazaki | 2,926 | 6,715 | 43.60 |
| 群馬県 | Gunma | 5,238 | 12,057 | 43.40 |
| 静岡県 | Shizuoka | 9,212 | 21,212 | 43.40 |
| 三重県 | Mie | 4,581 | 10,629 | 43.10 |
| 栃木県 | Tochigi | 5,623 | 13,049 | 43.10 |
| 広島県 | Hiroshima | 7,122 | 16,541 | 43.10 |
| 青森県 | Aomori | 3,970 | 9,226 | 43 |
| 埼玉県 | Saitama | 17,462 | 40,744 | 42.90 |
| 島根県 | Shimane | 1,600 | 3,733 | 42.90 |
| 茨城県 | Ibaraki | 7,727 | 18,136 | 42.60 |
| 宮城県 | Miyagi | 6,423 | 15,090 | 42.60 |
| 鳥取県 | Tottori | 1,239 | 2,912 | 42.60 |
| 北海道 | Hokkaido | 15,424 | 36,282 | 42.50 |
| 石川県 | Ishikawa | 2,816 | 6,621 | 42.50 |
| 岡山県 | Okayama | 4,934 | 11,632 | 42.40 |
| 高知県 | Kōchi | 1,802 | 4,248 | 42.40 |
| 長野県 | Nagano | 5,103 | 12,026 | 42.40 |
| 愛知県 | Aichi | 18,326 | 43,408 | 42.20 |
| 山梨県 | Yamanashi | 2,047 | 4,849 | 42.20 |
| 山形県 | Yamagata | 2,664 | 6,322 | 42.10 |
| 東京都 | Tokyo | 30,967 | 73,497 | 42.10 |
| 兵庫県 | Hyōgo | 13,273 | 31,558 | 42.10 |
| 佐賀県 | Saga | 2,025 | 4,833 | 41.90 |
| 千葉県 | Chiba | 15,484 | 37,066 | 41.80 |
| 福岡県 | Fukuoka | 12,434 | 29,823 | 41.70 |
| 神奈川県 | Kanagawa | 20,575 | 49,470 | 41.60 |
| 富山県 | Toyama | 2,533 | 6,083 | 41.60 |
| 福井県 | Fukui | 1,903 | 4,603 | 41.40 |
| 長崎県 | Nagasaki | 3,148 | 7,629 | 41.30 |
| 新潟県 | Niigata | 4,830 | 11,729 | 41.20 |
| 秋田県 | Akita | 2,669 | 6,514 | 41 |
| 熊本県 | Kumamoto | 4,468 | 10,922 | 40.90 |
| 岩手県 | Iwate | 3,405 | 8,383 | 40.60 |
| 徳島県 | Tokushima | 1,944 | 4,802 | 40.50 |
| 滋賀県 | Shiga | 2,984 | 7,372 | 40.50 |
| 岐阜県 | Gifu | 4,619 | 11,449 | 40.30 |
| 愛媛県 | Ehime | 3,276 | 8,227 | 39.80 |
| 和歌山県 | Wakayama | 2,172 | 5,472 | 39.70 |
| 大阪府 | Osaka | 19,975 | 50,459 | 39.60 |
| 京都府 | Kyoto | 5,295 | 13,465 | 39.30 |

## jp-vs-connecticut-class-mix

[queries/jp-vs-connecticut-class-mix.rq](../queries/jp-vs-connecticut-class-mix.rq): Japan (NDB FY2024, yen at NHI prices) vs Connecticut (Medicare Part D 2024, gross USD): each class's share of the country's diabetes drug value, through the shared ATC-based class tree. Single-ingredient products only. Shares, not amounts: different currencies, payers (all ages vs mostly 65+) and price levels. xsd:double: quantity x price overflows the fixed-point decimals of some engines (Oxigraph). COALESCE: in SPARQL, SUM over a variable that is unbound in some rows is an error, not a partial sum.

*10 rows, 0.7 s*

| class | japanPct | connecticutPct |
|---|---|---|
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | 39.30 | 34.10 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | 23.90 | 11.20 |
| Glucagon-like peptide-1 (GLP-1) analogues | 20.70 | 50.90 |
| Insulins and analogues | 7 | 3.20 |
| Biguanides | 4.40 | 0.50 |
| Alpha glucosidase inhibitors | 1.40 | 0 |
| Glimins | 1.30 | 0 |
| Glinides | 0.80 | 0 |
| Sulfonylureas | 0.80 | 0.10 |
| Thiazolidinediones | 0.40 | 0 |

## market-share-by-manufacturer

[queries/market-share-by-manufacturer.rq](../queries/market-share-by-manufacturer.rq): Market share by manufacturer within SGLT2 inhibitors and GLP-1 receptor agonists (claims and cost). Combination products count for every class they contain; multi-source generics have no single manufacturer and are grouped as "generic". Byetta has two application holders and appears under both. claimSharePct = the company's claims as a percentage of all claims in the class; the class total counts every claim once, so Byetta's two holders do not inflate it.

*11 rows, 0.7 s*

| class | company | claimsTotal | costTotal | claimSharePct |
|---|---|---|---|---|
| Glucagon-like peptide-1 (GLP-1) analogues | NOVO NORDISK A/S | 142,643 | 193,131,325 | 59.70 |
| Glucagon-like peptide-1 (GLP-1) analogues | ELI LILLY AND COMPANY | 94,444 | 124,785,093 | 39.50 |
| Glucagon-like peptide-1 (GLP-1) analogues | ASTRAZENECA PLC | 845 | 885,495 | 0.40 |
| Glucagon-like peptide-1 (GLP-1) analogues | SANOFI | 821 | 945,739 | 0.30 |
| Glucagon-like peptide-1 (GLP-1) analogues | generic (no single manufacturer) | 80 | 36,056 | 0 |
| Glucagon-like peptide-1 (GLP-1) analogues | AMYLIN | 12 | 10,535 | 0 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | C.H. Boehringer Sohn AG & Co. KG | 135,954 | 155,210,266 | 68.40 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | ASTRAZENECA PLC | 59,896 | 60,746,697 | 30.10 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | generic (no single manufacturer) | 1,857 | 836,449 | 0.90 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | Johnson & Johnson | 966 | 978,341 | 0.50 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | MERCK & CO., INC. | 13 | 4,337 | 0 |

## prescriber-overlap-reasoning

[queries/prescriber-overlap-reasoning.rq](../queries/prescriber-overlap-reasoning.rq): How many prescribers use SGLT2 inhibitors, GLP-1 receptor agonists, or both? dm:SGLT2Prescriber and dm:GLP1Prescriber are never stored: Stardog infers them from the OWL definitions at query time. Run with reasoning off and every count except "all" is 0.

*reasoning off, 1 rows, 0.6 s*

| group | prescribers |
|---|---|
| 1 all prescribers | 3,896 |

*reasoning on, 4 rows, 1.0 s*

| group | prescribers |
|---|---|
| 1 all prescribers | 3,896 |
| 2 SGLT2 prescribers | 2,701 |
| 3 GLP-1 prescribers | 2,362 |
| 4 both | 1,813 |

## provenance-of-a-graph

[queries/provenance-of-a-graph.rq](../queries/provenance-of-a-graph.rq): Where did the manufacturer graph come from? Sources with release and retrieval time, curated inputs and generated intermediates (with their hashes).

*7 rows, 0.6 s*

| input | release | retrieved | hash |
|---|---|---|---|
| GLEIF LEI records | 2026-10-14T16:00:00Z | 2026-10-15T02:14:42Z |  |
| Wikidata (CC0), labels by identifier |  | 2026-10-25T10:40:38Z |  |
| openFDA Drugs@FDA | 2026-10-14 | 2026-10-15T01:43:35Z |  |
| scripts/labels_ja_zh.csv |  | 2026-10-25T11:13:27Z | sha256:f114859db3275c9e24521d4e506ee4c9718a6545ad72f41b42ff07fcf61397c1 |
| scripts/organizations.csv |  | 2026-10-25T11:13:27Z | sha256:7023e016eb19baaad983152ca881e9e8518d937f247b26494af396f71533601c |
| vocab/src/organization_labels_ja_zh.csv |  |  | sha256:b4d1503e193d46a7279f4385ec4f27da1f8c65075d6d098f30b88a5aacbbd28d |
| vocab/src/sponsor_lei.csv |  |  | sha256:6904aec612e442197a632126a3a555bd7b12cd4abf65ac9bb33f7bb3681df7c0 |

## sglt2-by-japanese-label

[queries/sglt2-by-japanese-label.rq](../queries/sglt2-by-japanese-label.rq): Ask in Japanese: which specialties prescribe SGLT2阻害薬 (SGLT2 inhibitors) most? The class is found by its Japanese label (preferred or alternative), and specialties are shown with their Japanese label where one exists, otherwise in English.

*10 rows, 0.9 s*

| 専門分野 | 処方件数 | 処方医数 |
|---|---|---|
| 内科医 | 62,651 | 776 |
| 家庭医 | 24,069 | 369 |
| 内分泌・糖尿病・代謝内科医 | 23,186 | 121 |
| 循環器内科医 | 20,536 | 245 |
| 家庭医療ナースプラクティショナー | 17,740 | 353 |
| フィジシャン・アシスタント | 6,715 | 129 |
| 腎臓内科医 | 6,098 | 73 |
| 内科系フィジシャン・アシスタント | 5,833 | 97 |
| 成人医療ナースプラクティショナー | 5,514 | 99 |
| ナースプラクティショナー | 5,009 | 73 |

## sglt2-vs-glp1-by-specialty

[queries/sglt2-vs-glp1-by-specialty.rq](../queries/sglt2-vs-glp1-by-specialty.rq): SGLT2 vs GLP-1 claims by prescriber primary specialty (Connecticut, Medicare Part D 2024). Works with reasoning OFF: the class roll-up uses the skos:broader* property path, so tirzepatide (dual GIP/GLP-1) counts as GLP-1 and combination products count for every class they contain. sglt2SharePct = SGLT2 claims as a percentage of SGLT2 + GLP-1 claims.

*72 rows, 0.8 s*

| specialty | prescribers | sglt2Claims | glp1Claims | sglt2SharePct |
|---|---|---|---|---|
| Internal Medicine Physician | 910 | 62,651 | 76,487 | 45 |
| Endocrinology, Diabetes & Metabolism Physician | 136 | 23,186 | 52,729 | 30.50 |
| Family Medicine Physician | 444 | 24,069 | 31,130 | 43.60 |
| Family Nurse Practitioner | 453 | 17,740 | 29,970 | 37.20 |
| Cardiovascular Disease Physician | 250 | 20,536 | 2,166 | 90.50 |
| Physician Assistant | 166 | 6,715 | 9,249 | 42.10 |
| Medical Physician Assistant | 118 | 5,833 | 8,992 | 39.30 |
| Adult Health Nurse Practitioner | 116 | 5,514 | 5,981 | 48 |
| Nurse Practitioner | 97 | 5,009 | 5,267 | 48.70 |
| Nephrology Physician | 74 | 6,098 | 566 | 91.50 |
| Primary Care Nurse Practitioner | 42 | 2,468 | 2,974 | 45.40 |
| Geriatric Medicine (Internal Medicine) Physician | 37 | 3,256 | 1,399 | 69.90 |
| Acute Care Nurse Practitioner | 32 | 2,413 | 1,147 | 67.80 |
| Student in an Organized Health Care Education/Training Program | 85 | 1,277 | 973 | 56.80 |
| Interventional Cardiology Physician | 34 | 2,114 | 92 | 95.80 |
| Hospitalist Physician | 43 | 1,434 | 756 | 65.50 |
| Advanced Heart Failure and Transplant Cardiology Physician | 13 | 1,507 | 0 | 100 |
| Gerontology Nurse Practitioner | 24 | 837 | 654 | 56.10 |
| Pulmonary Disease Physician | 10 | 826 | 302 | 73.20 |
| Adult Medicine Physician | 11 | 513 | 478 | 51.80 |
| Specialist | 7 | 475 | 419 | 53.10 |
| Gastroenterology Physician | 9 | 203 | 681 | 23 |
| Adult Health Clinical Nurse Specialist | 1 | 289 | 576 | 33.40 |
| Infectious Disease Physician | 15 | 408 | 451 | 47.50 |
| Surgical Physician Assistant | 6 | 77 | 705 | 9.80 |
| Hospice and Palliative Medicine (Family Medicine) Physician | 2 | 572 | 93 | 86 |
| Obesity Medicine (Internal Medicine) Physician | 3 | 25 | 525 | 4.50 |
| Obesity Medicine (Family Medicine) Physician | 1 | 0 | 494 | 0 |
| Nuclear Cardiology Physician | 4 | 335 | 88 | 79.20 |
| Clinical Cardiac Electrophysiology Physician | 8 | 415 | 0 | 100 |
| Surgery Physician | 10 | 23 | 388 | 5.60 |
| Pediatrics Physician | 9 | 118 | 254 | 31.70 |
| Adolescent Medicine (Internal Medicine) Physician | 3 | 155 | 157 | 49.70 |
| Hypertension Specialist Physician | 1 | 52 | 249 | 17.30 |
| Geriatric Medicine (Family Medicine) Physician | 7 | 185 | 81 | 69.50 |
| Psychiatry Physician | 6 | 77 | 180 | 30 |
| Ambulatory Care Pharmacist | 1 | 20 | 188 | 9.60 |
| General Practice Physician | 3 | 95 | 110 | 46.30 |
| Sports Medicine (Family Medicine) Physician | 1 | 112 | 91 | 55.20 |
| Addiction Medicine (Internal Medicine) Physician | 1 | 94 | 89 | 51.40 |
| Obstetrics & Gynecology Physician | 4 | 0 | 168 | 0 |
| Critical Care Medicine (Internal Medicine) Physician | 1 | 52 | 107 | 32.70 |
| Addiction Medicine (Family Medicine) Physician | 1 | 44 | 98 | 31 |
| Sports Medicine (Internal Medicine) Physician | 1 | 50 | 67 | 42.70 |
| Dermatology Physician | 1 | 55 | 52 | 51.40 |
| Hematology & Oncology Physician | 3 | 14 | 91 | 13.30 |
| Sports Medicine (Orthopaedic Surgery) Physician | 1 | 24 | 76 | 24 |
| Women's Health Nurse Practitioner | 2 | 19 | 54 | 26 |
| Physical Medicine & Rehabilitation Physician | 2 | 19 | 53 | 26.40 |
| Vascular Surgery Physician | 2 | 53 | 17 | 75.70 |
| Reproductive Endocrinology Physician | 1 | 13 | 52 | 20 |
| Family Health Clinical Nurse Specialist | 1 | 0 | 65 | 0 |
| Registered Nurse | 1 | 0 | 64 | 0 |
| Pediatric Cardiology Physician | 3 | 61 | 0 | 100 |
| Rheumatology Physician | 2 | 0 | 53 | 0 |
| Critical Care Medicine Nurse Practitioner | 1 | 43 | 0 | 100 |
| Medical Specialty Clinic/Center | 1 | 16 | 27 | 37.20 |
| Community Health Nurse Practitioner | 1 | 20 | 15 | 57.10 |
| Psychiatric/Mental Health Nurse Practitioner | 2 | 16 | 12 | 57.10 |
| Pediatric Nurse Practitioner | 2 | 0 | 26 | 0 |
| Obesity Medicine (Preventive Medicine) Physician | 2 | 0 | 25 | 0 |
| Research Study Specialist | 1 | 17 | 0 | 100 |
| Emergency Medicine Physician | 1 | 0 | 16 | 0 |
| Pharmacist | 1 | 0 | 14 | 0 |
| Gynecology Physician | 1 | 13 | 0 | 100 |
| Orthopaedic Surgery Physician | 1 | 13 | 0 | 100 |
| Radiation Oncology Physician | 1 | 0 | 12 | 0 |
| Medical-Surgical Clinical Nurse Specialist | 1 | 0 | 12 | 0 |
| Plastic Surgery Physician | 1 | 11 | 0 | 100 |
| Neurology Physician | 1 | 0 | 11 | 0 |
| Anesthesiology Physician | 1 | 0 | 11 | 0 |
| Integrative Medicine Physician | 1 | 0 | 11 | 0 |

