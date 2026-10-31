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

Writes data/validation/analyst-eval-<label>.json and prints a summary.

Usage: .venv-snowflake/bin/python scripts/eval_analyst.py <label> [--runs N] [--only question-id]
"""
import argparse
import base64
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
    args = ap.parse_args()
    con = connect()
    cur = con.cursor()
    truth = ground_truth(cur)
    token = jwt()
    results = []
    for qid, (question, score) in QUESTIONS.items():
        if args.only and qid != args.only:
            continue
        for kind, view in VIEWS.items():
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
    out.write_text(json.dumps({"label": args.label, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "runs": args.runs, "results": results}, indent=1, ensure_ascii=False))

    print(f"\n{'question':12} {'check':18} " + " ".join(f"{k:>8}" for k in VIEWS))
    for qid in QUESTIONS:
        entries = [e for e in results if e["question"] == qid]
        if not entries:
            continue
        checks = next((list(e["checks"]) for e in entries if "checks" in e), [])
        for check in checks + ["errors", "warnings"]:
            cells = []
            for kind in VIEWS:
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
