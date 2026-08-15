# Swing Lab 자동 연구일지

> 기준일: 2026-08-15  
> 상태: 운영 중인 연구 요약/변화 추적 계층

## 목적

자동 백테스트와 연구 파이프라인이 많은 숫자를 생성해도 사용자가 매번 내부 패널을 전부 읽지 않아도 되도록, 핵심 결론과 이전 실행 대비 변화를 한 화면에 정리한다.

이 계층은 **연구 결과를 읽고 기록하는 역할만 하며 실전 전략을 자동 변경하지 않는다.**

## 입력

- `static/strategy_optimizer_results.json`
- `static/portfolio_walkforward_results.json`
- `static/forward_review.json`

화면은 위 파일을 직접 읽어 최신 상태를 보여주고, 일일 연구 파이프라인은 별도로 `research_journal.py`를 실행해 비교 가능한 스냅샷을 저장한다.

## 출력

- `static/research_journal.json`

주요 내용:

- 현재 균형형 Optimizer 선두
- 검증 통과 조합 수
- 선두의 OOS 수익/CAGR/MTM MDD
- Walk-forward 최상위 연구가족과 등급
- Forward 게이트와 최소 표본 진행률
- 이전 자동연구 실행 대비 변화
- 현재 판정과 다음 행동
- 최근 스냅샷 history

## 자동 변화 기록

다음 항목을 이전 실행과 비교한다.

1. 균형형 선두 전략 조합 변경
2. 선두 OOS 누적수익의 유의미한 변화
3. 검증 통과 조합 수 변화
4. Walk-forward 최상위 가족 변경
5. Walk-forward A/B/C 연구등급 변경
6. Forward promotion gate 변경
7. Forward 최소표본 진행률 증가

변화가 없으면 “핵심 선두·등급·Forward 게이트에 유의미한 변화 없음”으로 기록한다.

## 안전 경계

자동 연구일지는 아래 정책을 바꾸지 않는다.

- production strategy auto mutation: OFF
- automatic promotion: OFF
- live broker order submission: OFF
- Forward 표본 게이트 우회: 금지

Optimizer나 Walk-forward 숫자가 좋아져도 Forward 기준을 충족하기 전에는 실전 규칙을 자동 교체하지 않는다.

## 실행 위치

`.github/workflows/replay-lab-v2.yml`의 Daily Backtest Research Pipeline 마지막 연구 단계에서:

1. Replay pool 갱신
2. Optimizer
3. 전략별 선택 연구
4. Rolling Walk-forward
5. Regime/Volatility/Priority/Flow 진단
6. `research_journal.py`
7. journal validation
8. 모든 연구 JSON을 한 번에 `[skip render]` 데이터 커밋

## UI

`백테스트연구소` 상단의 `AI RESEARCH JOURNAL · 오늘의 자동연구` 카드에서 다음 순서로 읽는다.

1. 오늘 결론
2. 탐색량 / 백테스트 선두 / 재현성 / 미래검증
3. 지난 자동연구 대비 달라진 점
4. 다음 행동
5. 오늘 연구에서 읽어야 할 핵심 근거

상세 Optimizer/Walk-forward/진단 패널은 기존처럼 개발용 `자동 검증 기록` 안에 접어서 유지한다.
