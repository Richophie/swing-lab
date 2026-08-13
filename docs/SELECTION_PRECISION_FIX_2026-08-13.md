# Selection Precision Fix · 2026-08-13

## 발견 배경

NET RR sensitivity 연구 중 현재 스캔의 WRB RSI2 계획을 비용모델로 재계산했을 때 gross RR이 약 `1.1949`였으나 기존 trade plan에는 표시용으로 `1.20`이 저장되어 있었다.

기존 scanner hard gate는 이 **2자리 반올림 값**을 그대로 `>= 1.20`과 비교했다.

따라서 실제 계산값이 1.20보다 조금 낮은 거래가 경계에서 통과할 수 있었다.

## 수정

- 화면/기존 호환용 `risk_reward` 2자리 값은 유지
- elite hard gate용 RR은 BUY/TARGET/STOP 가격 수준에서 다시 계산한 `risk_reward_gate`를 사용
- gate 값은 4자리 정밀도로 저장
- `checks.risk_reward`도 precise gross RR로 판정
- elite score의 RR 항목도 같은 precise gross RR 사용
- 비용후 `net_risk_reward`는 진단값으로 함께 저장
- **net RR은 아직 hard gate가 아니다**

장중 이탈로그도 precise RR을 사용하므로 더 이상 `1.20 < 1.20`처럼 반올림 때문에 모순된 이유를 표시하지 않는다.

## 정책 유지

이번 수정은 RR threshold를 높이거나 낮추는 전략 튜닝이 아니다.

현재 정책은 그대로:

- gross RR hard gate >= 1.20
- net RR = 정보/연구용

단지 내부 판정은 원래 값으로 하고 UI 표현만 반올림한다.

## 테스트

새 회귀 테스트는 다음을 강제한다.

- 실제 RR 약 1.195가 표시상 1.20이어도 탈락
- 실제 RR 1.20 이상은 RR check 통과
- net RR이 1.20 아래여도 현재 정책상 gross RR이 통과하면 net RR만으로 탈락시키지 않음

이는 `docs/NET_RR_RESEARCH_2026-08-13.md`의 결론과 일치한다.
