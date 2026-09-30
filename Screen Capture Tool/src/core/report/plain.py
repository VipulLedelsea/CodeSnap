"""Plain-English wording for the report: every technical finding keeps its technical name and gains a sentence a
non-specialist can follow — what it is, why it matters, and what to do."""
import re

# rule -> (what it is, why it matters, what to do). {x} is filled with the component or library when known.
RULES = {
    "SEC-CRED": ("a password or key is written directly into the code (hard-coded credential)",
                 "anyone who can read the code can use it, and it can't be changed without a code release",
                 "move it to a secure secrets store and change the password"),
    "SEC-TLS": ("data is sent without encryption (plain HTTP or an unencrypted database connection)",
                "it can be read or changed on the network", "require TLS 1.2 or later on the connection (HTTPS, Encrypt=True)"),
    "SEC-ERR": ("errors are silently ignored, so a failed step looks like success",
                "failures such as a payment that did not post go unnoticed and are not logged",
                "log and raise every error; stop the run and alert support when a step fails"),
    "SEC-AUTHZ": ("an action that changes data has no authorization check",
                  "any signed-in or anonymous caller could run it, for example to approve a payment",
                  "require a named role for the action and record who performed it"),
    "SEC-CSRF": ("a form post is not protected against cross-site request forgery (CSRF)",
                 "another web page could make a signed-in user's browser submit it without their knowledge",
                 "add an anti-forgery token and validate it on every post"),
    "SEC-XSS": ("user input is written into the web page without being made safe (cross-site scripting, XSS)",
                "an attacker could run their own script in a user's browser",
                "encode everything written to the page; avoid innerHTML and document.write"),
    "SEC-SQLI": ("database queries are built by joining text together (SQL injection risk)",
                 "crafted input could read or change data it shouldn't", "use parameterised queries"),
    "SEC-SQLDYN": ("database queries are assembled at run time (dynamic SQL)",
                   "if user input reaches them, data could be read or changed", "use parameterised or static queries"),
    "SEC-CMD": ("an operating-system command is built from input (command injection risk)",
                "crafted input could run other commands on the server", "pass arguments separately; validate input"),
    "SEC-PATH": ("a file path is taken from user input (path traversal risk)",
                 "users could open files they shouldn't", "only allow known file names"),
    "SEC-DESER": ("untrusted data is turned back into program objects (unsafe deserialisation)",
                  "crafted data can run code on the server", "use a safe data format such as JSON"),
    "SEC-CRYPTO": ("weak or outdated encryption is used (e.g. MD5, DES)",
                   "protected data can be decoded", "move to current algorithms (AES, SHA-256 or better)"),
    "SEC-AUTH": ("sign-in is weak or missing", "people could use the application without proving who they are",
                 "use the organisation's single sign-on or strong passwords with MFA"),
    "SEC-CONF": ("the configuration exposes internal details or is insecure",
                 "error messages or settings help an attacker", "turn off detailed errors; harden the settings"),
    "SEC-MEM": ("the code uses unsafe memory functions (buffer overflow risk)",
                "bad input can crash the program or take it over", "use bounded, safe functions"),
    "SEC-PII": ("the application handles personal data", "it falls under privacy law and needs extra protection",
                "restrict access, encrypt it and log who sees it"),
    "SEC-FERPA": ("a serious security issue sits in code that handles personal data",
                  "a breach would expose personal records and trigger notification duties",
                  "fix these issues first"),
    "CVE": ("a published security weakness (CVE) exists in {x}", "attackers know about it and fixes exist",
            "upgrade to a fixed version"),
    "WEB-CVE": ("a published security weakness (CVE) exists in {x}", "attackers know about it", "upgrade it"),
    "EOL": ("{x} is past the vendor's end of support (end of life)", "it no longer receives security fixes",
            "upgrade or replace it"),
    "SUP-EOL": ("{x} is past the vendor's end of support (end of life)", "it no longer receives security fixes",
                "upgrade or replace it"),
    "WEB-EOL": ("{x} on the website is past end of support", "it no longer receives security fixes", "upgrade it"),
    "SUP-SKILLS": ("few people still have the skills to maintain this technology",
                   "support depends on a small, shrinking pool of staff or vendors",
                   "document the code and cross-train, or plan a move to a more common platform"),
    "UIS-GET": ("sensitive data such as a password is sent in the web address (GET request)",
                "web addresses are stored in browser history and server logs", "send it in the request body (POST)"),
    "UIS-PWFIELD": ("the password box shows the password as it is typed", "anyone nearby can read it",
                    "use a masked password field"),
    "UIS-PW": ("a password is shown or pre-filled on screen", "anyone who sees the screen can read it",
               "never display or pre-fill passwords"),
    "UIS-MIXED": ("part of the page is loaded over unencrypted HTTP (mixed content)",
                  "that part can be tampered with on the network", "load everything over HTTPS"),
    "UIS-CSRF": ("forms have no protection against forged requests (CSRF)",
                 "another site could submit the form on a signed-in user's behalf", "add anti-forgery tokens"),
    "UIS-HIDDEN": ("important values are kept in hidden form fields", "users can change them before sending",
                   "keep trusted values on the server"),
    "UIS-PII": ("personal data is shown in full on screen", "it can be seen by anyone nearby", "mask it"),
    "UIS-BLANK": ("links open new windows without protection (target=_blank)", "the new page can control the old one",
                  "add rel=noopener"),
    "WEB-HTTPS": ("the website does not force HTTPS", "traffic can be read or changed", "redirect all traffic to HTTPS"),
    "WEB-TLS": ("the website allows old encryption versions", "connections can be downgraded",
                "allow TLS 1.2 and 1.3 only"),
    "WEB-CERT": ("the website's certificate has a problem", "users see warnings or can be impersonated",
                 "renew or fix the certificate"),
    "WEB-HSTS": ("the website does not tell browsers to always use HTTPS (HSTS)", "first visits can be intercepted",
                 "add the HSTS header"),
    "WEB-CSP": ("the website has no content security policy (CSP)", "injected script is not blocked",
                "add a content security policy"),
    "WEB-COOKIE": ("cookies are missing security flags", "session cookies can be stolen",
                   "set Secure, HttpOnly and SameSite"),
    "WEB-FRAME": ("the site can be embedded in other sites (clickjacking)", "users can be tricked into clicks",
                  "send X-Frame-Options or a frame-ancestors policy"),
    "WEB-DISCLOSURE": ("the server reveals its software versions", "it helps attackers target known weaknesses",
                       "hide version headers"),
    "WEB-XCTO": ("a browser safety header is missing (X-Content-Type-Options)", "files can be misread as script",
                 "add the header"),
    "WEB-REFERRER": ("the referrer policy is not set", "page addresses can leak to other sites",
                     "set a referrer policy"),
    "ACC-ALT": ("an image has no text description", "screen-reader users can't tell what it is",
                "add alt text"),
    "ACC-LABEL": ("a form field has no label that a screen reader can announce",
                  "blind users can't tell what to type", "link each field to its label"),
    "ACC-CONTRAST": ("text is too faint against its background", "it is hard to read, especially for low vision",
                     "raise contrast to at least 4.5:1"),
    "ACC-LINK": ("link text such as 'click here' doesn't say where it goes", "screen-reader users lose context",
                 "use descriptive link text"),
    "ACC-TABLE": ("a data table has no header cells", "screen readers can't say which column a value is in",
                  "mark header cells"),
    "ACC-LANG": ("the page doesn't declare its language", "screen readers may read it with the wrong voice",
                 "set the page language"),
    "ACC-HEADINGS": ("the page has no headings", "keyboard and screen-reader users can't jump between sections",
                     "add headings"),
    "ACC-TITLE": ("the page has no title", "users can't tell tabs apart", "add a page title"),
    "ACC-DEPRECATED": ("the page uses obsolete HTML formatting tags", "it breaks in modern browsers and assistive tools",
                       "move styling to CSS"),
    "ACC-TEXTSIZE": ("text is very small", "it is hard to read", "use at least 12–14 px text that can be enlarged"),
    "ACC-COLOR": ("meaning is shown by colour alone (e.g. red text)", "colour-blind users miss it",
                  "add a word or symbol as well as the colour"),
    "ACC-TERMINAL": ("the screen is a mainframe (3270) terminal", "terminals can't meet web accessibility standards",
                     "put an accessible web front end over it"),
    "ACC-KEYBOARD": ("parts of the page can't be used with the keyboard alone", "keyboard users are blocked",
                     "make every control reachable by keyboard"),
    "ACC-ZOOM": ("the page blocks zooming", "low-vision users can't enlarge it", "allow zoom"),
    "UIB-OBSOLETE": ("the screen says it needs an outdated browser", "it may break in current browsers",
                     "test and fix it in current browsers"),
    "UIB-CRASH": ("the screen shows a system error to users", "users are stuck and data may be lost",
                  "find the cause and show a friendly, logged error"),
    "UIB-ERR": ("the screen shows an unclear error", "users don't know what to do", "write clear error messages"),
    "UIB-ERROR": ("the screen shows an unclear error", "users don't know what to do", "write clear error messages"),
    "UIB-OBSERVED": ("a usability problem is visible on the screen", "it slows users down or causes mistakes",
                     "address it in the redesign"),
    "USE-CODES": ("the screen uses cryptic codes instead of words", "new users need training to understand it",
                  "show descriptions next to codes"),
    "USE-ERR": ("error messages are unclear", "users can't fix their own mistakes", "write clear messages"),
    "USE-VALIDATION": ("input is not checked as it is typed", "mistakes are found late", "validate fields on entry"),
    "USE-CONFIRM": ("important actions have no confirmation step", "mistakes are easy to make", "add a confirmation"),
    "USE-BUTTON": ("buttons are unclear", "users hesitate or pick the wrong one", "label buttons by what they do"),
    "USE-LONGFORM": ("the form is very long", "entry is slow and error-prone", "split it into steps"),
    "DEBT-LEGACY": ("an outdated library or language feature is still in use", "it makes changes riskier and blocks upgrades",
                    "upgrade or replace it"),
    "DEBT-GOTO": ("the code jumps around with GO TO statements", "the logic is hard to follow and change safely",
                  "restructure into clear routines"),
    "DEBT-LONG": ("some routines are very long", "they are hard to understand and test", "split them up"),
    "DEBT-SIZE": ("the file is very large", "changes in one place can break another", "split it into modules"),
    "DEBT-TRANSLATED": ("the code was machine-translated from COBOL", "it keeps COBOL habits that make it hard to maintain",
                        "refactor it into normal code for its language"),
    "DEBT-PRESTD": ("the code uses a pre-standard dialect of its language", "modern compilers won't build it",
                    "port it to the current standard"),
    "HLT-GAPS": ("it calls programs that were not provided for this review", "their behaviour and risks are unknown",
                 "provide those programs"),
    "HLT-UNCHECKED": ("no compiler for this language was available to confirm the file compiles",
                      "small errors could go unnoticed", "compile it in its own environment"),
    "HLT-SYNTAX": ("the file does not compile as provided", "it may be incomplete or out of date",
                   "confirm it against the production version"),
    "HLT-FAILED": ("the file could not be read", "it is not covered by this review", "provide it again"),
    "HLT-FRAGILE": ("the code has an error-prone pattern", "it can fail at run time", "fix the pattern"),
    "CPX-DECISIONS": ("routines contain many decision points (high complexity)", "they are hard to test and change",
                      "simplify or split them"),
    "CPX-DENSITY": ("the logic is densely packed", "it is hard to read", "simplify it"),
    "CPX-SIZE": ("the file has a lot of code in one place", "it is hard to work on", "split it up"),
    "CPX-UNITS": ("the file has very many routines", "it is hard to find your way around", "group them into modules"),
    "CPL-FANOUT": ("it depends on many other parts", "changes elsewhere can break it", "reduce dependencies"),
    "CPL-FANIN": ("many other parts depend on it", "a change here ripples widely", "put a stable interface in front of it"),
    "CPL-SHARED": ("it writes to tables other programs also write", "one program can overwrite another's data",
                   "give each table a single owner"),
    "CPL-EXTERNAL": ("it connects directly to outside systems or data stores", "each connection must be moved in any change",
                     "put the connections behind one interface"),
}

TERMS = {
    "CVE": "Common Vulnerabilities and Exposures: the public list of known security weaknesses in software.",
    "CWE": "Common Weakness Enumeration: the standard catalogue of kinds of software weakness.",
    "CVSS": "Common Vulnerability Scoring System: a 0–10 severity score for a known weakness.",
    "XSS": "Cross-site scripting: an attacker's script runs in a user's browser through a vulnerable page.",
    "SQL injection": "Crafted input changes a database query so it reads or alters data it shouldn't.",
    "TLS": "Transport Layer Security: the encryption behind HTTPS.",
    "HTTPS": "The encrypted version of HTTP, the protocol web pages use.",
    "End of life": "The vendor has stopped releasing fixes, including security fixes.",
    "WCAG": "Web Content Accessibility Guidelines: the international standard for accessible web content (2.1 AA is the usual target).",
    "Section 508": "The US federal requirement that technology be accessible to people with disabilities.",
    "NIST SP 800-53": "The US government catalogue of security and privacy controls.",
    "COBOL": "A business programming language from 1959, still widely used on mainframes.",
    "JCL": "Job Control Language: the scripts that run batch jobs on IBM mainframes.",
    "CICS": "IBM's mainframe system for online (screen-based) transactions.",
    "IMS": "IBM's hierarchical mainframe database and transaction manager.",
    "DBD": "Database description: the definition of an IMS database's structure.",
    "RPG": "A business programming language for IBM i (AS/400) midrange systems.",
    "IBM i": "IBM's midrange operating system (formerly AS/400).",
    "3270": "The IBM mainframe terminal ('green screen') format.",
    "copybook": "A shared COBOL file of record layouts included by several programs.",
    "jQuery": "A widely used JavaScript library for web pages.",
    "PL/SQL": "Oracle's programming language for database procedures.",
    "VB6": "Visual Basic 6, a Microsoft desktop programming language whose support ended in 2008.",
    "Technical debt": "Shortcuts and outdated code that make every future change slower and riskier.",
    "Cyclomatic complexity": "The number of independent paths through a routine; higher means harder to test.",
    "Re-platform": "Move to supported versions of the platform with limited code change.",
    "Refactor": "Restructure the code without changing what it does.",
    "Re-host": "Move to new infrastructure or cloud without changing the code.",
    "Personal data": "Information that identifies a person (names, identifiers, contact details).",
    "Hard-coded credential": "A password or key written into the code itself.",
    "MFA": "Multi-factor authentication: signing in with a second proof such as a phone code.",
    "Mixed content": "An HTTPS page that loads some parts over unencrypted HTTP.",
    "CSRF": "Cross-site request forgery: another site submits a form on a signed-in user's behalf.",
}

DISPOSITIONS = {
    "retain": "Keep the application as it is, with routine maintenance only.",
    "rehost": "Move it to supported infrastructure or cloud with little or no code change.",
    "replatform": "Upgrade the out-of-date parts to supported versions, changing code only where needed.",
    "refactor": "Keep the platform, fix the security issues and restructure the weakest code.",
    "rearchitect": "Rebuild it on a modern, supported technology stack.",
    "replace": "Replace the custom code with a commercial or shared product.",
    "retire": "Switch it off and move any remaining function elsewhere.",
}

LEVEL = {1: "Excellent", 2: "Good", 3: "Fair", 4: "Poor", 5: "Critical"}


def _subject(text: str) -> str:
    m = re.search(r"\bin ([A-Za-z][\w .\-/]*?\d[\w.\-]*)", text)            # "CVE-2012-6708 in jQuery 1.4.2"
    if m:
        return m.group(1)
    m = re.match(r"([^:]+): end of life", text)
    if m:
        return m.group(1)
    return ""


def what(rule: str, text: str = "") -> str:
    """The plain-English description of one finding or deduction."""
    r = RULES.get(rule) or RULES.get((rule or "").split(":")[0])
    if not r:
        t = re.sub(r"^Observed usability problem — ", "", text or "")
        return t[:1].lower() + t[1:] if t else "an issue was found"
    s = r[0].replace("{x}", _subject(text) or "a component")
    if rule == "UIB-OBSERVED" and "—" in (text or ""):
        s = text.split("—", 1)[1].strip()
        s = s[:1].lower() + s[1:]
    return s


def why(rule: str) -> str:
    r = RULES.get(rule) or RULES.get((rule or "").split(":")[0])
    return r[1] if r else ""


def fix(rule: str) -> str:
    r = RULES.get(rule) or RULES.get((rule or "").split(":")[0])
    return r[2] if r else ""


def reasons(factors, n=3) -> list:
    """Deductions grouped by kind, largest first: 'a password is written into the code (1 place, −25 points)'."""
    groups = {}
    for f in factors or []:
        key = f["rule"] if f["rule"] not in ("UIB-OBSERVED",) else f["text"]
        g = groups.setdefault(key, {"rule": f["rule"], "text": f["text"], "pts": 0.0, "n": 0})
        g["pts"] += f["points"]
        g["n"] += 1
    out = []
    for g in sorted(groups.values(), key=lambda g: g["pts"])[:n]:
        where = f"{g['n']} places, " if g["n"] > 1 else ""
        out.append(f"{what(g['rule'], g['text'])} ({where}−{abs(g['pts']):g} points)")
    rest = sorted(groups.values(), key=lambda g: g["pts"])[n:]
    if rest:
        out.append(f"{len(rest)} smaller issue(s) (−{abs(sum(g['pts'] for g in rest)):g} points)")
    return out


def weight_word(pts) -> str:
    pts = abs(pts)
    return "major" if pts >= 30 else "significant" if pts >= 12 else "moderate" if pts >= 5 else "minor"


def reasons_words(factors, n=3) -> list:
    """Like reasons(), with the size of each deduction in words (major, significant, moderate, minor)."""
    groups = {}
    for f in factors or []:
        key = f["rule"] if f["rule"] not in ("UIB-OBSERVED",) else f["text"]
        g = groups.setdefault(key, {"rule": f["rule"], "text": f["text"], "pts": 0.0, "n": 0})
        g["pts"] += f["points"]
        g["n"] += 1
    out = []
    for g in sorted(groups.values(), key=lambda g: g["pts"])[:n]:
        where = f"{g['n']} places, " if g["n"] > 1 else ""
        out.append(f"{what(g['rule'], g['text'])} ({where}{weight_word(g['pts'])})")
    rest = sorted(groups.values(), key=lambda g: g["pts"])[n:]
    if rest:
        out.append(f"{len(rest)} smaller issue(s)")
    return out


def sentence(items) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    sep = "; " if any("," in i for i in items) else ", "
    return sep.join(items[:-1]) + ("; and " if sep == "; " else " and ") + items[-1]


def glossary(text: str) -> list:
    """The glossary entries for the terms that actually appear in the report."""
    out = []
    for term, meaning in TERMS.items():
        if re.search(r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])", text, re.I if term[0].islower() or " " in term else 0):
            out.append((term, meaning))
    return sorted(out, key=lambda t: t[0].lower())
