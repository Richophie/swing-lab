from __future__ import annotations

from flask import jsonify, request

from app import app, _decorate_paper_snapshot, _paper_state_path
from paper_restore import restore_browser_backup


@app.route('/api/paper/restore', methods=['POST'])
def paper_restore_api():
    body = request.get_json(silent=True) or {}
    try:
        restored = restore_browser_backup(body.get('state') or {}, state_path=_paper_state_path())
        return jsonify(_decorate_paper_snapshot(restored))
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400
