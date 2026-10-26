# Hand-off: second article (Japan, NDB Open Data)

Written 2026-10-26 at the end of the build session. Read `CLAUDE.md` first (constraints, pipeline);
this file covers only what the next session needs to write the article.

## The task
Write a second Medium article on the Japan extension, modelled on the first one:
`/Users/dgg32/Library/Mobile Documents/iCloud~md~obsidian/Documents/second_brain/Archives/Published-Articles/Building a Governed Diabetes Prescription Knowledge Graph in RDF.md`
(published 2026-10-25, ~3,400 words, subtitle "A Medicare-based graph that explains itself, checks its
own quality and speaks three languages"). The draft of article 1 is also in `docs/article.md`.

The second article should **not repeat** article 1's explanation of RDF, SKOS, OWL and SHACL. Link to it
and spend the words on what is new for Japan. Put the draft in `docs/article2.md` (suggested name).

## Writing rules (from memory, they override CLAUDE.md's "Neo4j Ninja" angle)
- Low profile: titles and intros are about the data and the problem, not about the author.
- No rhetorical questions, no Q&A framing, no "you". Use declarative sentences, "we" or passive voice.
  Turn long parenthetical asides into their own sentences (short acronym expansions in brackets are fine).
- When explaining a concept, the user's Neo4j `drug_atc` graph is a good comparison (public parts only).
- **Never mention the NDA client work** (Taiwan's drug evaluation center or regulator).
- Article 1's style: numbered sections (1. Building, 2. Governance, 3. Using the graph), "Figure N." and
  "Code N." captions, "Image by author.", a Conclusion that weighs RDF against property graphs honestly.

## Structure of article 1, and what changes for Japan
| Article 1 | Article 2 (Japan) |
|---|---|
| Intro: drug names are confusing; property graph vs RDF | Intro: same graph, second country. Japan files drugs differently (薬効分類, not ATC), counts quantities not claims, masks small cells, has no prescribers. The value of shared vocabularies shows when a second dataset arrives |
| 1.1 Data: CMS Part D, Connecticut | NDB Open Data, 11th release, FY2024 (Apr 2024 – Mar 2025), all of Japan; NHI price list for ingredients, holders and prices |
| 1.2 SKOS | 薬効分類 ↔ ATC crosswalk (computed, `narrowMatch`/`relatedMatch`/`broadMatch`); prefectures as a SKOS scheme; 26 new substances, 12 of them not in RxNorm (identified by UMLS) |
| 1.3 OWL | Defined classes `dm:GLP1Product` / `dm:SGLT2Product`; RDF Data Cube (`qb:Slice`); `dm:partOfCorporateGroup` links 日本ベーリンガーインゲルハイム to the same GLEIF group as the US holder |
| 1.4 SHACL | Masked XOR value (SDMX `confStatus`), 47 prefectures / 12 months / 42 sex-age bands per slice, sum ≤ national total, unmasked cells ≥ threshold. 59 rules, all proven to fire, 0 violations |
| 2. Governance | Provenance per graph as before, plus the incident: "check locally, publish once" |
| 3. Using the graph | Japan business queries, Japan vs Connecticut, reasoning across 249/396, MCP in Japanese |

## Story beats (numbers verified; sources in brackets)
1. **No doctors in the data.** NDB has products × prefecture | month | sex-age, no prescribers, specialties,
   claims or patients. The prescriber story of article 1 cannot be ported; the model shifts from doctors to
   products and regions. [`japan_extension.md` "Verdict"]
2. **The 1M-edge budget shaped the model.** 150,288 cells (incl. 40,944 zeros, 36,031 masked). A flat model
   (~6 triples per cell) would need ~1.15M triples in total and not fit Stardog Cloud Free. The RDF Data Cube
   puts product, setting and dimension on 4,464 slices, so a cell costs 3 triples: 734k triples in total,
   Connecticut included. Zeros are kept, so the graph is lossless and SHACL can check completeness.
   [`japan_extension.md` "Scope and triple budget", `docs/decisions.md` 2026-10-25]
3. **Japan's classification is not ATC.** GLP-1 drugs sit in 249 (other hormones), the insulin + GLP-1
   pens (Xultophy, Soliqua) in 396 (antidiabetics). A defined OWL class finds them all without knowing either
   code: with reasoning, `dm:GLP1Product` = 37 products (25 Japan: 23 in 249, 2 in 396; 12 US); without
   reasoning, 0. [`queries/jp-glp1-by-japanese-category-reasoning.rq`]
4. **RxNorm is American.** 12 of the 47 substances (teneligliptin, ipragliflozin, imeglimin, …) are not in
   RxNorm; they are identified by UMLS CUI, and their Wikidata labels found by P2892. Four substances have no
   ATC code at all and need a curated fallback class with a reason. Japan has two classes ATC lacks (glinides,
   glimins). [`docs/decisions.md` 2026-10-25]
5. **Masking modelled as a standard.** Cells < 1,000 (oral) or < 400 (injection) are "‐", plus secondary
   masking. Modelled with SDMX `sdmx-attribute:confStatus sdmx-code:confStatus-C`, the analogue of the CMS
   suppression flag; checked with `sh:xone`. Before writing the shapes, the rules were proven on the data:
   every unmasked slice sums exactly to its national total (1,378 of 1,378).
6. **Business results** [`docs/findings.md` §6–10]:
   - Class mix, Japan vs Connecticut (single-ingredient, value share): DPP-4 23.9% vs 11.2%; GLP-1 20.7% vs
     50.9%; SGLT2 39.3% vs 34.1%. Three classes exist only in Japan's market. Shares, not amounts (yen at list
     price vs gross USD; Part D mostly 65+, NDB all ages).
   - Boehringer group: 37.5% of SGLT2 value (¥116.4bn; AstraZeneca 32.2%), 27.0% of DPP-4 (¥67.3bn; MSD 22.2%).
     The Lilly co-promotion is not visible in the data.
   - Age: share of value to patients 75+: DPP-4 46%, SGLT2 36%, GLP-1 20%.
   - Tirzepatide (Mounjaro) ¥1.1bn → ¥4.5bn per month (Apr 2024 → Mar 2025, 4×); semaglutide flat at ~¥6.3bn.
   - Prefectures: SGLT2 share 39.3% (Kyoto) to 45.1% (Nara), Tokyo 42.1%. A narrow band; the regional story is
     weak, the class story strong.
   - October 2024 (長期収載品の選定療養): generic share steps up that month in α-GI, glinides, SU, TZD.
7. **A data-definition trap.** Metformin's generic share shows 0.2%: NDB's generic flag follows the
   reimbursement definition, which excludes generics priced like their originator (★, the metformin "MT"
   generics). The graph documents it with an `rdfs:comment` on `dm:isGeneric`. Good paragraph on why
   definitions belong in the model.
8. **The incident (governance section).** Five full reloads plus reasoning-on `VALIDATE` runs filled the Free
   instance's disk; the database was corrupted, could not be dropped, and the instance had to be recreated
   (Free has no backups). Lesson: validate locally (pyshacl, OWL 2 RL closure with owlrl, all queries on
   pyoxigraph; `scripts/check_local.py`, ~8–12 min), push once, load incrementally by content hash
   (`scripts/load_stardog.py`). Recovery took one load of 2.5 min because every graph is rebuilt from files.
   [`docs/governance.md` "check locally, publish once", `docs/decisions.md`]
9. *(Dropped 2026-10-26: the AllegroGraph portability story is not in the article; the code is deleted.)*
10. **MCP in Japanese.** Through the MCP server (tested 2026-10-26 against the new database): ジャディアンス →
    Jardiance products, 東京 → prefecture 13, 糖尿病用剤 → class 396, メトホルミン塩酸塩 (NDB spelling) →
    metformin, 日本ベーリンガーインゲルハイム → the Japanese holder, 院外 → community pharmacy. Tokyo's
    diabetes drug value: 501 products, ¥73,497 million. A plain-language question in Japanese answered by
    Claude would mirror article 1's Chinese example (Figure 8).

## Figures still to make (screenshots by the user)
- Stardog Explorer around a Japanese product (e.g. ジャディアンス錠10mg → empagliflozin → SGLT2 → class 396 / A10BK).
- The 薬効分類 ↔ ATC crosswalk as a diagram.
- The Data Cube slice: one slice with its observations (diagram).
- Stardog Studio: jp-class-share-yen or jp-vs-connecticut-class-mix result; the reasoning on/off pair.
- Claude Desktop answering a Japanese question via MCP.
- Optional: a monthly chart of tirzepatide vs semaglutide; the October 2024 generic step.
- Voicebox has **not** been retested on Japan data. It must be re-enabled on the recreated database first.
  Only one server-side query pass after any change (memory: check locally before Stardog).

## Where things are
- Plan and scope: `japan_extension.md`. Decisions: `docs/decisions.md` (2026-10-25 entries).
  Results: `docs/findings.md` §6–10, `docs/query-results.md` (Stardog), `data/validation/query-results-local.md`.
- Story notes from article 1: `docs/article-notes.md` (no Japan notes there yet).
- Code: `scripts/download_ndb.py`, `clean_ndb.py`, `build_ndb.py`, `check_local.py`; shapes in
  `shapes/diabetes-market-shapes.ttl` (0.3.0); ontology `ontology/diabetes-market.ttl` (0.5.0);
  queries `queries/jp-*.rq` (8).

## System state (2026-10-26)
- **Stardog Cloud:** recreated instance, database `glp`, 734,106 triples, SHACL gate 0 violations,
  `query.all.graphs` on, users as before. Incremental dry run: up to date. All 14 queries match local results.
- **MCP server:** `tests/test_mcp_server.py` 13/13 passed against the new database. A Claude Code session
  started before the endpoint change must reconnect `glp-stardog` with `/mcp`.
- **AllegroGraph:** server removed by the user; scripts, `run_queries.py --ag` and its results file deleted
  2026-10-26, the three jp queries have their `ROUND` back. `AG_*` keys may still be in `.env`.
- **Git:** not committed since "add japan" (88cea6a). Uncommitted: decisions, query-results, japan_extension,
  three jp queries (ROUND removed), `run_queries.py` (`--ag`, `--local`), the AllegroGraph scripts, this file.

## Open items (not required for the article)
- Japan-only indications (CHF and CKD for empagliflozin and dapagliflozin, type 1 add-on for some SGLT2
  inhibitors): would partly replace the missing specialty story ("Jardiance in Japan treats hearts and kidneys").
- 12th release (monthly FY2025) does not fit next to this data; it needs its own database.
- Native-speaker review of curated ja/zh labels (carried over from article 1).
