from pathlib import Path
import re

import paper_entry

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'static' / 'app'


def test_home_serves_new_app_and_classic_keeps_research_dashboard():
    client = paper_entry.app.test_client()
    home = client.get('/')
    assert home.status_code == 200
    html = home.get_data(as_text=True)
    assert '/static/app/app.js' in html and '/static/app/app.css' in html
    assert 'dashboard.js' not in html
    classic = client.get('/classic')
    assert classic.status_code == 200
    assert 'dashboard.js' in classic.get_data(as_text=True)
    for asset in ('app.js', 'app.css'):
        assert client.get(f'/static/app/{asset}').status_code == 200


def test_navigation_is_four_plain_tabs():
    html = (APP / 'index.html').read_text(encoding='utf-8')
    assert re.findall(r'data-tab="(\w+)"', html) == ['today', 'search', 'paper', 'report']
    assert '/classic' in html
    assert '실제 주문 기능은 없으며' in html


def test_app_only_calls_existing_endpoints_and_no_control_characters():
    js = (APP / 'app.js').read_text(encoding='utf-8')
    assert not re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', js)
    rules = {str(rule) for rule in paper_entry.app.url_map.iter_rules()}
    called = set(re.findall(r"'(/api/[a-z\-/]+)'", js)) | set(re.findall(r'`(/api/[a-z\-/]+?)/?\$', js))
    assert called
    for path in called:
        assert any(rule == path or rule.startswith(path + '/<') for rule in rules), path
    for name in re.findall(r"'([a-z_]+\.json)'", js):
        assert (ROOT / 'static' / name).exists(), name


def test_paper_account_reuses_existing_browser_identity_keys():
    js = (APP / 'app.js').read_text(encoding='utf-8')
    assert "'swingLabPaperClientV1'" in js and "'swingLabPaperStateBackupV1'" in js
    assert "'X-Paper-Client'" in js


def test_demoted_strategy_is_not_offered_as_public():
    version = paper_entry.app.test_client().get('/api/version').get_json()
    assert version['public_strategies'] == ['confirmed_pullback', 'momentum_pullback']


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
    print('app shell PASS')


def test_research_files_are_served_through_the_api_with_a_whitelist():
    js = (APP / 'app.js').read_text(encoding='utf-8')
    assert "fetch(`/static/${name}" not in js and '/api/research/${name}' in js
    client = paper_entry.app.test_client()
    for name in re.findall(r"staticJson\('([a-z_]+\.json)'\)", js):
        assert name in paper_entry.app.view_functions['research_file'].__globals__['RESEARCH_FILES'], name
        response = client.get(f'/api/research/{name}')
        assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store' and isinstance(response.get_json(), dict)
    assert client.get('/api/research/latest_scan.json').status_code == 404
    assert client.get('/api/research/..%2Fconfig.py').status_code == 404


def test_research_route_prefers_the_newest_remote_copy(monkeypatch):
    import repo_data
    monkeypatch.setattr(repo_data, 'remote_enabled', lambda: True)
    monkeypatch.setattr(repo_data, '_remote_json', lambda name: {'from': 'remote', 'name': name})
    body = paper_entry.app.test_client().get('/api/research/evolution_candidate_shadow.json').get_json()
    assert body == {'from': 'remote', 'name': 'evolution_candidate_shadow.json'}


def test_signal_rows_keep_their_buy_and_sell_dates_on_phones():
    css = (APP / 'app.css').read_text(encoding='utf-8')
    js = (APP / 'app.js').read_text(encoding='utf-8')
    assert 'class="row plan-row"' in js
    assert '.row.plan-row .row-mid{display:block' in css.split('.row-mid{display:none}')[1]
