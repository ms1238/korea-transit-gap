"""사용자 수정본 Word에 후보지(블록) 내용을 넣는다. 서식은 기존 문단·표를 복제해 유지."""
import copy, json, sys
import docx
from docx.shared import Cm

SRC, OUT, CJ, IMG_OV, IMG_PN = sys.argv[1:6]
d = docx.Document(SRC)
body = list(d.element.body.iterchildren())
P = lambda el: docx.text.paragraph.Paragraph(el, d)
C = json.load(open(CJ))
NUM = "①②③④⑤⑥⑦⑧"
c1 = C[:6]
for c in C:
    c["phase"] = 1 if c in c1 else 2
pos = {s: NUM[i] for i, c in enumerate(C) for s in c["stations"]}


def find(prefix):
    for el in d.element.body.iterchildren():
        if el.tag.endswith("}p") and P(el).text.strip().startswith(prefix):
            return el
    raise KeyError(prefix)


def set_text(p, text):
    """첫 run의 서식을 남기고 문단 글자만 바꾼다."""
    runs = p.runs
    runs[0].text = text
    for r in runs[1:]:
        r._r.getparent().remove(r._r)


def clone_para(template_el, text, after_el):
    el = copy.deepcopy(template_el)
    for dr in el.findall(".//{*}drawing"):
        dr.getparent().getparent().remove(dr.getparent())
    after_el.addnext(el)
    p = P(el)
    if not p.runs:
        p.add_run(text)
    else:
        set_text(p, text)
    return el


def image_para(template_el, img, after_el, width_cm=16.5):
    el = copy.deepcopy(template_el)
    for r in el.findall("{*}r"):
        el.remove(r)
    after_el.addnext(el)
    P(el).add_run().add_picture(img, width=Cm(width_cm))
    return el


normal_tpl = body[69]       # ㅇ 본문 문단
list_tpl = body[48]         # - 하위 항목(List Paragraph)
cap_tpl = body[67]          # [그림] 캡션
title_tpl = body[44]        # 표 제목(핵심구역(A등급) 도출 결과)
img_tpl = body[66]          # 그림 문단
tbl_tpl = body[45]          # 핵심구역 표 (6열)

# 1) 개요 문단
p28 = P(find("ㅇ 청초호 및 해안길 회랑 8.8km"))
for r in p28.runs:
    if "1단계 93개 구역 지정" in r.text:
        r.text = r.text.replace("1단계 93개 구역 지정", "1단계 후보지 6곳(블록), 93개 구역 지정")
        break
else:
    set_text(p28, p28.text.replace("1단계 93개 구역 지정", "1단계 후보지 6곳(블록), 93개 구역 지정"))

# 2) [그림 2] 캡션 뒤: 후보지 설명 + 위치도 + 표
anchor = find("※ 구간별 수는")
s1 = sum(c["spots"] for c in c1)
a = clone_para(normal_tpl, "ㅇ 가상주차구역 후보지는 입지점수 A등급 군집과 스테이션 반경 130m를 묶어 블록 단위로 설정함. "
               f"1단계 6곳, 2단계 2곳이며, S1은 {pos['S1']}, S2는 {pos['S2']}, S3은 {pos['S3']}, S4는 {pos['S4']} 후보지 안에 위치", anchor)
a = clone_para(list_tpl, f"1단계 후보지 6곳 안에 가상주차구역 {s1}개소, 후보지 밖 회랑(B등급)과 거점에 {93 - s1}개소", a)
a = clone_para(list_tpl, "후보지 안에서는 지정구역에서만 반납을 허용하고, 경계는 현장조사로 도로와 가구(블록) 경계에 맞춰 확정", a)
a = image_para(img_tpl, IMG_OV, a)
a = clone_para(cap_tpl, "[그림 3] 가상주차구역 후보지 위치도(실선 1단계, 점선 2단계, 세부는 붙임)", a)
a = clone_para(title_tpl, "가상주차구역 후보지", a)

tbl = copy.deepcopy(tbl_tpl)
a.addnext(tbl)
t = docx.table.Table(tbl, d)
heads = ["후보지", "면적", "가상주차구역", "스테이션", "숙박", "관광지"]
rows = tbl.findall("{*}tr")
for tr in rows[2:]:
    tbl.remove(tr)
body_tr = rows[1]
data = []
for i, c in enumerate(C):
    data.append([f"{NUM[i]} {c['name']}" + (" (2단계)" if c["phase"] == 2 else ""), f"{c['area']:.2f}㎢", f"{c['spots']}개소", ", ".join(c["stations"]) or "-",
                 str(c["lodg"]), str(len(c["tour"]))])
data.append(["1단계 계(6곳)", f"{sum(c['area'] for c in c1):.2f}㎢", f"{s1}개소", "S1~S4", str(sum(c['lodg'] for c in c1)),
             str(sum(len(c['tour']) for c in c1))])
for k in range(len(data) - 1):
    body_tr.addnext(copy.deepcopy(body_tr))
t = docx.table.Table(tbl, d)


def fill(cell, text):
    p = cell.paragraphs[0]
    if p.runs:
        set_text(p, text)
    else:
        p.add_run(text)
    for extra in cell.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)


for j, h in enumerate(heads):
    fill(t.rows[0].cells[j], h)
for i, row in enumerate(data):
    for j, v in enumerate(row):
        fill(t.rows[i + 1].cells[j], v)
w = [5.6, 2.0, 2.6, 2.4, 1.8, 2.0]
grid = tbl.find("{*}tblGrid")
for gc, wc in zip(grid.findall("{*}gridCol"), w):
    gc.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}w", str(int(wc * 567)))
for row in t.rows:
    for cell, wc in zip(row.cells, w):
        cell.width = Cm(wc)
note = clone_para(normal_tpl, "※ 숙박은 영업 숙박시설 수, 관광지는 한국관광공사 등록 관광지 수(후보지 경계 안). 면적은 경계 단순화 후 값이며 현장조사로 조정", tbl)

# 3) 스테이션 문단에 후보지 포함 명시
p75 = P(find("ㅇ 스테이션 4곳 반경 100m"))
p75.runs[-1].text = p75.runs[-1].text.rstrip() + \
    f". 스테이션 4곳은 모두 후보지 블록 안에 포함(S1 {pos['S1']}, S2 {pos['S2']}, S3 {pos['S3']}, S4 {pos['S4']})"

# 4) 향후 추진 ②
p90 = P(find("② 현장조사로"))
set_text(p90, p90.text.replace("② 현장조사로 핵심구역", "② 현장조사로 후보지 6곳 경계와 핵심구역"))

# 5) 붙임: 후보지 위치도(확대)
last = list(d.element.body.iterchildren())[-1]
if last.tag.endswith("}sectPr"):
    last = last.getprevious()
from docx.enum.text import WD_BREAK
h = clone_para(body[1], "붙임  가상주차구역 후보지 위치도", last)
P(h).runs[0].add_break(WD_BREAK.PAGE) if False else None
P(h).paragraph_format.page_break_before = True
img = image_para(img_tpl, IMG_PN, h, 12.0)
clone_para(cap_tpl, "※ 실선 1단계, 점선 2단계 후보지. 파란 점은 가상주차구역(지점), 주황 사각형은 MaaS 스테이션. 배경은 위성 토지피복(회색 시가지, 연두 산림, 파랑 수면)", img)
d.save(OUT)
print("saved", OUT)
