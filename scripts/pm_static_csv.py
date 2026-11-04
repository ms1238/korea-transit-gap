"""Turn the PM device and parking files that have no API into scripts/static/pm_fleet_static.csv and
scripts/static/pm_parking_static.csv:
- 서울시 민간대여 공유 전동킥보드 기기 현황 (25.12월 기준, CSV in CP949): 대여업체 (A~D사, anonymised), 브랜드, 기기대수, 운영지역
  (several 구 per row, so only the 서울 total and the number of companies per 구 can be told)
- 서울시 PM 주차구역 (2026년 3월, xlsx from the 서울 map service): 구명, 콘텐츠명, 주차구역 형태, 좌표; rows with 사용유무 Y
- 부산 동래구·남구·수영구·연제구 공유 PM 현황 (PDF, typed in below): 업체수, 운영대수, and 남구's 9 주차구역
- 화성시 동탄 PM 주차구역 (xlsx, one sheet per 동탄 1~9동, 2024 and 2025 installations side by side): 관리번호, 주변주소,
  상세위치, 좌표 ('lat,lon'), 설치수량; optional third argument

Run on a PC when the files are updated (needs openpyxl):
    python scripts/pm_static_csv.py 서울_기기현황.csv 서울_주차구역.xlsx [화성_동탄_주차구역.xlsx]
"""
import csv
import os
import re
import sys

import openpyxl

STATIC = os.path.join(os.path.dirname(__file__), "static")
SEOUL_FLEET = ("서울시 민간대여 공유 전동킥보드 기기 현황", "2025-12")
SEOUL_PARKING = ("서울시 PM 주차구역", "2026-03")
BUSAN = [  # 지역, 업체수, 운영대수, 종류, 기준일, 출처 (the 구's PDF)
    ("부산 동래구", 4, 1750, "공유 PM", "2024-12-31", "부산광역시 동래구 공유 PM 업체수 및 운영대수"),
    ("부산 남구", 3, 830, "공유 PM", "2024-12-31", "부산광역시 남구 공유 PM 업체수 및 운영대수"),
    ("부산 수영구", 4, 849, "전동킥보드 및 전기자전거", "2025-11-19", "부산광역시 수영구 전동킥보드 및 전기자전거(PM) 업체수 및 운영대수"),
    ("부산 연제구", 4, 871, "공유 PM", "2025-04-04", "부산광역시 연제구 공유 PM 업체수 및 운영대수"),
]
NAMGU_PARKING = [  # 부산 남구 PM 주차구역 (2024-12-31): 위치, 위도, 경도, 주차대수
    ("용소로 45 부경대 부산창업카페 앞", 35.135109, 129.100912, 5), ("수영로 297 (더바른이치과의원 앞)", 35.136918, 129.098749, 5),
    ("대연동 405 앞", 35.136604, 129.098131, 5), ("수영로 283 (벽산e솔렌스힐, 마이페브 헤어 앞)", 35.136254, 129.097383, 5),
    ("수영로 283 (벽산e솔렌스힐, 정문 앞)", 35.136307, 129.097486, 5), ("수영로 278 (전자랜드 대연점 앞)", 35.135913, 129.097078, 5),
    ("수영로 300 (ABC 마트 앞)", 35.136796, 129.099181, 5), ("수영로 238 (부산고려 병원 앞)", 35.135032, 129.092604, 5),
    ("수영로 261 (아이젠트리 대연점 앞)", 35.135526, 129.094452, 5),
]


def main():
    fleet_csv, parking_xlsx = sys.argv[1], sys.argv[2]
    with open(fleet_csv, encoding="cp949") as f:
        rows = list(csv.reader(f))
    fleet, company = [], None
    for r in rows:
        if len(r) < 5 or not r[3].replace(",", "").strip().isdigit():
            continue
        company = r[1].strip() or company  # a company's second brand leaves the name empty
        fleet.append(["서울특별시", company, r[2].strip(), "", int(r[3].replace(",", "")), "", "",
                      SEOUL_FLEET[1], SEOUL_FLEET[0], ",".join(g.strip() + "구" for g in r[4].split(","))])
    for region, n, total, kind, date, source in BUSAN:
        fleet.append([region, "", "", n, "", "", total, date, source, kind])  # 'PM' does not tell scooters from bicycles
    with open(os.path.join(STATIC, "pm_fleet_static.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["지역", "운영사", "브랜드", "업체수", "전동킥보드", "전기자전거", "합계(구분없음)", "기준일", "출처", "비고(운영구·종류)"])
        w.writerows(fleet)

    ws = openpyxl.load_workbook(parking_xlsx, read_only=True, data_only=True).worksheets[0]
    out = []
    for r in list(ws.iter_rows(values_only=True))[1:]:
        if r[0] and r[1] == "Y" and r[10] and r[11]:
            out.append([f"서울 {r[5]}", r[2], r[3] or "", "", float(r[10]), float(r[11]), SEOUL_PARKING[1], SEOUL_PARKING[0]])
    for name, lat, lon, cap in NAMGU_PARKING:
        out.append(["부산 남구", name, "", cap, lon, lat, "2024-12-31", "부산광역시 남구 PM 주차구역 설치 현황"])
    if len(sys.argv) > 3:  # 화성시 동탄: a 2024 block (columns A–G) and a 2025 block (I–O) per 동 sheet
        wb = openpyxl.load_workbook(sys.argv[3], read_only=True, data_only=True)
        for ws in wb.worksheets[1:]:
            for r in list(ws.iter_rows(values_only=True))[2:]:
                for off, year in ((0, "2024"), (8, "2025")):
                    c = r[off:off + 7]
                    m = re.findall(r"\d+\.\d+", str(c[4] or "")) if len(c) >= 6 else []
                    if len(m) == 2:
                        out.append(["경기 화성시", f"{c[3] or c[2]} ({c[1]})", f"{year}년 설치" + (f" · {c[6]}" if c[6] else ""), c[5] or "",
                                    float(m[1]), float(m[0]), "2025", "화성시 동탄 PM 주차구역 (2024·2025년 설치)"])
    with open(os.path.join(STATIC, "pm_parking_static.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["지역", "명칭", "형태", "주차대수", "경도", "위도", "기준일", "출처"])
        w.writerows(out)
    print(f"fleet rows {len(fleet)}, parking points {len(out)}")


if __name__ == "__main__":
    main()
