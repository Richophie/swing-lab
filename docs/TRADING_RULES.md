# Swing Lab Trading Rules

> 상태: 공식 매매/추천 규칙 문서  
> 기준일: 2026-08-13  
> 핵심 원칙: **실전과 백테스트의 strict signal 및 BUY/TARGET/STOP은 `strategy_rules.py`를 단일 원본으로 사용한다.**

## 1. 규칙의 우선순위

1. `strategy_rules.py` — strict signal / canonical trade levels
2. `scanner.py` — 현재 자리 엄선 및 표시 우선순위
3. `signal_log.py` — 장중 ENTER/EXIT 기록
4. `journal.py` — 마감 확정 추천과 결과 판정
5. `paper_broker.py` / `backtest_engine.py` — 체결 및 계좌 모델

전략 임계값 또는 BUY/TARGET/STOP 공식 변경은 단순 UI 변경과 다르다. 반드시 `VALIDATION_PROTOCOL.md`의 승격 절차를 거친다.

## 2. 공개 전략

### 2.1 확인형 눌림반등 — `confirmed_pullback`

목적: 120일선 근처에서 충분히 눌린 뒤 반전이 확인된 자리.

현재 strict 핵심 조건:

- 시장 상태 `조심` 제외
- pullback base score >= 72
- 반전 확인 4/4
- 반전일 거래량 / 20일 평균 거래량 >= 1.0
- RSI14 30~43
- 볼린저 위치 <= 40%
- 120일선 거리 절대값 <= 3.5%
- ATR/가격 <= 4.5%
- 장기 추세 바닥 조건 유지

BUY/TARGET/STOP:

- 기준 anchor: 120일선
- BUY: `anchor - 0.18 ATR` ~ `anchor + 0.22 ATR`
- raw stop: 최근 10일 저가와 `anchor - 0.95 ATR` 중 더 낮은 값
- TARGET: 최근 20일 고점과 `anchor + 1.8 ATR` 중 더 높은 값
- 기본 목표기간: 2~8 거래일
- 최종 STOP은 최소 1.5 ATR 손절여유를 보장하도록 더 넓어질 수 있다.

### 2.2 RSI2 추세내 과매도 — `rsi2_trend_reversion`

목적: 장기 상승추세는 유지되지만 단기적으로 극단 과매도에 들어온 자리.

현재 strict 핵심 조건:

- 시장 상태 `조심` 제외
- 종가 > 200일선
- 50일선 >= 120일선
- RSI2 < 3
- RSI14 <= 50
- 볼린저 위치 <= 45%
- 120일선 거리 -3% ~ +12%
- 200일선 대비 과도한 이격 제한: d200 <= +25%
- ATR/가격 <= 5%

BUY/TARGET/STOP:

- anchor: 현재 종가
- BUY: `anchor ± 0.12 ATR`
- raw stop: 최근 10일 저가와 `anchor - 1.15 ATR` 중 더 낮은 값
- TARGET: `anchor + 1.3 ATR` 또는 20일선 중 더 높은 값
- 기본 목표기간: 1~5 거래일
- 최종 STOP은 최소 1.5 ATR 손절여유를 보장한다.

### 2.3 모멘텀 눌림 지속 — `momentum_pullback`

목적: 강한 상승 뒤 1~5일 조정을 거친 후 추세 재개 가능성이 있는 자리.

현재 strict 핵심 조건:

- 시장 상태 `조심` 제외
- 종가 > 200일선
- 50일선 >= 120일선
- 20일 수익률 +5% ~ +20%
- 5일 수익률 -5% ~ -0.5%
- MACD histogram 개선
- RSI14 42~60
- 120일선 거리 0% ~ +20%
- 볼린저 위치 <= 80%
- ATR/가격 <= 6%

BUY/TARGET/STOP:

- anchor: 20일선
- BUY: `anchor - 0.20 ATR` ~ `anchor + 0.18 ATR`
- raw stop: 최근 10일 저가와 `anchor - 1.05 ATR` 중 더 낮은 값
- TARGET: 최근 20일 고점과 `anchor + 2.0 ATR` 중 더 높은 값
- 기본 목표기간: 3~10 거래일
- 최종 STOP은 최소 1.5 ATR 손절여유를 보장한다.

## 3. 실험 전략

`volatility_breakout`은 연구/검증 데이터로만 유지한다.

- 메인 공개 엄선 추천에서 제외
- 공식 전략 승격 전에는 실전 주력으로 취급하지 않는다.
- 승격 여부는 `VALIDATION_PROTOCOL.md`를 따른다.

## 4. S 신호와 엄선의 차이

### 전략 S

각 전략의 strict signal이 켜지고 전략 품질점수가 S 기준을 넘으면 전략별 탭에 표시된다.

현재 `S_THRESHOLD = 85`.

### 최종 엄선

전략 S 중에서도 현재 진입하기 좋은지 다시 걸러낸다.

현재 hard gate:

- `risk_reward >= 1.20`
- 수급/유동성 quality score `>= 42`
- 시장 상태 != `조심`
- `entry_viable == True`
- `stop_atr_multiple >= 1.5`
- 최종 `elite_score >= 72`

현재 엄선점수 구성:

- 전략 신호 품질: 68%
- 수급/유동성 품질: 22%
- 손익비 품질: 10%
- 20일선 첫 눌림 overlay가 있으면 +6점
- 시장 `중립`: -2점
- 시장 `조심`: -8점
- 진입 불가: -18점
- ATR 손절여유 부족: -12점

최종 점수는 0~99 범위로 제한한다.

## 5. 수급/유동성 quality score

기본 50점에서 가감한다.

현재 사용 요소:

- 5일/20일 거래량
- 상대거래량
- 반전일 거래량
- 상승/하락 거래량 비율
- 20일 평균 거래대금

대표 규칙:

- 5일/20일 거래량 0.65~1.05: +10
- 5일/20일 > 1.6: -8
- 상대거래량 0.8~1.8: +8
- 상대거래량 > 2.8: -10
- 반전일 거래량 >= 1.05: +12
- 상승/하락 거래량 비율 >= 1.15: +10
- 상승/하락 거래량 비율 < 0.75: -8
- 평균 거래대금 >= $50M: +10
- 평균 거래대금 < $5M: -15

점수는 0~100 범위로 제한한다.

## 6. 20일선 첫 눌림 overlay

다음 조건의 교집합을 별도 overlay로 본다.

- 5일 > 20일 > 50일 > 200일 정배열
- 최근 30일 안에 52주 신고가 근접
- 직전 20일 동안 20일선 위에서 유지
- 현재 저가가 20일선 근처에 닿고 종가가 크게 무너지지 않음

이 overlay는 `confirmed_pullback`, `momentum_pullback` 엄선점수에만 보너스를 준다.

이는 독립 전략이 아니라 **현재 자리 품질 overlay**다.

## 7. 시장 상태

시장 필터는 SPY/QQQ의 장기 추세와 RSI를 이용한다.

전략 strict signal은 시장 상태가 `조심`이면 진입 불가다.

시장 상태는 후보 우선순위와 엄선에도 반영되며, 전략 자체 규칙과 분리해서 기록한다.

## 8. 진입 gap guard

다음 거래일 시가가 계획 진입가에서 너무 멀어지면 추격하지 않는다.

canonical constants:

- `ENTRY_GAP_ATR = 0.75`
- `ENTRY_GAP_PCT = 0.01`

실전, Backtest V2, Paper Broker가 같은 철학을 사용한다.

## 9. 손절 최소 여유

모든 전략의 최종 stop은 최소 `1.5 ATR` 손절여유를 보장한다.

`MIN_STOP_ATR = 1.5`

이를 만족하지 못하는 현재 trade plan은 엄선에서 제외한다.

## 10. 장중 후보 lifecycle

장중 스캔은 mutable하다.

### ENTER

이전 스캔에 없던 `symbol|strategy` 엄선 후보가 새로 생기면 기록.

저장 정보 예:

- 종목/전략
- 당시 엄선점수
- 현재가
- BUY/TARGET/STOP
- RSI
- 120일선 거리
- 볼린저 위치
- 최초 포착시각

### EXIT

이전에는 엄선이었지만 현재 엄선에서 빠지면 기록.

가능한 이탈 이유:

- `strategy_score` — 전략 S 점수 기준 이탈
- `flow` — 수급점수 < 42
- `risk_reward` — 손익비 < 1.20
- `market` — 시장 조심
- `entry_viable` — 진입구간 이탈
- `atr_stop_margin` — ATR 손절여유 부족
- `elite_score` — 엄선점수 < 72
- `signal_missing` — 현재 스캔에서 해당 전략 S 자체가 사라짐
- 복합 조건이면 여러 code를 함께 기록

구버전 로그에 이유 데이터가 없으면 이유를 추정해서 만들어내지 않는다.

## 11. 공식 추천 publication rule

공식 성과 기록은 `journal.py`가 담당한다.

- 미국 동부시간 16:05 이후 스캔만 publish 가능
- 실제 최근 SPY trading date를 사용
- `publication_status = CONFIRMED_CLOSE`
- `signal_origin = daily_bar_close`
- 같은 market date의 같은 `symbol|strategy`는 한 번만 동결
- 장중 후보가 공식 추천보다 먼저 나타났더라도 공식 성과 시작점은 마감 확정 시점이다.

## 12. 공식 추천 결과 판정

결과는 추천일 **다음 거래일부터** 판정한다.

최대 목표기간은 전략별 `target_days_high`.

판정 순서:

1. STOP 터치 여부
2. TARGET 터치 여부
3. 목표기간 종료

같은 일봉에서 STOP과 TARGET이 모두 터치하면 STOP 우선.

종료 code:

- `SUCCESS`
- `STOP`
- `EXPIRED_GAIN`
- `EXPIRED_LOSS`
- `EXPIRED_FLAT`

목표기간 종료 시 마지막 종가 기준으로 결과를 계산한다.

## 13. Backtest V2 비용 가정

현재 중앙 설정:

- commission: 편도 0.10%
- slippage: 5 bps
- half spread: 2.5 bps

이 값은 실제 특정 증권사의 현재 수수료라고 주장하는 숫자가 아니라 **보수적 검증 가정**이다.

## 14. 계좌/포지션 규칙

기본 검증계좌:

- 3,000,000 KRW
- 최대 동시 3포지션
- 거래당 계획손실 1%
- 한 종목 최대 40% 노출

같은 날 후보가 많을 때 미래 수익률로 선별하지 않는다. 진입 당시 계산 가능한 canonical risk/reward와 현재 품질만 사용한다.

## 15. Paper Broker 규칙

- 실주문 없음
- 신호 당일 체결 없음
- 다음 거래일 첫 시가만 진입 검토
- gap guard 위반 시 CANCELLED
- 정수 주식 수량
- 현금/예약현금 분리
- 진입 수수료/청산 비용 반영
- 진입 당일에도 stop/target 검사
- 같은 봉 stop+target이면 stop 우선
- 최대 보유기간 종료 시 시장청산
- realized/unrealized P&L 기록
- `live_trading_enabled = false` 강제

## 16. 금지 규칙

- 후보가 줄었다고 hard gate를 즉흥 완화하지 않는다.
- 특정 종목 손절 하나 때문에 전략 RSI/이평선 기준을 수정하지 않는다.
- 승률만 보고 전략을 평가하지 않는다.
- 백테스트 결과가 나쁘다고 오늘 엄선에서 자동 제외하지 않는다.
- 장중 ENTER를 마감 확정 추천으로 소급하지 않는다.
- gap이 난 종목을 목표수익을 위해 추격매수한 것으로 백테스트하지 않는다.
- 실주문 기능을 Paper 검증 없이 추가하지 않는다.

## 17. 변경 절차

이 문서의 숫자 또는 전략 조건을 변경할 때는 같은 PR에 반드시 포함한다.

1. 변경 이유
2. baseline
3. 후보 변경안
4. IS/OOS 결과
5. 비용 적용 후 결과
6. regime/종목 분산
7. Backtrader parity 영향
8. Paper 영향
9. 문서 변경
10. 최종 승격 여부

자세한 승격 기준은 `VALIDATION_PROTOCOL.md`를 따른다.
