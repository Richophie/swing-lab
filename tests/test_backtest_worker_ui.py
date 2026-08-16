from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def main() -> None:
    core = text("replay_v2_core.js")
    ui = text("lab_replay_ui.js")
    worker = text("replay_worker.js")
    loader = text("lab_dashboard.js")
    html = text("dashboard.html")
    math = text("replay_math.js")

    assert "new Worker('/static/replay_worker.js" in core
    assert "fetch('/static/replay_backtest_pool_v2.json'" not in core
    assert "SwingReplayWorker.run" in ui
    assert "await window.SwingReplayWorker.run" in ui
    assert "worker_result_ui.js" in loader
    assert "v=20260816-2" in html
    assert "globalThis.SwingSequenceReplay" in math
    assert "replay_backtest_pool_v2.json" in worker
    assert "SwingSequenceReplay.run(rows" in worker
    assert "ablation(rows" in worker
    assert "postMessage({type:'progress'" in worker
    assert "renderSwingWorkerResult" in text("worker_result_ui.js")
    print("backtest worker UI tests: PASS")


if __name__ == "__main__":
    main()
