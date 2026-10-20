# kr-sti-data 설계서 (2026-10-20)

## 한 문장

한국 과학기술·R&D 통계와 과제·성과 메타데이터를 **한 CLI**(`sti.py`)로 받아 로컬 SQLite에 쌓고 CSV/Parquet로 내보내는 수집기 묶음. 소스마다 어댑터 파일 하나, 공통 규약은 `fetch`(쿼터 가드·재개) · `verify`(공식 총건수 대조) · `export`. prism-db 패턴(표준 라이브러리·코드만 배포·키는 각자) 그대로.

## 왜 — GitHub에 없는 바닥

`NTIS korea` 검색 결과가 0★ 4건, 한국 STI 데이터 접근층이 비어 있다. kr-grant-trace(논문)·policy-did(정책평가)가 쓸 입력(사업·예산·과제·성과 시계열)이 이 바닥 위에 선다. rnd-fiscal-dashboard의 NABOSTATS 수집기(`fetch_data.mjs`)를 흡수해 살린다.

## 소스와 접근 경로 (2026-10-20 확인)

| 소스 | 무엇 | 접근 | 키 | 확인 상태 |
|---|---|---|---|---|
| **KOSIS** (kosis.kr) | 연구개발활동조사(총R&D), 국가연구개발사업 조사·분석, 과학기술통계 다수 | `statisticsList.do`(목록 트리) · `Param/statisticsParameterData.do`(자료, orgId·tblId·objL1~8·itmId·prdSe) · `statisticsBigData.do`(대용량, 4만 행↑ XLS만·20만 행↑ 불가). JSON 지원. **분당 호출 제한 공지(2026-02·07), HTTP 종료→HTTPS만** | kosis.kr 회원·활용신청 | 가이드 원문 확인. 표 ID는 키 받은 뒤 목록 API로 탐색 |
| **NABOSTATS** (국회예산정책처) | 재원별·단계별·기관별 연구개발비, 기술료, SCI 논문 성과 등 | `openapi/Sttsapitbldata.do?STATBL_ID=…&DTACYCLE_CD=YY&Type=json&pIndex&pSize=1000&KEY` 봉투 `Sttsapitbldata[0].head[list_total_count]` / `[1].row` | nabostats.go.kr 발급 | 수집기 실동작 이력 있음(대시보드). 표 5종 ID 보유 |
| **NTIS OpenAPI** (ntis.go.kr/rndopen) | ①국가R&D 과제검색 ②성과검색(논문·특허·장비) ③수행기관 현황 ④연구보고서 검색 ⑤이슈로보는R&D ⑥용어사전 ⑦표준분류코드 ⑧연관콘텐츠 추천 — 전부 REST | NTIS 로그인 → **소속기관 등록 → 활용신청 → 기관 확인 뒤 승인**(며칠) | NTIS 개인 키 | 목록 확인. 명세는 승인 뒤 매뉴얼에서 |
| **PRISM** | 정책연구용역 74,129건 | 기존 `prism-db` 그대로 | 공공데이터포털 키 | 운영 중. 재구현 안 함, `sti.py prism …`은 안내만 |
| data.go.kr | NTIS 수행기관 현황(대국민용) 등 LINK형 | 포털 키 | 포털 | NTIS 본 API의 부분집합 — 2차 |

**KISTEP 통계(sts.kistep.re.kr)** 는 DNS 불가(2026-10-20). 연구개발활동조사·조사분석 통계는 KOSIS 경로로 받는다.

## 명령

```
sti.py kosis   list [--parent A] [--search 연구개발]      # 목록 트리 탐색 → tblId 찾기
sti.py kosis   fetch --org 136 --tbl DT_… [--items ...] [--from 2010 --to 2024]
sti.py nabo    tables                                      # 보유 표 ID 카탈로그
sti.py nabo    fetch --tbl T183673001055637 [--all]
sti.py ntis    projects --q "인공지능" --year 2024          # 승인 뒤
sti.py ntis    outputs --project-no 1711…                  # 성과(논문·특허)
sti.py verify  [--source kosis|nabo|ntis]                  # 공식 총건수 대조표
sti.py export  --source … --table … --format csv|parquet
sti.py status                                              # 키·쿼터·마지막 수집·행수
sti.py selftest
```

## 공통 규약 (어댑터마다 같게)

- `catalog.yaml`: 소스별로 "우리가 쓰는 표"의 ID·이름·단위·기준연도 범위·조회일 — 코드가 아니라 데이터로
- `fetch`는 **페이지 진행을 SQLite에 기록**해 끊겨도 이어받음(prism `sweep_progress`)
- **쿼터 가드**: 소스별 일/분 한도를 설정에 두고 90%에서 멈춤, 다음 실행이 이어받음
- **verify = 공식 총건수(`list_total_count`·KOSIS 셀 수)와 로컬 행수 1:1** — 다르면 "결손 n건"을 숫자로 적는다
- **기준 변경 표시**: 2024년 R&D 예산 재분류(약 1.8조 非R&D 이관) 같은 시계열 단절은 `breaks.yaml`에 적고 export 머리에 각주로 붙인다
- 값이 비거나 형식이 다르면 **0으로 바꾸지 않고 멈춘다**(대시보드 규칙 계승)
- 키는 `~/.kr-sti/keys.toml` 또는 환경변수. 저장소·산출물에 절대 안 들어감

## 함정 사전 기록

- 연도 분할 수집의 조용한 결손(prism 26% 사례) → 가능하면 단일 광역 범위 페이징
- KOSIS 분당 호출 제한 → 호출 간 `sleep`, 429/오류 봉투에 지수 후퇴
- NABOSTATS 봉투가 오류를 `RESULT.CODE`로 200 응답에 싸서 보냄 → 코드 검사 필수
- 통계표의 기준연도 표류(조사연도 vs 대상연도) → `catalog.yaml`에 `year_basis` 명시
- NTIS 승인은 소속기관 확인이라 며칠 걸림 → NTIS 어댑터는 기록된 응답 픽스처로 먼저 짓고 키 받은 뒤 실검증

## 완료 기준

어댑터 3개(KOSIS·NABOSTATS·NTIS) 중 **키가 있는 2개 실수집** + `verify` 1:1 + 연구개발활동조사(재원·단계·기관) 2010~최신 시계열 1벌 export. NTIS는 승인 뒤.

## 필요한 것 (사용자)

1. KOSIS 인증키 — kosis.kr 회원가입 → 공유서비스 활용신청(자동승인) → `~/.kr-sti/keys.toml`의 `kosis`
2. NABOSTATS 인증키 — 대시보드 때 쓴 키가 있으면 그것(`nabo`)
3. NTIS OpenAPI — 로그인 → 회원정보에 소속기관 등록 → 과제검색·성과검색 활용신청(승인 대기)
