# Live Research Overlay

> 기준일: 2026-08-15  
> 상태: production ranking 보조 규칙

## 목적

자동 백테스트·OOS·Rolling Walk-forward 연구를 메인 종목찾기와 완전히 분리해 두지 않고, 검증 수준에 맞게 보수적으로 반영한다.

현재 연구는 유용한 방향성을 보여주지만 Forward 표본과 Walk-forward 재현성이 아직 충분하지 않다. 따라서 연구 결과를 production hard gate나 BUY/TARGET/STOP에 직접 승격하지 않는다.

## 적용 순서

1. canonical 전략 신호 계산
2. 기존 live 엄선 hard gate 계산
3. 기존 base elite score로 합격/탈락 확정
4. 자동연구 결과를 전략별 research profile로 읽음
5. 합격 여부를 건드리지 않은 채 후보 정렬용 score에만 작은 보정 적용
6. 화면에서 base score와 research-adjusted score를 구분해 설명

## 현재 hard gate

연구 overlay 이전과 동일하다.

- gross RR >= 1.20
- flow >= 42
- 시장 `조심` 제외
- entry viable
- stop margin >= 1.5 ATR
- base elite score >= 72

## Research overlay

입력 데이터:

- `static/strategy_optimizer_results.json`
- `static/strategy_selection_results.json`
- `static/portfolio_walkforward_results.json`
- `static/portfolio_regime_results.json`

정책:

- mode: `soft_rank_only`
- 최대 가점: +2.0점
- 최대 감점: -1.5점
- hard gate 변경: 금지
- BUY/TARGET/STOP 변경: 금지
- 자동 production 승격: 금지
- 실브로커 주문 영향: 없음

현재 연구 결과가 C등급이거나 단순 diagnostic인 경우 이를 hard filter로 바꾸지 않는다. 해당 정보는 `연구 관찰`로 표시하고 후보의 해석과 다음 연구에 사용한다.

## 화면 표현

메인 후보 카드:

- 연구 우세 / 연구 지지 / 연구 관찰 / 연구 중립
- 연구 보정 점수
- 가능한 경우 `기본점수 → 연구반영 순위점수`
- 핵심 근거 한 줄

종목 상세:

- 현재 자리 기본점수
- 연구반영 순위점수
- Optimizer OOS
- Walk-forward 등급과 양(+) 구간 수
- 연구점수는 성공확률이 아니라는 설명

## 승격 조건

연구 결과가 실제 hard gate, 전략 조건, position sizing, BUY/TARGET/STOP을 변경하려면 별도의 전략 변경으로 취급한다. `VALIDATION_PROTOCOL.md`의 OOS/Walk-forward/독립감사/Paper 조건과 Forward 표본을 거친 뒤 명시적으로 승격해야 한다.

## 안전 회귀 테스트

`tests/test_research_overlay.py`는 다음을 고정한다.

- research score adjustment 범위
- hard gate mutation false
- BUY/TARGET/STOP mutation false
- automatic production promotion false
- 알 수 없는 전략은 0점 보정

이 안전 경계가 깨지면 live research overlay 변경은 배포하지 않는다.
