"""M3.5 legacy language packs: structure, formats, validation, security and EOL for older languages."""
from datetime import date
from pathlib import Path

import pytest

from core import langpacks
from core.cobol.parser import parse as parse_cobol
from core.langpacks.formats import detect_format, minimal_clean
from core.security import eol
from core.security.rules import family, scan_text

LP = Path(__file__).resolve().parent / "samples" / "langpacks"
TODAY = date(2026, 9, 26)

# file, pack, units that must exist, relation targets that must exist, legacy marker substring, eol keys
CASES = [
    ("AIDCALC.frm", "vb6", {"cmdCalc_Click", "ComputeAid", "frmAidCalc"},
     {"table:DISTRICT_ADM", "function:ComputeAid", "screen:frmResults", "data_store:SCHOOLFIN"}, "On Error", {"vb6"}),
    ("ImportLevy.bas", "vba", {"ImportLevyFile"}, {"table:LEVY_STAGING", "screen:frmLevyReview"}, "DAO", {"ms-access", "vba"}),
    ("AidService.vb", "vbnet", {"AidService", "btnFind_Click"}, {"table:AIDPAYMENT", "class:System.Web.UI.Page"}, "On Error", {"webforms"}),
    ("aidlookup.asp", "vbscript", {"ShowRow"}, {"table:DISTRICT", "file:inc/dbconn.asp", "screen:login"}, "On Error Resume Next",
     {"vbscript", "classic-asp"}),
    ("AIDPOST.rpgle", "rpg", {"CALCAID"}, {"paragraph:CALCAID", "data_store:DISTMST", "data_store:AIDPAY", "screen:AIDSCR"},
     "fixed-form RPG", {"ibm-i"}),
    ("AIDNIGHT.clle", "cl", {"LOOP"}, {"program:AIDPOST", "program:AIDRPT", "data_store:AIDHIST"}, "MONMSG", {"ibm-i"}),
    ("AIDCALC.nsp", "natural", {"COMPUTE-AID"}, {"program:AIDPOST1", "screen:AIDMAP01", "copybook:AIDLDA01", "data_store:DISTRICT-FILE"},
     "Line-numbered", {"natural-adabas"}),
    ("AIDRPT.pli", "pli", {"ACCUM"}, {"function:ACCUM", "copybook:AIDCOMM", "table:AID_SUMMARY", "data_store:DISTFILE"}, "ON-units", {"pli"}),
    ("AIDEDIT.asm", "asm", {"AIDEDIT", "EDITREC"}, {"program:AIDVAL", "paragraph:EDITREC", "data_store:DISTIN"}, "AMODE 24", {"hlasm"}),
    ("AIDEXTR.rexx", "rexx", {"CHECKAMT"}, {"function:CHECKAMT", "screen:AIDPNL1", "data_store:AIDIN"}, "SIGNAL", {"zos"}),
    ("AIDLIST.clist", "clist", set(), {"program:AIDLIST", "screen:AIDPNL2"}, "GOTO", {"zos"}),
    ("AIDSUMM.ezt", "easytrieve", {"WRITE-SUM", "AIDRPT"}, {"paragraph:WRITE-SUM", "data_store:AIDSUM"}, "report writer", {"easytrieve"}),
    ("aid_forecast.sas", "sas", {"forecast"}, {"data_store:SCHOOLFIN", "function:forecast"}, "LIBNAME", {"sas"}),
    ("aid_pkg.pkb", "plsql", {"POST_PAYMENTS"}, {"table:DISTRICT_ADM", "table:AID_PAYMENT", "table:AID_STAGING", "function:AUDIT_PKG.LOG_EVENT"},
     "EXECUTE IMMEDIATE", {"oracle-database"}),
    ("usp_AidReport.sql", "tsql", {"DBO.USP_AIDREPORT"}, {"table:DBO.AIDPAYMENT", "table:DBO.AUDITLOG", "function:DBO.USP_LOGRUN"},
     "xp_cmdshell", {"mssqlserver"}),
    ("w_aid_entry.srw", "powerbuilder", {"open", "clicked"}, {"screen:w_aid_detail", "table:AID_PAYMENT"}, "SQLCA", {"powerbuilder"}),
    ("aidsearch.cfm", "coldfusion", set(), {"table:DISTRICT_AID", "file:header.cfm", "data_store:schoolfin"}, "cfquery", {"coldfusion"}),
    ("aid_upload.php", "php", {"saveUpload"}, {"table:DISTRICT_AID", "file:config.php", "data_store:mdedb01"}, "mysql_", {"php"}),
    ("aid_feed.pl", "perl", {"build_file"}, {"table:AID_PAYMENT", "module:DBI"}, "Two-argument open", {"perl"}),
    ("aid_nightly.ksh", "shell", {"run_extract"}, {"external_system:sqlplus", "external_system:ftp"}, "FTP", set()),
    ("aid_copy.bat", "batch", {"load", "fail"}, {"paragraph:load", "external_system:sqlcmd"}, "GOTO", set()),
    ("Send-AidReport.ps1", "powershell", {"Get-AidRows"}, {"function:Get-AidRows", "data_store:MDESQL01", "table:AIDPAYMENT"},
     "Invoke-Expression", set()),
    ("aid_merge.py", "python", {"load", "main"}, {"table:ADM_MERGE", "data_store:SCHOOLFIN"}, "Python 2", {"python"}),
    ("aidgrid.js", "javascript", {"loadGrid", "exportGrid"}, {"api_endpoint:/aid/services/AidService.asmx/GetDistrict"}, "Synchronous XHR", set()),
    ("AidMain.pas", "delphi", {"TfrmAidMain"}, {"table:AID_PAYMENT"}, "BDE", {"delphi-bde"}),
    ("AIDPOST.prg", "foxpro", {"CALCADJ"}, {"function:CALCADJ", "screen:LEVYREVIEW", "data_store:LEVYADJ", "table:AID_PAYMENT"},
     "DBF", {"visual-foxpro"}),
    ("aidmaint.4gl", "informix4gl", {"LOAD_DISTRICT", "AID_RPT"}, {"function:LOAD_DISTRICT", "table:DISTRICT_AID", "screen:AIDFORM"},
     "WHENEVER ERROR", {"informix-4gl"}),
    ("aidpost.p", "progress", {"logRun"}, {"program:calcaid", "data_store:district", "copybook:aidcommon.i"}, "Shared", {"progress"}),
    ("ENRPRJ.f", "fortran", {"PROJ"}, {"function:PROJ", "data_store:ENROLL.DAT"}, "COMMON", set()),
    ("LEVYCALC.BAS", "basic", set(), {"paragraph:200", "data_store:LEVY.DAT"}, "GOSUB", {"gwbasic"}),
]

SPECIAL = [
    ("AIDDBD.dbd", "ims_dbd", {"table": {"DISTRICT", "PAYMENT", "ADJUST"}, "column": {"DISTID", "AMOUNT"}},
     {("depends_on", "table:DISTRICT"), ("uses", "data_store:AIDDB01")}, {"ims"}),
    ("AIDPSB.psb", "ims_psb", {"module": {"AIDPSB"}}, {("reads", "table:DISTRICT"), ("writes", "table:PAYMENT"),
                                                         ("uses", "data_store:AIDDBD")}, {"ims"}),
    ("AIDFMT.mfs", "ims_mfs", {"screen": {"AIDFMT"}, "ui_element": {"DISTID", "AMOUNT"}}, {("uses", "transaction:AIDIN")}, {"ims"}),
    ("LoadAid.dtsx", "ssis", {"job": {"LoadAid"}, "function": {"Truncate staging", "Load levy", "Post levy"}},
     {("writes", "table:DBO.LEVY"), ("reads", "table:DBO.LEVYSTAGING"), ("calls", "function:Post levy"),
      ("connects_to", "data_store:SCHOOLFIN")}, {"mssqlserver"}),
    ("aidform_fmb.xml", "oracle_forms", {"screen": {"AIDFORM"}, "ui_element": {"DISTRICT", "DISTRICT.TOTAL_AID"}},
     {("reads", "table:DISTRICT_AID"), ("navigates_to", "screen:LEVYFORM"), ("calls", "program:AIDRPT")}, {"oracle-forms"}),
    ("AIDPNL1.pnl", "ispf_panel", {"screen": {"AIDPNL1"}, "ui_element": {"DISTID", "PERIOD", "ZCMD"}},
     {("navigates_to", "program:AIDINQ")}, {"zos"}),
    ("aidform.per", "informix_form", {"screen": {"AIDFORM"}, "ui_element": {"f000", "f001"}},
     {("reads", "table:DISTRICT_AID"), ("connects_to", "data_store:SCHFIN")}, {"informix-4gl"}),
    ("AidMain.dfm", "dfm", {"screen": {"frmAidMain"}, "ui_element": {"edtDistrict", "qryAid"}},
     {("reads", "table:AID_PAYMENT"), ("reads", "table:DISTRICT")}, {"delphi-bde"}),
    ("AidDashboard.xaml", "xaml", {"screen": {"AidDashboard"}, "ui_element": {"AidGrid", "DistrictBox"}},
     {("navigates_to", "screen:LevyDetail"), ("uses", "class:Mde.Aid.Views.AidDashboard")}, {"silverlight"}),
    ("d_aid_list.srd", "datawindow", {"screen": {"d_aid_list"}, "ui_element": {"district_id", "amount"}},
     {("reads", "table:AID_PAYMENT"), ("writes", "table:AID_PAYMENT")}, {"powerbuilder"}),
]


def _parse(name):
    return langpacks.parse((LP / name).read_text(), name)


def _keys(techs):
    return {t.get("curated") or t.get("product") for t in techs}


@pytest.mark.parametrize("name,pack,units,targets,marker,techs", CASES, ids=[c[0] for c in CASES])
def test_language_pack_structure(name, pack, units, targets, marker, techs):
    out = _parse(name)
    prof = out["file_attrs"]["profile"]
    assert prof["pack"] == pack
    names = {e["name"] for e in out["entities"]}
    assert units <= names, units - names
    got = {r["target"] for r in out["relations"]}
    assert targets <= got, targets - got
    assert any(marker.lower() in m.lower() for m in prof["legacy_markers"]), prof["legacy_markers"]
    assert techs <= _keys(prof["techs"])


@pytest.mark.parametrize("name,sid,ents,rels,techs", SPECIAL, ids=[c[0] for c in SPECIAL])
def test_special_artifacts(name, sid, ents, rels, techs):
    out = _parse(name)
    assert out["file_attrs"]["profile"]["pack"] == sid
    for kind, expected in ents.items():
        have = {e["name"] for e in out["entities"] if e["kind"] == kind}
        assert expected <= have, (kind, expected - have)
    got = {(r["kind"], r["target"]) for r in out["relations"]}
    assert rels <= got, rels - got
    assert techs <= _keys(out["file_attrs"]["profile"]["techs"])


def test_special_detected_without_extension():
    text = (LP / "LoadAid.dtsx").read_text()
    assert langpacks.parse(text, "capture_17")["file_attrs"]["profile"]["pack"] == "ssis"
    assert langpacks.claims((LP / "aidform_fmb.xml").read_text(), "aidform_fmb.xml", "XML", "config")


def test_cobol_idms_and_ims_enrichment():
    idms = (LP / "AIDIDMS.cbl").read_text()
    out = langpacks.enrich_cobol(idms, parse_cobol(idms, "AIDIDMS.cbl"))
    rels = {(r["kind"], r["source"], r["target"]) for r in out["relations"]}
    assert ("reads", "1000-POST", "table:DISTRICT-REC") in rels and ("reads", "1000-POST", "table:PAYMENT-REC") in rels
    assert ("writes", "1000-POST", "table:DISTRICT-REC") in rels and ("writes", "1000-POST", "table:AUDIT-REC") in rels
    assert "IDMS" in out["file_attrs"]["profile"]["frameworks"] and {"idms"} <= _keys(out["file_attrs"]["profile"]["techs"])
    ims = (LP / "AIDIMS.cbl").read_text()
    out = langpacks.enrich_cobol(ims, parse_cobol(ims, "AIDIMS.cbl"))
    rels = {(r["kind"], r["target"]) for r in out["relations"]}
    assert ("reads", "data_store:AID-PCB") in rels and ("writes", "data_store:AID-PCB") in rels
    assert ("reads", "table:PAYMENT") in rels and "IMS DB/DC" in out["file_attrs"]["profile"]["frameworks"]
    plain = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. X.\n       PROCEDURE DIVISION.\n           STOP RUN.\n"
    assert "file_attrs" not in langpacks.enrich_cobol(plain, parse_cobol(plain, "X.cbl"))


@pytest.mark.parametrize("ext,text,expected", [
    ("pl", "#!/usr/bin/perl\nuse strict;\nmy $x = 1;\n", "perl"),
    ("pl", " MAIN: PROC OPTIONS(MAIN);\n DCL X FIXED BIN(31);\n END MAIN;\n", "pli"),
    ("bas", "10 PRINT \"HI\"\n20 GOTO 10\n", "basic"),
    ("bas", "Attribute VB_Name = \"Mod1\"\nPublic Sub X()\nEnd Sub\n", "vb6"),
    ("bas", "Sub X()\n  DoCmd.OpenForm \"f\"\nEnd Sub\n", "vba"),
    ("cmd", "@echo off\ngoto :eof\n", "batch"),
    ("cmd", "PGM\nDCL VAR(&A) TYPE(*CHAR)\nCALL PGM(X)\nENDPGM\n", "cl"),
    ("inc", "<%\nResponse.Write \"x\"\n%>\n", "vbscript"),
])
def test_ambiguous_extensions_use_content(ext, text, expected):
    assert langpacks.pack_for(f"f.{ext}", "", text)["id"] == expected


def test_language_name_and_content_only_detection():
    assert langpacks.pack_for("capture", "Natural")["id"] == "natural"
    assert langpacks.pack_for("capture", "", (LP / "aid_upload.php").read_text())["id"] == "php"
    assert langpacks.pack_for("capture", "", "hello world\nthis is text\n") is None
    assert langpacks.pack_for("Foo.java", "", "class Foo {}") is None


def test_comments_and_strings_do_not_create_structure():
    text = "' Call NotReal\nSub Real()\n    MsgBox \"Call AlsoNotReal\"\nEnd Sub\n"
    out = langpacks.parse(text, "m.frm")
    targets = {r["target"] for r in out["relations"]}
    assert "function:NotReal" not in targets and "function:AlsoNotReal" not in targets


def test_block_checks_catch_unbalanced_code():
    for name in ("AIDCALC.frm", "AIDPOST.rpgle", "AIDCALC.nsp", "AidMain.pas", "AIDSUMM.ezt", "aidmaint.4gl", "AIDPOST.prg"):
        ok, errors, tool = langpacks.check((LP / name).read_text(), name)
        assert ok, (name, errors)
    ok, errors, _ = langpacks.check("Sub A()\n  If x Then\n    y = 1\nEnd Sub\n", "a.frm")
    assert not ok and "If/End If" in errors
    ok, errors, _ = langpacks.check("0010 DEFINE DATA LOCAL\n0020 1 #A (A10)\n0030 IF #A = 'X'\n0040 END\n", "a.nsp")
    assert not ok and ("END-DEFINE" in errors or "END-IF" in errors)


def test_validate_uses_structural_check_for_legacy(tmp_path):
    from core.validate import check_source
    good = tmp_path / "AIDPOST.rpgle"
    good.write_text((LP / "AIDPOST.rpgle").read_text())
    res = check_source(good)
    assert res["checked"] and res["ok"] and "structure" in res["tool"]
    bad = tmp_path / "bad.frm"
    bad.write_text("Sub A()\n  With x\n    .y = 1\nEnd Sub\n")
    res = check_source(bad)
    assert res["checked"] and not res["ok"] and "With" in res["errors"]
    noblocks = tmp_path / "x.asm"
    noblocks.write_text((LP / "AIDEDIT.asm").read_text())
    assert check_source(noblocks)["checked"] is False
    py2 = tmp_path / "old.py"
    py2.write_text((LP / "aid_merge.py").read_text())
    res = check_source(py2)
    assert res["checked"] is False and "Python 2" in res["note"]


def test_fixed_format_preserved():
    rpg = (LP / "AIDPOST.rpgle").read_text()
    assert detect_format(rpg, "", "rpgle") == "rpg_fixed"
    assert minimal_clean(rpg).splitlines()[3][5] == "F"
    nat = (LP / "AIDCALC.nsp").read_text()
    assert detect_format(nat, "Natural", "") == "natural"
    assert minimal_clean(nat).splitlines()[0].startswith("0010 ")
    assert detect_format((LP / "AIDEDIT.asm").read_text()) == "asm"
    assert detect_format((LP / "AIDPNL1.pnl").read_text()) == "ispf_panel"
    assert detect_format((LP / "LEVYCALC.BAS").read_text()) == "basic"
    from core.analysis import _LEGACY_FORMAT_CLAUSE
    assert "actually visible" in _LEGACY_FORMAT_CLAUSE and "line numbers" in _LEGACY_FORMAT_CLAUSE
    assert "Never place text in conventional compiler columns by assumption" in _LEGACY_FORMAT_CLAUSE


SECURITY = [
    ("AIDCALC.frm", {("SEC-SQLI", 27)}), ("AidService.vb", {("SEC-SQLI", 9)}), ("ImportLevy.bas", {("SEC-SQLI", 17)}),
    ("aidlookup.asp", {("SEC-SQLI", 13), ("SEC-XSS", 15)}),
    ("aid_upload.php", {("SEC-CRED", 3), ("SEC-CMD", 8), ("SEC-SQLI", 10), ("SEC-XSS", 14)}),
    ("aid_feed.pl", {("SEC-CRED", 6), ("SEC-SQLI", 10), ("SEC-CMD", 17), ("SEC-TLS", 18)}),
    ("aid_nightly.ksh", {("SEC-CRED", 6), ("SEC-TLS", 14), ("SEC-CMD", 18)}),
    ("aid_copy.bat", {("SEC-CRED", 10)}), ("Send-AidReport.ps1", {("SEC-CRED", 4), ("SEC-CMD", 11)}),
    ("aid_merge.py", {("SEC-SQLI", 18)}), ("aid_pkg.pkb", {("SEC-SQLI", 10)}),
    ("usp_AidReport.sql", {("SEC-SQLI", 8), ("SEC-CMD", 11)}), ("aid_forecast.sas", {("SEC-CRED", 2), ("SEC-CMD", 15)}),
    ("aidsearch.cfm", {("SEC-SQLI", 6), ("SEC-XSS", 9)}), ("AidMain.pas", {("SEC-SQLI", 22)}),
    ("AIDPOST.prg", {("SEC-CRED", 8), ("SEC-SQLI", 9)}), ("w_aid_entry.srw", {("SEC-CRED", 14)}),
    ("AIDEXTR.rexx", {("SEC-CMD", 12)}),
]


@pytest.mark.parametrize("name,expected", SECURITY, ids=[c[0] for c in SECURITY])
def test_legacy_security_rules(name, expected):
    hits = {(h["rule"], h["line"]) for h in scan_text((LP / name).read_text(), name)}
    assert expected <= hits, expected - hits


def test_security_rules_avoid_obvious_false_positives():
    assert not scan_text("Set rs = conn.Execute(strSQL)\n", "a.asp")
    assert not scan_text("DoCmd.RunSQL \"DELETE FROM T\"\n", "m.bas")
    assert not scan_text("' sql = \"SELECT * FROM T WHERE A = \" & x\n", "m.frm")
    assert not scan_text("$r = $pdo->prepare('SELECT * FROM t WHERE id = ?');\n", "a.php")
    assert not scan_text("# system(\"rm $x\")\n", "a.pl", "Perl")
    assert family("aid_feed.pl", "", (LP / "aid_feed.pl").read_text()) == "perl"


def test_eol_for_legacy_technologies():
    data = eol.load_data()
    status = {}
    for key in ("vb6", "visual-foxpro", "angularjs1", "delphi-bde", "gwbasic", "vbscript", "oracle-forms", "ims", "idms"):
        t = {"product": None, "version": None, "curated": key, "label": key, "lines": [], "confidence": "confirmed", "basis": ""}
        status[key] = eol.assess(t, data, TODAY)["status"]
    assert status["vb6"] == status["visual-foxpro"] == status["angularjs1"] == status["delphi-bde"] == "eol"
    assert status["vbscript"] == "legacy" and status["oracle-forms"] == "ending" and status["ims"] == "supported"
    for prod, ver, expect in (("php", "5.6", "eol"), ("python", "2.7", "eol"), ("coldfusion", "2021", "extended"),
                              ("oracle-database", "11.2", "eol"), ("ibm-i", "7.4", "ending"), ("ibm-i", "7.3", "extended"), ("perl", "5.42", "supported")):
        t = {"product": prod, "version": ver, "curated": None, "label": prod, "lines": [], "confidence": "confirmed", "basis": ""}
        assert eol.assess(t, data, TODAY)["status"] == expect, prod
    techs = eol.technologies(_parse("aid_merge.py")["file_attrs"]["profile"])
    assert ("python", "2.7") in {(t["product"], t["version"]) for t in techs}
    hints = eol.technologies({"language": "UI screen", "frameworks": ["Oracle Forms", "5250 green screen", "Crystal Reports 2016"]})
    assert {"oracle-forms", "crystal-reports"} <= {t["curated"] for t in hints} and any(t["product"] == "ibm-i" for t in hints)
    assert all(t["confidence"] == "unconfirmed" for t in hints)
    for p in langpacks.ALL:
        for t in p.get("techs", []):
            assert (t.get("curated") in data["curated"]) or (t.get("product") in data["products"]), (p["id"], t)


MIXED = [("AIDPOST.rpgle", "RPG IV"), ("AIDNIGHT.clle", "CL"), ("AIDCALC.frm", "Visual Basic 6"), ("aidlookup.asp", "VBScript"),
         ("aid_pkg.pkb", "PL/SQL"), ("aid_forecast.sas", "SAS"), ("LoadAid.dtsx", "XML"), ("AIDDBD.dbd", "IMS DBD"),
         ("AIDPSB.psb", "IMS PSB"), ("AIDIDMS.cbl", "COBOL"), ("aid_upload.php", "PHP"), ("aid_merge.py", "Python"),
         ("aidform_fmb.xml", "XML"), ("AIDPNL1.pnl", "ISPF panel"), ("usp_AidReport.sql", "SQL"), ("AidMain.pas", "Delphi")]


def test_mixed_era_program_end_to_end(tmp_path):
    pytest.importorskip("tree_sitter")
    from core.assess import run_assessment
    from core.diagrams.build import all_diagrams, architecture
    from core.model import ProgramStore
    from core.report import html_report
    from test_linker import add
    store = ProgramStore.create("Mixed era", root=tmp_path)
    for name, lang in MIXED:
        ext = name.rsplit(".", 1)[-1]
        add(store, name, (LP / name).read_text(), lang, ext)
    arts = {a["name"]: a for a in store.artifacts()}
    assert all(a["status"] == "structured" for a in arts.values()), {n: a["status"] for n, a in arts.items()}
    result = run_assessment(store, today=TODAY)
    eol_titles = " | ".join(f["title"] for f in store.findings("eol"))
    for name in ("Visual Basic 6.0", "PHP", "Python", "Oracle Forms", "IBM i", "Classic ASP", "VBScript"):
        assert name in eol_titles, (name, eol_titles)
    assert "ActiveX controls (Internet Explorer)" not in eol_titles
    from core.security import run_scan
    inventory = {t["name"] for t in run_scan(store, today=TODAY)["technologies"]}
    assert {"CA IDMS", "IBM IMS (DB/DC)", "SAS 9.x", "Borland Database Engine (BDE)"} <= inventory, inventory
    sec = {(f["rule"], f["evidence"][0]["file"]) for f in store.findings("security")}
    for rule, file in (("SEC-SQLI", "AIDCALC.frm"), ("SEC-SQLI", "aid_pkg.pkb"), ("SEC-CMD", "usp_AidReport.sql"),
                       ("SEC-SQLI", "aid_upload.php"), ("SEC-CRED", "aid_forecast.sas")):
        assert (rule, file) in sec, (rule, file)
    comps = {c["name"]: c for c in result["components"]}
    rpg = comps["AIDPOST.rpgle"]
    assert any(f["rule"] == "SUP-SKILLS" and "RPG" in f["text"] for f in rpg["scores"]["supportability"]["factors"])
    arch = architecture(store)
    titles = {g["title"] for lane in arch.get("lanes", []) for g in lane.get("groups", [])} if arch.get("lanes") else \
        {g.get("title") for g in arch.get("groups", [])}
    blob = str(arch)
    for group in ("IBM i (RPG / CL)", "Visual Basic / VBA", "Stored procedures (PL/SQL / T-SQL)", "Reporting (SAS / Easytrieve)",
                  "Terminal screens (ISPF / IMS)", "Desktop / client-server screens"):
        assert group in blob, (group, titles)
    diagrams = all_diagrams(store)
    assert diagrams and all(d.get("nodes") is not None or d.get("lanes") is not None or d for d in diagrams)
    html = html_report(store, rescan=False, today=TODAY)
    assert "Visual Basic 6.0" in html and "RPG" in html
    store.close()


def test_api_failure_falls_back_to_language_pack(tmp_path):
    from core.model import ProgramStore
    from core.model.ingest import ingest_capture

    class Down:
        @property
        def messages(self):
            raise RuntimeError("api down")

    store = ProgramStore.create("Fallback", root=tmp_path)
    code = (LP / "aid_merge.py").read_text()
    aid = ingest_capture(store, Down(), [], {"is_code": True, "code": code, "extension": "py", "language": "Python",
                                             "errors": "None", "code_name": "aid_merge"})
    assert store.artifact(aid)["status"] == "structured"
    assert any(r["ok"] == 0 and "api down" in (r["error"] or "") for r in store.runs())
    f = next(e for e in store.entities("file") if e["artifact_id"] == aid)
    assert f["attrs"]["profile"]["pack"] == "python"
    assert store.entity_by_key("function:aid_merge.load") is not None
    store.close()


def test_pli_select_closing_end_is_valid():
    from core.langpacks import check
    text = "MAIN: PROC;\n SELECT(VALUE);\n WHEN('A') CALL WORK;\n OTHERWISE;\n END;\n END MAIN;"
    result = check(text, 'main.pli', 'PL/I')
    assert result[0], result
