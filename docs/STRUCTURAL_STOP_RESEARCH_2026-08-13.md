# Structural Stop Research · 2026-08-13

> 상태: 연구 완료 / **현재 최소 1.5 ATR STOP 유지**  
> 목적: 차트 구조상 STOP보다 최소 1.5ATR가 더 멀 때 STOP을 강제로 넓히는 현재 방식이 실제로 유리한지 검증한다.

## 1. 비교 정책

60개 current-liquid 후보 중 10년 history가 충분한 58종목, 공개 3전략에 대해 live-like selector와 3백만원/최대3포지션 계좌까지 재시뮬레이션했다.

비교:

1. `force_1_50` — 현재 방식. 구조 STOP과 `entry - 1.5ATR` 중 더 먼 STOP 사용
2. `force_1_25` — 최소 여유를 1.25ATR로 축소
3. `structural_raw` — 강제 확대 없이 원래 구조 STOP 사용
4. `structural_reject_lt_1_25` — 자연 구조 STOP이 1.25ATR보다 가까우면 거래 자체 거절
5. `structural_reject_lt_1_50` — 자연 구조 STOP이 1.5ATR보다 가까우면 거래 자체 거절

신호선정에는 canonical strict, S score, flow, precise gross RR, market, entry viability, elite score, first-20DMA overlay를 반영했다.

## 2. 핵심 결론: 현재 1.5ATR 강제 확대가 가장 낫다

### OOS

| 정책 | pooled 거래 | 평균거래 | PF | 계좌수익 | Stress DD |
|---|---:|---:|---:|---:|---:|
| **현재 1.5ATR** | 248 | **+0.635%** | **1.456** | **+41.06%** | **-8.99%** |
| 1.25ATR | 273 | +0.376% | 1.258 | +27.12% | -14.52% |
| 구조 STOP raw | 285 | +0.369% | 1.269 | +15.09% | -16.22% |
| 구조<1.25ATR 거절 | 41 | +2.013% | 2.805 | +19.18% | -6.61% |
| 구조<1.5ATR 거절 | 26 | +3.275% | 5.897 | +22.85% | -4.73% |

### 최근 약 2년

| 정책 | pooled 거래 | 평균거래 | PF | 계좌수익 | Stress DD |
|---|---:|---:|---:|---:|---:|
| **현재 1.5ATR** | 141 | +0.529% | 1.347 | **+13.47%** | -7.26% |
| 1.25ATR | 156 | +0.263% | 1.168 | +10.59% | -10.11% |
| 구조 STOP raw | 162 | +0.253% | 1.173 | +6.60% | -11.81% |
| 구조<1.25ATR 거절 | 26 | +1.952% | 2.646 | +10.31% | -4.63% |
| 구조<1.5ATR 거절 | 17 | +3.856% | 10.250 | **+16.44%** | **-3.00%** |

## 3. 왜 가까운 STOP이 나빴나

`force_1_25`와 `structural_raw`는 STOP이 더 가까워져 nominal RR은 좋아질 수 있지만 실제 결과는 반대였다.

OOS:

- 현재 1.5ATR 계좌 +41.1%
- 1.25ATR +27.1%
- raw +15.1%

Stress DD도:

- 현재 -9.0%
- 1.25ATR -14.5%
- raw -16.2%

로 악화했다.

즉 현재 표본에서는 **가격 노이즈/일중 변동에 의한 조기 손절 증가가 tighter stop의 RR 이점을 압도**한 것으로 해석한다.

따라서 `구조적 STOP이 가까우면 그대로 쓰자`는 가설은 지지되지 않는다.

## 4. 현재 강제 1.5ATR가 실제로 얼마나 자주 개입하나

현재 force_1.5로 실제 체결된 거래들의 자연 구조 STOP 거리는 평균 약 1.23ATR였다.

- 자연 구조 STOP <1.25ATR: 약 83%
- 자연 구조 STOP <1.50ATR: 약 90%

즉 최소 1.5ATR 규칙은 드물게 작동하는 예외처리가 아니라 **대부분 거래에서 실제 STOP을 넓히는 핵심 실행규칙**이다.

그럼에도 OOS/최근 결과가 더 좋았으므로 현재로서는 유지가 타당하다.

## 5. `자연 구조거리 충분한 거래만` 결과가 좋아 보이는 이유

`structural_reject_lt_1_25 / 1_50`은 STOP 자체를 바꾸는 실험이라기보다 사실상 **종목선정 필터**다.

자연 구조 STOP이 이미 1.5ATR 이상 떨어져 있으면 현재 `force_1_50`도 그 구조 STOP을 그대로 사용한다. 따라서 `reject_lt_1_50`의 성과 차이는 STOP 방식보다 **어떤 거래를 버렸는가**에서 나온다.

특히 확인형 눌림반등에서 강했다.

### 확인형 · 현재 baseline 1.5ATR

OOS:

- 48건
- 평균 +1.779%
- PF 2.55

최근2년:

- 28건
- 평균 +2.101%
- PF 2.95

### 확인형 · 자연 구조거리 >=1.5ATR만

OOS:

- 20건
- 평균 +4.091%
- PF 11.78
- 승률 80%

최근2년:

- 12건
- 평균 +4.814%
- PF 34.21
- 승률 91.7%

매우 강해 보인다.

## 6. 그러나 이 필터를 바로 채택하지 않는 이유

같은 확인형 필터의 IS 첫 70%는:

- 27건
- 평균 **-1.177%**
- PF **0.50**
- 승률 40.7%

였다.

OOS/최근에서 갑자기 매우 강해진 형태다.

따라서:

- 최근 시장구조와 우연히 잘 맞았을 가능성
- 표본 12~20건의 작은 수
- 현재-name universe bias
- 같은 연구에서 여러 STOP variant를 비교한 selection bias

를 무시할 수 없다.

`자연 구조거리 >=1.5ATR`는 **확인형 전용 연구 후보**로 남기되 live hard gate로 승격하지 않는다.

## 7. 전략별 영향

### 확인형 눌림반등

현재 force1.5가 이미 강하다.

- OOS +1.779% / PF 2.55
- 최근 +2.101% / PF 2.95

자연 구조거리 필터는 연구가치가 있지만 비정상적인 IS/OOS 차이 때문에 추가검증 필요.

### RSI2

현재 force1.5가 더 좋다.

OOS:

- force1.5: +0.325% / PF 1.24
- force1.25: +0.120% / PF 1.09
- raw: +0.084% / PF 1.06

최근:

- force1.5: +0.097% / PF 1.07
- force1.25: +0.017% / PF 1.01
- raw: -0.037% / PF 0.97

RSI2는 자연 raw stop이 공식상 최소 약 1.15ATR로 설계돼 있어 `자연>=1.25/1.5` 필터는 거의 모든 거래를 제거한다. 따라서 이 구조거리 필터를 RSI2에 공통 적용해서는 안 된다.

### 모멘텀 눌림

최근/OOS에서도 force1.5가 raw/tighter보다 우세하다.

최근:

- force1.5 +0.328% / PF 1.14
- force1.25 -0.461% / PF 0.83
- raw -0.537% / PF 0.79

따라서 현재 STOP을 줄일 근거가 없다.

## 8. 결정

### 유지

현재 canonical STOP:

`stop = min(raw_structural_stop, entry - 1.5 * ATR)`

즉 최소 1.5ATR 여유 유지.

### 의미 재정의

`stop_atr_multiple >= 1.5`는 현재 plan construction 때문에 대부분의 정상 plan에서 자동 충족한다.

따라서 이를 강력한 독립 품질필터라기보다 **STOP construction invariant / sanity check**로 보는 것이 정확하다.

### 채택하지 않음

- force1.25
- raw structural stop
- 전 전략 공통 natural-stop-distance gate

### 연구 후보

- confirmed_pullback 전용 `natural structural stop distance` quality overlay

단, 더 넓은 walk-forward/기간안정성 확인 전에는 live에 적용하지 않는다.

## 9. 다음 연구 우선순위

STOP은 현행 유지로 결론냈다.

다음 구조적 의문은 **공통 next-open gap guard 0.75ATR / 1%**다.

특히:

- RSI2 BUY zone은 매우 좁은데 gap 허용은 상대적으로 넓음
- confirmed pullback은 지지선 아래 gap과 위쪽 gap의 의미가 다름
- momentum은 소폭 상승 gap은 추세확인일 수 있지만 과한 상승 gap은 추격이 됨

따라서 다음은 전략별 gap guard sensitivity를 OOS/최근/portfolio 기준으로 연구한다.
