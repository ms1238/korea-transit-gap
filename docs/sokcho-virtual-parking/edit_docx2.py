"""사용자 수정본 Word에 '반납 의무는 후보지 블록에만, 블록 안은 고르게' 조정을 반영한다(Meng et al. 2025)."""
import copy, json, sys
import docx
from docx.shared import Cm

SRC, OUT, CJ, IMG_OV, IMG_PN = sys.argv[1:6]
d = docx.Document(SRC)
P = lambda el: docx.text.paragraph.Paragraph(el, d)
C = json.load(open(CJ))
NUM = "①②③④⑤⑥⑦⑧"
c1, c2 = C[:6], C[6:]
pos = {s: NUM[i] for i, c in enumerate(C) for s in c["stations"]}
T1 = sum(c["total"] for c in c1); H1 = sum(c["have"] for c in c1); N1 = T1 - H1
A1 = sum(c["area"] for c in c1); T2 = sum(c["total"] for c in c2); A2 = sum(c["area"] for c in c2)
OUT1_C, OUT1_P = 27, 6          # 1단계 블록 밖 회랑, 거점 (analyze.py OUTSIDE1)
OUT2_C, OUT2_P = 51, 6          # 2단계 블록 밖 회랑, 거점 (analyze.py P2)
cmin = min(c["cov200"] for c in c1); dmin = min(c["dens"] for c in c1); dmax = max(c["dens"] for c in c1)


def paras():
    return [el for el in d.element.body.iterchildren() if el.tag.endswith("}p")]


def find(prefix):
    for el in paras():
        if P(el).text.strip().startswith(prefix):
            return el
    raise KeyError(prefix)


def tables():
    return [docx.table.Table(el, d) for el in d.element.body.iterchildren() if el.tag.endswith("}tbl")]


def set_text(p, text):
    runs = p.runs
    if not runs:
        p.add_run(text); return
    runs[0].text = text
    for r in runs[1:]:
        r._r.getparent().remove(r._r)


def put(prefix, text):
    set_text(P(find(prefix)), text)


def clone_para(tpl, text, after):
    el = copy.deepcopy(tpl)
    for dr in el.findall(".//{*}drawing"):
        dr.getparent().getparent().remove(dr.getparent())
    for hl in el.findall("{*}hyperlink"):
        el.remove(hl)
    after.addnext(el)
    set_text(P(el), text)
    return el


def image_para(tpl, img, after, width_cm):
    el = copy.deepcopy(tpl)
    for r in el.findall("{*}r"):
        el.remove(r)
    after.addnext(el)
    P(el).add_run().add_picture(img, width=Cm(width_cm))
    return el


def fill(cell, text):
    p = cell.paragraphs[0]
    set_text(p, text)
    for extra in cell.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)


def table_by_head(first):
    for t in tables():
        if t.rows[0].cells[0].text.strip() == first and len(t.rows) > 1:
            yield t


def rebuild(t, rows, widths=None):
    """첫 데이터 행 서식으로 행 수를 맞추고 내용을 채운다. 열 수는 표 그대로."""
    trs = t._tbl.findall("{*}tr")
    tpl = trs[1]
    for tr in trs[1:]:
        t._tbl.remove(tr)
    for _ in rows:
        t._tbl.append(copy.deepcopy(tpl))
    for i, r in enumerate(rows):
        for j, v in enumerate(r):
            fill(t.rows[i + 1].cells[j], v)
    if widths:
        grid = t._tbl.find("{*}tblGrid")
        for gc, w in zip(grid.findall("{*}gridCol"), widths):
            gc.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}w", str(int(w * 567)))
        for row in t.rows:
            for cell, w in zip(row.cells, widths):
                cell.width = Cm(w)


normal_tpl = copy.deepcopy(find("ㅇ 기기 100대에 비해"))
list_tpl = copy.deepcopy(find("(관광지형 1단계 7곳)"))
cap_tpl = copy.deepcopy(find("[그림 2]"))
title_tpl = copy.deepcopy(find("핵심구역(A등급) 도출 결과"))
img_tpl = copy.deepcopy(find("[그림 1]").getprevious())
tbl_tpl = None
for t in table_by_head("구역"):
    tbl_tpl = copy.deepcopy(t._tbl)

# 추진 배경: 연구 근거 교체
put("(연구)", "(연구) 12개 도시 공유 킥보드 분석 결과, 반납 의무구역 안 주차구역이 1㎢당 20~30개(도보 약 1분)를 넘으면 "
    "준수율이 크게 오르고 그 이상은 효과가 미미함. 밀도가 낮을수록 구역이 고르게 퍼져 있는지(구역 200m 안 면적 비율)가 중요"
    "(Meng et al., 2025, Journal of Transport and Land Use)")

# 1. 적용 범위
put("ㅇ 청초호 및 해안길 회랑 8.8km", f"ㅇ 청초호 및 해안길 회랑 8.8km를 시범구역으로 하고, 반납 의무구역은 후보지 블록 6곳"
    f"({A1:.2f}㎢, {T1}개 구역)으로 한정. 블록 밖 회랑 구역과 거점 {OUT1_C + OUT1_P}개는 반납 권장(앱 할인), "
    "그 외 지역은 현행 반납 방식(금지구역만 설정) 유지")
put("ㅇ 사각지대는 노학동", "ㅇ 사각지대는 노학동, 대포동, 영랑동이나 관광 회랑 밖 주거지이므로 별도 구역을 두지 않고 현행 자유 반납"
    "(금지구역만 설정)을 유지함(3항)")

# 3. 구역 등급 및 지정 방식
put("ㅇ 회랑 안에서는 지정구역에서만", "ㅇ 반납 의무는 후보지 블록 안에만 적용하고, 블록 밖 회랑 구역과 거점은 반납 권장(앱 할인), "
    "그 외 시가지는 현행 자유 반납을 유지")
put("회랑 구역은 청초호와 해안길에만", "준수율은 구역 수보다 의무구역 안 밀도와 고른 분포가 좌우함. 1㎢당 20~30개를 넘으면 효과가 "
    "크게 줄고, 밀도가 낮을수록 구역 200m 안 면적 비율이 중요(Meng et al., 2025) → 의무구역을 시가지로 넓히기보다 블록 안을 고르게 채움")
put("시가지 생활권 구역은 1단계에", f"블록마다 구역 200m 안 면적 비율 90% 이상, 밀도 1㎢당 25개 이상이 되도록 블록 내부에 구역을 "
    f"추가 배치(1단계 {N1}개 추가, 회랑에만 몰려 있던 배치 보완)")
put("구역 수는 현장조사로 확정", "관광 블록은 구역을 더 늘리기보다 구역당 수용 대수를 키움(관광지 반납 수요는 상업지 대비 약 1.65배, "
    "Meng et al., 2025)")
for t in table_by_head("등급"):
    rebuild(t, [
        ["의무(후보지 블록)", f"입지점수 A등급 군집과 스테이션 4곳을 묶은 블록 6곳({A1:.2f}㎢)", "1㎢당 25개 이상, 200m 안 면적 90% 이상",
         "스테이션, 보도형, 연석 표시형, 주차면 전환형. 블록 안에서는 지정구역 밖 반납 불가"],
        ["권장(회랑)", "블록 밖 해안 자전거길, 청초호 둘레", "150~200m", "연석 표시형, 빗금구역형, 주차면 전환형(차도 인접 구간 제외). 반납 시 앱 할인"],
        ["권장(거점)", "블록 밖 관광지, 대형 숙박시설", "시설당 1개", "관광지형, 숙박시설형"],
        ["일반", "그 외 지역", "지정 없음", "자유 반납 + 금지구역(횡단보도, 버스정류장 등)"],
    ])
    break

# 4. 단계별 구역 배치
put("ㅇ 1단계 밀도는", f"ㅇ 반납 의무구역(블록 6곳, {A1:.2f}㎢)의 밀도는 1㎢당 약 {T1 / A1:.0f}개이며, 블록별 {dmin:.0f}~{dmax:.0f}개, "
    f"구역 200m 안 면적 비율 {cmin:.0%} 이상으로 논문 기준(1㎢당 20~30개, 고른 분포)을 충족")
cap = find("[그림 2]")
img_el = cap.getprevious()
for blip in img_el.findall(".//{*}blip"):
    rid = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
    d.part.related_parts[rid]._blob = open(IMG_OV, "rb").read()
set_text(P(cap), "[그림 2] 가상주차구역 후보지(반납 의무구역)와 회랑 권장 구역(초록 점은 블록 내부 추가 구역, 세부는 붙임)")
for t in table_by_head("단계"):
    if "구간" in t.rows[0].cells[1].text:
        rebuild(t, [
            ["1단계", "후보지 블록 6곳(반납 의무)", f"{A1:.2f}㎢", f"{T1} (기존 {H1}, 내부 추가 {N1})", "블록별 세부는 아래 표"],
            ["1단계", "회랑 권장 구역(블록 밖)", "-", str(OUT1_C), "연석 표시, 빗금구역(차도 인접 제외), S2 주변은 해변측"],
            ["1단계", "거점 권장 구역(블록 밖)", "-", str(OUT1_P), "관광지형, 숙박시설형"],
            ["1단계 계", "", "", f"{T1 + OUT1_C + OUT1_P} (의무 {T1}, 권장 {OUT1_C + OUT1_P})", ""],
            ["2단계", "후보지 블록 2곳(반납 의무)", f"{A2:.2f}㎢", str(T2), "시외버스터미널·속초항, 동명항·영금정"],
            ["2단계", "회랑·거점 권장 구역(블록 밖)", "-", str(OUT2_C + OUT2_P), "동명항~영금정 해안길, 영랑호 둘레"],
        ])
        break
put("ㅇ 초기에는 A등급", "ㅇ 반납 의무구역(블록)을 먼저 운영하고, 회랑 권장 구역은 이용 데이터를 보고 블록 확대 여부를 판단함")
anchor = find("※ 구간별 수는")
set_text(P(anchor), "※ 구역 위치는 분석상 배치 예시이며, 현장조사로 지점과 블록 경계를 확정")

# 후보지 설명 + 표
a = clone_para(normal_tpl, f"ㅇ 후보지 블록은 입지점수 A등급 군집과 스테이션 반경 130m를 묶어 설정함. 1단계 6곳, 2단계 2곳이며, "
               f"S1은 {pos['S1']}, S2는 {pos['S2']}, S3은 {pos['S3']}, S4는 {pos['S4']} 블록 안에 위치", anchor)
a = clone_para(title_tpl, "가상주차구역 후보지(반납 의무구역)", a)
tbl = copy.deepcopy(tbl_tpl)
a.addnext(tbl)
t = docx.table.Table(tbl, d)
rows = [[f"{NUM[i]} {c['name']}" + (" (2단계)" if i >= 6 else ""), f"{c['area']:.2f}㎢",
         f"{c['total']}개" + (f"(+{c['interior']})" if c["interior"] else ""), f"{c['cov200']:.0%}",
         ", ".join(c["stations"]) or "-", str(c["lodg"])] for i, c in enumerate(C)]
rows.append(["1단계 계(6곳)", f"{A1:.2f}㎢", f"{T1}개(+{N1})", f"{cmin:.0%} 이상", "S1~S4", str(sum(c['lodg'] for c in c1))])
heads = ["후보지", "면적", "가상주차구역(내부 추가)", "200m 안 면적", "스테이션", "숙박"]
rebuild(t, rows, [5.4, 1.8, 3.0, 2.2, 2.0, 1.6])
for j, h in enumerate(heads):
    fill(t.rows[0].cells[j], h)
n200 = clone_para(normal_tpl, "※ 200m 안 면적은 블록 면적 중 가장 가까운 구역까지 200m 이내인 비율(논문의 커버리지 정의), 숙박은 블록 안 영업 숙박시설 수", tbl)
b = clone_para(normal_tpl, "ㅇ 위 후보지와 구역 배치는 숙박시설, 관광지, 정류장 등 공간 자료로 만든 초안이며, 궁극적으로는 실제 이용 데이터와 "
               "지자체 민원 데이터로 검증하고 보정해야 함", n200)
b = clone_para(list_tpl, "(이용 데이터, 운영사) 대여 및 반납 위치, 구역 밖 반납 시도 위치, 시간대와 요일별 이용량, 구역별 회전율", b)
b = clone_para(list_tpl, "(민원 데이터, 속초시) PM 무단주차 민원과 견인 위치 및 일시, 처리 결과", b)
b = clone_para(list_tpl, "(활용) 반납이 몰리는 곳에 구역 추가, 민원이 반복되는 곳은 구역 이동 또는 금지구역 지정, 블록 경계 확대 및 축소, "
               "권장 구역의 의무 전환 여부 판단", b)
b = clone_para(list_tpl, "운영사 협약에 위치 단위 이용 데이터 제공 조항을 넣고, 시는 민원 및 견인 기록을 위치 정보와 함께 관리하도록 함", b)

# 5. 스테이션 문단
put("ㅇ 스테이션 4곳 반경 100m", f"ㅇ 스테이션 4곳은 모두 후보지 블록(반납 의무구역) 안에 포함(S1 {pos['S1']}, S2 {pos['S2']}, "
    f"S3 {pos['S3']}, S4 {pos['S4']}). 스테이션 위치(교수님안)는 옮기지 않고 블록 경계를 스테이션에 맞춰 설정")
put("ㅇ (가변 운영)", "ㅇ (가변 운영) 성수기(7~8월), 축제, 해맞이 기간에는 블록 안 구역의 수용 대수를 늘리고 블록 밖 권장 구역을 확대하며, "
    "비수기에는 권장 구역 일부를 끄는 방식으로 앱 설정만으로 조정")

# 향후 추진, 성과지표
put("② 현장조사로", f"② 현장조사로 후보지 블록 6곳 경계와 블록 내 구역 {T1}개, 회랑 권장 구역 확정(숙박사업자 협약 병행)")
for t in table_by_head("단계"):
    if "성과" in t.rows[0].cells[-1].text:
        for row in t.rows[1:]:
            k = row.cells[0].text.strip()
            if k.startswith("1"):
                fill(row.cells[1], f"후보지 블록 6곳(의무 {T1}개) + 회랑 권장 {OUT1_C + OUT1_P}개 + 스테이션 4곳, '27년 7~8월 집중 운영")
                fill(row.cells[2], "블록 안 반납 준수율 85% 이상(대구 달성 수준), 블록별 200m 안 면적 90% 이상 유지, 시범구역 PM 민원 감소율, 관광지 혼잡 주민 체감")
            elif k.startswith("2"):
                fill(row.cells[1], f"동명항·영금정, 시외버스터미널 블록 2곳(의무 {T2}개) 추가, 영랑호 둘레 권장 구역")
        break

p4 = find("④ '27년 7~8월")
clone_para(p4, "⑤ 실증 기간 운영사 이용 데이터와 속초시 민원 및 견인 데이터를 월 단위로 공유받아 블록 경계와 구역 위치를 보정"
           "(최종 입지는 데이터로 확정)", p4)

# 출처
src_last = find("주차 지점 밀도 권고")
clone_para(src_last, "Meng, S., Brown, A., Thigpen, C., Haydu, B., Klein, N. J. (2025). Cities with dense networks of shared "
           "scooter parking have higher parking compliance. Journal of Transport and Land Use, 18(1), 291-317", src_last)

# 붙임
body_last = list(d.element.body.iterchildren())[-1]
if body_last.tag.endswith("}sectPr"):
    body_last = body_last.getprevious()
h = clone_para(find("□ 추진 배경"), "붙임  가상주차구역 후보지 위치도", body_last)
P(h).paragraph_format.page_break_before = True
img = image_para(img_tpl, IMG_PN, h, 12.0)
clone_para(cap_tpl, "※ 실선 1단계, 점선 2단계 후보지(반납 의무구역). 파란 점은 회랑·거점 구역, 초록 점은 블록 내부 추가 구역, "
           "주황 사각형은 MaaS 스테이션. 배경은 위성 토지피복(회색 시가지, 연두 산림, 파랑 수면)", img)
d.save(OUT)
print("saved", T1, H1, N1, round(A1, 2), T2)
