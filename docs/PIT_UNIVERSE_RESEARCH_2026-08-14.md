# Point-in-Time Universe 연구 전환 — 2026-08-14

## 왜 이 단계가 필요한가

현재 `replay_pool_v2.py`는 `research_universe()`로 **현재 시점의 유동성/시가총액 스크리너**에서 약 80개 종목을 고른 뒤 그 종목들의 10년 가격을 되감습니다. 이 방식은 지금 살아남고 커진 종목을 과거에도 알고 있었던 것처럼 취급할 수 있어 survivorship bias가 남습니다.

PIT 연구의 목적은 백테스트 날짜마다 **그때 실제로 투자 가능했던 종목 집합**만 후보로 허용하고, 이후 상장폐지·합병·티커변경된 종목도 데이터에서 사라지지 않게 하는 것입니다.

## V1 원칙

1. 기존 `static/replay_backtest_pool_v2.json`은 건드리지 않습니다.
2. Frozen Forward V1/V2/V3/V4 calibration/state를 읽거나 변경하지 않습니다.
3. PIT 데이터가 없을 때 오늘의 universe로 fallback하지 않습니다.
4. ticker를 영구 식별자로 쓰지 않습니다. `security_id`가 필수입니다.
5. membership window는 start/end 모두 포함합니다.
6. 신호일과 다음 시가 진입일이 모두 membership window 안에 있어야 신규 진입 자격이 생깁니다.
7. 상장폐지/합병 종목을 포함하는 가격 원본이 검증되지 않으면 `READY_FOR_PIT_REPLAY`가 될 수 없습니다.
8. community reconstructed membership는 sensitivity/diagnostic에는 쓸 수 있지만 최종 survivorship-free 증거로 승격하지 않습니다.

## 필요한 데이터는 두 종류

### 1) Historical membership / identity

필수 필드:

- stable `security_id`
- historical ticker
- membership `start_date`
- membership `end_date`
- source provenance
- 가능하면 exchange / company name

현 시점 공식 Nasdaq Symbol Directory는 현재 상장종목을 제공하므로 그것만으로는 과거 PIT universe가 되지 않습니다. Nasdaq Daily List는 신규상장, 상장폐지, 종목명/티커 변경 같은 corporate-action history를 제공하지만 라이선스/구독 데이터이므로 자동으로 무료 원본처럼 취급하지 않습니다.

### 2) Historical prices including inactive securities

전략이 Open/High/Low/Close/Volume과 200일 이동평균을 사용하므로 단순 월말 수익률 데이터로는 부족합니다. 상장폐지/합병된 종목도 당시 daily OHLCV와 corporate-action price basis가 남아 있어야 합니다.

CRSP 계열 데이터처럼 active/inactive US securities와 영구식별자를 함께 보존하는 research-grade source가 가장 깔끔한 후보지만, 라이선스가 필요한 외부 데이터이므로 repo에 있다고 가정하지 않습니다.

## Source tier

### Tier A — 최종 PIT 검증 가능

- 전체 목표기간 2017-01-01 ~ 2026-08-13 커버
- inactive/delisted securities 포함
- stable security identifier
- historical ticker mapping
- daily OHLCV
- corporate actions / 가격기준 처리 확인 가능
- 출처/라이선스 명시

### Tier B — 강한 보조검증

- membership는 신뢰 가능하지만 inactive OHLCV가 일부 누락되거나
- OHLCV는 있으나 identifier/corporate-action provenance가 불완전

이 경우 결과는 `DIAGNOSTIC_ONLY`이며 production promotion 근거로 단독 사용하지 않습니다.

### Tier C — 탐색용

- Wikipedia 등 community-reconstructed index history
- 현재 종목 리스트를 과거로 되감은 데이터
- delisted price coverage가 검증되지 않은 무료 API

아이디어 확인에는 쓸 수 있어도 `survivorship-free`라고 부르지 않습니다.

## 구현 상태

`pit_universe.py`
- membership window 파싱/검증
- stable ID 강제
- overlapping identity/ticker 충돌 차단
- 날짜별 membership 조회
- 신호일+진입일 동시 자격 검사
- source capability/coverage audit
- current-universe fallback 금지

`pit_universe_audit.py`
- `data/pit_universe/source_manifest.json`을 읽음
- 실제 membership 원본이 없거나 source가 VERIFIED가 아니면 `static/pit_universe_status.json`을 `BLOCKED_INCOMPLETE_PIT_DATA`로 생성
- Forward/production mutation 없음

현재 단계는 의도적으로 **BLOCKED**가 정상입니다. 검증된 원본을 확보하기 전에 빈 데이터를 current universe로 채워 넣지 않기 위해서입니다.

## 다음 구현 순서

1. membership + inactive-price source 결정
2. source manifest에 provenance/license/coverage/capability 기록
3. membership windows ingest
4. inactive securities OHLCV loader 추가
5. 별도 `replay_backtest_pool_pit_v1.json` 생성
6. 현재-universe replay와 PIT replay의 후보수/수익/MDD/연도별 차이를 감사
7. PIT에서도 살아남은 규칙만 Forward 연구와 함께 해석

Forward V2/V3/V4는 이 작업과 독립적으로 계속 미래 데이터를 누적합니다.
