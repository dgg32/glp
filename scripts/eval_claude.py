"""Ask Claude the Cortex Analyst evaluation questions through the Snowflake MCP server, score the answers.

The counterpart of eval_analyst.py: same questions, same ground truth (plain SQL on the loaded tables), same number
of runs. Claude Code runs headless (`claude -p`) with nothing but mcp_server/snowflake_server.py: no built-in tools,
no other MCP servers, no settings, and a working directory outside the repo, so it cannot read CLAUDE.md,
docs/findings.md or the queries. GLP_SF_LAYER picks the views the server describes (native or OSI).

Analyst returns SQL and rows; Claude returns a written answer. So the checks read the answer text (numbers with
thousands separators, percentages, yen in 億/万/million/billion) and, where a check is about the query (prepared
metric used), the SQL of Claude's run_sql calls. Checks that cannot be read from prose are restated on the text:

  ja-specialty   numbers right; the specialty names in Japanese (循環器内科医 and 内科医 written)
  share          numbers right; share right; prepared metric (SGLT2_SHARE_VS_GLP1) used in a query
  cost           no figure of a parent class (drugs used in diabetes, ...) given; single-ingredient convention;
                 cost per 30-day fill shown
  top-cost       no parent-class figure; GLP-1 named before the other drug classes
  jp-mounjaro    April 2024 and March 2025 totals written (no per-strength sum check)
  jp-age         the class with the highest 75+ share named (en or ja) and its share right
  the rest       as in eval_analyst.py, on the numbers of the text

Writes data/validation/claude-eval-<label>.json (answers, tool calls, cost, turns) and prints a summary.

Usage: .venv-snowflake/bin/python scripts/eval_claude.py <label> [--model us|jp] [--layer native|osi]
           [--runs N] [--only question-id] [--parallel N] [--claude-model MODEL]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_analyst import (BI, NOVO, JP_QUESTIONS, QUESTIONS, ground_truth, has, has_yen,  # noqa: E402
                          jp_ground_truth)
from load_snowflake import connect  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "mcp_server" / "snowflake_server.py"
TOOLS = ["mcp__glp-snowflake__describe_model", "mcp__glp-snowflake__resolve_term", "mcp__glp-snowflake__run_sql"]
SYSTEM = ("Answer the user's question about the data with the glp-snowflake tools. The user cannot reply, so do not "
          "ask clarifying questions; state any assumption you make.")
NUMBER = re.compile(r"(?<![A-Za-z0-9_.])-?\d[\d,]*(?:\.\d+)?")  # ASCII: 約1,846億 and 合計135,954件 count
SCALES = {"億": 1e8, "万": 1e4, "million": 1e6, "billion": 1e9, "百万": 1e6}


def claude_binary():
    found = shutil.which("claude") or next(iter(sorted(
        Path.home().glob(".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude"))), None)
    if not found:
        sys.exit("claude CLI not found (PATH or the VS Code extension)")
    return str(found)


def text_numbers(text):
    """Every number in the text, plus the same number scaled by a following unit (1,234億 -> 1.234e11)."""
    out = []
    for m in NUMBER.finditer(text):
        v = float(m.group().replace(",", ""))
        out.append(v)
        unit = re.match(r"\s*(億|百万|万|million|billion)", text[m.end():m.end() + 10], re.I)
        if unit:
            out.append(v * SCALES[unit.group(1).lower()])
    return out


def has_share_text(text, share):
    """A share as a fraction or a percentage, to the precision written (68.4%, 68%, 0.684)."""
    for m in NUMBER.finditer(text):
        raw = m.group().replace(",", "")
        v, decimals = float(raw), len(raw.split(".")[1]) if "." in raw else 0
        for target in (share, 100 * share):
            if abs(v - target) <= 0.5 * 10 ** -decimals + 1e-9 and (target > 1 or decimals >= 2):
                return True
    return False


def has_number(text, target):
    return has(text_numbers(text), target)


def first_named(text, names):
    """The key of `names` (key -> patterns) whose first mention comes first in the text."""
    positions = {k: min((m.start() for p in ps for m in re.finditer(p, text, re.I)), default=None)
                 for k, ps in names.items()}
    found = {k: p for k, p in positions.items() if p is not None}
    return min(found, key=found.get) if found else None


DRUG_CLASSES = {"GLP1ReceptorAgonist": [r"GLP-?1"], "SGLT2Inhibitor": [r"SGLT-?2"], "DPP4Inhibitor": [r"DPP-?4"],
                "insulin": [r"insulin", r"インスリン"], "Biguanide": [r"biguanide", r"metformin", r"ビグアナイド"],
                "Sulfonylurea": [r"sulfonylurea", r"スルホニル"], "Thiazolidinedione": [r"thiazolidinedione", r"チアゾリジン"]}


def extra_truth(cur):
    """What the text checks need beyond eval_analyst's ground truth."""
    one = lambda sql: cur.execute(sql).fetchall()  # noqa: E731
    # Parent classes (ATC levels 1-3), all products. An answer presents one as a drug class if it names it or gives
    # one of its figures. Figures a drug class shares (Connecticut's only insulins are long-acting, so "Insulins and
    # analogues" = "Long-acting insulins") and the market's figures (the top class: the overall average or total,
    # given as context or as the denominator of shares) are no evidence.
    rows = one("""SELECT c.PREF_LABEL_EN, c.PREF_LABEL_JA, LENGTH(c.NOTATION) < 5, c.BROADER_CLASS_ID IS NULL,
               SUM(p.TOTAL_DRUG_COST) / SUM(p.TOTAL_CLAIMS), SUM(p.TOTAL_DRUG_COST)
        FROM GLP.US.PRESCRIPTION p JOIN GLP.US.PRODUCT_CLASS pc ON pc.PRODUCT_ID = p.PRODUCT_ID
        JOIN GLP.VOCAB.THERAPEUTIC_CLASS c ON c.CLASS_ID = pc.CLASS_ID GROUP BY 1, 2, 3, 4""")
    classes = [r for r in rows if not r[2]]
    shared = lambda v, i: any(abs(v - float(r[i])) <= abs(v) * 0.005 for r in classes)  # noqa: E731
    parents = [r for r in rows if r[2]]
    ja = dict(one("SELECT PREF_LABEL_EN, PREF_LABEL_JA FROM GLP.VOCAB.SPECIALTY WHERE PREF_LABEL_JA IS NOT NULL"))
    return {"parent_names": [n for r in parents for n in r[:2] if n],
            "parent_cost_per_claim": {r[0]: float(r[4]) for r in parents if not shared(float(r[4]), 4) and not r[3]},
            "parent_total_cost": {r[0]: float(r[5]) for r in parents if not shared(float(r[5]), 5) and not r[3]},
            "specialty_ja": {k: ja[k] for k in ("Internal Medicine Physician", "Cardiovascular Disease Physician")}}


def no_parent_class(text, names, values, per_claim=False):
    if per_claim:  # amounts in millions are totals, not costs per claim ($644.6M is not $645 per claim)
        text = re.sub(r"\d[\d,.]*\s*(?:M|million|bn|billion|億|万)(?![a-z])", " ", text, flags=re.I)
    nums = text_numbers(text)
    named = any(n.lower() in text.lower() for n in names)
    return not named and not any(has(nums, v, rel=0.001) or has([n * 1e6 for n in nums], v, rel=0.005) for v in values)


def score(qid, t, x, text, sqls):
    sql = " ".join(sqls).upper()
    us = t.get("shares")
    if qid == "ja-specialty":
        return {"numbers": all(has_number(text, t["sglt2_by_specialty"][s][0]) for s in
                               ("Internal Medicine Physician", "Family Medicine Physician",
                                "Cardiovascular Disease Physician")),
                "japanese_labels": all(name in text for name in x["specialty_ja"].values())}
    if qid == "share":
        return {"numbers": all(has_number(text, v) for v in t["sglt2_by_specialty"]["Cardiovascular Disease Physician"]),
                "share": has_share_text(text, 20536 / (20536 + 2166)),
                "prepared_metric": "SGLT2_SHARE_VS_GLP1" in sql}
    if qid == "cost":
        return {"level4_only": no_parent_class(text, x["parent_names"], x["parent_cost_per_claim"].values(), True),
                "single_ingredient": has_number(text, t["cost"]["DPP4Inhibitor"][0]),
                "per_30day_fill": has_number(text, t["cost"]["GLP1ReceptorAgonist"][1])}
    if qid in ("bi-share", "ja-bi-share"):
        return {"claims": has_number(text, us["SGLT2Inhibitor"][BI][0]),
                "share": has_share_text(text, us["SGLT2Inhibitor"][BI][1])}
    if qid == "glp1-share":
        return {"novo_claims": has_number(text, us["GLP1ReceptorAgonist"][NOVO][0]),
                "novo_share": has_share_text(text, us["GLP1ReceptorAgonist"][NOVO][1])}
    if qid == "top-cost":
        return {"level4_only": no_parent_class(text, x["parent_names"], x["parent_total_cost"].values()),
                "glp1_first": first_named(text, DRUG_CLASSES) == "GLP1ReceptorAgonist"}
    if qid == "jp-tokyo":
        return {"value": has_yen(text_numbers(text), t["tokyo"])}
    if qid == "jp-bi-share":
        return {"share": has_share_text(text, t["bi_sglt2_share"])}
    if qid == "jp-glp1-cat":
        return {"both_categories": "249" in text and "396" in text,
                "counts_23_2": has(text_numbers(text), 23) and has(text_numbers(text), 2)}
    if qid == "jp-mounjaro":
        return {"monthly_totals": all(has_yen(text_numbers(text), t["mounjaro"][m]) for m in ("2024-04", "2025-03"))}
    if qid == "jp-age":
        en, ja = t["oldest_class"]
        return {"right_class_named": ja in text or en.rstrip("s").lower() in text.lower() or "グリニド" in text,
                "share": has_share_text(text, t["oldest_share"])}
    raise KeyError(qid)


def ask(claude, workdir, question, model):
    cmd = [claude, "-p", question, "--mcp-config", str(workdir / "mcp.json"), "--strict-mcp-config",
           "--tools", "", "--allowedTools", *TOOLS, "--setting-sources", "", "--no-session-persistence",
           "--append-system-prompt", SYSTEM, "--output-format", "stream-json", "--verbose"]
    if model:
        cmd += ["--model", model]
    proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=900)
    calls, entry = [], {"model": None}
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "system" and event.get("subtype") == "init":
            entry["model"] = event.get("model")
        elif event.get("type") == "assistant":
            calls += [{"tool": b["name"].split("__")[-1], "input": b["input"]}
                      for b in event["message"]["content"] if b.get("type") == "tool_use"]
        elif event.get("type") == "result":
            entry.update(answer=event.get("result") or "", turns=event.get("num_turns"),
                         seconds=round((event.get("duration_ms") or 0) / 1000), cost_usd=event.get("total_cost_usd"),
                         status=event.get("subtype"))
    if "answer" not in entry:
        entry["error"] = (proc.stderr or "no result")[-500:]
    entry["tool_calls"] = calls
    return entry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("label")
    ap.add_argument("--model", choices=["us", "jp"], default="us")
    ap.add_argument("--layer", choices=["native", "osi"], default="native")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--only")
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--claude-model")
    ap.add_argument("--rescore", action="store_true", help="score the saved answers of <label> again, ask nothing")
    args = ap.parse_args()
    out = ROOT / "data" / "validation" / f"claude-eval-{args.label}.json"
    if args.rescore:
        saved = json.loads(out.read_text())
        args.model = saved["model"]

    con = connect()
    cur = con.cursor()
    truth = (ground_truth if args.model == "us" else jp_ground_truth)(cur)
    extra = extra_truth(cur) if args.model == "us" else {}
    con.close()
    questions = {q: text for q, (text, _) in (QUESTIONS if args.model == "us" else JP_QUESTIONS).items()
                 if not args.only or q == args.only}

    if args.rescore:
        truth = json.loads(json.dumps(truth, default=str))  # the same shape as the saved file
        for e in saved["results"]:
            if "error" not in e:
                sqls = [c["input"].get("sql", "") for c in e["tool_calls"] if c["tool"] == "run_sql"]
                e["checks"] = score(e["question"], truth, extra, e["answer"], sqls)
        saved.update(truth=truth, extra_truth=extra, rescored=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        out.write_text(json.dumps(saved, indent=1, ensure_ascii=False, default=str))
        summary(questions, saved["results"], out)
        return

    workdir = Path(tempfile.mkdtemp(prefix="glp-claude-eval-"))  # outside the repo: no CLAUDE.md, no project files
    (workdir / "mcp.json").write_text(json.dumps({"mcpServers": {"glp-snowflake": {
        "command": str(ROOT / ".venv-snowflake" / "bin" / "python"), "args": [str(SERVER)],
        "env": {"GLP_SF_LAYER": args.layer}}}}))
    claude = claude_binary()
    jobs = [(qid, run) for qid in questions for run in range(args.runs)]

    def work(job):
        qid, run = job
        entry = {"question": qid, "run": run, **ask(claude, workdir, questions[qid], args.claude_model)}
        if "error" not in entry:
            sqls = [c["input"].get("sql", "") for c in entry["tool_calls"] if c["tool"] == "run_sql"]
            entry["checks"] = score(qid, truth, extra, entry["answer"], sqls)
            entry["semantic_view_used"] = any("SEMANTIC_VIEW(" in s.upper() for s in sqls)
            entry["raw_tables_used"] = any(re.search(r"GLP\.(US|JP|VOCAB)\.", s, re.I) for s in sqls)
        mark = "ERR" if "error" in entry else " ".join(f"{k}={'✓' if v else '✗'}" for k, v in entry["checks"].items())
        print(f"{qid:12} run {run}: {mark}  ({entry.get('turns')} turns, {entry.get('seconds')} s)", flush=True)
        return entry

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        results = list(pool.map(work, jobs))
    shutil.rmtree(workdir, ignore_errors=True)

    out.write_text(json.dumps({"label": args.label, "model": args.model, "layer": args.layer, "truth": truth,
                               "extra_truth": extra, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "runs": args.runs, "results": results}, indent=1, ensure_ascii=False, default=str))
    summary(questions, results, out)


def summary(questions, results, out):
    print(f"\n{'question':12} {'check':18} {'claude':>8}")
    for qid in questions:
        es = [e for e in results if e["question"] == qid]
        checks = next((list(e["checks"]) for e in es if "checks" in e), [])
        for check in checks + ["errors"]:
            n = sum("error" in e for e in es) if check == "errors" else sum(bool(e.get("checks", {}).get(check)) for e in es)
            print(f"{qid:12} {check:18} {f'{n}/{len(es)}':>8}")
    done = [e for e in results if "error" not in e]
    if done:
        print(f"\nmean {sum(e['turns'] or 0 for e in done) / len(done):.1f} turns, "
              f"{sum(e['seconds'] or 0 for e in done) / len(done):.0f} s, "
              f"${sum(e['cost_usd'] or 0 for e in done) / len(done):.2f} per answer; "
              f"model {done[0]['model']}; semantic views in {sum(e['semantic_view_used'] for e in done)}/{len(done)}, "
              f"raw tables in {sum(e['raw_tables_used'] for e in done)}/{len(done)}")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
