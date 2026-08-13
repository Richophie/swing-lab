# Swing Lab P0 Trading Structure · 2026-08-13

> 상태: 구현 배치 1  
> 목적: 전략 임계값을 미세조정하기 전에 데이터/성과측정/Paper 기준의 구조적 왜곡을 줄인다.

## 원칙

이번 배치에서는 RSI, 볼린저, 이동평균, RR 컷, BUY/TARGET/STOP 공식 같은 canonical 전략 숫자를 변경하지 않는다.

변경 대상은 다음 세 가지다.

1. 장중 미완성 거래량이 elite flow 점수를 시간 경과만으로 흔드는 문제
2. 실험전략이 공식 추천 성과에 섞일 수 있는 문제
3. 장중 mutable 후보에서 만든 Paper 주문이 공식추천 Paper와 구분되지 않는 문제

가격 corporate-action basis는 바로 변경하지 않고 감사 후 결정한다.

---

## 1. 장중 수급점수의 완성 세션 기준화

### 기존

형성 중인 오늘 daily bar의 거래량을 20일 완성 거래량과 직접 비교했다.

개장 초기에는 같은 종목도 RVOL/반전거래량이 낮아지고 시간이 지나면 자연스럽게 높아질 수 있다.

### 변경

미국장 당일 daily bar가 아직 16:05 ET 이전의 미완성 bar이면:

- 가격, RSI, 볼린저, 전략 strict signal: 현재 live bar 유지
- elite ranking의 `flow/liquidity quality`: 직전 **완성된 일봉** 기준 사용
- 현재 미완성 거래량 지표는 `live_flow`로 별도 저장
- `flow_basis = previous_completed_session` 기록

16:05 ET 이후 또는 마지막 일봉이 오늘의 미완성 bar가 아니면 현재 완성 세션 flow를 사용한다.

### 예외

`confirmed_pullback`의 strict `반전일 거래량 >= 1.0`은 이번 배치에서 완화하지 않는다.

이는 전략 자체의 확인 조건이므로 canonical rule 변경에 해당한다. 향후 intraday time-adjusted cumulative RVOL을 별도 실험한 뒤 OOS 검증을 거쳐 결정한다.

---

## 2. 공식 추천과 실험전략 성과 분리

### 기존 위험

`journal.py`는 experimental signal도 같은 day items에 freeze할 수 있었고 summary가 전체 닫힌 거래를 합산할 수 있었다.

### 변경

새 공식 마감추천 publication은 다음만 허용한다.

- `strategy_id in PUBLIC_STRATEGIES`
- `experimental == false`
- `elite_pass == true`
- 미국 동부 16:05 이후

새 공식 item에는:

- `performance_bucket = official_public`
- `publication_status = CONFIRMED_CLOSE`
- `signal_origin = daily_bar_close`

을 저장한다.

기존 legacy experimental item은 삭제하지 않는다. 대신:

- 공식 `summary`에서 제외
- `research_summary`로 별도 집계
- `performance_bucket = research_excluded`

로 표시한다.

공식 승률/평균수익률/추천수는 공개 3전략만 의미한다.

---

## 3. Paper 주문 출처 분리

현재 실시간 후보 상세에서 생성되는 Paper 주문은 공식 마감추천 주문이 아니다.

새 주문에는:

- `order_origin = LIVE_CANDIDATE`
- `signal_origin = intraday_latest_scan`

을 저장한다.

UI에서는 `장중 실험` 배지를 표시한다.

이 필드가 생기기 전에는 마감확정 history에서 Paper 주문을 만드는 경로가 없었으므로 기존 출처 미기록 주문은 `LIVE_CANDIDATE`로 자동 마이그레이션한다. 마이그레이션된 주문에는 `origin_migrated = true`를 남긴다.

향후 `CONFIRMED_CLOSE` 전용 Paper 진입경로를 추가한 뒤 두 성과표를 완전히 별도로 비교한다.

---

## 4. Corporate-action price basis audit

현재 canonical history는 Yahoo/yfinance `auto_adjust=False`를 사용한다.

이를 즉시 `auto_adjust=True`로 바꾸지 않는다. auto-adjust는 OHLC 전체의 의미를 바꾸므로 전략/백테스트 결과 자체가 달라질 수 있다.

`corporate_action_audit.py`로 다음 split 이력이 많은 대표 종목을 점검했다.

- AAPL
- NVDA
- TSLA
- AMZN
- GOOGL

감사 항목:

- split event date/ratio
- raw close의 split 전후 overnight return
- auto-adjusted close의 같은 구간 return
- raw/adjusted series 차이

### 2026-08-13 감사 결과

확인된 대표 split:

- AAPL 2020-08-31 · 4:1
- NVDA 2021-07-20 · 4:1 / 2024-06-10 · 10:1
- TSLA 2020-08-31 · 5:1 / 2022-08-25 · 3:1
- AMZN 2022-06-06 · 20:1
- GOOGL 2022-07-18 · 20:1

이 모든 split event에서 현재 Yahoo raw `Close`는 split ratio만큼 기계적으로 폭락/폭등하는 불연속을 보이지 않았고, split 당일 raw와 auto-adjusted overnight return은 동일했다.

따라서 **주식분할 연속성만을 이유로 canonical history를 auto-adjust=True로 바꿀 근거는 발견하지 못했다.**

현재 가격 basis는 유지한다. auto-adjust는 배당 등의 조정까지 OHLC에 반영하므로 별도 연구 없이 기술적 가격계열을 변경하지 않는다.

감사 artifact: `corporate-action-audit` / `artifacts/corporate_action_audit.json`.

---

## 5. 테스트 게이트

`tests/test_p0_structure.py`가 다음을 강제한다.

1. 미완성 US daily bar에서 elite flow는 직전 완성세션을 사용
2. 장 마감 이후에는 현재 세션 flow 사용
3. experimental signal은 공식 journal publication에서 제외
4. 공식 summary와 research summary 분리
5. live-candidate Paper 주문에 연구 출처 저장
6. 실제주문 플래그는 계속 false

기존 CI도 그대로 유지한다.

- canonical strategy parity
- Backtest V2
- Backtrader audit
- Paper lifecycle
- Paper mark-to-market
- browser restore
- signal history
- startup stability
- UI regression
- real 10y × 20 stocks × 3 strategies audit

---

## 6. 다음 배치 P1 우선순위

P0 통과 뒤 다음 순서로 실험한다.

1. `net_risk_reward` — 비용 반영 RR
2. 구조적 STOP을 억지로 1.5 ATR까지 넓히지 않는 대안
3. 전략별 gap guard
4. earnings/event risk flag
5. liquid universe 확장 + dollar-volume/spread 중심 필터
6. 전략별 market regime
7. sector/correlation concentration penalty

각 변경은 한 번에 하나씩 baseline과 OOS/Walk-forward 비교 후 승격한다.
