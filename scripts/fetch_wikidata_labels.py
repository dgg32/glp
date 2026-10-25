"""Choose the Japanese and Chinese labels: Wikidata where it is reliable, curated labels otherwise.

Run after resolve_vocab.py, resolve_drugs.py and resolve_organizations.py (it reads their outputs).

Wikidata (CC0) items are found by identifier, never by name: substances by RxNorm CUI (P3345) or, for
substances not in RxNorm (Japan only), by UMLS CUI (P2892),
companies by LEI (P1278), indications by MeSH descriptor ID (P486), drug classes by ATC code (P267).
Policy, from comparing Wikidata with the curated drafts (docs/decisions.md, 2026-10-15):
  Japanese    from Wikidata for substances, companies and indications
  Chinese     from Wikidata for companies and indications, Simplified only (zh-hans / zh-cn); the
              plain "zh" labels of substances mix Traditional script and Taiwanese names
  otherwise   the curated label (vocab/src/*_ja_zh.csv, therapeutic_classes.csv, indications.csv);
              drug classes always, because Wikidata's ATC links often point to chemical families;
              also where a curated row sets keep_curated after review (Merck & Co. is MSD in Japan)
Every curated label is compared with Wikidata where Wikidata has one, and docs/label-review.md lists
the disagreements for native-speaker review. NUCC specialties have no Wikidata identifier and are
not covered.

Responses are cached in data/raw/wikidata/, so reruns are offline.

Output (generated, do not edit): scripts/labels_ja_zh.csv; report: docs/label-review.md

Usage: python3 scripts/fetch_wikidata_labels.py
"""
import csv
import hashlib
import json
import time
import urllib.parse
import urllib.request

from build_skos import RAW, ROOT, read_csv

SPARQL = "https://query.wikidata.org/sparql"
USER_AGENT = "glp-diabetes-graph/0.1 (https://github.com/dgg32; label lookup by identifier)"
FROM_WIKIDATA = {("substance", "ja"), ("organization", "ja"), ("organization", "zh"),
                 ("indication", "ja"), ("indication", "zh")}


def wikidata_labels(prop, keys):
    """identifier -> {item, ja, zh_hans, zh} for items with wdt:prop identifier (unique items only)."""
    values = " ".join(json.dumps(k) for k in sorted(keys))
    query = f"""SELECT ?key ?item ?lang ?label WHERE {{
  VALUES ?key {{ {values} }}
  ?item wdt:{prop} ?key .
  OPTIONAL {{ ?item rdfs:label ?label . BIND(lang(?label) AS ?lang)
             FILTER(?lang IN ("ja", "zh", "zh-hans", "zh-cn")) }}
}}"""
    cache = RAW / "wikidata" / f"{prop}_{hashlib.sha256(query.encode()).hexdigest()[:16]}.json"
    if not cache.exists():
        req = urllib.request.Request(SPARQL + "?" + urllib.parse.urlencode({"query": query, "format": "json"}),
                                     headers={"User-Agent": USER_AGENT})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    body = json.load(resp)
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(10 * (attempt + 1))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(body, ensure_ascii=False, indent=1))
    items, labels = {}, {}
    for b in json.loads(cache.read_text())["results"]["bindings"]:
        key, item = b["key"]["value"], b["item"]["value"].rsplit("/", 1)[1]
        items.setdefault(key, set()).add(item)
        if "label" in b:
            labels.setdefault((key, item), {})[b["lang"]["value"]] = b["label"]["value"]
    out = {}
    for key, its in items.items():
        if len(its) != 1:
            continue  # ambiguous identifier: several items, use none
        item = its.pop()
        l = labels.get((key, item), {})
        out[key] = {"item": item, "ja": l.get("ja", ""), "zh_hans": l.get("zh-hans") or l.get("zh-cn", ""),
                    "zh": l.get("zh", "")}
    return out


def concepts(keep):
    """(kind, concept id, Wikidata property, identifier, curated ja, curated zh); fills keep with
    (concept, lang) pairs whose curated label was reviewed and wins over Wikidata (keep_curated column)."""
    out = []
    subs = {r["id"]: r for r in read_csv("substance_labels_ja_zh.csv")}
    for s in csv.DictReader(open(ROOT / "scripts" / "substances.csv", newline="", encoding="utf-8")):
        c = subs.get(s["substance"], {})
        # Japan-only substances have no RxCUI; they are found by UMLS CUI (P2892) instead
        prop, key = ("P3345", s["rxcui"]) if s["rxcui"] else ("P2892", s["umls_cui"])
        out.append(("substance", s["substance"], prop, key, c.get("pref_ja", ""), c.get("pref_zh", "")))
        keep.update((s["substance"], lang) for lang in c.get("keep_curated", "").split("|") if lang)
    orgs = {r["organization"]: r for r in read_csv("organization_labels_ja_zh.csv")}
    seen = set()
    for o in csv.DictReader(open(ROOT / "scripts" / "organizations.csv", newline="", encoding="utf-8")):
        if o["organization"] in seen:
            continue
        seen.add(o["organization"])
        c = orgs.get(o["organization"], {})
        out.append(("organization", o["organization"], "P1278", o["lei"], c.get("label_ja", ""), c.get("label_zh", "")))
        keep.update((o["organization"], lang) for lang in c.get("keep_curated", "").split("|") if lang)
    for i in csv.DictReader(open(ROOT / "scripts" / "indications.csv", newline="", encoding="utf-8")):
        out.append(("indication", i["id"], "P486", i["mesh_id"], i["pref_ja"], i["pref_zh"]))
    for c in csv.DictReader(open(ROOT / "scripts" / "therapeutic_classes.csv", newline="", encoding="utf-8")):
        out.append(("class", c["id"], "P267", c["atc"], c["pref_ja"], c["pref_zh"]))
    return out


def main():
    keep = set()
    rows_in = concepts(keep)
    found = {}
    for prop in sorted({r[2] for r in rows_in}):
        found[prop] = wikidata_labels(prop, {r[3] for r in rows_in if r[2] == prop and r[3]})

    rows, review = [], []
    for kind, cid, prop, key, cur_ja, cur_zh in rows_in:
        wd = found[prop].get(key, {}) if key else {}
        row = {"kind": kind, "concept": cid, "wikidata": wd.get("item", "")}
        for lang, cur, wd_label in (("ja", cur_ja, wd.get("ja", "")), ("zh", cur_zh, wd.get("zh_hans", ""))):
            use_wd = (kind, lang) in FROM_WIKIDATA and wd_label and (cid, lang) not in keep
            row[f"pref_{lang}"] = wd_label if use_wd else cur
            row[f"{lang}_source"] = "wikidata" if use_wd else ("curated" if cur else "")
            if not row[f"pref_{lang}"]:
                raise SystemExit(f"{kind} {cid}: no {lang} label in Wikidata or the curated files")
            shown = wd_label or (wd.get("zh", "") if lang == "zh" else "")
            if shown and cur and shown != cur:
                review.append((kind, cid, lang, cur, shown + ("" if wd_label else " (zh, script not marked)"),
                               "Wikidata" if use_wd else "curated", wd.get("item", "")))
        rows.append(row)

    with open(ROOT / "scripts" / "labels_ja_zh.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    counts = {(k, l): sum(1 for r in rows if r["kind"] == k and r[f"{l}_source"] == "wikidata")
              for k in ("substance", "organization", "indication", "class") for l in ("ja", "zh")}
    lines = ["# Japanese and Chinese label review", "",
             "Generated by `scripts/fetch_wikidata_labels.py`; do not edit. Curated labels are drafts pending "
             "native-speaker review. This list shows where a curated label and Wikidata disagree, which "
             "label the graph uses, and the Wikidata item to check. Chinese means Simplified Chinese.", "",
             "Labels taken from Wikidata: " + ", ".join(f"{k} {l} {n}" for (k, l), n in counts.items() if n) + ".", "",
             "| Kind | Concept | Lang | Curated | Wikidata | Used | Item |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {k} | {c} | {l} | {cur} | {wd} | {used} | [{item}](https://www.wikidata.org/wiki/{item}) |"
              for k, c, l, cur, wd, used, item in review]
    (ROOT / "docs" / "label-review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote scripts/labels_ja_zh.csv ({len(rows)} concepts) and docs/label-review.md "
          f"({len(review)} disagreements)")
    for (k, l), n in counts.items():
        total = sum(1 for r in rows if r["kind"] == k)
        print(f"  {k:12} {l}: {n}/{total} from Wikidata")


if __name__ == "__main__":
    main()
