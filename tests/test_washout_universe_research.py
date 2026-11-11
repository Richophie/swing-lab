import json
from pathlib import Path

import washout_universe_research as wu


def _table(rows):
    body = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    return f'<table><tr><th>Symbol</th><th>Security</th></tr>{body}</table>'


def test_parse_members_reads_the_symbol_column_of_the_large_table_only():
    small = '<table><tr><th>Symbol</th></tr><tr><td>ZZZ</td></tr></table>'
    rows = [[f'T{i:03d}', 'Company'] for i in range(320)] + [['BRK.B', 'Class B'], ['<a href="#">LNK</a>', 'Linked']]
    members = wu.parse_members(small + _table(rows))
    assert 'ZZZ' not in members and 'T000' in members and 'BRK-B' in members and 'LNK' in members
    assert len(members) == 322


def test_parse_members_fails_loudly_without_a_table():
    try:
        wu.parse_members('<p>nothing here</p>')
    except RuntimeError:
        return
    raise AssertionError('expected an error')


def test_saved_report_contract():
    path = Path('static/washout_universe_research.json')
    if not path.exists():
        return
    d = json.loads(path.read_text(encoding='utf-8'))
    assert d['status'] == 'RESEARCH_ONLY' and d['survivorship_free'] is False and d['frozen_rules_mutated'] is False
    assert set(d['groups']) == set(wu.SOURCES)
    for group in d['groups'].values():
        assert set(wu.LIQUIDITY_FLOORS) <= set(group)


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
    print('washout universe research PASS')
