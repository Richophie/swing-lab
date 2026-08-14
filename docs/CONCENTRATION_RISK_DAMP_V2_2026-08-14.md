# Concentration Risk Damp V2 · 2026-08-14

> 상태: DEVELOPMENT RESEARCH ONLY. 메인 종목선정, Frozen Forward V1/V2, 실제 주문 규칙을 변경하지 않는다.

## 왜 다시 보는가

과거 PR #27은 max-3 / 1% 구형 계좌에서 trailing-60d correlation을 연구했다. 당시 high-correlation hard cap과 자동 half-risk는 정당화되지 않았고, low-correlation priority는 일부 기간에서 유망했지만 시간축 안정성이 부족해 production 보류했다.

현재 개발 기준은 달라졌다.

- 확인형 + SMA200·20 + Donchian
- TRAIN 전략별 상위 50% 품질 gate
- TRAIN hybrid_50 priority
- 거래당 계좌위험 0.75%
- 최대 10포지션
- 자연청산
- daily-close MTM

따라서 예전 max-3 결과를 production에 이식하지 않고, 현재 기준에서 **후보를 탈락시키지 않는 soft risk damp**만 다시 확인한다.

## 사전 고정 정책

1. baseline: 집중도 무시, 0.75% 그대로
2. sector_half: 이미 같은 행동섹터 포지션이 2개 이상이면 새 후보만 0.375% 위험
3. corr_half: 보유종목 중 trailing-60d correlation >= 0.75가 있으면 새 후보만 0.375%
4. combined_half: 위 두 조건 중 하나라도 있으면 새 후보만 0.375%

두 조건이 동시에 걸려도 0.25배로 중복 감액하지 않고 0.5배 한 번만 적용한다.

## 행동섹터

회사 프로필의 현재 섹터 라벨을 과거에 소급하지 않는다. 각 신호일 시점까지의 trailing 60거래일 일수익률만 사용해 해당 종목이 11개 sector ETF 중 어디와 가장 높은 correlation을 보였는지로 행동섹터를 정한다.

- XLK 기술
- XLC 커뮤니케이션
- XLY 경기소비재
- XLP 필수소비재
- XLF 금융
- XLV 헬스케어
- XLI 산업재
- XLB 소재
- XLE 에너지
- XLU 유틸리티
- XLRE 부동산

이는 Global Flow Map V1과 같은 factor 축을 사용하지만 **Flow Score 자체를 매매에 사용하지 않는다.**

## 검증 규칙

- correlation/행동섹터: signal date 이후 데이터 금지
- minimum overlap 40 sessions
- 정책 parameter grid 금지
- valid candidate hard reject 금지
- rolling 2021~2026 TEST에서 baseline과 직접 비교
- stitched return만이 아니라 fold별 승패와 MTM MDD를 함께 본다
- baseline이 기존 0.75% 연구 결과 약 +89.45%를 재현하지 못하면 결과를 해석하지 않는다

## 승격 기준

이 연구에서 수익이 한 번 높다고 메인에 적용하지 않는다. 최소한 다음을 같이 확인해야 한다.

- 여러 TEST fold에서 baseline보다 반복적으로 우세
- MDD가 의미 있게 악화되지 않음
- 특정 한 해만의 효과가 아님
- concentration intervention이 충분히 발생해 결과가 우연한 1~2건이 아님

살아남더라도 historical data는 이미 본 개발 데이터이므로 별도 Frozen Challenger/Forward Shadow에서 다시 시험한 뒤에만 실제 메인 종목선정 또는 자금배분으로 승격한다.
