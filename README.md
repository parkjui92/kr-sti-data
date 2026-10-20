# kr-sti-data — 한국 과학기술·R&D 통계 수집기

KOSIS(연구개발활동조사·국가연구개발사업통계)·NABOSTATS(국회예산정책처)·NTIS 오픈API를 **한 CLI**로 받아 로컬 SQLite에 쌓고, 공식 건수와 대조(`verify`)한 뒤 CSV로 냅니다. 표준 라이브러리만, 코드만 배포, 키는 각자.

```bash
python3 sti.py kosis search 연구개발활동조사          # 표 ID 찾기
python3 sti.py kosis meta  --tbl DT_KBA0010           # 분류 수준·항목·시점
python3 sti.py kosis fetch --tbl DT_KBA0010           # 1991~최신 전부
python3 sti.py kosis fetch --all                      # catalog.json의 표 15개
python3 sti.py verify
python3 sti.py export --source kosis --tbl DT_KBA0010 --out rnd_by_sector.csv
```

## 왜

정책연구·사업평가에서 매번 KOSIS 화면에서 표를 내려받고 열 이름을 손으로 맞춥니다. 같은 표를 다시 받을 때 분류 코드가 바뀌었는지, 빠진 연도가 있는지 아무도 확인하지 않습니다. 이 도구는 **표 ID·분류·기준연도를 `catalog.json`에 데이터로 고정**하고, 받은 뒤 **공식 건수와 1:1 대조한 기록을 남깁니다**. kr-grant-trace(논문 추적)·정책평가 도구의 입력 바닥입니다.

## 소스

| 소스 | 받는 것 | 키 | 상태 |
|---|---|---|---|
| **KOSIS** `kosis.kr/openapi` | 연구개발활동조사(총R&D: 재원·비목·단계·주체·인력·기관), 국가연구개발사업통계(정부R&D 집행: 부처·단계·주체·지역·분야·연구책임자) — orgId 127 | kosis.kr 회원 → 공유서비스 활용신청 | **동작** (2026-10-20 15표 실수집) |
| **NABOSTATS** `nabostats.go.kr` | 재원·단계·기관별 연구개발비, 기술료, SCI 논문 성과(표 5종) | nabostats.go.kr 발급 | 수집기 이식 완료, 키 있을 때 실검증 |
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

KOSIS 자료 API는 표마다 분류 수준(objL1~8)이 달라 호출 형식을 사람이 맞춰야 했습니다. 이 도구는 `getMeta type=ITM`에서 **분류 수준 수와 항목을 자동으로 읽어** `objL{n}=ALL`·`itmId=ALL`로 호출하고, 연도를 10년 단위로 쪼개 받습니다(실패하면 1년씩 재시도). 분당 호출 제한 공지(2026-02·07)에 맞춰 호출 사이에 0.6초 쉽니다(`KR_STI_KOSIS_SLEEP`).

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
- NABOSTATS·NTIS는 키·승인 뒤 실검증 예정

## 한계

- KOSIS 통합검색 API는 상위 20건만 돌려주는 듯 — 좁게 검색
- KOSIS 셀 수 상한은 문서에 없음 → 10년 단위 분할, 실패 시 1년 재시도
- NTIS는 소속기관 확인 승인이라 개인이 바로 못 씀. 어댑터는 승인 뒤
- Parquet 출력 없음(의존성 0 유지). CSV를 받아 쓰세요

## 라이선스

MIT. 통계 자료의 이용 조건은 각 기관(KOSIS 공공누리, NABOSTATS 이용약관)을 따릅니다.
