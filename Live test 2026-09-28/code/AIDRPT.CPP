#include <iostream.h>
#include <fstream.h>
#include <string.h>
#include "aidrec.h"

class AidReport : public ReportBase {
public:
    AidReport(char far *title);
    void Print(ostream &out);
private:
    int lineCount;
    AidRecord current;
};

AidReport::AidReport(char far *title) {
    lineCount = 0;
}

void AidReport::Print(ostream &out) {
    out << "DISTRICT AID REPORT" << endl;
    current.Load();
    FormatLine(out);
}

void main() {
    AidReport report("FY1998");
    ofstream out("AIDRPT.TXT");
    report.Print(out);
    cout << "done" << endl;
}
