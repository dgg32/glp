"""Ask Cortex Analyst the business questions on both semantic views, run its SQL, score the answers.

Each question is asked RUNS times per view through the Cortex Analyst REST API (key-pair JWT, the
credentials of .env), because Analyst is not deterministic. The SQL it returns is run with the
connector. Scores are checks against ground truth computed by plain SQL on the loaded tables
(independent of the semantic views) and the conventions of docs/findings.md:

  ja-specialty   「SGLT2阻害薬の処方件数を専門分野別に教えて」  numbers right; specialty names in Japanese
  share          SGLT2 vs GLP-1 share by specialty             numbers right; share right; prepared metric used
  cost           cost per claim by drug class                  ATC level-4 classes only; single-ingredient
                                                                 convention; cost per 30-day fill shown
  bi-share       Boehringer's share of SGLT2 claims            claims and share right
  glp1-share     company shares of GLP-1 claims                Novo Nordisk share right (class claims as
                                                                 the denominator: Byetta has two holders)
  ja-bi-share    「ベーリンガーのSGLT2阻害薬シェアは？」       claims and share right

With --model jp, the Japan questions on JAPAN_MARKET (NDB Open Data), all in Japanese:

  jp-tokyo       「東京都で処方された糖尿病治療薬の金額は？」     value right (prefecture cells, all settings)
  jp-bi-share    「日本ベーリンガーインゲルハイムのSGLT2阻害薬シェアは？」  share right (the subsidiary resolved
                                                                 to its corporate group)
  jp-glp1-cat    「GLP-1受容体作動薬は薬効分類のどこに入っている？」  both 249 and 396 named; 23 products in 249,
                                                                 2 in 396 (counted, or listed one per row)
  jp-mounjaro    「マンジャロの月別の金額の推移は？」              April 2024 and March 2025 totals right, or
                                                                 at least right when its rows are added up
  jp-age         「75歳以上の患者への割合が最も高い薬効群は？」    the drug class with the highest share first
                                                                 (glinides, not the DPP-4 inhibitors), share right

Writes data/validation/analyst-eval-<label>.json and prints a summary.

Usage: .venv-snowflake/bin/python scripts/eval_analyst.py <label> [--model us|jp] [--runs N] [--only question-id]
"""
import argparse
import base64
from collections import Counter
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_snowflake import connect  # noqa: E402  (also loads .env)

ROOT = Path(__file__).resolve().parent.parent
VIEWS = {"native": "GLP.SEMANTIC.DIABETES_MARKET", "osi": "GLP.SEMANTIC.DIABETES_MARKET_OSI"}
JP_VIEWS = {"native": "GLP.SEMANTIC.JAPAN_MARKET", "osi": "GLP.SEMANTIC.JAPAN_MARKET_OSI"}
JAPANESE = re.compile(r"[぀-ヿ一-鿿]")


def jwt():
    account = os.environ["SNOWFLAKE_ACCOUNT"].upper()
    user = os.environ["SNOWFLAKE_USER"].upper()
    key = serialization.load_pem_private_key(
        Path(os.path.expanduser(os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"])).read_bytes(), password=None)
    public = key.public_key().public_bytes(serialization.Encoding.DER,
                                           serialization.PublicFormat.SubjectPublicKeyInfo)
    fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(public).digest()).decode()
    now = int(time.time())
    b64 = lambda data: base64.urlsafe_b64encode(data).rstrip(b"=").decode()  # noqa: E731
    head = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    body = b64(json.dumps({"iss": f"{account}.{user}.{fingerprint}", "sub": f"{account}.{user}",
                           "iat": now, "exp": now + 3000}).encode())
    signature = key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{b64(signature)}"


def ask(token, view, question):
    url = f"https://{os.environ['SNOWFLAKE_ACCOUNT'].lower()}.snowflakecomputing.com/api/v2/cortex/analyst/message"
    payload = {"messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
               "semantic_view": view, "stream": False}
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST", headers={
        "Authorization": f"Bearer {token}", "X-Snowflake-Authorization-Token-Type": "KEYPAIR_JWT",
        "Content-Type": "application/json", "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=180) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == 2:
                return {"error": f"HTTP {exc.code}: {exc.read().decode()[:500]}"}
        except OSError as exc:
            if attempt == 2:
                return {"error": str(exc)}
        time.sleep(10 * (attempt + 1))


def ground_truth(cur):
    """Expected values, from plain SQL on the loaded tables (not through the semantic views)."""
    one = lambda sql: cur.execute(sql).fetchall()  # noqa: E731
    sglt2_by_specialty = {name: (int(s), int(g)) for name, s, g in one("""
        SELECT s.PREF_LABEL_EN, SUM(IFF(pc.CLASS_ID = 'SGLT2Inhibitor', p.TOTAL_CLAIMS, 0)),
               SUM(IFF(pc.CLASS_ID = 'GLP1ReceptorAgonist', p.TOTAL_CLAIMS, 0))
        FROM GLP.US.PRESCRIPTION p JOIN GLP.US.PRODUCT_CLASS pc ON pc.PRODUCT_ID = p.PRODUCT_ID
        JOIN GLP.US.PRESCRIBER d ON d.PRESCRIBER_ID = p.PRESCRIBER_ID
        JOIN GLP.VOCAB.SPECIALTY s ON s.SPECIALTY_CODE = d.PRIMARY_SPECIALTY_CODE
        WHERE pc.CLASS_ID IN ('SGLT2Inhibitor', 'GLP1ReceptorAgonist') GROUP BY 1""")}
    cost = {cls: (float(c), float(f)) for cls, c, f in one("""
        SELECT pc.CLASS_ID, SUM(p.TOTAL_DRUG_COST) / SUM(p.TOTAL_CLAIMS), SUM(p.TOTAL_DRUG_COST) / SUM(p.TOTAL_30DAY_FILLS)
        FROM GLP.US.PRESCRIPTION p JOIN GLP.US.PRODUCT_CLASS pc ON pc.PRODUCT_ID = p.PRODUCT_ID
        JOIN GLP.US.PRODUCT pr ON pr.PRODUCT_ID = p.PRODUCT_ID
        WHERE NOT pr.IS_COMBINATION GROUP BY 1""")}
    shares = {}
    for cls in ("SGLT2Inhibitor", "GLP1ReceptorAgonist"):
        total = one(f"""SELECT SUM(p.TOTAL_CLAIMS) FROM GLP.US.PRESCRIPTION p
                        JOIN GLP.US.PRODUCT_CLASS pc ON pc.PRODUCT_ID = p.PRODUCT_ID WHERE pc.CLASS_ID = '{cls}'""")[0][0]
        shares[cls] = {org: (int(c), int(c) / total) for org, c in one(f"""
            SELECT pm.ORGANIZATION_ID, SUM(p.TOTAL_CLAIMS) FROM GLP.US.PRESCRIPTION p
            JOIN GLP.US.PRODUCT_CLASS pc ON pc.PRODUCT_ID = p.PRODUCT_ID
            JOIN GLP.US.PRODUCT_MANUFACTURER pm ON pm.PRODUCT_ID = p.PRODUCT_ID
            WHERE pc.CLASS_ID = '{cls}' GROUP BY 1""")}
    non_level4 = [r[0] for r in one("SELECT PREF_LABEL_EN FROM GLP.VOCAB.THERAPEUTIC_CLASS WHERE LENGTH(NOTATION) < 5")]
    return {"sglt2_by_specialty": sglt2_by_specialty, "cost": cost, "shares": shares, "non_level4": non_level4}


def numbers(rows):
    out = []
    for row in rows:
        for v in row:
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                pass
    return out


def has(values, target, rel=0.002):
    return any(abs(v - target) <= max(abs(target) * rel, 0.5 if abs(target) > 100 else 0.0005) for v in values)


def has_share(values, share):
    """A share may come as a fraction (0.684) or a percentage (68.4), rounded to one decimal or not."""
    return any(abs(v - share) < 0.0006 or abs(v - 100 * share) < 0.06 for v in values)


def texts(rows):
    return [str(v) for row in rows for v in row if isinstance(v, str)]


BI, NOVO = "529900P5FAANZASUYL28", "549300DAQ1CVT6CXN342"


def jp_ground_truth(cur):
    """Expected values for the Japan questions, from plain SQL on JP.* (not through the semantic views)."""
    one = lambda sql: cur.execute(sql).fetchall()  # noqa: E731
    value = "q.QUANTITY * p.NHI_PRICE"
    cells = "GLP.JP.QUANTITY q JOIN GLP.JP.PRODUCT p ON p.PRODUCT_ID = q.PRODUCT_ID"
    tokyo = one(f"SELECT SUM({value}) FROM {cells} WHERE q.BREAKDOWN = 'prefecture' AND q.PREFECTURE_CODE = '13'")[0][0]
    sglt2 = dict(one(f"""SELECT COALESCE(o.CORPORATE_GROUP_ID, o.ORGANIZATION_ID, 'none'), SUM(t.TOTAL_QUANTITY * p.NHI_PRICE)
        FROM GLP.JP.NATIONAL_TOTAL t JOIN GLP.JP.PRODUCT p ON p.PRODUCT_ID = t.PRODUCT_ID
        JOIN GLP.JP.PRODUCT_SUBSTANCE ps ON ps.PRODUCT_ID = p.PRODUCT_ID
        JOIN GLP.VOCAB.SUBSTANCE s ON s.SUBSTANCE_ID = ps.SUBSTANCE_ID AND s.CLASS_ID = 'SGLT2Inhibitor'
        LEFT JOIN GLP.JP.ORGANIZATION o ON o.ORGANIZATION_ID = p.ORGANIZATION_ID GROUP BY 1"""))
    mounjaro = dict(one(f"""SELECT TO_CHAR(q.MONTH, 'YYYY-MM'), SUM({value}) FROM {cells}
        WHERE q.BREAKDOWN = 'month' AND p.PRODUCT_NAME_JA LIKE 'マンジャロ%' GROUP BY 1"""))
    # drug classes = depth 3 of the class tree, as therapeutic_class.is_drug_class
    oldest = one(f"""SELECT c.PREF_LABEL_EN, SUM(IFF(g.MIN_AGE >= 75, {value}, 0)) / SUM({value}) AS SHARE FROM {cells}
        JOIN GLP.JP.PRODUCT_CLASS pc ON pc.PRODUCT_ID = p.PRODUCT_ID
        JOIN GLP.VOCAB.THERAPEUTIC_CLASS c ON c.CLASS_ID = pc.CLASS_ID
        JOIN GLP.VOCAB.SEX_AGE_GROUP g ON g.SEX_AGE_CODE = q.SEX_AGE_CODE
        WHERE q.BREAKDOWN = 'sex-age'
          AND (SELECT COUNT(*) FROM GLP.VOCAB.CLASS_ANCESTOR a WHERE a.CLASS_ID = c.CLASS_ID) = 3
        GROUP BY 1 ORDER BY SHARE DESC LIMIT 1""")[0]
    labels = dict(one("SELECT PREF_LABEL_EN, PREF_LABEL_JA FROM GLP.VOCAB.THERAPEUTIC_CLASS"))
    return {"tokyo": float(tokyo), "bi_sglt2_share": float(sglt2[BI]) / float(sum(sglt2.values())),
            "mounjaro": {m: float(v) for m, v in mounjaro.items()},
            "oldest_class": [oldest[0], labels[oldest[0]]], "oldest_share": float(oldest[1])}


def has_yen(values, target):
    """Yen may come as yen, millions or billions (rounded to the unit shown)."""
    return any(has(values, target / scale, rel=0.005) for scale in (1, 1e6, 1e8, 1e9))


def jp_categories(rows):
    """Products per Japanese category when the answer lists products one per row (code or Japanese name)."""
    found = Counter()
    for row in rows:
        values = [str(v) for v in row]
        for code, name in (("249", "その他のホルモン剤"), ("396", "糖尿病用剤")):
            if code in values or any(v.startswith(name) for v in values):
                found[code] += 1
    return found


def monthly_sums(rows):
    """Values per month when the answer splits a month into several rows (e.g. one per strength)."""
    sums = Counter()
    for row in rows:
        month = next((str(v)[:7] for v in row if re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", str(v))), None)
        values = [float(v) for v in row if not re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", str(v))
                  and re.fullmatch(r"-?\d+(\.\d+)?", str(v))]
        if month and len(values) == 1:
            sums[month] += values[0]
    return sums


JP_QUESTIONS = {
    "jp-tokyo": ("東京都で処方された糖尿病治療薬の金額は？", lambda t, sql, rows: {
        "value": has_yen(numbers(rows), t["tokyo"])}),
    "jp-bi-share": ("日本ベーリンガーインゲルハイムのSGLT2阻害薬シェアは？", lambda t, sql, rows: {
        "share": has_share(numbers(rows), t["bi_sglt2_share"])}),
    "jp-glp1-cat": ("GLP-1受容体作動薬は薬効分類のどこに入っている？", lambda t, sql, rows: {
        "both_categories": {"249", "396"} <= set(jp_categories(rows)),
        "counts_23_2": {23.0, 2.0} <= set(numbers(rows)) or jp_categories(rows) == {"249": 23, "396": 2},
        "japanese_labels": any(JAPANESE.search(x) for x in texts(rows))}),
    "jp-mounjaro": ("マンジャロの月別の金額の推移は？", lambda t, sql, rows: {
        "monthly_totals": all(has_yen(numbers(rows), t["mounjaro"][m]) for m in ("2024-04", "2025-03")),
        "rows_add_up": all(has_yen([monthly_sums(rows)[m]], t["mounjaro"][m]) for m in ("2024-04", "2025-03"))}),
    "jp-age": ("75歳以上の患者への割合が最も高い薬効群は？", lambda t, sql, rows: {
        "right_class_first": bool(rows) and any(str(v) in t["oldest_class"] or str(v).rstrip("s") == t["oldest_class"][0].rstrip("s")
                                                for v in rows[0]),
        "share": has_share(numbers(rows), t["oldest_share"])}),
}

QUESTIONS = {
    "ja-specialty": ("SGLT2阻害薬の処方件数を専門分野別に教えて", lambda t, sql, rows: {
        "numbers": all(has(numbers(rows), t["sglt2_by_specialty"][s][0]) for s in
                       ("Internal Medicine Physician", "Family Medicine Physician", "Cardiovascular Disease Physician")),
        "japanese_labels": any(JAPANESE.search(x) for x in texts(rows))}),
    "share": ("What is the SGLT2 vs GLP-1 share by specialty?", lambda t, sql, rows: {
        "numbers": all(has(numbers(rows), v) for v in t["sglt2_by_specialty"]["Cardiovascular Disease Physician"]),
        "share": has_share(numbers(rows), 20536 / (20536 + 2166)),
        "prepared_metric": "SGLT2_SHARE_VS_GLP1" in sql.upper()}),
    "cost": ("Cost per claim by drug class", lambda t, sql, rows: {
        "level4_only": not any(x in t["non_level4"] for x in texts(rows)),
        "single_ingredient": has(numbers(rows), t["cost"]["DPP4Inhibitor"][0]),
        "per_30day_fill": has(numbers(rows), t["cost"]["GLP1ReceptorAgonist"][1])}),
    "bi-share": ("What is Boehringer's share of SGLT2 claims?", lambda t, sql, rows: {
        "claims": has(numbers(rows), t["shares"]["SGLT2Inhibitor"][BI][0]),
        "share": has_share(numbers(rows), t["shares"]["SGLT2Inhibitor"][BI][1])}),
    "glp1-share": ("What is each company's share of GLP-1 claims?", lambda t, sql, rows: {
        "novo_claims": has(numbers(rows), t["shares"]["GLP1ReceptorAgonist"][NOVO][0]),
        "novo_share": has_share(numbers(rows), t["shares"]["GLP1ReceptorAgonist"][NOVO][1])}),
    "ja-bi-share": ("ベーリンガーのSGLT2阻害薬シェアは？", lambda t, sql, rows: {
        "claims": has(numbers(rows), t["shares"]["SGLT2Inhibitor"][BI][0]),
        "share": has_share(numbers(rows), t["shares"]["SGLT2Inhibitor"][BI][1])}),
    # Held out: no verified query covers it, so it tests the model itself (is_drug_class).
    "top-cost": ("Which drug classes cost the most?", lambda t, sql, rows: {
        "level4_only": not any(x in t["non_level4"] for x in texts(rows)),
        "glp1_first": bool(rows) and any("GLP-1" in str(v) for v in rows[0])}),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("label")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--only")
    ap.add_argument("--model", choices=["us", "jp"], default="us")
    args = ap.parse_args()
    con = connect()
    cur = con.cursor()
    views, questions = (VIEWS, QUESTIONS) if args.model == "us" else (JP_VIEWS, JP_QUESTIONS)
    truth = (ground_truth if args.model == "us" else jp_ground_truth)(cur)
    token = jwt()
    results = []
    for qid, (question, score) in questions.items():
        if args.only and qid != args.only:
            continue
        for kind, view in views.items():
            for run in range(args.runs):
                reply = ask(token, view, question)
                content = reply.get("message", {}).get("content", [])
                sql = next((c.get("statement", "") for c in content if c.get("type") == "sql"), "")
                entry = {"question": qid, "view": kind, "run": run, "sql": sql,
                         "warnings": [w.get("message", "") for w in reply.get("warnings", [])],
                         "text": " ".join(c.get("text", "") for c in content if c.get("type") == "text")[:500]}
                if "error" in reply or not sql:
                    entry["error"] = reply.get("error", "no SQL returned")
                else:
                    try:
                        rows = cur.execute(sql).fetchall()
                        entry["rows"] = [[str(v) for v in r] for r in rows[:30]]
                        entry["checks"] = score(truth, sql, rows)
                    except Exception as exc:  # the SQL Analyst wrote fails
                        entry["error"] = str(exc)[:300]
                results.append(entry)
                mark = "ERR" if "error" in entry else " ".join(f"{k}={'✓' if v else '✗'}" for k, v in entry["checks"].items())
                print(f"{qid:12} {kind:6} run {run}: {mark}{' (warning)' if entry['warnings'] else ''}")
    out = ROOT / "data" / "validation" / f"analyst-eval-{args.label}.json"
    out.write_text(json.dumps({"label": args.label, "model": args.model, "truth": truth,
                               "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "runs": args.runs, "results": results}, indent=1, ensure_ascii=False, default=str))

    print(f"\n{'question':12} {'check':18} " + " ".join(f"{k:>8}" for k in views))
    for qid in questions:
        entries = [e for e in results if e["question"] == qid]
        if not entries:
            continue
        checks = next((list(e["checks"]) for e in entries if "checks" in e), [])
        for check in checks + ["errors", "warnings"]:
            cells = []
            for kind in views:
                es = [e for e in entries if e["view"] == kind]
                if check == "errors":
                    n = sum("error" in e for e in es)
                elif check == "warnings":
                    n = sum(bool(e["warnings"]) for e in es)
                else:
                    n = sum(bool(e.get("checks", {}).get(check)) for e in es)
                cells.append(f"{n}/{len(es)}")
            print(f"{qid:12} {check:18} " + " ".join(f"{c:>8}" for c in cells))
    print(f"\nwrote {out.relative_to(ROOT)}")
    con.close()


if __name__ == "__main__":
    main()
