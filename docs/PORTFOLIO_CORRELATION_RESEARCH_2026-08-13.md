# Portfolio Correlation Research · 2026-08-13

> 상태: 탐색 + 80종목 확인 완료 / **production hard cap 및 자동 priority 변경 보류**

## 질문

Swing Lab 계좌는 최대 3포지션이다.

개별 거래당 risk가 1%여도 NVDA/AMD/AVGO처럼 비슷한 위험요인에 몰리면 실질 위험은 더 클 수 있다.

따라서 신호일 시점에서만 사용할 수 있는 과거 60거래일 일수익률 상관계수를 계산해 다음을 비교했다.

1. 현재 RR 우선
2. 낮은 상관 우선(priority-only)
3. 상관 0.75 hard cap
4. 상관 0.60 hard cap
5. 상관 0.75 이상 half-risk

상관 계산에는 신호일 이후 데이터가 들어가지 않는다.

## 1차 탐색 · 58종목

### OOS

| 정책 | 계좌수익 | Stress DD | 체결 | corr≥0.75 체결 |
|---|---:|---:|---:|---:|
| 현재 RR | +41.06% | -8.99% | 178 | 14 |
| 낮은 상관 우선 | **+44.94%** | **-8.83%** | 177 | 11 |
| hard 0.75 | +37.78% | -9.06% | 169 | 0 |
| hard 0.60 | +36.89% | -9.06% | 163 | 0 |
| corr≥0.75 half-risk | +38.94% | -9.02% | 178 | 14 |

### 최근 약 2년

- 현재: +13.47%, Stress DD -7.26%
- 낮은 상관 우선: **+14.88%, -7.09%**
- hard 0.75: +12.43%, -7.33%
- hard 0.60: +12.97%, -7.33%
- half-risk: +12.54%, -7.30%

## 중요한 반전 · 고상관 거래 자체는 나쁘지 않았다

현재 baseline에서 상관 0.75 이상인 거래:

### OOS

- 14건
- 승률 64.3%
- 평균 **+2.032%**

### 최근2년

- 8건
- 승률 62.5%
- 평균 **+1.769%**

즉 `상관 높음 = 나쁜 거래`가 아니다.

동일 테마가 강하게 움직이는 추세장에서는 높은 상관이 오히려 수익원일 수 있다.

따라서 correlation hard cap이나 자동 half-risk는 이 표본에서 정당화되지 않는다.

## 낮은 상관 priority 후보

`low_corr_priority`는 거래를 거절하지 않는다.

계좌에 빈 슬롯보다 후보가 더 많아 경쟁이 생길 때:

1. 현재 보유종목과 trailing-60d 최대 상관이 낮은 후보를 먼저 보고
2. 그 다음 ex-ante RR을 tie-break에 사용한다.

1차 탐색에서 OOS/recent가 동시에 개선돼 이 후보 하나만 80종목으로 고정 확인했다.

## 2차 확인 · 80 요청 / 77 사용

### OOS

Current RR:

- +27.49%
- Stress DD -10.27%
- 체결 193

Low-corr priority:

- **+32.80%**
- Stress DD -10.59%
- 체결 192

차이:

- 수익 **+5.31%p**
- Stress DD **-0.32%p 악화**

### 최근 약 2년

Current:

- +11.73%
- Stress DD -7.91%
- 체결 119

Low-corr:

- **+15.36%**
- Stress DD **-7.91% 동일**
- 체결 120

차이 +3.63%p.

## Leave-one-symbol-out

### OOS

활성종목 75개를 하나씩 제거:

- candidate 우위: **75/75 = 100%**
- candidate-current 차이: +0.37%p ~ +9.11%p
- median +5.31%p

### Recent

활성종목 63개:

- candidate 우위: **62/63 = 98.41%**
- 차이: -0.67%p ~ +6.76%p
- median +3.61%p

즉 특정 한 종목 하나가 만든 효과는 아니다.

## 그러나 시간축 안정성은 부족

OOS trade를 signal year별로 나누면:

- 2023: +0.17%p
- 2024: **-0.74%p**
- 2025: **+4.29%p**
- 2026: -0.02%p

전체 개선의 상당 부분이 2025에 집중돼 있다.

또한 OOS Stress DD가 current보다 0.32%p 악화했다.

따라서 `모든 환경에서 더 좋은 새로운 production allocator`라고 단정하기에는 부족하다.

## Production 결정

### 하지 않음

- corr 0.75 hard cap
- corr 0.60 hard cap
- 고상관 half-risk 자동 적용
- 기존 portfolio RR priority를 즉시 low-corr priority로 교체

### 연구상 유효한 활용

Correlation은 **거래 합격/탈락 조건**이 아니라 다음 용도로 더 적합하다.

- 포지션 슬롯이 실제로 경쟁할 때 참고 tie-break
- Paper 보유종목 대비 `포트폴리오 적합도` 정보
- 동시에 잡힌 후보가 같은 위험요인인지 사용자에게 표시

즉 `상관이 높으니 사지 마세요`가 아니라:

> 현재 보유 포지션과 움직임이 많이 겹칩니다. 개별 신호는 유효하지만 계좌 전체 노출은 커질 수 있습니다.

형태가 더 타당하다.

## 현재 최종 원칙

- 개별 전략 S/elite: correlation 영향 없음
- BUY/TARGET/STOP: 영향 없음
- Paper/live order 자동 차단: 없음
- high-correlation trade도 허용
- 향후 portfolio-fit UI/allocator를 만들 때 low-corr tie-break를 후보로 재사용

## 다음 우선순위

이번 구조검증 사이클에서:

1. Earnings EVENT RISK → **정보성 경고 production 반영**
2. Universe dollar-liquidity expansion → **현행 500 유지**
3. Portfolio correlation hard cap → **기각**
4. Low-corr priority → **유망하지만 시간안정성 부족으로 production 보류**

따라서 다음 실제 개선은 매매공식 숫자를 더 만지기보다 **Paper 실거래 표본을 쌓으면서 EVENT RISK / correlation / slippage가 실제 성과와 어떻게 연결되는지 추적하는 관측층**을 강화하는 쪽이 우선이다.
