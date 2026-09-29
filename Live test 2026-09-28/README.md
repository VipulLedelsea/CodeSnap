# Live capture test — 16 code files + 2 UI screens

Don't edit these files: they're the "truth" copies the captures get scored against.

## A. Code (open in your editor, capture as code, scroll top to bottom)
| # | File | Lines | Language / what it tests |
|---|---|---|---|
| 1 | AIDPAYRN.cbl | 174 | COBOL batch, sequence numbers, 4–6 screens (main one; do one pass a bit fast) |
| 2 | AIDINQ.cbl | 41 | COBOL + CICS (zoom so it takes 2 screens) |
| 3 | AIDJOB.jcl | 8 | JCL |
| 4 | AIDMAP.bms | 9 | CICS BMS map (continuation in column 72) |
| 5 | AIDDBD.dbd | 13 | IMS DBD macros (leading blanks) |
| 6 | AIDRPT.pli | 23 | PL/I |
| 7 | AIDEXTR.rexx | 20 | REXX |
| 8 | AIDPOST.rpgle | 28 | RPG fixed-form (every column matters) |
| 9 | AIDCALC.frm | 45 | VB6 form + code |
| 10 | AidMain.pas | 28 | Delphi |
| 11 | aidlookup.asp | 27 | Classic ASP |
| 12 | DistrictAid.aspx | 20 | ASP.NET Web Forms markup |
| 13 | district_aid_lookup.html | 82 | Legacy HTML 4 page (inline JS/CSS), 2–3 screens |
| 14 | AIDRPT.CPP | 30 | Pre-standard C++ |
| 15 | aid_pkg.pkb | 17 | Oracle PL/SQL package body |
| 16 | AidPaymentController.cs | 43 | C# (zoom to 2 screens) |

## B. UI front end (open in a browser, capture as a UI screen, not as code)
| # | File | What it tests |
|---|---|---|
| 17 | ui/district_aid_lookup.html | Legacy web form: fields, table, accessibility + security issues planted |
| 18 | ui/aidinq_3270.html | Green-screen 3270 inquiry: labels, exact numbers, PF keys, warning message |
