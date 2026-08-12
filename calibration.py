from pathlib import Path
import json

CALIBRATION_FILE = Path(__file__).parent / 'static' / 'score_calibration.json'
DEFAULT = {
    'version': 'default',
    'buckets': [
        {'min': 0, 'max': 49.99, 'calibrated': 40, 'win_rate': None, 'avg_return': None, 'samples': 0},
        {'min': 50, 'max': 59.99, 'calibrated': 52, 'win_rate': None, 'avg_return': None, 'samples': 0},
        {'min': 60, 'max': 69.99, 'calibrated': 62, 'win_rate': None, 'avg_return': None, 'samples': 0},
        {'min': 70, 'max': 79.99, 'calibrated': 73, 'win_rate': None, 'avg_return': None, 'samples': 0},
        {'min': 80, 'max': 89.99, 'calibrated': 83, 'win_rate': None, 'avg_return': None, 'samples': 0},
        {'min': 90, 'max': 100, 'calibrated': 92, 'win_rate': None, 'avg_return': None, 'samples': 0},
    ]
}

def load_calibration():
    try:
        if CALIBRATION_FILE.exists():
            return json.loads(CALIBRATION_FILE.read_text(encoding='utf-8'))
    except Exception:
        pass
    return DEFAULT

def apply_calibration(raw_score):
    raw = float(raw_score)
    data = load_calibration()
    bucket = None
    for b in data.get('buckets', []):
        if float(b['min']) <= raw <= float(b['max']):
            bucket = b
            break
    if bucket is None:
        return {'raw_score': round(raw,1), 'calibrated_score': round(raw,1), 'confidence': '기본', 'samples': 0}
    calibrated = float(bucket.get('calibrated', raw))
    samples = int(bucket.get('samples') or 0)
    confidence = '높음' if samples >= 1000 else '보통' if samples >= 300 else '낮음'
    return {
        'raw_score': round(raw,1),
        'calibrated_score': round(calibrated,1),
        'confidence': confidence,
        'samples': samples,
        'bucket_win_rate': bucket.get('win_rate'),
        'bucket_avg_return': bucket.get('avg_return'),
        'calibration_version': data.get('version','default')
    }

def calibrated_grade(score):
    s=float(score)
    return 'S' if s>=82 else 'A' if s>=72 else 'B' if s>=58 else 'C'
