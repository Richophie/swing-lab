from __future__ import annotations

from datetime import date
from pathlib import Path
import hashlib
import tempfile

import pit_universe as pit
import pit_replay_pool as pit_replay


def verified_manifest():
    return {
        'strict_no_current_universe_fallback': True,
        'prohibited_fallbacks': ['current screener'],
        'membership_source': {
            'status': 'VERIFIED',
            'coverage': {'start': '2016-01-01', 'end': '2026-12-31'},
            'includes_inactive': True,
            'stable_security_ids': True,
            'ticker_history': True,
        },
        'price_source': {
            'status': 'VERIFIED',
            'coverage': {'start': '2016-01-01', 'end': '2026-12-31'},
            'includes_inactive': True,
            'daily_ohlcv': True,
            'corporate_action_adjustment': True,
        },
    }


def w(asset='SEC1', symbol='AAA', start='2017-01-01', end=None):
    return pit.MembershipWindow(
        security_id=asset,
        symbol=symbol,
        start_date=date.fromisoformat(start),
        end_date=None if end is None else date.fromisoformat(end),
        source_id='fixture',
    )


def test_membership_boundaries_are_inclusive_and_entry_must_still_be_member():
    rows = [w(end='2020-06-30')]
    assert pit.symbols_on(date(2017, 1, 1), rows) == ['AAA']
    assert pit.symbols_on(date(2020, 6, 30), rows) == ['AAA']
    assert pit.symbols_on(date(2020, 7, 1), rows) == []
    assert pit.eligible_for_signal_and_entry('SEC1', date(2020, 6, 29), date(2020, 6, 30), rows)
    assert not pit.eligible_for_signal_and_entry('SEC1', date(2020, 6, 30), date(2020, 7, 1), rows)


def test_ticker_change_uses_stable_security_identity_without_overlap():
    rows = [
        w(symbol='OLD', start='2017-01-01', end='2019-12-31'),
        w(symbol='NEW', start='2020-01-01', end=None),
    ]
    pit.validate_windows(rows)
    assert pit.window_for('SEC1', date(2019, 12, 31), rows).symbol == 'OLD'
    assert pit.window_for('SEC1', date(2020, 1, 1), rows).symbol == 'NEW'


def test_overlapping_identity_windows_are_rejected():
    rows = [
        w(symbol='OLD', start='2017-01-01', end='2020-01-15'),
        w(symbol='NEW', start='2020-01-01', end=None),
    ]
    try:
        pit.validate_windows(rows)
        raise AssertionError('overlap should have failed')
    except ValueError as exc:
        assert 'overlapping windows' in str(exc)


def test_same_ticker_cannot_map_to_two_securities_at_once():
    rows = [w('SEC1', 'AAA'), w('SEC2', 'AAA')]
    try:
        pit.validate_windows(rows)
        raise AssertionError('ambiguous ticker reuse should have failed')
    except ValueError as exc:
        assert 'multiple security_ids' in str(exc)


def test_csv_requires_stable_security_id_not_ticker_only():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'membership.csv'
        path.write_text(
            'security_id,symbol,start_date,end_date,source_id,exchange,security_name\n'
            ',AAA,2017-01-01,,fixture,NYSE,AAA Corp\n',
            encoding='utf-8',
        )
        try:
            pit.load_membership_csv(path)
            raise AssertionError('ticker-only row should have failed')
        except ValueError as exc:
            assert 'stable PIT identifier' in str(exc)


def test_unverified_or_missing_inactive_sources_block_pit_ready():
    manifest = verified_manifest()
    manifest['price_source']['status'] = 'UNCONFIGURED'
    manifest['price_source']['includes_inactive'] = False
    report = pit.audit_dataset(manifest, [w()], min_active=1)
    assert report['ready'] is False
    assert report['status'] == 'BLOCKED_INCOMPLETE_PIT_DATA'
    assert any('prices source' in x for x in report['blocking_reasons'])


def test_verified_full_coverage_can_become_ready_without_current_fallback():
    report = pit.audit_dataset(verified_manifest(), [w()], min_active=1)
    assert report['ready'] is True
    assert report['status'] == 'READY_FOR_PIT_REPLAY'
    assert report['strict_no_current_universe_fallback'] is True
    assert report['methodology']['current_universe_fallback_allowed'] is False


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def test_pit_status_artifact_is_isolated_and_never_overwrites_current_replay():
    assert pit_replay.OUT.name == 'replay_backtest_pool_pit_v1.json'
    assert pit_replay.LEGACY_POOL.name == 'replay_backtest_pool_v2.json'
    assert pit_replay.OUT != pit_replay.LEGACY_POOL
    before = _sha(pit_replay.LEGACY_POOL)
    result = pit_replay.build_status()
    after = _sha(pit_replay.LEGACY_POOL)
    assert before == after
    assert result['ready'] is False
    assert result['status'] == 'BLOCKED_PIT_SOURCE'
    assert result['output_isolated_from_current_replay'] is True
    assert result['production_main_picker_mutated'] is False
    assert result['forward_challengers_mutated'] is False


def test_pit_module_cannot_silently_import_current_universe_fallbacks():
    src = Path('pit_universe.py').read_text(encoding='utf-8')
    for forbidden in ('research_universe', 'prefilter_symbols', 'load_us_universe', 'static_liquid_fallback'):
        assert forbidden not in src
    replay_src = Path('pit_replay_pool.py').read_text(encoding='utf-8')
    assert 'from rsi2_broad_regime_research' not in replay_src
    assert 'from market_data import prefilter_symbols' not in replay_src
    audit_src = Path('pit_universe_audit.py').read_text(encoding='utf-8')
    for frozen in ('priority_challenger_v1', 'priority_challenger_v2', 'priority_challenger_v3', 'priority_challenger_v4'):
        assert frozen not in audit_src


def main():
    test_membership_boundaries_are_inclusive_and_entry_must_still_be_member()
    test_ticker_change_uses_stable_security_identity_without_overlap()
    test_overlapping_identity_windows_are_rejected()
    test_same_ticker_cannot_map_to_two_securities_at_once()
    test_csv_requires_stable_security_id_not_ticker_only()
    test_unverified_or_missing_inactive_sources_block_pit_ready()
    test_verified_full_coverage_can_become_ready_without_current_fallback()
    test_pit_status_artifact_is_isolated_and_never_overwrites_current_replay()
    test_pit_module_cannot_silently_import_current_universe_fallbacks()
    print('PIT universe foundation PASS')


if __name__ == '__main__':
    main()
