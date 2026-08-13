import os

import repo_data


class _Response:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _Session:
    def __init__(self, data=None, fail=False):
        self.data = data
        self.fail = fail
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError('network down')
        return _Response(self.data)


def test_explicit_off_disables_remote_even_on_render():
    old_render = os.environ.get('RENDER')
    old_override = os.environ.get('SWING_LAB_REMOTE_DATA')
    try:
        os.environ['RENDER'] = 'true'
        os.environ['SWING_LAB_REMOTE_DATA'] = '0'
        assert repo_data.remote_enabled() is False
    finally:
        if old_render is None:
            os.environ.pop('RENDER', None)
        else:
            os.environ['RENDER'] = old_render
        if old_override is None:
            os.environ.pop('SWING_LAB_REMOTE_DATA', None)
        else:
            os.environ['SWING_LAB_REMOTE_DATA'] = old_override


def test_remote_static_json_is_cached_and_falls_back_locally():
    old_override = os.environ.get('SWING_LAB_REMOTE_DATA')
    old_session = repo_data._session
    try:
        os.environ['SWING_LAB_REMOTE_DATA'] = '1'
        repo_data.clear_cache()
        fake = _Session({'fresh': 1})
        repo_data._session = fake
        path = repo_data.STATIC / '__repo_data_test__.json'
        first = repo_data.load_json(path, {'fallback': True})
        second = repo_data.load_json(path, {'fallback': True})
        assert first == {'fresh': 1}
        assert second == {'fresh': 1}
        assert fake.calls == 1

        repo_data.clear_cache()
        repo_data._session = _Session(fail=True)
        fallback = repo_data.load_json(path, {'fallback': True})
        assert fallback == {'fallback': True}
    finally:
        repo_data._session = old_session
        repo_data.clear_cache()
        if old_override is None:
            os.environ.pop('SWING_LAB_REMOTE_DATA', None)
        else:
            os.environ['SWING_LAB_REMOTE_DATA'] = old_override


def main():
    test_explicit_off_disables_remote_even_on_render()
    test_remote_static_json_is_cached_and_falls_back_locally()
    print('repo data PASS')


if __name__ == '__main__':
    main()
