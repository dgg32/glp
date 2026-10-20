# Query results

*Generated 2026-10-15 by `scripts/run_queries.py` against Stardog database `glp`. Interpretation: [findings.md](findings.md).*

## cost-per-claim-by-class

[queries/cost-per-claim-by-class.rq](../queries/cost-per-claim-by-class.rq): Cost per claim and per 30-day fill by therapeutic class (Connecticut, Medicare Part D 2024). Single-ingredient products only, so a combination pill's cost is not counted twice. Per 30-day fill is the fairer comparison: a 90-day fill is one claim but three 30-day fills.

*7 rows, 1.0 s*

| class | claimsTotal | costTotal | costPerClaim | costPer30DayFill |
|---|---|---|---|---|
| Glucagon-like peptide-1 (GLP-1) analogues | 237,719 | 318,386,863 | 1,339 | 970 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | 194,304 | 213,102,233 | 1,097 | 559 |
| Dipeptidyl peptidase 4 (DPP-4) inhibitors | 76,159 | 69,965,079 | 919 | 499 |
| Insulins and analogues for injection, long-acting | 82,368 | 19,953,188 | 242 | 127 |
| Thiazolidinediones | 20,136 | 235,907 | 12 | 5 |
| Sulfonylureas | 74,120 | 689,841 | 9 | 4 |
| Biguanides | 346,597 | 3,123,420 | 9 | 4 |

## market-share-by-manufacturer

[queries/market-share-by-manufacturer.rq](../queries/market-share-by-manufacturer.rq): Market share by manufacturer within SGLT2 inhibitors and GLP-1 receptor agonists (claims and cost). Combination products count for every class they contain; multi-source generics have no single manufacturer and are grouped as "generic". Byetta has two application holders and appears under both.

*11 rows, 0.7 s*

| class | company | claimsTotal | costTotal |
|---|---|---|---|
| Glucagon-like peptide-1 (GLP-1) analogues | NOVO NORDISK A/S | 142,643 | 193,131,325 |
| Glucagon-like peptide-1 (GLP-1) analogues | ELI LILLY AND COMPANY | 94,444 | 124,785,093 |
| Glucagon-like peptide-1 (GLP-1) analogues | ASTRAZENECA PLC | 845 | 885,495 |
| Glucagon-like peptide-1 (GLP-1) analogues | SANOFI | 821 | 945,739 |
| Glucagon-like peptide-1 (GLP-1) analogues | generic (no single manufacturer) | 80 | 36,056 |
| Glucagon-like peptide-1 (GLP-1) analogues | AMYLIN | 12 | 10,535 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | C.H. Boehringer Sohn AG & Co. KG | 135,954 | 155,210,266 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | ASTRAZENECA PLC | 59,896 | 60,746,697 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | generic (no single manufacturer) | 1,857 | 836,449 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | Johnson & Johnson | 966 | 978,341 |
| Sodium-glucose co-transporter 2 (SGLT2) inhibitors | MERCK & CO., INC. | 13 | 4,337 |

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

[queries/provenance-of-a-graph.rq](../queries/provenance-of-a-graph.rq): Where did the manufacturer graph come from? Sources with release and retrieval time, and curated inputs.

*5 rows, 0.6 s*

| input | release | retrieved | hash |
|---|---|---|---|
| GLEIF LEI records | 2026-10-14T16:00:00Z | 2026-10-15T02:14:42Z |  |
| Wikidata (CC0), labels by identifier |  | 2026-10-15T02:35:08Z |  |
| openFDA Drugs@FDA | 2026-10-14 | 2026-10-15T01:43:35Z |  |
| vocab/src/organization_labels_ja_zh.csv |  |  | sha256:b4d1503e193d46a7279f4385ec4f27da1f8c65075d6d098f30b88a5aacbbd28d |
| vocab/src/sponsor_lei.csv |  |  | sha256:6904aec612e442197a632126a3a555bd7b12cd4abf65ac9bb33f7bb3681df7c0 |

## sglt2-by-japanese-label

[queries/sglt2-by-japanese-label.rq](../queries/sglt2-by-japanese-label.rq): Ask in Japanese: which specialties prescribe SGLT2阻害薬 (SGLT2 inhibitors) most? The class is found by its Japanese label (preferred or alternative), and specialties are shown with their Japanese label where one exists, otherwise in English.

*10 rows, 1.1 s*

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

[queries/sglt2-vs-glp1-by-specialty.rq](../queries/sglt2-vs-glp1-by-specialty.rq): SGLT2 vs GLP-1 claims by prescriber primary specialty (Connecticut, Medicare Part D 2024). Works with reasoning OFF: the class roll-up uses the skos:broader* property path, so tirzepatide (dual GIP/GLP-1) counts as GLP-1 and combination products count for every class they contain.

*72 rows, 0.9 s*

| specialty | prescribers | sglt2Claims | glp1Claims |
|---|---|---|---|
| Internal Medicine Physician | 910 | 62,651 | 76,487 |
| Endocrinology, Diabetes & Metabolism Physician | 136 | 23,186 | 52,729 |
| Family Medicine Physician | 444 | 24,069 | 31,130 |
| Family Nurse Practitioner | 453 | 17,740 | 29,970 |
| Cardiovascular Disease Physician | 250 | 20,536 | 2,166 |
| Physician Assistant | 166 | 6,715 | 9,249 |
| Medical Physician Assistant | 118 | 5,833 | 8,992 |
| Adult Health Nurse Practitioner | 116 | 5,514 | 5,981 |
| Nurse Practitioner | 97 | 5,009 | 5,267 |
| Nephrology Physician | 74 | 6,098 | 566 |
| Primary Care Nurse Practitioner | 42 | 2,468 | 2,974 |
| Geriatric Medicine (Internal Medicine) Physician | 37 | 3,256 | 1,399 |
| Acute Care Nurse Practitioner | 32 | 2,413 | 1,147 |
| Student in an Organized Health Care Education/Training Program | 85 | 1,277 | 973 |
| Interventional Cardiology Physician | 34 | 2,114 | 92 |
| Hospitalist Physician | 43 | 1,434 | 756 |
| Advanced Heart Failure and Transplant Cardiology Physician | 13 | 1,507 | 0 |
| Gerontology Nurse Practitioner | 24 | 837 | 654 |
| Pulmonary Disease Physician | 10 | 826 | 302 |
| Adult Medicine Physician | 11 | 513 | 478 |
| Specialist | 7 | 475 | 419 |
| Gastroenterology Physician | 9 | 203 | 681 |
| Adult Health Clinical Nurse Specialist | 1 | 289 | 576 |
| Infectious Disease Physician | 15 | 408 | 451 |
| Surgical Physician Assistant | 6 | 77 | 705 |
| Hospice and Palliative Medicine (Family Medicine) Physician | 2 | 572 | 93 |
| Obesity Medicine (Internal Medicine) Physician | 3 | 25 | 525 |
| Obesity Medicine (Family Medicine) Physician | 1 | 0 | 494 |
| Nuclear Cardiology Physician | 4 | 335 | 88 |
| Clinical Cardiac Electrophysiology Physician | 8 | 415 | 0 |
| Surgery Physician | 10 | 23 | 388 |
| Pediatrics Physician | 9 | 118 | 254 |
| Adolescent Medicine (Internal Medicine) Physician | 3 | 155 | 157 |
| Hypertension Specialist Physician | 1 | 52 | 249 |
| Geriatric Medicine (Family Medicine) Physician | 7 | 185 | 81 |
| Psychiatry Physician | 6 | 77 | 180 |
| Ambulatory Care Pharmacist | 1 | 20 | 188 |
| General Practice Physician | 3 | 95 | 110 |
| Sports Medicine (Family Medicine) Physician | 1 | 112 | 91 |
| Addiction Medicine (Internal Medicine) Physician | 1 | 94 | 89 |
| Obstetrics & Gynecology Physician | 4 | 0 | 168 |
| Critical Care Medicine (Internal Medicine) Physician | 1 | 52 | 107 |
| Addiction Medicine (Family Medicine) Physician | 1 | 44 | 98 |
| Sports Medicine (Internal Medicine) Physician | 1 | 50 | 67 |
| Dermatology Physician | 1 | 55 | 52 |
| Hematology & Oncology Physician | 3 | 14 | 91 |
| Sports Medicine (Orthopaedic Surgery) Physician | 1 | 24 | 76 |
| Women's Health Nurse Practitioner | 2 | 19 | 54 |
| Physical Medicine & Rehabilitation Physician | 2 | 19 | 53 |
| Vascular Surgery Physician | 2 | 53 | 17 |
| Reproductive Endocrinology Physician | 1 | 13 | 52 |
| Family Health Clinical Nurse Specialist | 1 | 0 | 65 |
| Registered Nurse | 1 | 0 | 64 |
| Pediatric Cardiology Physician | 3 | 61 | 0 |
| Rheumatology Physician | 2 | 0 | 53 |
| Medical Specialty Clinic/Center | 1 | 16 | 27 |
| Critical Care Medicine Nurse Practitioner | 1 | 43 | 0 |
| Community Health Nurse Practitioner | 1 | 20 | 15 |
| Psychiatric/Mental Health Nurse Practitioner | 2 | 16 | 12 |
| Pediatric Nurse Practitioner | 2 | 0 | 26 |
| Obesity Medicine (Preventive Medicine) Physician | 2 | 0 | 25 |
| Research Study Specialist | 1 | 17 | 0 |
| Emergency Medicine Physician | 1 | 0 | 16 |
| Pharmacist | 1 | 0 | 14 |
| Gynecology Physician | 1 | 13 | 0 |
| Orthopaedic Surgery Physician | 1 | 13 | 0 |
| Radiation Oncology Physician | 1 | 0 | 12 |
| Medical-Surgical Clinical Nurse Specialist | 1 | 0 | 12 |
| Plastic Surgery Physician | 1 | 11 | 0 |
| Integrative Medicine Physician | 1 | 0 | 11 |
| Neurology Physician | 1 | 0 | 11 |
| Anesthesiology Physician | 1 | 0 | 11 |

