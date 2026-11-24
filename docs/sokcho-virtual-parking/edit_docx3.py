"""2차 보완: 요약, 용어 통일, 숫자 갱신, 운영사 유인, 효과 측정, 구역 규격, 반납 처리, 제도 경로."""
import copy, json, sys
import docx

SRC, OUT, REACH = sys.argv[1:4]
d = docx.Document(SRC)
P = lambda el: docx.text.paragraph.Paragraph(el, d)
R = json.load(open(REACH))
pct = lambda a, b: f"{a} ({a / b * 100:.0f}%)"
NL, NT, NS = 358, 100, 96


def paras():
    return [el for el in d.element.body.iterchildren() if el.tag.endswith("}p")]


def find(prefix):
    for el in paras():
        if P(el).text.strip().startswith(prefix):
            return el
    raise KeyError(prefix)


def set_text(p, text):
    runs = p.runs
    if not runs:
        p.add_run(text); return
    runs[0].text = text
    for r in runs[1:]:
        r._r.getparent().remove(r._r)


def clone_para(tpl, text, after):
    el = copy.deepcopy(tpl)
    for dr in el.findall(".//{*}drawing"):
        dr.getparent().getparent().remove(dr.getparent())
    for hl in el.findall("{*}hyperlink"):
        el.remove(hl)
    after.addnext(el)
    set_text(P(el), text)
    return el


def bullets(after, items):
    for t in items:
        after = clone_para(list_tpl, t, after)
    return after


def all_paragraphs():
    for el in paras():
        yield P(el)
    for t in d.tables:
        for row in t.rows:
            for cell in row.cells:
                yield from cell.paragraphs


def replace_all(old, new):
    n = 0
    for p in all_paragraphs():
        if old in p.text:
            hit = False
            for r in p.runs:
                if old in r.text:
                    r.text = r.text.replace(old, new); hit = True; n += 1
            if not hit:
                set_text(p, p.text.replace(old, new)); n += 1
    return n


def fill(cell, text):
    set_text(cell.paragraphs[0], text)
    for extra in cell.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)


def two_col_table(after, title, rows):
    a = clone_para(title_tpl, title, after)
    tbl = copy.deepcopy(two_tpl)
    a.addnext(tbl)
    t = docx.table.Table(tbl, d)
    trs = tbl.findall("{*}tr")
    for tr in trs[2:]:
        tbl.remove(tr)
    for _ in rows[1:]:
        trs[1].addnext(copy.deepcopy(trs[1]))
    t = docx.table.Table(tbl, d)
    fill(t.rows[0].cells[0], "항목"); fill(t.rows[0].cells[1], "기준(안)")
    for i, (k, v) in enumerate(rows):
        fill(t.rows[i + 1].cells[0], k); fill(t.rows[i + 1].cells[1], v)
    return tbl


h2_tpl = copy.deepcopy(find("□ 추진 배경"))
normal_tpl = copy.deepcopy(find("ㅇ 기기 100대에 비해"))
list_tpl = copy.deepcopy(find("(관광지형 1단계 7곳)"))
title_tpl = copy.deepcopy(find("단계별 성과지표(안)"))
note_tpl = copy.deepcopy(find("※ 지정 금지(예시)"))
two_tpl = None
for t in d.tables:
    if t.rows[0].cells[0].text.strip() == "항목" and len(t.columns) == 2:
        two_tpl = copy.deepcopy(t._tbl)

# 1) 1쪽 요약 + 용어
title = paras()[0]
h = clone_para(h2_tpl, "□ 요약", title)
b = bullets(h, [
    "(제안) MaaS 스테이션 4곳에 가상주차구역을 결합하고, 반납 의무는 관광 및 상권이 밀집한 후보지 블록 6곳(1.37㎢)에만 적용",
    "(배치) 블록 안 93개 구역을 도보 1분(100m) 간격으로 고르게 두고, 블록 밖 회랑 및 거점 33개는 반납 권장(앱 할인)",
    "(근거) 의무구역 안 밀도(1㎢당 20~30개 이상)와 고른 분포가 준수율을 좌우(Meng et al., 2025), 대구 달성군 준수율 약 85%",
    f"(효과 범위) 회랑만으로 시가지의 약 60%가 PM 10분권, 숙박시설의 {R['r1w']['lodg'] / NL * 100:.0f}%가 구역 도보 5분 이내",
    "(전제조건) 공유자전거 운영사 참여 확인, 실증 전 민원 및 무단주차 기준선 확보, 운영사 이용 데이터와 시 민원 데이터 공유",
    "(요청사항) 속초시는 시범구역 지정, 운영사 협약 주도, 조례 개정 검토 / 경찰은 연석 표시 및 빗금구역 활용 협의",
])
clone_para(note_tpl, "※ 용어: '후보지 블록(반납 의무구역)'은 지정구역에서만 반납할 수 있는 구역, '권장 구역'은 블록 밖 회랑 및 거점에 두고 "
           "반납 시 앱 할인을 주는 구역", b)

# 2) 용어 통일
replace_all("2. 입지 기준 및 핵심구역", "2. 입지 기준 및 후보지 블록 도출")
replace_all("핵심구역(A등급) 도출 결과", "A등급 군집 도출 결과(후보지 블록의 재료)")
replace_all("중앙시장 핵심구역", "중앙시장 블록")
replace_all("핵심구역을 늘리고", "블록 안 구역을 늘리고")
replace_all("핵심구역", "후보지 블록")
tA = None
for t in d.tables:
    if t.rows[0].cells[0].text.strip() == "구역" and "정류장" in t.rows[0].cells[4].text:
        tA = t
if tA is not None:
    clone_para(note_tpl, "※ 위 군집을 스테이션과 묶어 4항의 후보지 블록으로 확정(설악동 일대는 PM 회랑 밖이라 제외)", tA._tbl)

# 3) 숫자 갱신
replace_all("속초 숙박시설의 44%가", f"속초 숙박시설의 {R['r1w']['lodg'] / NL * 100:.0f}%가")
replace_all("숙박시설 도보 5분 내 59%", f"숙박시설 도보 5분 내 {R['r12w']['lodg'] / NL * 100:.0f}%")
for t in d.tables:
    if t.rows[0].cells[0].text.strip() == "구분" and "속초시 전체" in t.rows[0].cells[1].text:
        vals = {"숙박": ("lodg", NL), "관광": ("tour", NT), "버스": ("stops", NS)}
        for row in t.rows[1:]:
            key = next((k for k in vals if row.cells[0].text.strip().startswith(k)), None)
            if not key:
                continue
            f, n = vals[key]
            for j, k in enumerate(["r1w", "r12w", "r1p", "r12p"]):
                fill(row.cells[j + 2], pct(R[k][f], n))
cov_title = find("구역 기준 시설 커버리지")
set_text(P(cov_title), "구역 기준 시설 커버리지(블록 내부 추가 구역 포함)")

# 4) 구역 규격 + 반납 처리 (3항 끝)
anchor = find("※ 지정 금지(예시)")
t1 = two_col_table(anchor, "가상주차구역 기본 규격(안)", [
    ("구역 크기", "보도형 및 연석 표시형은 폭 1.5m, 길이 3~5m(킥보드 4~6대), 주차면 전환형은 차량 1면"),
    ("지오펜스 여유폭", "표시 구역보다 도심 5m, 해안 10m 넓게 설정(GPS 오차 감안)"),
    ("구역당 수용", "일반 블록 4~6대, 관광 블록(② 중앙시장, ⑤ 해수욕장) 6~10대(관광지 반납 수요가 상업지 대비 약 1.65배, Meng et al., 2025)"),
    ("블록 총 수용", "1단계 블록 93개 기준 약 400~600대로, 킥보드 약 100대와 공유자전거를 충분히 수용"),
])
n1 = clone_para(note_tpl, "※ 작성자 일반안이며, 운영사 실무 기준과 현장조사로 조정", t1)
t2 = two_col_table(n1, "블록 안에서 지정구역 밖 반납 시 처리(안)", [
    ("1단계 안내", "반납 버튼을 비활성화하고 가장 가까운 구역까지 거리와 방향을 안내"),
    ("2단계 여유", "지오펜스 여유폭 안 반납은 허용"),
    ("3단계 확인", "경계 부근 반납은 사진 반납 인증으로 확인"),
    ("4단계 조치", "반복 위반 시 운영사 약관에 따른 추가요금 또는 이용 제한"),
    ("예외", "GPS 오류나 기기 고장은 고객센터에서 예외 처리하고 로그로 원인 기록"),
])

# 5) 운영사 참여 유인 (5항 운영)
op = next(t._tbl for t in d.tables if t.rows[0].cells[0].text.strip() == "주체")
o = clone_para(normal_tpl, "ㅇ (운영사 참여 유인) 기기 100대 규모에서 운영사가 구역 설정과 관리를 맡을 이유를 협약에 명시", op)
bullets(o, [
    "MaaS 앱 및 스테이션 연계로 관광객 노출과 대여 거점 확보(S1 터미널 등 스테이션 우선 사용)",
    "시범구역 운영 협약으로 사업 지속성 확보, 향후 PM법 등록제 전환 시 운영 실적으로 활용",
    "견인 및 민원 감소로 운영사의 견인료(1건 2만원) 부담 경감",
    "구역 설정은 지오펜스 입력뿐이며, 연석 표시 등 현장 표시 비용은 시와 운영사가 분담 협의",
])

# 6) 효과 측정 설계 (성과지표 앞)
kp = find("단계별 성과지표(안)").getprevious()
e = clone_para(normal_tpl, "ㅇ (효과 측정 설계) 실증 전 기준선을 먼저 확보해야 성과를 입증할 수 있음", kp)
bullets(e, [
    "(기준선) 실증 전 3개월간 블록 안팎의 PM 민원 및 견인 건수와 위치, 주 2회(평일과 주말 각 1회) 현장 무단주차 집계",
    "(준수율 정의) 블록 안 반납 중 반납 좌표가 지정구역 지오펜스 안인 비율, 매주 사진 반납 표본과 대조해 GPS 오차 보정",
    "(비교 설계) 블록 안과 밖, 시행 전과 후를 함께 비교해 계절 효과 등 외부 요인을 걸러냄",
    "(점검) 월 1회 운영사와 시가 공동 점검하고, 실증 종료 후 블록 경계와 구역을 확정",
])

# 7) 향후 추진 문구
p1 = P(find("① 공유자전거 운영사"))
set_text(p1, "① (착수 전제) 공유자전거 운영사 참여 의사와 운영 대수 확인. 확보되지 않으면 1단계는 킥보드만으로 스테이션이 있는 블록부터 축소 운영")
p3 = P(find("③ 경찰 협의"))
set_text(p3, "③ 경찰 협의(연석 표시 및 빗금구역 활용 지점)와 「속초시 개인형 이동장치 이용안전 증진 조례」 개정 검토")

# 8) 제도 경로 (리스크: 경찰 협의 아래)
rk = find("ㅇ (경찰 협의)")
bullets(rk, [
    "(법률 현황) PM법은 국회 국토교통위원회에서 통합 대안이 의결됐으나 '26.11월 현재 제정되지 않음. 대안에는 대여사업 등록제 전환, 대여 기기 최고속도 시속 20km 이하 등이 담김",
    "(사례) 서울시의회는 '26.9월 조례 개정으로 시장의 PM 지정주차구역 설치 및 운영 근거를 마련. 대구시는 '25.3월 국토교통부에 규제샌드박스 특례를 신청했으나 승인 결과는 확인 필요",
    "(경로) 1단계는 운영사 자율과 시 가이드라인으로 시작하고, 2단계에 속초시 조례 개정(가상주차구역 지정 근거, 이동조치 규정 신설)을 추진하며, PM법이 제정되면 대여사업 등록 조건과 연계",
])

# 9) 출처
src = find("Meng, S.")
s = clone_para(src, "블로터, 「'6년 표류' PM법…전문가·업계·시민, 안전·주차 해법 모색」 / 서울신문, 하남시의원 PM 법안 국회 계류 보도('26.11.18.)", src)
s = clone_para(src, "웹이코노미, 「서울시의회, 개인형 이동장치 지정주차구역 설치 근거 마련」('26.9.) / 전기신문, 퍼스널 모빌리티 업계 자율과 협력 보도(대구 샌드박스 신청)", s)

d.save(OUT)
print("saved")
