"""Taint tracing: request data followed to a query, a path, a command or the page, in several languages, with the safe forms left alone."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from core.security import taint  # noqa: E402


def rules(text, fam):
    return sorted({r for r, _, _, _ in taint.flows(text, fam)})


def test_python_request_data_in_a_query_a_path_and_a_command_is_found_and_the_safe_forms_are_not():
    bad = ('@app.route("/f/<name>")\n'
           'def show(name):\n'
           '    term = request.args.get("q", "")\n'
           '    sql = "SELECT * FROM t WHERE d LIKE \'%" + term + "%\'"\n'
           '    rows = db.execute(sql).fetchall()\n'
           '    path = os.path.join(BASE, name)\n'
           '    return send_file(path)\n'
           'def run():\n'
           '    host = request.form["h"]\n'
           '    os.system("ping " + host)\n')
    assert rules(bad, "python") == ["SEC-CMD", "SEC-PATH", "SEC-SQLI"]
    good = ('def show():\n'
            '    term = request.args.get("q", "")\n'
            '    rows = db.execute("SELECT * FROM t WHERE d LIKE ?", ("%" + term + "%",)).fetchall()\n'
            '    page = int(request.args.get("page", 1))\n'
            '    rows = db.execute("SELECT * FROM t LIMIT 25 OFFSET " + str(page))\n'
            '    name = secure_filename(request.args.get("n"))\n'
            '    return send_file(os.path.join(BASE, name))\n'
            '    other = helper(request.args.get("x"))\n'
            '    return send_file(other)\n')
    assert rules(good, "python") == []


def test_javascript_server_data_written_as_html_is_found_and_text_content_is_not():
    bad = 'async function f() {\n  const rows = await res.json();\n  rows.forEach(function (p) {\n    li.innerHTML = "<b>" + p.description + "</b>";\n  });\n}\n'
    assert rules(bad, "js") == ["SEC-XSS"]
    good = 'async function f() {\n  const rows = await res.json();\n  rows.forEach(function (p) {\n    li.textContent = p.description;\n  });\n  list.innerHTML = "";\n}\n'
    assert rules(good, "js") == []


def test_php_java_and_csharp_sources_reach_their_sinks():
    assert rules('<?php\n$id = $_GET["id"];\n$r = mysqli_query($c, "SELECT * FROM t WHERE id = " . $id);\n', "php") == ["SEC-SQLI"]
    assert rules('void f(HttpServletRequest request) {\n  String n = request.getParameter("n");\n  File f = new File("/data/" + n);\n}\n', "java") == ["SEC-PATH"]
    assert rules('void F() {\n  var n = Request.QueryString["n"];\n  var c = new SqlCommand("SELECT * FROM t WHERE n = \'" + n + "\'", conn);\n}\n', "cs") == ["SEC-SQLI"]


def test_a_function_that_passes_its_parameter_to_a_sink_is_remembered_across_files():
    class S:
        def artifacts(self):
            return [{"id": 1, "name": "db.py", "language": "Python", "transcription": 'def find(term):\n    sql = "SELECT * FROM t WHERE d = \'" + term + "\'"\n    return conn.execute(sql)\n'},
                    {"id": 2, "name": "web.py", "language": "Python", "transcription": 'def view():\n    q = request.args.get("q")\n    return find(q)\n'}]
    out = taint.conflicts(S())
    assert len(out) == 1 and "find()" in out[0]["title"] and out[0]["files"] == ["db.py", "web.py"]
