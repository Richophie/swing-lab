# RSI2 Regime Sizing Portfolio Research · 2026-08-13

> 상태: 연구 완료 / **중립 리스크 축소 채택하지 않음**  
> 목적: pooled trade 평균이 아니라 실제 Swing Lab 계좌 구조에서 중립시장 RSI2 포지션 크기를 줄이는 것이 수익/리스크를 개선하는지 확인한다.

## 1. 계좌 모델

- 시작자금 3,000,000 KRW
- 최대 동시 3포지션
- 기본 거래당 계획리스크 1%
- 종목당 최대 40% 노출
- 같은 날 진입은 청산보다 먼저 처리
- 슬롯 초과 시 ex-ante RR 우선
- 현재 live-like RSI2 trade pool
- 객관적 current prefilter 80종목 요청, 77종목 사용
- 후보 거래 550건

비교:

- 중립 100% risk — 현재 baseline
- 중립 75%
- 중립 50%
- 중립 25%
- 중립 0% — 좋음 only
- 중립 50% + 좋음 후보 우선순위

좋음 시장은 모든 variant에서 기본 100% risk를 유지한다.

## 2. OOS 결과

| 중립 리스크 | 계좌수익 | 실현손익 | Stress DD | Max DD | 체결거래 |
|---|---:|---:|---:|---:|---:|
| **100% baseline** | **+18.72%** | **+561,570원** | -10.45% | -7.88% | 145 |
| 75% | +16.57% | +497,232원 | -10.33% | -7.71% | 145 |
| 50% | +14.58% | +437,423원 | -10.21% | -7.53% | 145 |
| 25% | +13.21% | +396,431원 | **-10.09%** | **-7.37%** | 145 |
| 0% / 좋음 only | +12.63% | +378,813원 | -10.57% | -7.99% | 114 |

OOS에서 중립거래는 실제 받아들여진 34건이었고 baseline 기준 약 +203,858원의 기여를 했다.

중립 노출을 낮출수록 stress drawdown은 25%까지 약 0.36%p 개선되지만 계좌수익은 약 5.5%p 줄었다.

즉 **위험 감소 대비 수익 희생이 크다.**

## 3. 최근 약 2년

| 중립 리스크 | 계좌수익 | 실현손익 | Stress DD | Max DD | 체결거래 |
|---|---:|---:|---:|---:|---:|
| **100% baseline** | **+4.39%** | **+131,808원** | -10.45% | -7.88% | 87 |
| 75% | +3.86% | +115,730원 | -10.33% | -7.71% | 87 |
| 50% | +3.17% | +95,084원 | -10.21% | -7.53% | 87 |
| 25% | +2.71% | +81,195원 | **-10.09%** | **-7.37% | 87 |
| 0% / 좋음 only | +2.95% | +88,421원 | -10.57% | -7.99% | 68 |

최근2년 baseline에서 실제 체결된 중립거래 22건은 약 +68,157원을 기여했다.

이는 직전 pooled 분석에서 최근 중립 전체가 음수였던 결과와 다르다.

이유는 finite-account가 모든 중립 신호를 받지 않기 때문이다.

- 최대 3슬롯
- RR 우선순위
- 현금/position sizing
- 겹치는 거래의 capacity reject

를 거치면서 실제 계좌가 받은 중립 subset이 달라진다.

따라서 **pooled 개별거래 평균만 보고 sizing 규칙을 바꾸면 안 된다.**

## 4. 전체/IS

전체 10년과 IS 초반은 모든 variant가 음수였고 중립을 줄일수록 손실폭은 감소했다.

baseline 전체:

- -13.10%
- stress DD -33.76%

좋음 only 전체:

- +4.80%
- stress DD -16.39%

IS baseline:

- -25.11%

IS good-only:

- -6.95%

이는 초기 역사에서 RSI2, 특히 중립장이 매우 약했다는 이전 연구와 일치한다.

그러나 실제 승격 판단에서 더 중요한 OOS/최근 구간은 정반대다. 최근 계좌에서는 중립을 유지하는 것이 수익을 높였다.

즉 RSI2는 강한 **time/regime non-stationarity**가 존재한다.

## 5. Good-first priority

`neutral 50% + good first priority`는 이번 표본에서 일반 `neutral 50%`와 결과가 동일했다.

이는 실제 동시 entry에서 시장상태 우선순위가 기존 RR 우선순위를 바꿀 만큼 충돌한 경우가 없었거나 결과적으로 같은 3개가 선택되었음을 의미한다.

따라서 현재 evidence로는 market-state를 candidate priority로 올릴 근거도 없다.

## 6. 결정

### 유지

현재 계좌 sizing:

- 좋음: 기본 1% risk budget
- 중립: 기본 1% risk budget
- 조심: 신호 진입 제외

즉 **중립 risk multiplier = 1.0 유지**.

### 채택하지 않음

- 중립 75/50/25% 축소
- 중립 전면 제외
- good-first portfolio priority

### 이유

OOS와 최근2년 모두 baseline이 가장 높은 계좌수익을 냈고, 중립 축소의 drawdown 개선은 작았다.

## 7. 중요한 방법론 결론

이번 결과는 Swing Lab의 연구 절차에 중요한 원칙을 추가한다.

**선정 필터/position sizing 변경은 pooled trade 통계뿐 아니라 실제 finite-account portfolio simulation에서도 확인해야 한다.**

특히:

- 동시신호
- 3포지션 슬롯
- RR 우선순위
- position sizing
- cash constraint

때문에 개별 거래 평균과 실제 계좌 결과가 반대로 나올 수 있다.

## 8. 다음 우선순위

시장 sizing은 현행 유지하고 다음 구조적 문제로 이동한다.

1. **강제 최소 1.5 ATR STOP vs 구조적 STOP**
2. 전략별 gap guard
3. momentum regime 안정성
4. earnings/event risk
5. portfolio sector/correlation concentration

다음 연구는 STOP을 억지로 1.5 ATR까지 넓히는 현재 방식이 실제 기대값/낙폭/포지션 크기에 도움이 되는지 검증한다.

## 9. 한계

- current-name liquid universe → survivorship bias 존재
- historical sector composition 미반영
- portfolio equity는 일중 MTM 전체를 복원하는 모델이 아니라 체결/계획손절 기반 보수적 stress model
- 실제 USD/KRW와 정수주식 수량은 Paper Broker에서 더 현실적으로 다룸

따라서 정확한 미래수익률 추정이 아니라 **규칙 간 상대 비교**로 사용한다.
