# Swing Lab Autonomous Experiment Loop

> 상태: 자동 연구 가설 생성/판정 규칙  
> 기준일: 2026-08-15

## 목적

Swing Lab의 자동연구가 단순히 고정된 백테스트를 반복하는 데서 끝나지 않고, 매일 생성되는 OOS·Walk-forward·시장상태·우선순위·Flow 진단을 읽어 **다음 연구 질문을 자동으로 만들고 판정**하게 한다.

핵심 루프:

1. 기존 일일 연구 실행
2. 약점/반복 패턴 탐지
3. 가설 자동 생성
4. 실험 큐 우선순위 부여
5. TRAIN에서만 선택/튜닝
6. 다음 OOS 구간은 report-only로 판정
7. `DROP / WATCH / CHALLENGER_CANDIDATE` 분류
8. 다음 데이터 갱신 때 재평가

## 현재 자동 생성 실험

### Adaptive volatility sizing

Walk-forward 재현성이 약하거나 고변동 drag 진단이 감지되면 생성한다.

각 rolling fold에서:

- 품질 엄선 강도: TRAIN에서만 선택
- 고변동 risk multiplier: `1.0 / 0.75 / 0.5 / 0.0`
- multiplier 선택: TRAIN에서만 선택
- 다음 calendar-year TEST에는 고정 적용
- TEST를 본 뒤 같은 fold를 재튜닝하지 않음

이 실험은 기존 전략 신호, BUY/TARGET/STOP을 변경하지 않고 포트폴리오 risk allocation만 연구한다.

### Regime gate review

기존 rolling regime 연구의 TRAIN-only gate 선택 결과를 자동 판독한다.

### Priority ranker review

현재 priority와 quality percentile / hybrid ranker의 rolling OOS 결과를 비교한다.

### Flow selection review

Flow는 현재 development evidence이므로 결과가 좋아도 `WATCH`까지만 허용한다.

## 상태 정의

- `QUEUED`: 새 가설, 아직 실행 전
- `RETEST`: 입력 연구데이터가 갱신되어 재실험 필요
- `DROP`: OOS 반복성 부족, 현재 가설 폐기
- `WATCH`: 방향성은 있으나 표본/재현성 부족
- `CHALLENGER_CANDIDATE`: 별도 Frozen Forward Challenger로 검토할 가치가 있는 연구 후보
- `BLOCKED`: 데이터/runner 문제로 판정 불가

`CHALLENGER_CANDIDATE`는 Production 승격을 뜻하지 않는다.

## 안전 경계

자동 실험 루프가 할 수 없는 것:

- Production 전략 규칙 자동 변경
- BUY/TARGET/STOP 자동 변경
- 기존 Frozen V1~V4 재튜닝
- Forward Challenger 자동 생성
- Production 자동 승격
- 실브로커 주문

자동연구는 공격적으로 반복하되 실전 변경은 별도 검증/승격 게이트를 유지한다.

## 자동 실행

`.github/workflows/auto-experiment-loop.yml`

- `Daily Backtest Research Pipeline` 성공 완료 후 자동 실행
- 코드 변경 후 main push 시에도 실행
- `auto_experiment_queue.py`가 가설 생성
- `auto_experiment_runner.py`가 큐를 소비하고 판정
- 결과는 아래에 저장
  - `static/auto_experiment_queue.json`
  - `static/auto_experiment_results.json`

## UI

백테스트연구소의 `AI RESEARCH JOURNAL` 바로 아래에서 자동 실험 큐를 확인한다.

사용자가 우선 확인할 항목:

- 지금 새로 생긴 연구 질문
- 왜 이 질문이 생성됐는지
- 어떤 OOS 방식으로 검사했는지
- DROP/WATCH/Challenger 후보 판정
- Production 자동변경이 꺼져 있는지
