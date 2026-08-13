# RSI2 Upside Gap Validation · 2026-08-13

> 상태: 탐색 + 확인검증 완료 / **production gap guard 변경하지 않음**  
> 목적: 1차 gap 연구에서 약하게 보였던 RSI2의 BUY 위쪽 next-open에 대해 0.50ATR/0.25ATR 제한이 실제 계좌 개선으로 이어지는지 확인한다.

## 1. 탐색 단계 · 58종목

다른 전략과 downside guard는 모두 current로 유지하고 RSI2 upside만 비교했다.

- current: `max(0.75ATR, 1%)`
- 0.50ATR
- 0.25ATR

### 58종목 OOS

| 정책 | RSI2 거래 | RSI2 평균 | RSI2 PF | 전체 계좌수익 | Stress DD |
|---|---:|---:|---:|---:|---:|
| current | 169 | +0.325% | 1.242 | +41.06% | -8.99% |
| **up 0.50** | 161 | **+0.403%** | **1.315** | **+42.27%** | **-8.53%** |
| up 0.25 | 146 | +0.535% | 1.454 | +35.55% | -6.62% |

### 58종목 최근2년

| 정책 | RSI2 거래 | RSI2 평균 | RSI2 PF | 전체 계좌수익 | Stress DD |
|---|---:|---:|---:|---:|---:|
| current | 91 | +0.097% | 1.065 | +13.47% | -7.26% |
| **up 0.50** | 86 | +0.069% | 1.047 | **+14.30%** | **-6.59%** |
| up 0.25 | 78 | +0.025% | 1.017 | +12.08% | -6.62% |

0.50ATR는 탐색표본에서 OOS/최근 전체 계좌수익과 stress DD가 동시에 개선되어 유력 후보로 보였다.

따라서 숫자를 더 탐색하지 않고 **0.50ATR 하나만 고정하여 80종목 확인검증**으로 넘어갔다.

## 2. 확인 단계 · 80 요청 / 77 사용

객관적 current-liquid prefilter 상위 80개를 요청했고 10년 history가 충분한 77종목을 사용했다.

확인 단계에서는 딱 두 정책만 비교했다.

1. current
2. RSI2 upside 0.50ATR

다른 모든 규칙은 동일하다.

### OOS

#### Current

- 전체 304거래
- 전체 평균 +0.463%
- 전체 PF 1.328
- RSI2 207거래
- RSI2 평균 +0.262%
- RSI2 PF 1.195
- 3백만원 계좌 **+27.49%**
- stress DD -10.27%
- 실제 계좌 체결 193건

#### RSI2 upside 0.50ATR

- 전체 297거래
- 전체 평균 +0.518%
- 전체 PF 1.379
- RSI2 200거래
- RSI2 평균 **+0.337%**
- RSI2 PF **1.264**
- 3백만원 계좌 **+26.75%**
- stress DD -10.13%
- 실제 계좌 체결 192건

즉 개별 거래 평균/PF는 좋아졌지만 **실제 finite account 수익은 current보다 낮아졌다.**

### 최근 약 2년

#### Current

- 전체 169거래
- RSI2 111거래
- RSI2 평균 **+0.047%**
- RSI2 PF **1.032**
- 계좌 **+11.73%**
- stress DD -7.91%
- 계좌 체결 119건

#### RSI2 upside 0.50ATR

- 전체 165거래
- RSI2 107거래
- RSI2 평균 **-0.003%**
- RSI2 PF **0.998**
- 계좌 **+10.66%**
- stress DD -7.91%
- 계좌 체결 117건

최근에서는 candidate가 RSI2 자체와 전체 계좌 모두 악화했다.

## 3. Leave-one-symbol-out 확인

### OOS current

한 종목씩 제거한 계좌수익 범위:

- +19.59% ~ +32.65%

### OOS 0.50ATR

- +18.71% ~ +31.89%

둘 다 특정 한 종목 하나에 완전히 의존하지는 않지만 candidate가 current 대비 안정적인 상향을 만들지 못했다.

### Recent current

- +5.88% ~ +16.68%

### Recent 0.50ATR

- +4.87% ~ +14.75%

recent에서도 current가 우세하다.

## 4. 종목별 RSI2 개선 분포

OOS에서 current/candidate 둘 다 거래가 있는 비교가능 종목 69개 중 candidate의 평균수익이 current보다 실제로 높아진 종목은 약 **11.6%**였다.

최근2년 비교가능 56개 중 개선 종목은 약 **5.4%**였다.

이는 0.50ATR가 전체 RSI2 거래의 일부 약한 upside-gap 거래를 제거해 pooled 평균을 높일 수는 있지만, **대부분 종목에서 반복적으로 우위를 만드는 보편 규칙은 아니라는 신호**다.

## 5. 최종 결정

### Production 유지

현재 next-open gap guard를 그대로 유지한다.

`max(0.75 * ATR, 1% * signal close)`

- downside current 유지
- upside current 유지
- RSI2도 별도 0.50/0.25 제한을 적용하지 않음

### 이유

탐색표본에서는 0.50ATR가 좋아 보였으나 더 넓은 확인표본에서:

- OOS 전체 계좌수익 하락
- recent 전체 계좌수익 하락
- recent RSI2 PF가 1 아래로 하락
- 종목별 반복 개선 비율 낮음

이 확인됐다.

즉 **탐색 결과를 production에 즉시 적용했다면 과최적화된 변경이 되었을 가능성이 높다.**

## 6. 방법론적 의미

이번 연구는 Swing Lab의 validation protocol이 실제로 필요한 이유를 잘 보여준다.

1차 58종목 탐색:

- 0.50ATR가 OOS/최근 계좌 모두 개선 → 매력적인 후보

2차 77종목 고정후보 확인:

- current가 OOS/recent 계좌 모두 우위 → 후보 기각

따라서 앞으로도:

**아이디어 → 탐색 → 후보 1개 고정 → 더 넓은 확인 → production 여부 결정**

순서를 유지한다.

## 7. 다음 연구 우선순위

Gap guard는 현행 유지로 닫는다.

다음 구조적 우선순위:

1. momentum pullback의 regime 안정성
2. earnings/event gap risk
3. universe의 dollar-liquidity/spread 기준화
4. portfolio sector/correlation concentration
5. confirmed pullback natural structural-distance 후보의 기간안정성

이 중 다음은 **momentum pullback의 live-like broad regime 안정성**을 먼저 본다.
