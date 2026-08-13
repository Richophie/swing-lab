# Earnings Event Data Audit · 2026-08-13

> 상태: 데이터 품질 검증 완료 / **informational EVENT RISK 기능 승격 가능**  
> 원칙: 실적일 데이터 하나만으로 거래를 hard-exclude하지 않는다.

## 1. 1차 60종목 감사

객관적 current-liquid prefilter 상위 60종목을 조회했다.

- upcoming earnings date 확인: **59/60 (98.33%)**
- 10일 이내: 3종목
- 30일 이내: 10종목
- `Ticker.calendar`는 높은 커버리지를 보였다.
- `get_earnings_dates()`는 CI에 `lxml`이 없어 전부 실패했다.

따라서 이 단계에서는 교차검증을 할 수 없었고 production 승격을 보류했다.

## 2. 2차 교차검증 · 20종목

`lxml`을 audit-only dependency로 설치하고 대표 유동주 20개를 두 경로로 다시 조회했다.

- any upcoming date: **20/20 = 100%**
- both sources available: **20/20 = 100%**
- 두 경로가 1일 이내 일치: **20/20 = 100%**
- 실제 day difference: 전부 0일

검증 경로:

1. `Ticker.get_earnings_dates()`
2. `Ticker.calendar`

예시:

- NVDA: 2026-08-26 / 두 경로 일치
- WMT: 2026-08-20 / 두 경로 일치
- AVGO: 2026-09-02 / 두 경로 일치

## 3. Production 결정

### 허용

엄선 통과 후보에 한해 다음 정보를 캐시하여 표시한다.

- 다음 실적 예정일
- 남은 달력 일수
- 예상 보유기간 안에 실적이 들어오는지
- 데이터 신뢰도: `confirmed / single_source / conflicting / unavailable`

### 금지

- 실적일 때문에 전략 S 신호를 제거하지 않음
- 실적일 때문에 elite score를 감점하지 않음
- 실적일 때문에 BUY/TARGET/STOP을 변경하지 않음
- 전체 500~1500종목을 페이지 렌더 시 동기 조회하지 않음

## 4. 운영 구조

**scanner가 엄선 통과 후보를 만든 뒤 → 후보 소수만 조회 → `static/earnings_cache.json`에 저장 → UI는 캐시만 읽는다.**

권장 cache TTL: 12시간.

조회가 실패하면 마지막 정상 cache를 유지하고 `stale` 상태를 표시한다.

## 5. EVENT RISK 정의

경고는 정보용이다.

- `IMMINENT`: 실적까지 0~3일
- `WITHIN_HOLD`: 예상 최대 보유기간을 달력일로 환산한 창 안에 실적 존재
- `UPCOMING`: 14일 이내지만 예상 보유창 바깥
- `CLEAR`: 그보다 멀리 있음
- `UNKNOWN`: 날짜 확인 실패/충돌

실적발표는 overnight gap으로 STOP을 뛰어넘을 수 있으므로, 사용자가 실제 주문 여부를 결정할 때 별도 위험요인으로 보여준다.

## 6. 다음 단계

1. cache-first earnings event module 추가
2. scanner에서 elite 후보만 enrich
3. 카드/상세에 EVENT RISK 배지 표시
4. hard gate 없음
5. 기능 검증 후 universe의 dollar-liquidity/spread 연구로 이동
