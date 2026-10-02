"""Live accuracy check of the line-by-line code analysis (uses the real model and the API key on this machine).

    python tests/evals/deepdive_eval.py            # all run-1 files + the planted-defect and clean files
    python tests/evals/deepdive_eval.py AIDINQ.cbl # one file

Scores:
  recall     share of the expected facts (written by hand from the code) that the analysis found
  traps      statements it must NOT make (things the code does not do); any hit fails the run
  clean      a well-written file must produce no defect or security statements
  planted    a file with five known defects must have all five found
Writes tests/results/DEEPDIVE_EVAL_<date>.md with every statement, its lines and quote, for a person to check
precision (that nothing it says is wrong). Exit code 1 if recall < 90%, any trap fires, the clean file gets a defect,
or a planted defect is missed.
"""
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "src"))
sys.path.insert(0, str(HERE.parent))
RUN1 = HERE.parent / "fixtures" / "run1_program"
RESULTS = HERE.parent / "results"
RECALL_TARGET = 0.9

# Each expected fact is a list of groups; every group must match (regex, case-insensitive) somewhere in ONE statement
# (with its quote). Written from the code itself, line by line.
EXPECTED = {
    "AIDPAYRN.cbl": {
        "holdback 10%": [r"holdback", r"\.100|10 ?%|0\.1\b|ten per"],
        "adjustment types PY/LE/AU": [r"\bPY\b|prior.?year", r"\bLE\b|levy", r"\bAU\b|audit"],
        "audit adjustments are subtracted": [r"audit|\bAU\b", r"subtract|reduc|deduct|negative"],
        "zero or negative gross is counted, not paid": [r"zero|negative|not > zero|<= ?0", r"count|not (paid|written)|skip"],
        "exits with return code 16 if the open fails": [r"\b16\b", r"open|status|fail"],
        "net = gross - holdback": [r"net", r"gross", r"holdback"],
        "writes PAYMENT-REC / PAYMENT-FILE": [r"PAYMENT-(REC|FILE)", r"writ"],
        "pay period hard-coded 202609 (on a cut-off line: must be held back, not stated)": "HELD:202609",
        "totals accumulated but never written out": [r"WS-TOTAL-(GROSS|NET)|total", r"never|not (written|output|used|displayed|reported)"],
        "unknown adjustment types are only displayed": [r"unknown|other", r"display|ignor|skip|not applied"],
        "only the entitlement file open status is checked": [r"WS-ENT-STATUS|entitle", r"only|not.*(ADJ|PAY|adjust|payment)|other files"],
    },
    "aid_pkg_post_payments.sql": {
        "amount = adm * 6728": [r"6728"],
        "WHEN OTHERS THEN NULL swallows errors": [r"WHEN OTHERS|all errors|every error|exception", r"null|swallow|ignor|silent|suppress"],
        "dynamic DELETE built with ||": [r"EXECUTE IMMEDIATE|dynamic", r"\|\||concaten|p_period|inject"],
        "inserts into aid_payment": [r"aid_payment", r"insert"],
        "marks aid_run DONE": [r"aid_run", r"DONE"],
        "logs POST via audit_pkg": [r"audit_pkg|log_event"],
        "no COMMIT in the procedure": [r"commit", r"no|not|without|never"],
    },
    "AidPaymentController.cs": {
        "hard-coded password in the connection string": [r"password|credential|P@ssw0rd1", r"hard.?coded|connection string|in the code|literal"],
        "Approve updates dbo.PaymentBatch Status 'A'": [r"PaymentBatch", r"Status|'A'|approv"],
        "Approve has no authorization attribute": [r"Authori[sz]e|authori[sz]ation|any (caller|user)|anonymous"],
        "@id placeholder never bound (no parameter added)": [r"@id", r"(never|not|no).{0,40}(bound|added|supplied|set|pass)|Parameters|missing parameter"],
        "LoadHistory builds SQL but never runs it and returns an empty list": [r"LoadHistory|history", r"never (execut|run)|not (execut|run)|empty|unused"],
        "AuditTrail.Write after approve": [r"AuditTrail"],
        "uses SqlClient / SQL Server": [r"SqlConnection|SqlClient|SQL Server|SchoolFinance|MDESQL02"],
    },
    "frmAidCalc.frm": {
        "SQL built from txtDistrict.Text": [r"txtDistrict", r"concaten|inject|built|&"],
        "hard-coded password Winter2009": [r"Winter2009|password|credential", r"hard.?coded|connection string|constant|literal"],
        "audit written to C:\\AID\\AUDIT.LOG": [r"AUDIT\.LOG"],
        "Resume Next continues after the error": [r"Resume Next|continu", r"error"],
        "ComputeAid only writes the ADM value to the log (no calculation)": [r"ComputeAid", r"(only|just|no|not|does not).{0,60}(log|writ|comput|calculat)"],
        "PUPIL_UNITS selected but unused": [r"PUPIL_UNITS", r"unused|never|not used|ignored"],
        "uses ADO / SQLOLEDB": [r"ADODB|ADO\b|SQLOLEDB|SCHOOLFIN"],
    },
    "AidPaymentPosting.rpg": {
        "QCMDEXC runs a command built with PERIOD": [r"QCMDEXC", r"PERIOD|concaten|built|SBMJOB"],
        "submits AIDRPT": [r"AIDRPT"],
        "WKAMT = ADM * RATE is computed": [r"WKAMT", r"ADM|RATE"],
        "WKAMT is never moved to the record before UPDATE": [r"WKAMT", r"never|not (moved|stored|written|used|assigned)|unused|lost"],
        "AIDPAY updated if found, otherwise written": [r"AIDPAY", r"%FOUND|found|exist", r"WRITE|writ|add|insert"],
        "reads DISTMST in a loop": [r"DISTMST", r"read|loop|each"],
    },
    "AIDINQ.cbl": {
        "CICS transaction AIDQ": [r"AIDQ"],
        "WS-DISTRICT-ID is never set from the map": [r"WS-DISTRICT-ID|district id", r"never|not (set|populated|moved|received|filled)|uninitiali[sz]ed|no INTO"],
        "SELECT TOTAL_AMOUNT from DISTRICT_AID": [r"TOTAL_AMOUNT|DISTRICT_AID"],
        "errors transfer to AIDERR": [r"AIDERR"],
        "LINK to AIDAUDIT": [r"AIDAUDIT"],
    },
    "AIDDBD.asm": {
        "HIDAM access": [r"HIDAM"],
        "segment hierarchy DISTRICT > PAYMENT > ADJUST": [r"PAYMENT", r"DISTRICT", r"parent|child|under|hierarch"],
        "DISTRICT key DISTID": [r"DISTID"],
        "dataset AIDDB01": [r"AIDDB01"],
    },
}

# Statements the analysis must never make (the code does not do these).
TRAPS = {
    "AIDPAYRN.cbl": [r"(writ|output)\w*.{0,30}(total|trailer).{0,30}PAYMENT-FILE", r"trailer record is written",
                     r"checks? the (open )?status of (ADJUST|PAYMENT)-FILE"],
    "aid_pkg_post_payments.sql": [r"\bcommits\b", r"parameteri[sz]ed (safely|correctly)"],
    "AidPaymentController.cs": [r"records? (who|the approver)", r"\[Authorize\] (is )?(present|applied)", r"parameter (is )?(correctly )?bound"],
    "frmAidCalc.frm": [r"ComputeAid (calculates|computes) the aid (amount|payment)"],
    "AidPaymentPosting.rpg": [r"WKAMT (is )?(written|stored|saved) (to|in) AIDPAY"],
    "AIDINQ.cbl": [r"(moves|receives|reads) the district id (from|into) the map"],
}

PLANTED = ("Planted.py", '''"""Synthetic file for the analysis eval: five deliberate defects."""
import sqlite3

RATE = 0.0725
conn = sqlite3.connect("orders.db")


def order_total(order_id, customer_type):
    discount = 0.1 if customer_type == "gold" else 0.0          # computed but never used
    cur = conn.cursor()
    cur.execute("SELECT qty, price FROM lines WHERE order_id = " + str(order_id))
    total = sum(q * p for q, p in cur.fetchall())
    if total < 0 and total > 1000:                              # can never be true
        total = 1000
    try:
        tax = total * RATE
    except Exception:
        pass                                                    # error swallowed
    return total + tax
''', {
    "unused discount": [r"discount", r"never|not used|unused|ignored"],
    "impossible condition": [r"total < 0 and total > 1000|never be true|impossible|contradict|always false"],
    "swallowed error": [r"except|exception|error", r"pass|swallow|ignor|silent"],
    "SQL injection": [r"order_id", r"concaten|inject|\+ ?str"],
    "hard-coded tax rate": [r"0\.0725|RATE|tax rate", r"hard.?coded|constant|literal|fixed"],
})

CLEAN = ("Clean.py", '''"""Synthetic well-written file for the analysis eval: nothing to report."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Money:
    cents: int

    def add(self, other: "Money") -> "Money":
        return Money(self.cents + other.cents)

    def __str__(self) -> str:
        return f"${self.cents // 100}.{self.cents % 100:02d}"
''')


def _match(groups, facts):
    for f in facts:
        if all(re.search(g, f["statement"], re.I) for g in groups):          # the statement itself, not just the quote
            return f
    return None


def _held(token, res):
    """An expectation on an unreadable line passes when the analysis does not state it as fact (held back or omitted)."""
    stated = [f for f in res["facts"] if token in f["statement"] or token in (f.get("quote") or "")]
    return None if stated else {"lines": [0, 0], "statement": "not stated (line unreadable)"}


def score(name, res):
    exp = EXPECTED.get(name, {})
    found = {k: (_held(g[5:], res) if isinstance(g, str) else _match(g, res["facts"])) for k, g in exp.items()}
    traps = [(t, f) for t in TRAPS.get(name, []) for f in res["facts"] if re.search(t, f["statement"], re.I)]
    return {"found": found, "traps": traps}


def main(only=None):
    from core import analysis, deepdive
    from core.model import ProgramStore
    from test_linker import add
    import anthropic
    import os
    analysis.load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("No ANTHROPIC_API_KEY: run this on the machine that has the key (~/.codesnap/.env).")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=3, timeout=600.0)
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(RUN1, tmp / "live-test-09-29")
    store = ProgramStore.open("live-test-09-29", root=tmp)
    extra = ProgramStore.create("Eval extras", root=tmp)
    for n, code, *_ in (PLANTED, CLEAN):
        add(extra, n, code, "Python", "py")
    targets = [(store, a) for a in store.artifacts() if a["artifact_type"] != "ui_screen"] + \
              [(extra, a) for a in extra.artifacts()]
    if only:
        targets = [(s, a) for s, a in targets if a["name"] in only]
    rows, ok = [], True
    total_exp = total_found = 0
    for st, a in targets:
        print(f"analysing {a['name']} …", flush=True)
        res = deepdive.analyse_file(st, client, a)
        entry = {"name": a["name"], "res": res}
        if a["name"] == PLANTED[0]:
            entry["planted"] = {k: _match(g, res["facts"]) for k, g in PLANTED[2].items()}
            ok &= all(entry["planted"].values())
        elif a["name"] == CLEAN[0]:
            entry["clean_defects"] = [f for f in res["facts"] if f["category"] in ("defect", "security", "data_integrity")
                                      and f.get("severity") in ("high", "medium")]
            ok &= not entry["clean_defects"]
        else:
            sc = score(a["name"], res)
            entry.update(sc)
            total_exp += len(sc["found"])
            total_found += sum(1 for v in sc["found"].values() if v)
            ok &= not sc["traps"]
        rows.append(entry)
    recall = total_found / total_exp if total_exp else 1.0
    ok &= recall >= RECALL_TARGET
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"DEEPDIVE_EVAL_{datetime.now():%Y-%m-%d_%H%M}.md"
    lines = [f"# Line-by-line analysis eval — {datetime.now():%Y-%m-%d %H:%M}", "",
             f"Model: {deepdive.PROMPT_VERSION} on {rows[0]['res']['model'] if rows else '?'}", "",
             f"**Recall: {total_found}/{total_exp} = {recall:.0%}** (target {RECALL_TARGET:.0%}) · "
             f"**{'PASS' if ok else 'FAIL'}**", ""]
    for e in rows:
        r = e["res"]
        lines += [f"## {e['name']}", "", f"Purpose: {r['purpose']}", "",
                  f"{len(r['facts'])} statements kept · {r['rejected']} rejected by the checks · "
                  f"{len(r['unverifiable'])} held back · review: {r['reviewed']}", ""]
        if "found" in e:
            lines += [f"- {'✅' if v else '❌'} {k}" + (f" — L{v['lines'][0]}: {v['statement']}" if v else "") for k, v in e["found"].items()]
            lines += [f"- ⛔ TRAP `{t}` — L{f['lines'][0]}: {f['statement']}" for t, f in e["traps"]]
        if "planted" in e:
            lines += [f"- {'✅' if v else '❌'} planted: {k}" for k, v in e["planted"].items()]
        if "clean_defects" in e:
            lines += [f"- {'✅ no defects claimed' if not e['clean_defects'] else '⛔ claimed defects in a clean file:'}"]
            lines += [f"  - L{f['lines'][0]}: {f['statement']}" for f in e["clean_defects"]]
        lines += ["", "Every statement (check each one against the code):", ""]
        lines += [f"{i}. [{f['category']}{'/' + f['severity'] if f.get('severity') else ''}{', inferred' if f.get('basis') == 'inferred' else ''}] "
                  f"L{f['lines'][0]}–{f['lines'][1]}: {f['statement']}  \n   `{f.get('quote', '')}`" for i, f in enumerate(r["facts"], 1)]
        if r.get("rejected_detail"):
            lines += ["", "Rejected by the checks:", ""] + [f"- {x.get('statement', '')} — {x.get('why')}" for x in r["rejected_detail"]]
        lines.append("")
    out.write_text("\n".join(lines))
    (out.with_suffix(".json")).write_text(json.dumps([{**{k: v for k, v in e.items() if k != "res"}, "res": e["res"]}
                                                      for e in rows], default=str, indent=1))
    print(f"\nRecall {recall:.0%} · {'PASS' if ok else 'FAIL'} · report: {out}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(set(sys.argv[1:]) or None)
