"""Turn the 지자체 PM·견인 조례 analysis sheet (one row per 광역·기초 지자체: PM 조례, 이동조치 규정, 견인 조례의 PM 항목,
PM 견인료, 자전거 견인) into scripts/static/ordinance.csv, unchanged apart from the format.

Run on a PC when the sheet is updated (needs openpyxl):
    python scripts/ordinance_csv.py "전국_지자체_PM_견인조례_분석현황.xlsx"
"""
import csv
import os
import sys

import openpyxl


def main():
    ws = openpyxl.load_workbook(sys.argv[1], read_only=True, data_only=True).worksheets[0]
    rows = [["" if v is None else str(v).strip() for v in r] for r in ws.iter_rows(values_only=True)]
    out = os.path.join(os.path.dirname(__file__), "static", "ordinance.csv")
    with open(out, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(r for r in rows if any(r))
    print(f"wrote {out}: {len(rows) - 1} 지자체")


if __name__ == "__main__":
    main()
