"""Turn the 도시계획현황 sheets (국토교통부, 국토교통통계누리 · 도시계획정보서비스) into scripts/static/upis.csv.

Run on a PC once a year with the two downloaded files (needs openpyxl):
    python scripts/upis_csv.py "2-1-3.용도지역(시군구별)_2025.xlsx" "1-1-2.도시지역 인구현황(시군구별)_2025.xlsx" 2025
Rows are the 시군구 as the 도시계획 statistics list them (시 with 구 as one 시); areas in ㎡.
"""
import csv
import os
import sys

import openpyxl


def rows(path):
    return list(openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0].iter_rows(values_only=True))


def by_area(table, start):
    """{(시도, 시군구): row}, the 시도 taken from the preceding '<시도> 소계' row."""
    out, sido = {}, None
    for r in table[start:]:
        name = str(r[0] or "").strip()
        if not name or name == "총계":
            continue
        if name.endswith("소계"):
            sido = name[:-2].strip()
        else:
            out[(sido, name)] = r
    return out


def main(zone_xlsx, pop_xlsx, year):
    zone, pop = by_area(rows(zone_xlsx), 4), by_area(rows(pop_xlsx), 5)
    n = lambda v: round(float(v or 0))
    path = os.path.join(os.path.dirname(__file__), "static", "upis.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["기준연도", "시도", "시군구", "용도지역합계_m2", "도시지역_m2", "주거_m2", "상업_m2", "공업_m2", "녹지_m2", "미세분_m2",
                    "전체인구", "도시지역인구"])
        for (sido, name), r in zone.items():
            p = pop.get((sido, name))
            w.writerow([year, sido, name, n(r[1]), n(r[2]), n(r[3]), n(r[13]), n(r[19]), n(r[24]), n(r[29]),
                        n(p[1]) if p else "", n(p[2]) if p else ""])
    print(f"{path}: {len(zone)} 시군구, population for {sum(k in pop for k in zone)}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
