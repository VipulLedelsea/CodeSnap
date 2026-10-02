#!/usr/bin/env python
# Merge district ADM extracts (written for Python 2.6 on the old reporting server)
import csv
import string
import pyodbc

def load(path):
    rows = []
    for line in open(path):
        rows.append(string.split(line, "|"))
    return rows

def main():
    conn = pyodbc.connect("DSN=SCHOOLFIN;UID=rpt;PWD=rpt2010")
    cur = conn.cursor()
    try:
        for r in load("/data/adm.txt"):
            cur.execute("INSERT INTO ADM_MERGE VALUES ('%s', %s)" % (r[0], r[1]))
    except Exception, e:
        print "merge failed:", e
    print "done"

if __name__ == "__main__":
    main()
