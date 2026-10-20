#!/usr/bin/env python3
"""kr-sti-data — 한국 과학기술·R&D 통계 수집기 묶음 (표준 라이브러리만).

  sti.py kosis  search 연구개발활동조사 | list [--parent A] | meta --tbl DT_… | fetch --tbl DT_… [--from 2010 --to 2024]
  sti.py nabo   tables | fetch --tbl T… | fetch --all
  sti.py ntis   status
  sti.py verify [--source kosis|nabo]
  sti.py export --source kosis --tbl DT_… --out x.csv
  sti.py status
  sti.py selftest

키: ~/.kr-sti/keys.json {"kosis": "...", "nabo": "...", "ntis": "..."} 또는 환경변수 KOSIS_API_KEY / NABOSTATS_API_KEY / NTIS_API_KEY.
(호환: ~/.kosis/key 파일도 읽는다.) 설계: docs/design.md
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path

__version__ = "0.1.0"
HERE = Path(__file__).resolve().parent
HOME = Path(os.environ.get("KR_STI_HOME", Path.home() / ".kr-sti"))
DB_PATH = Path(os.environ.get("KR_STI_DB", HOME / "sti.db"))
CATALOG = json.loads((HERE / "catalog.json").read_text(encoding="utf-8"))

KOSIS = "https://kosis.kr/openapi"
NABO = CATALOG["nabo"]["base"]
UA = f"kr-sti-data/{__version__}"
SLEEP_KOSIS = float(os.environ.get("KR_STI_KOSIS_SLEEP", "0.6"))   # 분당 호출 제한 공지 대응


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# 키
# ---------------------------------------------------------------------------

def get_key(source: str, required: bool = True) -> str:
    env = {"kosis": "KOSIS_API_KEY", "nabo": "NABOSTATS_API_KEY", "ntis": "NTIS_API_KEY"}[source]
    k = os.environ.get(env, "").strip()
    if not k and (HOME / "keys.json").exists():
        k = (json.loads((HOME / "keys.json").read_text(encoding="utf-8")).get(source) or "").strip()
    if not k and source == "kosis" and (Path.home() / ".kosis" / "key").exists():
        k = (Path.home() / ".kosis" / "key").read_text(encoding="utf-8").strip()
    if not k and required:
        where = {"kosis": "kosis.kr 회원 → 공유서비스 활용신청",
                 "nabo": "nabostats.go.kr 인증키 발급",
                 "ntis": "ntis.go.kr 로그인 → 소속기관 등록 → OpenAPI 활용신청(승인 대기)"}[source]
        sys.exit(f"{source} 인증키 없음 — {where} 뒤 ~/.kr-sti/keys.json 의 \"{source}\" 또는 환경변수 {env}")
    return k


# ---------------------------------------------------------------------------
# HTTP (urllib → certifi → curl)
# ---------------------------------------------------------------------------

def http_json(url: str, retries: int = 3):
    last = None
    for attempt in range(retries):
        for fn in (_urllib, _certifi, _curl):
            try:
                body = fn(url)
                if body is None:
                    continue
                return json.loads(body)
            except json.JSONDecodeError as e:
                last = RuntimeError(f"JSON 아님: {body[:120]!r}")
                break
            except Exception as e:      # noqa: BLE001
                last = e
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"요청 실패 {url.split('?')[0]} ({last})")


def _urllib(url, ctx=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=90, context=ctx) as r:
        return r.read().decode("utf-8")


def _certifi(url):
    try:
        import certifi, ssl  # noqa: PLC0415
    except ImportError:
        return None
    return _urllib(url, ssl.create_default_context(cafile=certifi.where()))


def _curl(url):
    p = subprocess.run(["curl", "-sS", "--max-time", "90", "-A", UA, url], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[:200])
    return p.stdout


def _redact(url: str) -> str:
    return url.split("apiKey=")[0].split("KEY=")[0]


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def open_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS kosis_meta(org TEXT, tbl TEXT, obj_sn TEXT, obj_id TEXT, obj_nm TEXT,
        itm_id TEXT, itm_nm TEXT, up_itm_id TEXT, fetched TEXT, PRIMARY KEY(org,tbl,obj_sn,itm_id));
    CREATE TABLE IF NOT EXISTS kosis_tables(org TEXT, tbl TEXT PRIMARY KEY, tbl_nm TEXT, prd_se TEXT,
        prd_start TEXT, prd_end TEXT, levels INT, fetched TEXT);
    CREATE TABLE IF NOT EXISTS kosis_cells(org TEXT, tbl TEXT, prd_de TEXT, itm_id TEXT, itm_nm TEXT,
        c1 TEXT, c1_nm TEXT, c2 TEXT, c2_nm TEXT, c3 TEXT, c3_nm TEXT, c4 TEXT, c4_nm TEXT,
        unit TEXT, dt TEXT, lst_chn_de TEXT, fetched TEXT,
        PRIMARY KEY(org,tbl,prd_de,itm_id,c1,c2,c3,c4));
    CREATE TABLE IF NOT EXISTS nabo_rows(tbl TEXT, year TEXT, grp TEXT, cls TEXT, itm TEXT, val TEXT, unit TEXT,
        fetched TEXT, PRIMARY KEY(tbl,year,grp,cls,itm));
    CREATE TABLE IF NOT EXISTS harvest(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, tbl TEXT, action TEXT,
        expected INT, got INT, note TEXT, at TEXT);
    """)
    return con


def log_harvest(con, source, tbl, action, expected, got, note=""):
    con.execute("INSERT INTO harvest(source,tbl,action,expected,got,note,at) VALUES(?,?,?,?,?,?,?)",
                (source, tbl, action, expected, got, note, now()))
    con.commit()


# ---------------------------------------------------------------------------
# KOSIS
# ---------------------------------------------------------------------------

def kosis_call(path: str, **params):
    params.setdefault("format", "json")
    params.setdefault("jsonVD", "Y")
    params["apiKey"] = get_key("kosis")
    time.sleep(SLEEP_KOSIS)
    d = http_json(f"{KOSIS}/{path}?" + urllib.parse.urlencode(params))
    if isinstance(d, dict) and "err" in d:
        if d.get("err") == "30":           # 데이터 없음
            return []
        raise RuntimeError(f"KOSIS 오류 {d.get('err')}: {d.get('errMsg')} ({path} {params.get('tblId','')})")
    return d


def kosis_search(args):
    d = kosis_call("statisticsSearch.do", method="getList", searchNm=args.query)
    print(f"| ORG | TBL_ID | 표 이름 | 통계 |\n|---|---|---|---|")
    for x in d:
        mark = " ★" if x.get("TBL_ID") in CATALOG["kosis"]["tables"] else ""
        print(f"| {x.get('ORG_ID')} | {x.get('TBL_ID')}{mark} | {x.get('TBL_NM')} | {x.get('STAT_NM')} |")
    print(f"\n{len(d)}건 (★ = catalog.json 등재). 검색 API는 상위 20건만 돌려주는 듯 — 더 좁게 검색")


def kosis_list(args):
    d = kosis_call("statisticsList.do", method="getList", vwCd=args.vw, parentListId=args.parent)
    for x in d:
        if x.get("TBL_ID"):
            print(f"  표  {x['ORG_ID']} {x['TBL_ID']}  {x['TBL_NM']}")
        else:
            print(f"  폴더 {x.get('LIST_ID')}  {x.get('LIST_NM')}")


def _kosis_meta(con, org: str, tbl: str, refresh=False):
    """ITM 메타에서 분류 수준(objL1..n)과 항목을 끌어낸다. 캐시."""
    rows = con.execute("SELECT obj_sn,obj_id,obj_nm,itm_id,itm_nm FROM kosis_meta WHERE org=? AND tbl=?", (org, tbl)).fetchall()
    if not rows or refresh:
        meta = kosis_call("statisticsData.do", method="getMeta", type="ITM", orgId=org, tblId=tbl)
        if not meta:
            raise RuntimeError(f"{tbl}: 메타 없음 — 표 ID 확인")
        tblmeta = kosis_call("statisticsData.do", method="getMeta", type="TBL", orgId=org, tblId=tbl)
        prd = kosis_call("statisticsData.do", method="getMeta", type="PRD", orgId=org, tblId=tbl)
        con.execute("DELETE FROM kosis_meta WHERE org=? AND tbl=?", (org, tbl))
        for m in meta:
            sn = "ITEM" if m.get("OBJ_ID") == "ITEM" else m.get("OBJ_ID_SN")
            con.execute("INSERT OR REPLACE INTO kosis_meta VALUES(?,?,?,?,?,?,?,?,?)",
                        (org, tbl, sn, m.get("OBJ_ID"), m.get("OBJ_NM"), m.get("ITM_ID"), m.get("ITM_NM"), m.get("UP_ITM_ID"), now()))
        levels = len({m.get("OBJ_ID_SN") for m in meta if m.get("OBJ_ID") != "ITEM"})
        p = prd[0] if prd else {}
        con.execute("INSERT OR REPLACE INTO kosis_tables VALUES(?,?,?,?,?,?,?,?)",
                    (org, tbl, (tblmeta[0].get("TBL_NM") if tblmeta else None), p.get("PRD_SE"),
                     p.get("STRT_PRD_DE"), p.get("END_PRD_DE"), levels, now()))
        con.commit()
        rows = con.execute("SELECT obj_sn,obj_id,obj_nm,itm_id,itm_nm FROM kosis_meta WHERE org=? AND tbl=?", (org, tbl)).fetchall()
    levels = OrderedDict()
    items = []
    for sn, oid, onm, iid, inm in rows:
        if sn == "ITEM":
            items.append((iid, inm))
        else:
            levels.setdefault(sn, (onm, []))[1].append((iid, inm))
    t = con.execute("SELECT tbl_nm,prd_se,prd_start,prd_end FROM kosis_tables WHERE tbl=?", (tbl,)).fetchone()
    return levels, items, t


def kosis_meta(args):
    con = open_db()
    levels, items, t = _kosis_meta(con, args.org, args.tbl, refresh=args.refresh)
    print(f"# {args.tbl} — {t[0]}  ({t[1]} {t[2]}~{t[3]})")
    for sn, (nm, its) in sorted(levels.items()):
        print(f"- objL{sn} {nm}: {len(its)}개  예) {', '.join(n for _, n in its[:6])}…")
    print(f"- 항목(itmId): {len(items)}개  {', '.join(n for _, n in items[:6])}")


def _year_chunks(start: int, end: int, size: int):
    y = start
    while y <= end:
        yield y, min(end, y + size - 1)
        y += size


def kosis_fetch(args):
    con = open_db()
    org = args.org
    tbls = [args.tbl] if args.tbl else (list(CATALOG["kosis"]["tables"]) if args.all else [])
    if not tbls:
        sys.exit("--tbl 또는 --all")
    for tbl in tbls:
        levels, items, t = _kosis_meta(con, org, tbl)
        if not t or not t[2]:
            print(f"! {tbl}: 시점 정보 없음, 건너뜀", file=sys.stderr)
            continue
        prd_se_code = {"년": "Y", "월": "M", "분기": "Q", "반기": "S"}.get(t[1], "Y")
        y0 = max(int(t[2][:4]), args.frm or 0)
        y1 = min(int(t[3][:4]), args.to or 9999)
        total = 0
        per_year = Counter()
        for a, b in _year_chunks(y0, y1, args.chunk):
            params = dict(method="getList", orgId=org, tblId=tbl, itmId="ALL", prdSe=prd_se_code,
                          startPrdDe=str(a), endPrdDe=str(b))
            for sn in levels:
                params[f"objL{sn}"] = "ALL"
            try:
                cells = kosis_call("Param/statisticsParameterData.do", **params)
            except RuntimeError as e:
                if args.chunk > 1 and ("21" in str(e) or "한도" in str(e) or "초과" in str(e)):
                    print(f"  ! {a}~{b} 실패({e}) → 연도 1개씩 재시도", file=sys.stderr)
                    cells = []
                    for y in range(a, b + 1):
                        params.update(startPrdDe=str(y), endPrdDe=str(y))
                        cells += kosis_call("Param/statisticsParameterData.do", **params)
                else:
                    raise
            for c in cells:
                row = (org, tbl, c.get("PRD_DE"), c.get("ITM_ID"), c.get("ITM_NM"),
                       c.get("C1", ""), c.get("C1_NM"), c.get("C2", ""), c.get("C2_NM"),
                       c.get("C3", ""), c.get("C3_NM"), c.get("C4", ""), c.get("C4_NM"),
                       c.get("UNIT_NM"), c.get("DT"), c.get("LST_CHN_DE"), now())
                con.execute("INSERT OR REPLACE INTO kosis_cells VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
                per_year[c.get("PRD_DE")] += 1
            total += len(cells)
            con.commit()
            print(f"  {tbl} {a}~{b}: {len(cells)}셀", file=sys.stderr)
        # 셀 수 상한 = 분류 조합 × 항목 × 연도. 실제는 빈 셀이 빠져 더 적다 → 상한 대비 비율만 적는다
        combos = 1
        for _, its in levels.values():
            combos *= len(its)
        upper = combos * len(items) * (y1 - y0 + 1)
        empty_years = [str(y) for y in range(y0, y1 + 1) if per_year.get(str(y), 0) == 0]
        log_harvest(con, "kosis", tbl, "fetch", upper, total,
                    f"{y0}-{y1}; 상한 대비 {total/upper:.0%}; 빈 연도 {len(empty_years)}" + (f" ({', '.join(empty_years[:8])})" if empty_years else ""))
        print(f"{tbl} 완료: {total}셀 ({y0}~{y1}), 상한 {upper} 대비 {total/upper:.0%}"
              + (f", 셀 0인 연도 {len(empty_years)}개: {', '.join(empty_years[:8])}" if empty_years else ""))
        if args.verbose and args.all is False:
            pass


# ---------------------------------------------------------------------------
# NABOSTATS
# ---------------------------------------------------------------------------

def nabo_envelope(env: dict):
    """응답 봉투 → (total, rows). 200 응답 안의 오류 봉투도 잡는다."""
    if isinstance(env, dict) and env.get("RESULT"):
        raise RuntimeError(f"NABOSTATS {env['RESULT'].get('CODE')}: {env['RESULT'].get('MESSAGE')}")
    svc = env.get("Sttsapitbldata") if isinstance(env, dict) else None
    if not isinstance(svc, list):
        raise RuntimeError(f"예상 밖 응답 구조: {json.dumps(env, ensure_ascii=False)[:200]}")
    head = (svc[0] or {}).get("head", []) if svc else []
    total = next((h["list_total_count"] for h in head if isinstance(h, dict) and "list_total_count" in h), None)
    res = next((h["RESULT"] for h in head if isinstance(h, dict) and "RESULT" in h), None)
    if res and res.get("CODE") != "INFO-000":
        raise RuntimeError(f"NABOSTATS {res.get('CODE')}: {res.get('MESSAGE')}")
    rows = (svc[1] or {}).get("row", []) if len(svc) > 1 else []
    out = [dict(year=str(r.get("WRTTIME_IDTFR_ID")), grp=r.get("GRP_NM") or "", cls=r.get("CLS_NM") or "",
                itm=r.get("ITM_NM") or "", val=r.get("DTA_VAL", r.get("DTA_SVAL")), unit=r.get("UI_NM")) for r in rows]
    return total, out


def nabo_tables(_args):
    print("| STATBL_ID | 표 | 출처 | 범위 |\n|---|---|---|---|")
    for k, v in CATALOG["nabo"]["tables"].items():
        print(f"| {k} | {v['name']} | {v['source']} | {v['scope']} |")


def nabo_fetch(args):
    key = get_key("nabo")
    con = open_db()
    tbls = [args.tbl] if args.tbl else list(CATALOG["nabo"]["tables"])
    for tbl in tbls:
        got, page, total = 0, 1, None
        while True:
            q = urllib.parse.urlencode(dict(STATBL_ID=tbl, DTACYCLE_CD="YY", Type="json", pIndex=page, pSize=1000, KEY=key))
            total, rows = nabo_envelope(http_json(f"{NABO}?{q}"))
            for r in rows:
                if r["val"] in (None, ""):
                    raise RuntimeError(f"{tbl} {r['year']} {r['grp']}/{r['cls']}/{r['itm']}: 값이 비어 있음 — 0으로 바꾸지 않고 멈춤")
                con.execute("INSERT OR REPLACE INTO nabo_rows VALUES(?,?,?,?,?,?,?,?)",
                            (tbl, r["year"], r["grp"], r["cls"], r["itm"], str(r["val"]), r["unit"], now()))
            got += len(rows)
            con.commit()
            if not rows or (total is not None and got >= total):
                break
            page += 1
        log_harvest(con, "nabo", tbl, "fetch", total, got, "" if total == got else f"결손 {total - got}")
        name = CATALOG["nabo"]["tables"].get(tbl, {}).get("name", "")
        print(f"{tbl} {name}: 공식 {total} / 수집 {got}" + ("" if total == got else f"  ! 결손 {total - got}"))


# ---------------------------------------------------------------------------
# NTIS (승인 전)
# ---------------------------------------------------------------------------

def ntis_status(_args):
    k = get_key("ntis", required=False)
    c = CATALOG["ntis"]
    print(f"NTIS OpenAPI: {c['portal']}")
    print("서비스:", " · ".join(c["services"]))
    print("승인:", c["approval"])
    print("키:", "있음" if k else "없음")
    print("어댑터:", c["status"])


# ---------------------------------------------------------------------------
# verify · export · status
# ---------------------------------------------------------------------------

def verify(args):
    con = open_db()
    print("| 소스 | 표 | 공식/상한 | 로컬 | 판정 |\n|---|---|---|---|---|")
    if args.source in (None, "nabo"):
        key = get_key("nabo", required=False)
        for (tbl,) in con.execute("SELECT DISTINCT tbl FROM nabo_rows"):
            local = con.execute("SELECT COUNT(*) FROM nabo_rows WHERE tbl=?", (tbl,)).fetchone()[0]
            if key:
                q = urllib.parse.urlencode(dict(STATBL_ID=tbl, DTACYCLE_CD="YY", Type="json", pIndex=1, pSize=1, KEY=key))
                total, _ = nabo_envelope(http_json(f"{NABO}?{q}"))
            else:
                total = con.execute("SELECT expected FROM harvest WHERE source='nabo' AND tbl=? ORDER BY id DESC LIMIT 1", (tbl,)).fetchone()
                total = total[0] if total else None
            ok = "일치" if total == local else f"결손 {total - local}" if total is not None else "공식값 없음(키 없음)"
            print(f"| nabo | {tbl} | {total} | {local} | {ok} |")
    if args.source in (None, "kosis"):
        for (tbl,) in con.execute("SELECT DISTINCT tbl FROM kosis_cells"):
            local = con.execute("SELECT COUNT(*) FROM kosis_cells WHERE tbl=?", (tbl,)).fetchone()[0]
            years = con.execute("SELECT MIN(prd_de),MAX(prd_de) FROM kosis_cells WHERE tbl=?", (tbl,)).fetchone()
            # KOSIS는 공식 총건수가 없다 → 최신 연도 1개를 다시 받아 로컬과 1:1 대조(표본 검증)
            levels, items, t = _kosis_meta(con, CATALOG["kosis"]["org"], tbl)
            params = dict(method="getList", orgId=CATALOG["kosis"]["org"], tblId=tbl, itmId="ALL", prdSe="Y",
                          startPrdDe=years[1], endPrdDe=years[1])
            for sn in levels:
                params[f"objL{sn}"] = "ALL"
            live = len(kosis_call("Param/statisticsParameterData.do", **params))
            loc_y = con.execute("SELECT COUNT(*) FROM kosis_cells WHERE tbl=? AND prd_de=?", (tbl, years[1])).fetchone()[0]
            ok = "최신 연도 일치" if live == loc_y else f"최신 연도 차이 {live - loc_y}"
            print(f"| kosis | {tbl} | {years[1]}년 {live}셀(실시간) | {local}셀({years[0]}~{years[1]}), {years[1]}년 {loc_y} | {ok} |")
    print("\nKOSIS는 공식 총건수를 주지 않아 최신 연도 재조회로 표본 대조한다. NABOSTATS는 list_total_count와 1:1.")


def export(args):
    con = open_db()
    out = Path(args.out)
    notes = []
    if args.source == "kosis":
        cols = ["org", "tbl", "prd_de", "itm_id", "itm_nm", "c1", "c1_nm", "c2", "c2_nm", "c3", "c3_nm", "c4", "c4_nm", "unit", "dt", "lst_chn_de", "fetched"]
        rows = con.execute(f"SELECT {','.join(cols)} FROM kosis_cells WHERE tbl=? ORDER BY prd_de,c1,c2,c3,c4,itm_id", (args.tbl,)).fetchall()
        meta = CATALOG["kosis"]["tables"].get(args.tbl, {})
    else:
        cols = ["tbl", "year", "grp", "cls", "itm", "val", "unit", "fetched"]
        rows = con.execute(f"SELECT {','.join(cols)} FROM nabo_rows WHERE tbl=? ORDER BY year,grp,cls,itm", (args.tbl,)).fetchall()
        meta = CATALOG["nabo"]["tables"].get(args.tbl, {})
    if not rows:
        sys.exit(f"{args.tbl}: 로컬에 없음 — 먼저 fetch")
    for b in CATALOG.get("breaks", []):
        if meta.get("scope") and any(meta["scope"].split("(")[0] in a for a in b["applies_to"]):
            notes.append(f"{b['year']}: {b['note']}")
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        if args.header_notes:
            f.write(f"# {args.tbl} {meta.get('name','')} | 출처 {meta.get('survey', meta.get('source',''))} | 연도 기준 {meta.get('year_basis','')} | 조회 {rows[0][-1][:10]}\n")
            for n in notes:
                f.write(f"# 시계열 단절 {n}\n")
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)
    print(f"→ {out} ({len(rows)}행)" + (f" · 단절 각주 {len(notes)}" if notes else ""))


def status(_args):
    con = open_db()
    print(f"DB {DB_PATH}")
    for s in ("kosis", "nabo", "ntis"):
        print(f"  {s} 키: {'있음' if get_key(s, required=False) else '없음'}")
    for tbl, n, mn, mx in con.execute("SELECT tbl,COUNT(*),MIN(prd_de),MAX(prd_de) FROM kosis_cells GROUP BY tbl"):
        print(f"  kosis {tbl}: {n}셀 {mn}~{mx}")
    for tbl, n, mn, mx in con.execute("SELECT tbl,COUNT(*),MIN(year),MAX(year) FROM nabo_rows GROUP BY tbl"):
        print(f"  nabo  {tbl}: {n}행 {mn}~{mx}")
    last = con.execute("SELECT source,tbl,action,expected,got,note,at FROM harvest ORDER BY id DESC LIMIT 5").fetchall()
    for r in last:
        print("  수집 기록:", r)


# ---------------------------------------------------------------------------
# selftest (네트워크 없이)
# ---------------------------------------------------------------------------

def selftest(_args=None) -> int:
    fails = 0
    # 1 NABOSTATS 봉투
    env = {"Sttsapitbldata": [{"head": [{"list_total_count": 2}, {"RESULT": {"CODE": "INFO-000", "MESSAGE": "ok"}}]},
                               {"row": [{"WRTTIME_IDTFR_ID": 2023, "GRP_NM": "g", "CLS_NM": "c", "ITM_NM": "i", "DTA_VAL": 1.5, "UI_NM": "억원"},
                                        {"WRTTIME_IDTFR_ID": 2024, "DTA_SVAL": "-", "UI_NM": "억원"}]}]}
    total, rows = nabo_envelope(env)
    if not (total == 2 and rows[0]["val"] == 1.5 and rows[1]["val"] == "-" and rows[1]["grp"] == ""):
        fails += 1; print("FAIL nabo envelope", total, rows)
    for bad in ({"RESULT": {"CODE": "ERROR-300", "MESSAGE": "키"}},
                {"Sttsapitbldata": [{"head": [{"RESULT": {"CODE": "INFO-200", "MESSAGE": "없음"}}]}]},
                {"foo": 1}):
        try:
            nabo_envelope(bad); fails += 1; print("FAIL nabo should raise", bad)
        except RuntimeError:
            pass
    # 2 카탈로그 무결성
    for src in ("kosis", "nabo"):
        for k, v in CATALOG[src]["tables"].items():
            if not v.get("name") or not v.get("verified_at"):
                fails += 1; print("FAIL catalog", src, k)
    if not CATALOG["kosis"]["org"].isdigit():
        fails += 1; print("FAIL org")
    # 3 연도 조각
    if list(_year_chunks(2010, 2024, 10)) != [(2010, 2019), (2020, 2024)]:
        fails += 1; print("FAIL chunks")
    # 4 키 경로 URL 가리기
    if "apiKey" in _redact("https://x/y?apiKey=SECRET") or "KEY" in _redact("https://x/y?KEY=SECRET"):
        fails += 1; print("FAIL redact")
    # 5 DB 스키마 (임시)
    global DB_PATH
    old = DB_PATH
    DB_PATH = Path(os.environ.get("TMPDIR", "/tmp")) / f"kr-sti-selftest-{os.getpid()}.db"
    try:
        con = open_db()
        con.execute("INSERT OR REPLACE INTO nabo_rows VALUES(?,?,?,?,?,?,?,?)", ("T", "2024", "g", "c", "i", "1", "u", now()))
        con.execute("INSERT OR REPLACE INTO nabo_rows VALUES(?,?,?,?,?,?,?,?)", ("T", "2024", "g", "c", "i", "2", "u", now()))
        if con.execute("SELECT COUNT(*) FROM nabo_rows").fetchone()[0] != 1:
            fails += 1; print("FAIL upsert")
        con.close()
    finally:
        DB_PATH.unlink(missing_ok=True)
        DB_PATH = old
    print(f"selftest: {fails} fail")
    return 1 if fails else 0


# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(prog="sti", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    k = sub.add_parser("kosis", help="KOSIS 통계").add_subparsers(dest="sub", required=True)
    p = k.add_parser("search"); p.add_argument("query"); p.set_defaults(fn=kosis_search)
    p = k.add_parser("list"); p.add_argument("--vw", default="MT_ZTITLE"); p.add_argument("--parent", default="A"); p.set_defaults(fn=kosis_list)
    p = k.add_parser("meta"); p.add_argument("--org", default=CATALOG["kosis"]["org"]); p.add_argument("--tbl", required=True)
    p.add_argument("--refresh", action="store_true"); p.set_defaults(fn=kosis_meta)
    p = k.add_parser("fetch"); p.add_argument("--org", default=CATALOG["kosis"]["org"]); p.add_argument("--tbl")
    p.add_argument("--all", action="store_true", help="catalog.json의 KOSIS 표 전부")
    p.add_argument("--from", dest="frm", type=int); p.add_argument("--to", type=int)
    p.add_argument("--chunk", type=int, default=10, help="한 호출에 묶는 연도 수"); p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=kosis_fetch)

    n = sub.add_parser("nabo", help="NABOSTATS").add_subparsers(dest="sub", required=True)
    n.add_parser("tables").set_defaults(fn=nabo_tables)
    p = n.add_parser("fetch"); p.add_argument("--tbl"); p.add_argument("--all", action="store_true"); p.set_defaults(fn=nabo_fetch)

    t = sub.add_parser("ntis", help="NTIS OpenAPI(승인 전)").add_subparsers(dest="sub", required=True)
    t.add_parser("status").set_defaults(fn=ntis_status)

    p = sub.add_parser("verify"); p.add_argument("--source", choices=["kosis", "nabo"]); p.set_defaults(fn=verify)
    p = sub.add_parser("export"); p.add_argument("--source", choices=["kosis", "nabo"], required=True); p.add_argument("--tbl", required=True)
    p.add_argument("--out", required=True); p.add_argument("--no-header-notes", dest="header_notes", action="store_false"); p.set_defaults(fn=export)
    sub.add_parser("status").set_defaults(fn=status)
    sub.add_parser("selftest").set_defaults(fn=lambda a: sys.exit(selftest(a)))
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    main()
