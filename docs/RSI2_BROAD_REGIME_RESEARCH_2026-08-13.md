# RSI2 Broad Market-Regime Validation · 2026-08-13

> 상태: 표본확대 연구 완료 / **라이브 hard gate 변경 없음**  
> 목적: 20종목 연구에서 유일하게 살아남은 `market state == 좋음 only` 후보를 더 넓은 유동주 표본에서 재검증한다.

## 1. 연구 설계

다중비교 위험을 줄이기 위해 이번에는 딱 두 정책만 비교했다.

1. `baseline_live_like` — 현재 RSI2 live-like selector, 즉 시장 `좋음 + 중립` 허용
2. `market_good_only` — 같은 selector에서 `좋음`만 허용

주요 조건은 현재 시스템과 최대한 맞췄다.

- canonical RSI2 strict signal
- strategy score >= 85
- flow quality
- precise gross RR >= 1.20
- elite score >= 72
- next-open gap guard
- commission / slippage / half-spread

표본:

- 객관적 현재 prefilter 상위 80종목 요청
- 10년 history 1,000 row 이상 요구
- 실제 사용 77종목
- 제외: SPCX, GEV, SNDK — history 부족
- selection source: `objective_current_prefilter`

각 종목별 70/30 IS/OOS와 최근 약 2년을 별도 집계했다.

추가 robustness:

- 수익 종목 비율
- 상위 5종목 거래 집중도
- 한 종목씩 제거한 leave-one-symbol-out pooled 결과

## 2. 표본확대 핵심 결과

### Baseline live-like

전체:

- 550건
- 평균 -0.219%
- PF 0.860

OOS:

- 207건
- 승률 55.6%
- 평균 **+0.272%**
- PF **1.205**
- 70개 종목에 거래 존재
- 수익 평균 종목 비율 58.6%
- 상위 5종목 거래비중 15.5%
- 한 종목씩 제거해도 평균 +0.224~+0.368% 수준, PF 약 1.16~1.29 범위로 양호

최근2년:

- 111건
- 평균 **+0.047%**
- PF **1.032**
- 57개 종목에 거래 존재
- leave-one-symbol-out 평균은 약 -0.07~+0.15% 수준으로 0을 넘나들어 안정성이 약함

### Market good only

전체:

- 381건
- baseline 대비 69.4% coverage
- 평균 -0.050%
- PF 0.963

OOS:

- 151건
- baseline 대비 73.3% coverage
- 평균 **+0.142%**
- PF **1.111**
- 60개 종목에 거래 존재
- 상위 5종목 거래비중 17.2%
- leave-one-symbol-out 평균 **+0.078~+0.239%**
- leave-one-symbol-out PF **1.060~1.194**

최근2년:

- 85건
- baseline 대비 77.3% coverage
- 평균 **+0.126%**
- PF **1.100**
- 47개 종목에 거래 존재
- 상위 5종목 거래비중 23.5%
- leave-one-symbol-out 평균 **+0.048~+0.246%**
- leave-one-symbol-out PF **1.037~1.207**

## 3. 20종목 연구와 다른 점

20종목에서는 baseline RSI2가 OOS/최근 모두 음수였고 `좋음 only`가 최근 플러스로 전환되어 강한 후보처럼 보였다.

80종목 표본에서는 baseline 자체가:

- OOS +0.272% / PF 1.205
- 최근2년 +0.047% / PF 1.032

로 훨씬 좋아졌다.

즉 **RSI2 자체를 약한 전략으로 단정했던 초기 결론은 현재 20종목 표본 의존성이 컸다.**

이것이 바로 현재-name 소표본 한계 때문에 표본확대가 필요한 이유다.

## 4. 시장상태별 직접 분해

Baseline 거래를 신호 당시 시장상태로 나누면 더 중요한 패턴이 나온다.

### 전체 10년

좋음:

- 374건
- 평균 -0.048%
- PF 0.965

중립:

- 176건
- 평균 -0.583%
- PF 0.710

전체 역사에서는 중립이 크게 나빴다.

### IS 첫 70%

좋음:

- 227건
- 평균 -0.173%
- PF 0.878

중립:

- 116건
- 평균 -1.186%
- PF 0.482

초기 구간에서 중립이 매우 약했다.

### OOS 마지막 30%

좋음:

- 147건
- 평균 +0.145%
- PF 1.115

중립:

- 60건
- 평균 **+0.582%**
- PF **1.394**

OOS에서는 반대로 중립 RSI2가 더 강했다.

### 최근 약 2년

좋음:

- 82건
- 평균 **+0.158%**
- PF **1.129**

중립:

- 29건
- 평균 **-0.267%**
- PF **0.877**

최근에는 다시 중립이 약했다.

## 5. 해석

`중립 = 항상 나쁜 환경`이라는 가설은 기각한다.

중립 RSI2 성과가 시간에 따라 크게 달라졌다.

- 과거 IS: 매우 나쁨
- OOS 전체: 매우 좋음
- 최근2년: 다시 약함

따라서 `시장 좋음 only`를 hard reject로 만들면 최근 안정성은 좋아지지만 OOS에서 실제로 유효했던 중립 거래 60건을 버리고 OOS 기대값/PF도 낮춘다.

실제로:

- baseline OOS +0.272% / PF 1.205
- good-only OOS +0.142% / PF 1.111

즉 **good-only는 더 매끈하지만 전체 OOS 우위는 baseline이 더 크다.**

## 6. 결정

### 채택하지 않음

`RSI2는 market state == 좋음일 때만 허용` hard gate.

### 현재 유지

현재 RSI2 시장 규칙:

- `조심` 제외
- `좋음 + 중립` 허용
- 현재 scanner의 중립 score penalty 유지

### 다음 연구 후보

시장상태는 **진입 허용/금지보다 포지션 크기와 ranking 변수**로 보는 것이 더 자연스럽다.

예:

- 좋음: 기본 risk budget
- 중립: reduced risk budget 후보
- 조심: 현재처럼 진입 제외

하지만 `중립 50% sizing` 같은 숫자는 아직 채택하지 않는다. 먼저 portfolio-level에서 risk multiplier sensitivity를 검증한다.

## 7. 추가 결론

이 연구는 RSI2에 대해 중요한 교정도 제공한다.

1. 20종목 고정표본에서의 음수 결과만 보고 전략을 폐기하면 안 된다.
2. 77개 유동주에서는 OOS RSI2 live-like selector가 PF>1, 양의 기대값을 보였다.
3. 최근2년은 baseline이 거의 손익분기 수준이어서 지속적인 Paper/공식 추천 데이터가 중요하다.
4. 단순 반전확인보다 시장/포트폴리오 risk management가 더 유망하다.

## 8. 한계

여전히 current-name universe다. 즉 survivorship/current-universe bias는 남아 있다.

또한 이 결과는 종목별 독립 거래를 pooled한 것으로 실제 300만원, 최대 3포지션 포트폴리오의 동시신호/자금제약을 완전히 반영하지 않는다.

따라서 다음 단계는 **market regime별 position-risk multiplier를 실제 portfolio simulator에서 비교**하는 것이다.
