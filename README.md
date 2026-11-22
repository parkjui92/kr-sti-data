# kr-sti-data — 한국 과학기술·R&D 통계 수집기

KOSIS(연구개발활동조사·국가연구개발사업통계)와 NABOSTATS(국회예산정책처)를 **한 CLI**로 받아 로컬 SQLite에 쌓고, 행·셀 건수를 대조(`verify`)한 뒤 CSV로 냅니다. **NTIS는 현재 신청·키 설정 상태 안내만 지원하며, 과제·성과 수집 어댑터는 아직 없습니다.** Python 3.10 이상과 표준 라이브러리만 사용하며, API 키는 각자 준비합니다.

```bash
python3 sti.py kosis search 연구개발활동조사          # 표 ID 찾기
python3 sti.py kosis meta  --tbl DT_KBA0010           # 분류 수준·항목·시점
python3 sti.py kosis fetch --tbl DT_KBA0010           # 1991~최신 전부
python3 sti.py kosis fetch --all                      # catalog.json의 표 15개
python3 sti.py verify
python3 sti.py export --source kosis --tbl DT_KBA0010 --out rnd_by_sector.csv
```

## 언제 쓰면 좋은가 · 강점

| 업무 | 이 도구로 하는 일 | 결과를 읽을 때 주의 |
|---|---|---|
| R&D 투자 추이 분석 | 재원·주체·단계별 통계를 동일한 CLI로 반복 수집 | 총R&D와 정부R&D 집행을 구분 |
| 정책평가 입력자료 만들기 | 분류 코드·금액 단위·조회일을 보존한 긴 형식 CSV 출력 | 합계와 하위 항목을 함께 더하지 않기 |
| 정기 통계 업데이트 | 저장된 표를 다시 받고 건수 변화 점검 | 건수 일치가 모든 값의 정확성을 증명하지는 않음 |

장점은 표 ID와 수집 범위를 `catalog.json`으로 관리하고, 집계 기준이 바뀐 해의 각주를 자료와 함께 내보낸다는 점입니다. 화면에서 매번 내려받아 열을 맞추는 작업을 줄일 수 있습니다. 경제·정책 해석과 결측의 원인 판정은 사용자가 맡습니다.

## 설치부터 첫 CSV까지

```bash
git clone https://github.com/parkjui92/kr-sti-data.git
cd kr-sti-data
python3 sti.py selftest         # 키·인터넷 없이 기본 검사
python3 sti.py nabo tables      # 수집 가능한 표 목록
```

아래 「키」에 따라 발급한 키를 설정한 뒤 한 표부터 실행합니다.

```bash
python3 sti.py nabo fetch --tbl T183673001055637
python3 sti.py verify --source nabo
python3 sti.py export --source nabo --tbl T183673001055637 --out out/rnd-funding.csv
```

기대 결과는 재원별 총연구개발비 CSV입니다. `year`는 시점, `grp`·`cls`·`itm`은 분류, `val`은 원문 값, `unit`은 단위입니다. 행 수는 원천 통계 갱신에 따라 달라집니다. KOSIS CSV는 `prd_de`(시점), `c1_nm` 등(분류), `dt`(값), `unit`(단위)을 사용합니다.

CSV 첫머리의 `#` 줄은 출처·연도 기준·시계열 단절 각주입니다. pandas에서는 `pd.read_csv("out/rnd-funding.csv", comment="#", encoding="utf-8-sig")`로 읽을 수 있습니다. 각주 없는 CSV가 필요하면 `export`에 `--no-header-notes`를 붙이되 각주는 별도로 보관하세요.

기본 DB는 `~/.kr-sti/sti.db`입니다. 프로젝트별로 분리하려면 실행 전에 `KR_STI_DB`를 별도 파일 경로로 설정합니다. KOSIS는 성공한 연도 구간을, NABOSTATS는 공식 건수와 일치한 표 전체를 교체하므로 재수집 때 원천에서 사라진 행이 계속 남는 문제를 막습니다. KOSIS 여러 구간 중 후반 수집이 실패하면 앞서 성공한 구간은 이미 갱신되어 있을 수 있습니다.

## 왜

정책연구·사업평가에서 매번 KOSIS 화면에서 표를 내려받고 열 이름을 손으로 맞춥니다. 같은 표를 다시 받을 때 분류 코드가 바뀌었는지, 빠진 연도가 있는지 아무도 확인하지 않습니다. 이 도구는 **표 ID·분류·기준연도를 `catalog.json`에 데이터로 고정**하고, 받은 뒤 **수집 건수 기록과 재조회 점검 결과를 남깁니다**. kr-grant-trace(논문 추적)·정책평가 도구의 입력 바닥입니다.

## 소스

| 소스 | 받는 것 | 키 | 상태 |
|---|---|---|---|
| **KOSIS** `kosis.kr/openapi` | 연구개발활동조사(총R&D: 재원·비목·단계·주체·인력·기관), 국가연구개발사업통계(정부R&D 집행: 부처·단계·주체·지역·분야·연구책임자) — orgId 127 | kosis.kr 회원 → 공유서비스 활용신청 | **동작** (2026-10-20 15표 실수집) |
| **NABOSTATS** `nabostats.go.kr` | 재원·단계·기관별 연구개발비, 기술료, SCI 논문 성과(표 5종) | nabostats.go.kr 발급(로그인 뒤) | **동작** (2026-10-20 5표 실수집, list_total_count 1:1) |
| **NTIS OpenAPI** | 과제검색·성과검색·수행기관·연구보고서 등 8종 REST | NTIS 로그인 → **소속기관 등록 → 활용신청 → 승인(며칠)** | `ntis status`만. 승인·명세 뒤 어댑터 |
| PRISM(정책연구용역) | 74,129건 | 공공데이터포털 | [prism-db](https://github.com/parkjui92/prism-db)를 그대로 쓴다 |

KISTEP 통계 사이트(sts.kistep.re.kr)는 2026-10 현재 접속되지 않아 같은 통계를 KOSIS 경로로 받습니다.

## 키

`~/.kr-sti/keys.json`
```json
{"kosis": "…", "nabo": "…", "ntis": "…"}
```
또는 환경변수 `KOSIS_API_KEY` · `NABOSTATS_API_KEY` · `NTIS_API_KEY`. (호환: `~/.kosis/key`도 읽습니다.) 키는 저장소·산출물·로그 어디에도 들어가지 않습니다.

## KOSIS 어댑터가 하는 일

KOSIS 자료 API는 표마다 분류 수준(objL1~4)이 달라 호출 형식을 사람이 맞춰야 했습니다. 이 도구는 `getMeta type=ITM`에서 **분류 수준 수와 항목을 자동으로 읽어** `objL{n}=ALL`·`itmId=ALL`로 호출하고, 연도를 10년 단위로 쪼개 받습니다(실패하면 1년씩 재시도). 분당 호출 제한 공지(2026-02·07)에 맞춰 호출 사이에 0.6초 쉽니다(`KR_STI_KOSIS_SLEEP`).

## 정직성 규칙

- **verify 기록을 남긴다** — NABOSTATS는 `list_total_count`와 로컬 행수 1:1, KOSIS는 공식 총건수가 없어 **최신 연도를 다시 받아 표본 대조**. 수집마다 `harvest` 표에 기대/실제/비고가 쌓임
- **빈 값은 0으로 바꾸지 않고 멈춘다**
- **셀 0인 연도를 이름으로 적는다** — "상한 대비 66%"처럼 빈 셀 비율만으로는 결손인지 구조인지 모르니, 연도별 0건을 따로 보여 줌
- **시계열 단절을 각주로 붙인다** — `catalog.json`의 `breaks`(예: 2024년 R&D 예산 기준 변경, 약 1.8조원 재분류)가 export 머리에 자동으로 들어감
- **연도 기준(`year_basis`)을 표마다 명시** — 조사연도와 대상연도, 집행연도를 섞지 않게
- **코드 조각에 이름을 붙이지 않는다** — KOSIS 분류 코드(`AB01`)는 API가 준 이름(`일반회계`)만 옮김

## 카탈로그

`catalog.json`에 쓰는 표 ID·이름·출처·범위·연도 기준·대조일을 적습니다. 표를 더하려면 `kosis search`로 ID를 찾아 한 줄 추가하면 `fetch --all`에 들어갑니다. 코드는 건드리지 않습니다.

## 검증 상태 (2026-10-20)

- `kosis fetch --all` 15표 전수 수집(최장 1975~2024), `verify` 최신 연도 재조회 15/15 일치, 셀 0인 연도 0
- 상한 대비 55~100%는 결손이 아니라 과거 연도에 없던 분류(빈 셀을 KOSIS가 생략) — 그래서 "빈 연도"를 따로 센다
- `nabo fetch --all` 5표(56·172·200·22·33행) 공식 총건수와 1:1 일치
- NTIS는 활용신청 승인 뒤 실검증 예정

## 한계

- 현재 저장 형식은 연간 통계·분류 4수준까지입니다. 5수준 이상·비연간 표는 값 손실을 막기 위해 수집 전에 중단합니다.
- `verify`는 NABOSTATS 전체 행수, KOSIS 최신 연도의 셀 수를 비교합니다. 금액값 자체나 모든 과거 연도를 검증하지 않습니다.
- `--from`이 `--to`보다 크거나 `--chunk`가 0 이하이면 수집 전에 중단합니다.

- KOSIS 통합검색 API는 상위 20건만 돌려주는 듯 — 좁게 검색
- KOSIS 셀 수 상한은 문서에 없음 → 10년 단위 분할, 실패 시 1년 재시도
- NTIS는 소속기관 확인 승인이라 개인이 바로 못 씀. 어댑터는 승인 뒤
- Parquet 출력 없음(의존성 0 유지). CSV를 받아 쓰세요

## R&D 정책평가 도구 묶음에서의 위치

필요한 단계만 골라 사용할 수 있습니다. 아래 순서는 업무 흐름이며 자동으로 연결된 파이프라인은 아닙니다. 도구 사이에 자료를 옮길 때 식별자·단위·연도·분류를 확인하세요.

| 필요 | 도구 |
|---|---|
| 공식 통계 수집 | [kr-sti-data](https://github.com/parkjui92/kr-sti-data) |
| 과제번호로 논문 추적 | [kr-grant-trace](https://github.com/parkjui92/kr-grant-trace) |
| 논리모형·성과지표 설계 점검 | [rnd-program-logic](https://github.com/parkjui92/rnd-program-logic) |
| 인과효과 추정 전 설계 점검 | [policy-did](https://github.com/parkjui92/policy-did) |
| AI와 평가 문서 검토 | [rnd-eval-skills](https://github.com/parkjui92/rnd-eval-skills) |
| 예산표 금액 대조 | [won-diff](https://github.com/parkjui92/won-diff) |

## 라이선스

MIT. 통계 자료의 이용 조건은 각 기관(KOSIS 공공누리, NABOSTATS 이용약관)을 따릅니다.
