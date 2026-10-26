# Hand-off: Japan extension with NDB Open Data

## Why
The US graph (see `CLAUDE.md`) closed most gaps to the Boehringer Ingelheim Japan Semantic Engineer job (ID 38340), and the article was published 2026-10-25. The biggest remaining gap is **pharma commercial data from Japan**: the role serves BI's commercial business in Japan, and everything so far is US Medicare data. This extension repeats the project on Japan's national claims data, **NDB Open Data (厚労省 NDBオープンデータ)**. Researched 2026-10-25; the facts below were checked against the downloaded files unless marked otherwise.

## Verdict
NDB Open Data is good for the **drug side** (all of Japan, brand and strength level, prefecture, month, sex/age) but has **no prescribers, no specialties and no claim or patient counts**. The doctor-level parts of the US project (pseudonymized prescribers, `GLP1Prescriber` OWL class, "cardiologists 91% SGLT2") cannot be ported. So this is a different project on the same stack, not a copy.

## The data
- Index page: https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000177182.html
- **11th release** (FY2024 claims, Apr 2024–Mar 2025; published 2026-06-16): https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000177221_00017.html
  - Prescription ZIP incl. public-expense claims (41 MB): https://www.mhlw.go.jp/content/12400000/001744600.zip
  - Same without public-expense-only claims (comparable with releases ≤ 9): https://www.mhlw.go.jp/content/12400000/001742577.zip
  - Overview PDF (ja): https://www.mhlw.go.jp/content/12400000/001711787.pdf · Guide (en): https://www.mhlw.go.jp/content/12400000/001711792.pdf · 解説編 (ja): https://www.mhlw.go.jp/content/12400000/001742571.pdf
  - The reference NHI prices, YJ codes and generic flags were updated 2026-09-02 (aggregates unchanged), so prices in the files are current prices, not FY2024 prices.
- **12th release** is new and **monthly** (FY2025 claims, Apr–Jun 2025 so far; published 2026-10-06, pulled 10-09, re-posted 10-16; the May 2025 prescription file was replaced, use data from 10-16 or later): https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000177221_00020.html
- **Licence:** free to use without application; cite the source (NDB Open Data FAQ: https://www.mhlw.go.jp/content/12400000/001568663.pdf).
- New in the 11th release: the top-100/300/500 cutoff per class was **abolished**, so all products appear.

### Files in the ZIP
Filenames are Shift-JIS: unzip with Python `zipfile.ZipFile(path, metadata_encoding="cp932")` (macOS `unzip` fails). Folder `05_処方薬_シート統合後(公開対象)/`:
- `01_処方薬（内服／外用／注射）全/`: for 【内服】 (oral; separate files for 外来（院外）, 外来（院内）, 入院), 【外用】 and 【注射】 (injections; one file with three sheets: 外来 (院内), 外来 (院外), 入院), each as `_都道府県別` (47 prefectures), `_診療月別` (12 months) and `_性年齢別` (male/female × 21 five-year bands, 0–4 … 100+). **No cross-tabulation** (e.g. no prefecture × age).
- `02_処方薬（医科／歯科）/`: oral outpatient (院外) split into 医科 vs 歯科, top 10 per class only. This is the only "specialty" split there is.

### Columns (row 2 is the header, row 3 the prefecture/age labels, data from row 4)
`薬効分類` (3-digit class, only on the first row of each class block; forward-fill) · `薬効分類名称` · `医薬品コード` (9-digit receipt code) · `医薬品名` (full-width brand + strength) · `単位` (錠, キット …) · `薬価基準収載医薬品コード` (YJ code; first 4 digits = class) · `薬価` · `後発品区分` (0/1) · `総計(処方数量)` · one column per prefecture/month/age band.

### Things to watch
- **Masking:** "‐" (or "-") for values < 1,000 in oral tables and < 400 in injection tables, plus secondary masking (if only one cell is masked, the smallest remaining values are masked too). In class 396 outpatient (院外) prefecture data, 2,164 of 19,834 cells are masked (~11%). National totals are unmasked; small products in small prefectures are not. Model a masked cell like the CMS suppression flag (SHACL `sh:xone`: value present XOR masked).
- **Unit is quantity, not claims or patients:** tablets for oral drugs, pens/kits for injections. Not comparable across dose forms (one Ozempic 2 mg pen lasts ~4 weeks). Use **yen = quantity × 薬価** for cross-product shares, or a DDD-style normalization.
- **Classification:** GLP-1 drugs are not in 396 (糖尿病用剤) but in **249 (その他のホルモン剤)**, both injections and oral Rybelsus. Japan's 薬効分類 ≠ ATC.
- Sum 院外 + 院内 + 入院 for a full picture; injections in outpatient care are often 院内.

### Spot checks done (11th release, oral 院外, prefecture file)
- Class 396 has 422 product rows. Jardiance 10 mg 299.5M tablets (Tokyo 29.6M), Jardiance 25 mg 47.8M, Tradiance AP 81.3M / BP 35.4M, Trazenta 5 mg 226.1M, Forxiga 10 mg 221.6M, Twymeeg 500 mg 218.0M, Metgluco 250 mg 531.8M.
- Class 249 oral: Rybelsus 3/7/14 mg present (35.4M / 81.5M / 28.7M).
- Injection sheet 外来 (院内), class 249: Trulicity, Mounjaro (all six strengths), Ozempic, Victoza present; Ozempic SD and Wegovy pens are near or below the mask threshold in many prefectures.

## Gaps and how to fill them
| Needed | Source | Status |
|---|---|---|
| Manufacturer / marketing authorization holder | MHLW 薬価基準収載品目リスト, or PMDA product records | **Not verified** whether the MHLW list has a manufacturer column; check first. Note BI/Lilly co-promotion of Jardiance, Tradiance, Trazenta |
| Ingredient (一般名) and English name | 薬価基準収載品目リスト (has 一般名), then map to RxNorm/UMLS | To do |
| ATC class | Crosswalk from 一般名 → RxNorm → ATC (reuse `resolve_drugs.py`); KEGG DRUG has JP↔ATC but restrictive licence | To do |
| Indications | PMDA package inserts (添付文書). Jardiance in Japan: T2D, chronic heart failure, CKD, which partly replaces the missing specialty story | To do |
| Prescriber / specialty | Only NDB special extraction (research application, months) or commercial JMDC/MDV | **Out of scope** |

## Project idea
- **Semantic core:** a SKOS crosswalk between Japan's 薬効分類 and ATC (`skos:closeMatch`, `broader`/`narrower`), so a query for "GLP-1 receptor agonists" finds products filed under 249 and 396 alike. This is the "adopt and extend industry vocabularies" item in the job posting.
- **Reuse:** the existing ontology (`ontology/diabetes-market.ttl`, IDMP-O alignment), SKOS therapeutic-class scheme and ja/zh labels, SHACL gate, PROV-O named graphs (e.g. `graph:ndb-2024`), MCP server.
- **New in the model:** an aggregate observation class (product × prefecture | month | sex-age band, with quantity and masked flag); a SKOS scheme for the 47 prefectures (JIS codes 01–47); reasoning shifts from prescribers to products and regions (e.g. a defined `GLP1Product`).
- **Business questions:** SGLT2 share in yen by prefecture (BI share); monthly uptake of Mounjaro vs Ozempic vs Rybelsus (12th release adds FY2025); age profile of SGLT2 vs DPP-4; generic penetration per class; Japan vs Connecticut comparison through the shared ATC classes.
- **Size:** see "Scope and triple budget" below.

## Scope and triple budget (decided 2026-10-25, measured on the 11th release)
Headroom: 1,000,000 edges − 247,211 (Connecticut, shared vocabularies, shapes and provenance; measured per graph on 2026-10-26, the 276,677 used while planning was not reproducible) = ~753k. Japan goes into the same `glp` database as named graph `graph:ndb-2024`, so both countries share the ATC concepts.

**Product filter** (510 products, 286 of them generics): all of 薬効分類 396 (incl. the combination pens Xultophy and Soliqua), every insulin (YJ prefix 2492), and the GLP-1 ingredients in 2499 by YJ prefix: 2499410 liraglutide, 2499411 exenatide, 2499415 lixisenatide, 2499416 dulaglutide, 2499418 semaglutide injection (Ozempic and Wegovy), 2499014 oral semaglutide (Rybelsus), 2499422 tirzepatide. Glucagon (722) and the rest of 249 are out. The 医科/歯科 files (top 10 only) are out.

**Cell filter: none.** All 6 settings (oral and injection × 院外/院内/入院), all 3 dimensions, zeros and masked cells kept. Measured cells: 150,288 = 73,313 values + 40,944 zeros + 36,031 masked (24%).

**What makes it fit is the model, not a filter.** One `qb:Slice` per product × setting × dimension (4,464 slices, ~4 triples each, holding product, setting and dimension) and 3 triples per observation (`slice qb:observation obs`, the dimension value, the quantity or `sdmx-attribute:confStatus`). Prefecture, month and sex-age band are each one SKOS concept, so sex and age band are not separate triples.

| Design | Japan triples | Total | Fits? |
|---|---|---|---|
| Flat observations (~6 triples each), all cells | ~900k | ~1.15M | no |
| Slices, all cells (**chosen**) | 486,900 (measured) | 734,106 | yes, ~266k left |
| Slices, zeros dropped (fallback) | ~364k | ~611k | yes, ~389k left |

Zeros are kept because the graph is then lossless: a SHACL rule can check that every prefecture slice has exactly 47 observations, and a round-trip test can rebuild the Excel totals. If headroom is needed later, drop zeros first (−123k), then 入院 (heavily masked, −~90k). The 12th release (monthly) will not fit next to this; it needs its own database or only its month table.

## Constraints
Same as `CLAUDE.md`: public data only; never use or mention the NDA client work for Taiwan's drug evaluation center or regulator; raw downloads in `data/raw/` (e.g. `data/raw/ndb/`), generated RDF in `data/rdf/`; rerunnable scripts; no credentials in the repo. The earlier download sat in a temporary scratchpad and is gone; re-download the ZIP.

## First steps
1. Download the 11th-release ZIP into `data/raw/ndb/`, extract with cp932 names, and write a loader that turns the class 396 + 249 (+ insulin) blocks into tidy CSV (forward-fill class, "‐" → masked).
2. Download the 薬価基準収載品目リスト and check for a manufacturer column.
3. Map 一般名 → RxNorm → ATC; draft the 薬効分類 ↔ ATC crosswalk.
4. Decide whether this becomes a second article ("the same graph for Japan") or a section added to the existing one.

## Status (2026-10-25, end of first build session)
Built and validated locally, loaded once successfully (734,105 triples, SHACL gate 0 violations, all 59
rules proven to fire on `tests/shacl/broken-examples.ttl`, every graph count verified). Queries
`queries/jp-*.rq` ran against that load; results in `docs/query-results.md`, interpretation in
`docs/findings.md` §6–10, design decisions in `docs/decisions.md` (2026-10-25).

**Incident (resolved 2026-10-26):** a new Stardog Cloud instance was created; `glp` loaded once from the locally checked files (734,106 triples, SHACL gate 0 violations, 2.5 min), and all 14 queries give the same results as locally. History: after five full reloads and several reasoning-on `VALIDATE` attempts, Stardog Cloud
answered 503/502, then a sixth reload failed with "No space left on device", and since then every query
returns `CorruptionException: Error reading from txn store` for database `glp`. Cloud Free has no backups,
but every graph is rebuilt from local files. The Free instance is being recreated; then run
`scripts/setup_stardog.py` (database, options, users; needs a temporary admin login in `.env`),
`scripts/check_local.py` and `scripts/load_stardog.py` once, in that order. The last reload only added an `rdfs:comment` to `dm:isGeneric`; the
local files are newer than what was loaded. Voicebox must be re-enabled on a recreated database.

**Changed after the incident:** all validation happens locally before a push (`scripts/check_local.py`:
SHACL with pyshacl, rule coverage, OWL 2 RL closure + SHACL, every query on pyoxigraph, which agree with
the Stardog results). `load_stardog.py` refuses unchecked files and rewrites only changed graphs.
Reasoning-on SHACL in Stardog (`tests/test_shapes_reasoning.py`) is too heavy for Cloud Free with the NDB
observations; it is replaced by the local OWL RL check.
