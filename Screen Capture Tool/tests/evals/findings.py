"""Seeded-vulnerability eval: insert a known-vulnerable line and its safe counterpart into real host files, scan both."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
S = HERE.parent / "samples"

# host, rule, vulnerable line(s), safe line(s)
CASES = [
    ("legacy/AidPaymentController.cs", "SEC-SQLI", 'var cmd = new SqlCommand("SELECT * FROM dbo.Pay WHERE Id = " + id, conn);',
     'var cmd = new SqlCommand("SELECT * FROM dbo.Pay WHERE Id = @id", conn);'),
    ("legacy/AidPaymentController.cs", "SEC-CRED", 'string password = "Spring2011!";', 'string password = Environment.GetEnvironmentVariable("PW");'),
    ("legacy/AidPaymentController.cs", "SEC-XSS", 'Response.Write(Request.QueryString["name"]);', 'Response.Write(HttpUtility.HtmlEncode(name));'),
    ("legacy/AidPaymentController.cs", "SEC-DESER", 'var f = new BinaryFormatter();', 'var f = new DataContractSerializer(typeof(Pay));'),
    ("legacy/AidPaymentController.cs", "SEC-CRYPTO", 'var h = MD5.Create();', 'var h = SHA256.Create();'),
    ("legacy/AidPaymentController.cs", "SEC-CMD", 'Process.Start("cmd.exe", "/c " + userArg);', 'Process.Start("report.exe");'),
    ("legacy/AidLookupServlet.java", "SEC-SQLI", 'Statement st = conn.createStatement(); st.executeQuery("SELECT * FROM T WHERE ID = " + id);',
     'PreparedStatement st = conn.prepareStatement("SELECT * FROM T WHERE ID = ?");'),
    ("legacy/AidLookupServlet.java", "SEC-XSS", 'out.println(request.getParameter("q"));', 'out.println(Encode.forHtml(q));'),
    ("legacy/AidLookupServlet.java", "SEC-DESER", 'Object o = new ObjectInputStream(in).readObject();', 'Object o = mapper.readValue(in, Pay.class);'),
    ("legacy/AidLookupServlet.java", "SEC-CRYPTO", 'MessageDigest md = MessageDigest.getInstance("MD5");', 'MessageDigest md = MessageDigest.getInstance("SHA-256");'),
    ("legacy/AidLookupServlet.java", "SEC-CMD", 'Runtime.getRuntime().exec("sh -c " + cmd);', 'new ProcessBuilder("report.sh").start();'),
    ("legacy/AIDRPT.CPP", "SEC-MEM", '    gets(buffer);', '    fgets(buffer, sizeof(buffer), stdin);'),
    ("legacy/AIDRPT.CPP", "SEC-MEM", '    strcpy(name, input);', '    strncpy(name, input, sizeof(name) - 1);'),
    ("legacy/AIDRPT.CPP", "SEC-CMD", '    system(cmdline);', '    printf("%s", cmdline);'),
    ("langpacks/AIDCALC.frm", "SEC-SQLI", '    sql = "DELETE FROM PAY WHERE ID = " & txtId.Text',
     '    cmd.Parameters.Append cmd.CreateParameter("id", adInteger, adParamInput, , txtId.Text)'),
    ("langpacks/AIDCALC.frm", "SEC-CMD", '    Shell "cmd /c copy " & txtFile.Text', '    Shell "C:\\AID\\REPORT.EXE"'),
    ("langpacks/aidlookup.asp", "SEC-XSS", 'Response.Write "<b>" & Request.Form("name") & "</b>"', 'Response.Write "<b>" & Server.HTMLEncode(name) & "</b>"'),
    ("langpacks/aidlookup.asp", "SEC-SQLI", 'strSQL = "SELECT * FROM PAY WHERE ID = " & Request("id")', 'cmd.Parameters.Append cmd.CreateParameter("id", 3, 1, , id)'),
    ("langpacks/aid_upload.php", "SEC-SQLI", '$r = mysql_query("SELECT * FROM pay WHERE id = " . $_GET["id"]);',
     '$st = $pdo->prepare("SELECT * FROM pay WHERE id = ?");'),
    ("langpacks/aid_upload.php", "SEC-PATH", 'include($_GET["page"] . ".php");', 'include("pages/home.php");'),
    ("langpacks/aid_upload.php", "SEC-CMD", 'exec("convert " . $name);', 'exec("convert /var/aid/fixed.pdf");'),
    ("langpacks/aid_upload.php", "SEC-XSS", 'echo $_POST["comment"];', 'echo htmlspecialchars($comment);'),
    ("langpacks/aid_feed.pl", "SEC-SQLI", 'my $s = $dbh->prepare("SELECT * FROM pay WHERE id = $id");', 'my $s = $dbh->prepare("SELECT * FROM pay WHERE id = ?");'),
    ("langpacks/aid_feed.pl", "SEC-CMD", 'system("rm -f $file");', 'system("rm", "-f", $file);'),
    ("langpacks/aid_nightly.ksh", "SEC-CRED", 'sqlplus scott/tiger123@PROD @x.sql', 'sqlplus /@PROD @x.sql'),
    ("langpacks/aid_nightly.ksh", "SEC-CMD", 'eval "$USER_CMD"', 'echo "$USER_CMD"'),
    ("langpacks/aid_copy.bat", "SEC-CRED", 'net use Y: \\\\srv\\share Pass123 /user:MDE\\svc', 'net use Y: \\\\srv\\share'),
    ("langpacks/Send-AidReport.ps1", "SEC-CMD", 'Invoke-Expression $cmd', '& $scriptPath'),
    ("langpacks/aid_merge.py", "SEC-SQLI", '        cur.execute("DELETE FROM T WHERE ID = %s" % r[0])', '        cur.execute("DELETE FROM T WHERE ID = ?", r[0])'),
    ("langpacks/aid_merge.py", "SEC-DESER", '    data = pickle.loads(blob)', '    data = json.loads(blob)'),
    ("langpacks/aid_pkg.pkb", "SEC-SQLI", "    EXECUTE IMMEDIATE 'DELETE FROM t WHERE id = ' || p_id;",
     "    EXECUTE IMMEDIATE 'DELETE FROM t WHERE id = :1' USING p_id;"),
    ("langpacks/usp_AidReport.sql", "SEC-SQLI", "    EXEC('SELECT * FROM dbo.T WHERE Id = ' + @Id)",
     "    EXEC sp_executesql N'SELECT * FROM dbo.T WHERE Id = @Id', N'@Id int', @Id"),
    ("langpacks/usp_AidReport.sql", "SEC-CMD", "    EXEC xp_cmdshell 'dir'", "    EXEC dbo.usp_List"),
    ("langpacks/aid_forecast.sas", "SEC-CRED", "LIBNAME db ORACLE user=sas password=Oracle01 path=PROD;", "LIBNAME db ORACLE authdomain=OraAuth path=PROD;"),
    ("langpacks/aidsearch.cfm", "SEC-SQLI", "  WHERE id = #form.id#", '  WHERE id = <cfqueryparam value="#form.id#" cfsqltype="cf_sql_integer">'),
    ("langpacks/AidMain.pas", "SEC-SQLI", "  qryAid.SQL.Add('DELETE FROM PAY WHERE ID = ' + edtId.Text);", "  qryAid.SQL.Add('DELETE FROM PAY WHERE ID = :ID');"),
    ("langpacks/AIDPOST.prg", "SEC-SQLI", 'lcSql = "DELETE FROM PAY WHERE ID = " + lcId', 'lcSql = "DELETE FROM PAY WHERE ID = ?lcId"'),
    ("langpacks/w_aid_entry.srw", "SEC-CRED", 'SQLCA.LogPass = "admin99"', 'SQLCA.LogPass = ProfileString("app.ini", "db", "pw", "")'),
    ("cobol/AIDCALC.cbl", "SEC-CRED", "       01  WS-PASSWORD            PIC X(8) VALUE 'SECRET01'.",
     "       01  WS-PASSWORD            PIC X(8) VALUE SPACES."),
    ("cobol/AIDINQ.cbl", "SEC-SQLDYN", "           EXEC SQL EXECUTE IMMEDIATE :WS-STMT END-EXEC",
     "           EXEC SQL SELECT 1 INTO :WS-X FROM SYSIBM.SYSDUMMY1 END-EXEC"),
    ("legacy/web.config", "SEC-CONF", '    <compilation debug="true" />', '    <compilation debug="false" />'),
    ("legacy/web.config", "SEC-AUTH", '    <authentication mode="None" />', '    <authentication mode="Windows" />'),
]


def _insert(host_text, snippet, host):
    lines = host_text.splitlines()
    at = max(1, len(lines) // 2)
    if host.endswith((".cbl", ".cpy")):
        for i, l in enumerate(lines):
            if ("WORKING-STORAGE" in l and "PASSWORD" in snippet) or ("PROCEDURE DIVISION" in l and "PASSWORD" not in snippet):
                at = i + 1
                if "PROCEDURE" in l:
                    at = i + 2
                break
    if host.endswith(".config"):
        at = next((i + 1 for i, l in enumerate(lines) if "<system.web" in l), at)
    return "\n".join(lines[:at] + snippet.splitlines() + lines[at:]) + "\n", at + 1


def run():
    from core.security.rules import scan_text
    rows = []
    for host, rule, bad, good in CASES:
        base = (S / host).read_text()
        name = Path(host).name
        before = {(h["rule"], h["line"]) for h in scan_text(base, name)}
        vuln, line = _insert(base, bad, host)
        safe, _ = _insert(base, good, host)
        hits_v = {h["rule"] for h in scan_text(vuln, name) if h["line"] == line}
        hits_s = {h["rule"] for h in scan_text(safe, name) if h["line"] == line}
        rows.append({"host": host, "rule": rule, "detected": rule in hits_v, "false_positive": bool(hits_s),
                     "safe_hits": sorted(hits_s), "baseline_findings": len(before)})
    tp = sum(r["detected"] for r in rows)
    fp = sum(r["false_positive"] for r in rows)
    by_rule = {}
    for r in rows:
        b = by_rule.setdefault(r["rule"], [0, 0, 0])
        b[0] += r["detected"]
        b[1] += 1
        b[2] += r["false_positive"]
    return {"cases": len(rows), "detection_rate": round(tp / len(rows), 3), "safe_variant_fp_rate": round(fp / len(rows), 3),
            "by_rule": {k: {"detected": f"{v[0]}/{v[1]}", "fp": v[2]} for k, v in sorted(by_rule.items())},
            "misses": [f'{r["rule"]} in {r["host"]}' for r in rows if not r["detected"]],
            "false_positives": [f'{r["safe_hits"]} on safe variant in {r["host"]}' for r in rows if r["false_positive"]]}


if __name__ == "__main__":
    import json, sys
    sys.path.insert(0, str(HERE.parent.parent / "src"))
    print(json.dumps(run(), indent=1))
