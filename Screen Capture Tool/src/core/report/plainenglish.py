import re

DROP = (
    r"Full wording and tables are in the supporting detail appendix\.?",
    r"Full tables are in the supporting detail appendix\.?",
    r"Key entries shown\.?",
    r"Findings are tied to current reviewed text\.?",
    r"Each component's full review and line references are in the supporting detail appendix\.?",
)

REWRITES = (
    (r"Scores in this report are measured on a 0 to 100 scale \(100 = best\) from itemised deductions and converted to the condition scale below: 90 or more is 1 – Excellent, 75 to 89 is 2 – Good, 55 to 74 is 3 – Fair, 35 to 54 is 4 – Poor, and below 35 is 5 – Critical\.?",
     "Scores run from 0 to 100, and 100 is best. They become ratings like this: 90 or more is 1 (Excellent), 75 to 89 is 2 (Good), 55 to 74 is 3 (Fair), 35 to 54 is 4 (Poor), and below 35 is 5 (Critical)."),
    (r"Each shortlisted option is scored from 1 to 5 on every criterion, where 5 is always the most favourable: for implementation complexity and disruption, 5 means the least complex and least disruptive\.?",
     "Each option is scored from 1 to 5 on every point, and 5 is always the best. For complexity and disruption, 5 means the least."),
    (r"The architecture view shows components and connections derived from the supplied code\. It does not establish the full production topology or every external integration\.?",
     "The diagrams show the components and links found in the code. They do not show the live setup or every outside system."),
    (r"Sensitive details are restricted to the appendix\.?", "Sensitive details are in the appendix."),
    (r"The usability findings come from the screens and page code\. They do not establish user satisfaction, accessibility conformance or the experience of every user group\.",
     "These usability findings come from the screens and page code only. They say nothing about user satisfaction or full accessibility."),
    (r"Operational workload and support arrangements cannot be measured from source alone\. The activities below are starting points for review with the IT owner\.",
     "Workload and support cannot be measured from code. Review the items below with the IT owner."),
    (r"The evidence register identifies the information reviewed\. Open items record missing information and the confirmations needed before the client accepts the assessment\.",
     "The evidence list shows what was reviewed. Open items show what is missing and what must be confirmed before the client accepts this report."),
    (r"The technical profile lists components and technology identifiers found in the code provided\. Missing versions, deployment details and support status are marked for confirmation\.",
     "This section lists the components and technologies found in the code. Missing versions, deployment details and support status are marked as open."),
    (r"The data inventory shows structures referenced or defined in the code reviewed\. Ownership, record volumes, retention and downstream reporting dependencies must still be checked\.",
     "This section lists the data stores found in the code. Ownership, volumes, retention and reporting links must still be checked."),
    (r"The health scorecard combines the areas that could be assessed\. Ratings use the condition scale from 1 to 5; unassessed areas and weighting are explained below\.",
     "The scorecard rates each area that could be assessed, from 1 (best) to 5 (worst). Areas that could not be assessed are explained below."),
    (r"The debt register records code and technology findings that may increase maintenance effort\. Proposed repairs are included in the planning estimate in Section 12\.",
     "These are the findings that make the code harder to maintain. The cost to fix them is in the estimate in Section 12."),
    (r"Indicators below are measured from the source code provided for this review\. Indicators that need a running build or test suite are marked not measured\.",
     "These measures come from the code only. Anything that needs a running build or test suite is marked not measured."),
    (r"Performance and resilience could not be measured from the code\. The requirements below are the ones that matter for this application; each is an open item for the operations team\.",
     "Speed and reliability cannot be measured from code. The needs below matter for this application, and the operations team must confirm each one."),
    (r"Production configuration and operational controls need separate confirmation; sensitive details are restricted to the appendix\.?",
     "Live settings and day-to-day controls are not visible in code and must be checked separately."),
    (r"The security review records findings and the controls visible in the information provided\.",
     "This section lists security problems and the controls the code shows."),
    (r"The application handles payments, so the findings below are assessed as financial controls \(segregation of duties, audit integrity, completeness and accuracy of posting\) rather than as code hygiene\.",
     "The application handles payments, so these findings are judged as money controls: who can approve, whether records can be trusted, and whether postings are complete and correct."),
    (r"Likelihood comes from end-of-life status, skills, what the code shows and incident history where it is known; impact comes from what the component does to money and data\.",
     "Likelihood comes from end-of-life status, skills, what the code shows and past incidents. Impact comes from what the component does to money and data."),
    (r"Rates are planning-level and need validating with the delivery teams; each skill set needs its own people \((.*?) rarely sit in one person\)\.",
     r"These rates are rough and must be checked with the delivery teams. Each skill needs different people (\1 rarely sit in one person)."),
    (r"The nodes below are inferred from the code and are the starting point for the physical view; for a payment system the network zones, availability and disaster recovery of each node are essential and are open items\.",
     "The servers below are guessed from the code. For a payment system, each one needs its network zone, uptime and recovery plan checked. These are open items."),
)

PHRASES = (
    (r"\bTo confirm \(read only in the supplied code\)", "Unknown (only the code was read)"),
    (r"\bTo confirm \(([^)]*)\)", r"Not confirmed (\1)"),
    (r"\bto confirm \(([^)]*)\)", r"not confirmed (\1)"),
    (r"\b(is|are) to confirm\b", "must be confirmed"),
    (r"\b(is|are) to check\b", "must be checked"),
    (r"\bremains? to check\b", "must still be checked"),
    (r"\bneed checking\b", "must be checked"),
    (r"\bneeds checking\b", "must be checked"),
    (r"\bis not confirmed\b", "is not confirmed"),
    (r"\bto be confirmed by\b", "to be confirmed by"),
    (r"\bto be confirmed\b", "not yet confirmed"),
    (r"\bTo confirm\b", "Not confirmed"),
    (r"\bneeds? confirmation\b", "must be confirmed"),
    (r"\brequires? confirmation\b", "must be confirmed"),
    (r"\bneed separate confirmation\b", "must be checked separately"),
    (r"\(version not confirmed\)", "(version unknown)"),
    (r"\bversion not confirmed\b", "version unknown"),
    (r"\bthe supplied code\b", "the code reviewed"),
    (r"\bin the supplied code\b", "in the code reviewed"),
    (r"\bsupplied-source checks\b", "checks of the code reviewed"),
    (r"\bthe supplied components\b", "the components reviewed"),
    (r"\bsupplied components\b", "components reviewed"),
    (r"\bsupplied source\b", "source reviewed"),
    (r"\bsupplied material\b", "material reviewed"),
    (r"\bthe supplied\b", "the"),
    (r"\bSupplied\b", "Provided"),
    (r"\bsupplied\b", "provided"),
    (r"\bInsufficient evidence\b", "Not enough evidence"),
    (r"\binsufficient evidence\b", "not enough evidence"),
    (r"\bunconfirmed\b", "not confirmed"),
    (r"\bprovisional\b", "temporary"),
    (r"\bderived from\b", "based on"),
    (r"\binferred from\b", "worked out from"),
    (r"\bis inferred\b", "is a guess"),
    (r"\bare inferred\b", "are guesses"),
    (r"\bmaker-checker\b", "two-person approval"),
    (r"\bsegregation of duties\b", "separation of duties"),
    (r"\bcharacterization tests\b", "tests that record today's results"),
    (r"\butilis(e|ing|ed)\b", r"us\1"),
    (r"\bin order to\b", "to"),
    (r"\bprior to\b", "before"),
    (r"\bsubsequent\b", "later"),
    (r"\bapproximately\b", "about"),
    (r"\bnumerous\b", "many"),
    (r"\bfacilitate\b", "help"),
    (r"\bdemonstrates\b", "shows"),
    (r"\bcommence\b", "start"),
    (r"\bin the information provided\b", "in the code provided"),
)

_SENT = re.compile(r"(?<=[.!?])\s+")
_IDENT = re.compile(r"^[A-Z0-9_.\-/]+(\s|$)|^[A-Za-z0-9_\-]+\.[A-Za-z]{2,4}\b")


def _split_semicolons(sentence):
    if len(sentence.split()) <= 24 or "; " not in sentence:
        return sentence
    parts = sentence.split("; ")
    out = parts[0]
    for part in parts[1:]:
        words = part.split()
        if len(words) >= 5 and not _IDENT.match(part) and len(out.split()) >= 5 and "(" not in out[-12:]:
            out = out.rstrip(".") + ". " + part[0].upper() + part[1:]
        else:
            out += "; " + part
    return out


def simplify(text, *, prose=True):
    if not text or not text.strip():
        return text
    for pattern, new in REWRITES:
        text = re.sub(pattern, new, text)
    for pattern, new in PHRASES:
        text = re.sub(pattern, new, text)
    for pattern, new in REWRITES:
        text = re.sub(pattern, new, text)
    sentences = [s for s in _SENT.split(text) if s.strip()]
    sentences = [s for s in sentences if not any(re.fullmatch(d, s.strip()) for d in DROP)]
    if prose:
        sentences = [_split_semicolons(s) for s in sentences]
    text = " ".join(sentences)
    return re.sub(r"\.\.(?=\s|$)", ".", re.sub(r"[ ]{2,}", " ", text)).strip()
