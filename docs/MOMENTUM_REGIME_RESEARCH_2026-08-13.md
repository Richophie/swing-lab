# Momentum Pullback Regime Research · 2026-08-13

> 상태: 진단 완료 / **production 모멘텀 규칙 변경 없음**  
> 목적: 작은 20종목 표본에서 약해 보였던 momentum_pullback이 넓은 live-like selector에서도 실제로 불안정한지, 특정 시장 레짐에서만 깨지는지 확인한다.

## 1. 연구 설계

객관적 current-liquid universe 상위 80개를 요청하고 10년 history가 충분한 77종목을 사용했다.

현재 live-like momentum 경로를 그대로 사용했다.

- canonical momentum strict signal
- strategy S score >=85
- historical flow quality
- precise gross RR >=1.20
- market != 조심
- elite score >=72
- force minimum 1.5ATR STOP
- current next-open gap guard
- commission / slippage / spread

신호일 SPY 기준으로 다음 레짐을 붙였다.

- market state: 좋음 / 중립
- SPY 20일 realized volatility의 trailing-252일 percentile
- SPY 20일 고점 대비 drawdown
- SPY 5일 수익률
- deep drawdown rebound: 20일 drawdown <= -5% AND 5일 수익률 >= +3%

모든 변수는 신호일까지의 데이터만 사용했다.

## 2. 넓은 표본의 baseline 결과

전체:

- 140거래
- 평균 +0.724%
- PF 1.429
- 3백만원 계좌 +22.08%

OOS:

- 47거래
- 승률 57.45%
- **평균 +1.120%**
- **PF 1.770**
- 계좌 **+18.72%**
- stress DD -11.36%

최근 약 2년:

- 30거래
- 승률 60.0%
- **평균 +1.195%**
- **PF 1.818**
- 계좌 **+11.67%**
- stress DD -7.69%

따라서 이전 20종목 canonical 표본에서 나타났던 OOS 붕괴는 넓은 live-like selector에서는 재현되지 않았다.

## 3. 시장상태

OOS:

- 좋음 44건 · +1.013% · PF 1.65
- 중립 3건 · +2.684% · 손실거래 없음

최근:

- 좋음 29건 · +0.928% · PF 1.57
- 중립 1건 · +8.935%

중립 표본이 작지만 적어도 중립을 제외해야 한다는 증거는 없다.

`market_good_only` 포트폴리오:

- OOS +15.20% vs baseline +18.72%
- 최근 +8.34% vs baseline +11.67%

따라서 good-only hard filter는 채택하지 않는다.

## 4. 변동성

OOS:

- high vol >=80p: 6건 · +1.702% · PF 1.95
- mid vol: 38건 · +1.093% · PF 1.78
- low vol <=20p: 3건 · +0.387%

최근:

- high vol: 4건 · +2.151%
- mid vol: 25건 · +1.108% · PF 1.70
- low vol: 1건 · -0.467%

고변동성에서 momentum이 붕괴한다는 패턴은 현재 엄선 이후 거래에서는 나타나지 않았다.

`high-vol 제외` 포트폴리오도 baseline보다 낮았다.

- OOS +18.45% vs +18.72%
- 최근 +11.33% vs +11.67%

따라서 volatility hard filter는 추가하지 않는다.

## 5. SPY drawdown

OOS:

- shallow <2%: 36건 · +0.794% · PF 1.48
- 2~5% drawdown: 9건 · **+2.385% · PF 3.75**
- >=5% deep drawdown: 2건 · +1.672%

최근:

- shallow: 24건 · +0.805% · PF 1.50
- 2~5%: 5건 · **+3.420%** · 손실 없음
- deep: 1건 · -0.811%

깊은 drawdown 표본이 너무 작고, 2~5% 시장조정 구간은 오히려 성과가 강했다.

`deep drawdown 제외`는 OOS baseline과 거의 동일하고 recent에서는 약간 낮았다.

따라서 drawdown hard filter도 추가하지 않는다.

## 6. 급락/급반등 가설

OOS SPY 5일 수익률별:

- <= -3%: 2건 · +1.125%
- -3~0%: 15건 · +0.207%
- 0~+3%: 29건 · +1.276%
- >=+3% rebound: 1건 · +9.521%

최근에서는 >=+3% 급반등 거래가 0건이었다.

`deep drawdown <=-5% + 5d rebound >=+3%` 조건에 해당하는 live-like momentum 거래는 사실상 존재하지 않았다.

즉 현재 strict+elite selector가 이미 전형적인 panic-rebound momentum-crash 구간을 상당 부분 피하고 있을 가능성이 있다.

## 7. 결론

### 유지

현재 momentum_pullback:

- strict signal
- 시장 좋음+중립 허용
- current flow/RR/elite
- force 1.5ATR STOP
- current gap guard

모두 유지한다.

### 채택하지 않음

- high-vol exclusion
- deep-drawdown exclusion
- market-good-only
- panic-rebound 추가 hard gate

### 이유

어떤 단순 레짐 제외도 OOS와 최근 finite-account baseline을 동시에 개선하지 못했다.

## 8. 중요한 교정

초기 20종목 연구에서는 momentum OOS가 크게 약해 보였으나, 77개 liquid-name live-like selector에서는:

- OOS PF 1.77
- recent PF 1.82

로 재현되지 않았다.

따라서 **작은 current-name 표본에서 전략을 폐기하거나 강하게 수정하지 않는다**는 Validation Protocol 원칙이 다시 확인됐다.

## 9. 다음 단계

기술적 진입규칙과 시장레짐은 현재 evidence상 큰 변경 근거가 없다.

다음 우선순위는 **earnings / corporate event처럼 STOP으로 막기 어려운 overnight gap risk**다.

초기 단계에서는:

1. 데이터 신뢰도/가용성 확인
2. 후보 상세에 informational EVENT RISK 표시
3. Paper/공식 추천에 event proximity 저장
4. 충분한 표본이 쌓인 뒤 hard gate 여부 연구

순서가 적절하다.
