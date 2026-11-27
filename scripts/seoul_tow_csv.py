"""Turn the 서울시 전동킥보드 견인 신고 내역 exports (reportList_*.xlsx, the 신고 목록 an operator downloads from the 서울시
PM 신고 시스템, here 빔모빌리티's) into scripts/static/seoul_tow.csv for the 서울 견인 page (site/tow.html).

The exports come in half-year files and may overlap (the same half downloaded twice), so rows are de-duplicated on
every column but the per-file 번호. Only what the page needs is kept, nothing that names a person, a device or a
photo:
    d     신고일 (YYYY-MM-DD)            h   신고 시각 (0–23)
    gu    구정보                         s   상태: T 견인완료, C 수거완료 (운영사 직접 이동·수거), E 처리시간 경과
                                             (24시간 안에 조치 없음, 자동 종결), N 기기미발견, R 신고 (미처리)
    k     즉시/일반 (I / G)              m   신고 → 조치일 (분, 소수 1자리; 조치일이 없으면 비움)
    by    조치 주체: B 운영사, W 견인업체, G 구청, (비움) 없음
    co    조치업체 이름 (견인업체·구청일 때만; 운영사는 비움)
    lat, lon  신고 위치, 소수 5자리 (약 1 m)로 반올림 (주차구역 후보를 건물 밖에 두는 데 씀)

Run when new exports arrive:
    python scripts/seoul_tow_csv.py <folder with reportList_*.xlsx>
(needs pandas and openpyxl)
"""
import glob
import os
import sys
import warnings

import pandas as pd

OUT = os.path.join(os.path.dirname(__file__), "static", "seoul_tow.csv")
STATUS = {"견인완료": "T", "수거완료": "C", "처리시간 경과": "E", "기기미발견": "N", "신고": "R"}
OPERATOR = "빔모빌리티"


def main(folder):
    warnings.filterwarnings("ignore")  # openpyxl: "Workbook contains no default style"
    files = sorted(glob.glob(os.path.join(folder, "*.xlsx")))
    if not files:
        sys.exit(f"no .xlsx in {folder}")
    d = pd.concat([pd.read_excel(f, header=1, dtype=str) for f in files], ignore_index=True)
    n0 = len(d)
    d = d.drop_duplicates([c for c in d.columns if c != "번호"])
    t0 = pd.to_datetime(d["신고일시"])
    t1 = pd.to_datetime(d["조치일"], errors="coerce")
    unknown = set(d["상태"].dropna()) - set(STATUS)
    if unknown:
        sys.exit(f"unknown 상태: {unknown}")
    by = d["조치업체"].fillna("").map(lambda x: "" if not x else "B" if x == OPERATOR else "G" if "구청" in x else "W")
    out = pd.DataFrame({
        "d": t0.dt.strftime("%Y-%m-%d"), "h": t0.dt.hour, "gu": d["구정보"].fillna(""),
        "s": d["상태"].map(STATUS), "k": d["즉시/일반"].map({"즉시": "I", "일반": "G"}).fillna(""),
        "m": ((t1 - t0).dt.total_seconds() / 60).round(1), "by": by,
        "co": d["조치업체"].fillna("").where(by.isin(["W", "G"]), ""),
        "lat": pd.to_numeric(d["신고시점 위도"], errors="coerce").round(5),
        "lon": pd.to_numeric(d["신고시점 경도"], errors="coerce").round(5),
    }).sort_values(["d", "h"], kind="stable")
    out.to_csv(OUT, index=False)
    print(f"{len(files)} files, {n0} rows, {len(out)} after de-duplication, {out.d.min()} – {out.d.max()} → {OUT}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
