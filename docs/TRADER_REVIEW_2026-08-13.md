# Swing Lab Trader Review · 2026-08-13

> 목적: 현재 공개 3전략과 종목선정/체결/포트폴리오 규칙을 **실전 트레이더의 실행 가능성, 리스크, 데이터 품질, 과최적화 위험** 관점에서 재검토한다.  
> 상태: 연구/개선 backlog. 이 문서의 제안은 아직 라이브 규칙이 아니다. 실제 임계값 변경은 `VALIDATION_PROTOCOL.md`의 OOS/Walk-forward 승격 절차를 통과해야 한다.

## 결론 요약

현재 Swing Lab의 큰 방향은 타당하다.

- 장기 추세 안의 눌림/평균회귀/모멘텀 재개를 분리한다.
- BUY/TARGET/STOP을 사전에 고정한다.
- 다음 시가 체결과 gap risk를 모델링한다.
- Paper와 Backtest에 비용을 반영한다.
- 장중 후보와 마감 확정 추천을 분리한다.
- 한 종목의 결과를 보고 임계값을 즉흥 조정하지 않는다.

다만 현재 성능을 더 정교하게 만들려면 **새 지표를 많이 추가하기보다 데이터/실행/리스크의 구조적 왜곡을 먼저 제거**해야 한다.

---

# P0 · 규칙 튜닝 전에 먼저 바로잡을 것

## P0-1. 장중 거래량의 시간대 편향

현재 `strategy_engine.py` / `scanner.py`의 수급 품질은 형성 중인 당일 거래량을 20일의 완성된 하루 거래량과 직접 비교한다.

문제:

- 미국장 개장 직후에는 오늘 거래량이 당연히 작다.
- 시간이 지나면 같은 종목도 별다른 질적 변화 없이 RVOL 점수가 자연스럽게 올라간다.
- `confirmed_pullback`은 반전일 거래량 >= 1.0이 strict 조건이어서 장중에는 특히 시간대 영향이 크다.
- 장중 ENTER/EXIT 일부가 가격 변화가 아니라 **시계가 진행된 효과**일 수 있다.

개선 후보:

A. 장중에는 intraday RVOL을 사용한다.

- 같은 시각까지의 과거 평균 누적거래량 대비 현재 누적거래량
- 예: 11:00 ET 현재 누적거래량 / 최근 20일 11:00 ET 평균 누적거래량

B. intraday 데이터 비용이 너무 크면:

- 공식 close-confirmed 추천에는 현재 일봉 거래량 사용
- 장중 엄선에서는 오늘 미완성 거래량을 hard gate에서 제거
- 이전 완성일 기준 5/20일 거래량, 평균 거래대금, 상승/하락 거래량을 주로 사용
- 당일 거래량은 정보 표시만 하고 점수 반영은 장 후반으로 제한

우선순위: **최상**.

---

## P0-2. 가격 히스토리의 corporate-action 정합성

현재 `market_data.py`의 Yahoo history는 `auto_adjust=False`를 사용한다.

검증 필요:

- 주식분할/병합 시점 전후의 OHLC가 장기 이동평균, ATR, RSI, 10년 Backtest에 연속적인 가격계열로 사용 가능한지 종목별 확인
- 필요하면 전략 지표/백테스트는 split-adjusted OHLC를 사용
- 실제 주문 가격/현재가 표시는 raw price를 별도 유지

원칙:

**지표용 가격계열과 실제 주문가격계열을 혼동하지 않는다.**

우선순위: **최상**. 장기 백테스트 신뢰도 문제이므로 임계값 미세조정보다 먼저 검증한다.

---

## P0-3. 공식 추천 성과와 실험전략 성과 분리

현재 `journal.py`는 experimental 신호도 journal에 freeze할 수 있고 summary는 닫힌 거래 전체를 집계한다.

개선:

- `official_public`과 `experimental` 성과 집계를 완전히 분리
- 메인 성공률/평균수익률/추천 수에는 공개 3전략만 사용
- 실험 전략은 별도 Research 성과표에서만 표시

원칙:

**연구 중 전략이 공식 추천 성과를 좋게도 나쁘게도 오염시키지 못하게 한다.**

우선순위: **최상**.

---

## P0-4. Paper Broker의 기준 신호 정의

현재 Paper 주문은 `latest_scan.json`의 현재 신호에서 제출할 수 있다. 따라서 장중 mutable 후보를 Paper에 넣는 경우 공식 `CONFIRMED_CLOSE` 성과와 기준이 달라질 수 있다.

권장 구조:

- 기본 모드: `OFFICIAL PAPER` — 마감 확정 추천만 주문 가능
- 별도 연구 모드: `LIVE CANDIDATE PAPER` — 장중 후보를 대상으로 실험
- 두 성과표는 섞지 않음

이유:

Paper의 목적은 라이브 주문 전에 **공식 시스템의 실제 체결 lifecycle**을 재현하는 것이므로 기준 신호가 공식 성과와 같아야 한다.

---

# P1 · 실전 성과에 직접 영향을 줄 가능성이 큰 개선

## P1-1. 공통 gap guard를 전략별로 분리

현재:

- `ENTRY_GAP_ATR = 0.75`
- `ENTRY_GAP_PCT = 1%`
- 허용 여유는 둘 중 큰 값

문제:

BUY 구간 자체보다 gap guard가 훨씬 넓을 수 있다.

예: RSI2 BUY는 anchor ±0.12 ATR인데 체결 허용은 BUY 밖으로 최대 0.75 ATR 수준까지 넓어진다. 신호가 발생한 가격 위치와 실제 진입 위치가 다른 거래가 될 수 있다.

연구 후보:

- RSI2: 가장 엄격한 gap tolerance
- confirmed pullback: 지지선 아래/위 방향을 비대칭 처리
- momentum pullback: 상승 gap은 일부 허용하되 과한 추격은 거절

테스트 grid 예시:

- 0.20 ATR
- 0.35 ATR
- 0.50 ATR
- 현재 0.75 ATR

단, 숫자는 OOS 결과 전에는 승격하지 않는다.

---

## P1-2. Gross RR 대신 비용 반영 Net RR

현재 엄선 hard gate는 `risk_reward >= 1.20`이다.

하지만 실제 Backtest/Paper는:

- commission
- slippage
- half spread

를 양쪽 체결에 적용한다.

따라서 엄선 단계에서도:

- 예상 entry fill
- target exit 비용
- stop exit 비용

을 넣은 `net_risk_reward`를 계산하는 것이 일관적이다.

연구:

- gross RR와 net RR의 통과 종목 차이
- net RR 1.20 / 1.30 / 1.40 sensitivity

핵심은 단순히 컷을 올리는 것이 아니라 **선정과 체결 모델의 비용 가정을 같은 언어로 맞추는 것**이다.

---

## P1-3. 전략별 market regime

현재 공개 3전략 모두 시장 `조심`이면 strict 진입 불가다.

하지만 세 전략의 위험은 다르다.

### RSI2 mean reversion

- 패닉 하락 후 반등에서 기회가 커질 수 있음
- 동시에 falling knife 위험도 큼
- 시장 변동성/유동성 상태를 별도 사용해야 함

### momentum pullback

- 강한 추세 시장에서 유리
- 큰 하락 뒤 급반등하는 panic/rebound 구간에서는 momentum crash 위험이 커질 수 있음

### confirmed pullback

- 추세선 지지가 실제 작동하는 정상/중립 시장과 구조적 붕괴 시장을 구분할 필요

연구 후보:

- SPY/QQQ 장기 추세
- SPY 20일 drawdown
- VIX 또는 realized volatility percentile
- 현재 코드의 `panic_setup`

처음부터 복잡한 새 regime model을 만들지 말고 **현재 market state + volatility/panic 1개 변수**부터 실험한다.

---

## P1-4. 실적발표/중요 이벤트 risk gate

3~10일 swing은 overnight gap에 민감하다. STOP은 장중 가격 리스크를 통제하지만 실적발표 gap은 stop price를 뛰어넘을 수 있다.

권장:

- 다음 earnings date가 예상 최대 보유기간 안에 있으면 기본 엄선 제외 또는 `EVENT RISK` 별도 상태
- 이미 보유 중인 경우 실적 전 청산 정책을 독립 실험
- earnings 직후 전략은 일반 mean-reversion과 분리하여 별도 이벤트 전략으로 연구

실적발표 데이터가 불확실하면 hard gate보다 경고로 시작하고 데이터 신뢰도를 먼저 측정한다.

---

## P1-5. Universe를 시총 중심에서 실행가능성 중심으로

현재 main universe:

- 미국 상장 operating company
- ETF 제외
- price >= $5
- avg daily volume >= 500k shares
- market cap >= $2B
- market cap 기준 상위 최대 500개

장점:

- 거래 가능한 대형주 중심
- 데이터/스캔 비용 낮음
- 극단적 microcap 회피

문제:

- `500k shares`는 가격에 따라 실제 유동성이 크게 다르다.
- 상위 시총 500개 제한은 충분히 유동적인 mid-cap 기회를 많이 제외할 수 있다.
- 3백만원급 계좌에서 중요한 것은 시총 자체보다 실제 체결 유동성/스프레드다.

연구 후보:

- 800 / 1000 / 1500 종목 후보군
- 최소 20일 평균 dollar volume
- daily OHLC 기반 effective-spread proxy
- market cap은 낮은 우선순위 안전필터로 사용

추천 방향:

**시장가치보다 dollar liquidity + estimated spread를 먼저 보자.**

---

## P1-6. 포트폴리오 상관위험

현재:

- 최대 3포지션
- 거래당 계획손실 1%
- 종목당 최대 40%

문제:

AAPL / NVDA / AMD처럼 같은 factor/sector에 몰리면 세 개의 1% risk가 사실상 하나의 방향성 베팅이 된다.

연구 후보:

- 같은 sector 최대 2개
- 최근 60일 수익률 상관계수 > 0.75인 후보끼리 동시선정 패널티
- 이미 보유한 포지션과 상관이 높은 신규 후보의 sizing 감소

처음에는 hard reject보다 ranking penalty가 안전하다.

---

## P1-7. Paper/실전 성과에서 주식 수익과 FX 분리

현재 Paper KRW 손익은 USD/KRW 변화까지 포함할 수 있다.

실제 체감손익에는 맞지만 전략 자체 품질을 평가할 때는 혼합효과다.

별도 기록 권장:

- `price_return_pct_usd`
- `fx_effect_krw`
- `total_pnl_krw`

공식 전략 승률/기대값은 USD price return 기준을 우선하고, 사용자 계좌 체감손익은 KRW 기준을 병기한다.

---

# P2 · 점수/신호 품질 미세조정

## P2-1. 점수의 중복정보 줄이기

현재 elite score는 전략 품질 68% + 수급 22% + RR 10%다.

그러나 전략 품질 자체에 RSI/거래량/추세가 이미 들어 있고 flow에도 거래량이 다시 들어간다. 20일선 첫 눌림 overlay도 추세/가격위치를 다시 보상한다.

즉 서로 독립적이지 않은 증거가 여러 번 가산될 수 있다.

차기 score architecture 후보:

1. `SETUP` — 전략 자체 price pattern
2. `EXECUTION` — entry location / gap / RR / stop distance
3. `LIQUIDITY` — dollar volume / estimated spread
4. `REGIME` — market / volatility
5. `EVENT` — earnings/news gap risk

각 bucket 내부 변수는 많아도 최종 합성 단계에서는 bucket이 서로 덜 중복되게 한다.

---

## P2-2. 20일선 첫 눌림 +6 bonus 검증

현재 overlay는 논리적으로 매력적이지만 +6이라는 숫자가 독립 OOS 검증을 거쳤다는 근거는 아직 없다.

연구:

- overlay 없는 baseline
- flag만 표시
- +3 / +6 / hard condition

OOS 기대값과 MDD가 실제 개선되는지 확인 후 유지한다.

---

## P2-3. 전략별 exit invalidation

현재 기본 exit은 STOP / TARGET / max hold다.

추가 실험 가치가 있는 조건:

### confirmed pullback
- 120일선 종가 이탈 + 반등 실패

### RSI2
- RSI2/RSI가 빠르게 정상화되었는데 가격이 못 오르는 failure-to-bounce

### momentum
- 20일선 재이탈 + MACD 재악화

주의:

동적 exit을 추가할수록 과최적화 위험이 빠르게 커진다. 반드시 baseline보다 명확한 OOS 개선이 있을 때만 승격한다.

---

# 현재 계좌 모델에 대한 트레이더 관점 메모

현재 기본 Paper/Portfolio model은 **총자금 300만원**, 한 종목 최대 40%다.

즉 300만원 계좌에서는 한 종목의 명목 최대 투입금이 약 120만원이고, 세 포지션이 동시에 열릴 수 있다. 이것은 `한 번의 주문에 300만원을 모두 투입하는 모델`과 다른 실험이다.

향후 UI에서 계좌 실험 모드를 명확히 구분할 가치가 있다.

- `300만원 총계좌 / 3포지션 분산`
- `300만원 1회 포지션 / 단일거래 성과`

둘은 전략 신호가 같아도 실제 원화 손익과 자본회전율이 다르다.

---

# 실험 순서 제안

새 지표를 한꺼번에 넣지 않는다.

## Phase A · 데이터/평가 정합성

1. split-adjusted price 검증
2. public vs experimental journal 분리
3. Paper official/live 모드 분리
4. USD alpha vs FX P&L 분리

## Phase B · 실행 품질

5. intraday volume time normalization
6. strategy-specific gap tolerance
7. cost-adjusted net RR
8. earnings/event risk flag

## Phase C · 후보군/포트폴리오

9. dollar-volume/spread 기반 universe 확대 실험
10. sector/correlation concentration control
11. strategy-specific regime

## Phase D · 신호 미세조정

12. elite score bucket 재설계
13. first-20DMA overlay 검증
14. dynamic invalidation exit

각 단계는 baseline과 **한 번에 하나의 변경만** 비교한다.

---

# 승격 판단 지표

최소:

- pooled OOS expectancy
- Profit Factor
- MDD
- trade count
- 최근 2년
- bull / neutral / panic regime
- sector concentration
- average turnover
- cost-adjusted result
- gap-loss tail
- parameter-neighborhood robustness

하나의 숫자가 최고인 설정보다 **근처 파라미터에서도 비슷한 성능을 내는 안정적인 plateau**를 우선한다.

---

# 외부 연구 참고

이 검토에서 방향성을 확인한 연구:

- Nagel, Stefan. “Evaporating Liquidity.” Review of Financial Studies 25(7), 2012. Short-term reversal과 liquidity provision / VIX 상태의 연결.
- Wang, Huijun and Yu, Jianfeng. “Short-term Momentum.” Review of Financial Studies 35(3), 2022. 저 turnover에서는 단기 reversal, 고 turnover·대형·유동주에서는 단기 momentum이 강한 패턴.
- Daniel, Kent and Tobias Moskowitz. “Momentum Crashes.” NBER / Journal of Financial Economics. 시장 급락·고변동성 이후 반등 국면의 momentum crash 위험.
- Barroso, Pedro and Pedro Santa-Clara. “Momentum Has Its Moments.” Journal of Financial Economics 116(1), 2015. momentum risk가 시간가변적이며 volatility management의 효용을 제시.
- Abdi, Farshid and Angelo Ranaldo. “A Simple Estimation of Bid-Ask Spreads from Daily Close, High, and Low Prices.” Review of Financial Studies 30(12), 2017. quote가 없을 때 daily OHLC로 spread를 추정하는 방법.
- Frazzini, Andrea, Ronen Israel, Tobias Moskowitz. “Trading Costs of Asset Pricing Anomalies.” live execution data를 사용한 비용/규모 분석; short-term reversal은 거래비용 제약이 특히 큼.
- Titman et al. “Short-Term Reversals and Longer-Term Momentum around the World: Theory and Evidence.” Review of Financial Studies 38(12), 2025. 짧은 horizon reversal과 더 긴 horizon momentum의 전환, earnings 이후 reversal 약화.
- Luo, Patrick et al. “Retail Investors’ Contrarian Behavior Around News, Attention, and the Momentum Effect.” NBER Working Paper 34086, 2025. earnings surprise 이후 retail contrarian flow와 momentum/PEAD 관계.

외부 연구는 특정 임계값을 그대로 가져오는 근거가 아니라 **어떤 위험요인을 실험해야 하는지 정하는 근거**로만 사용한다.
