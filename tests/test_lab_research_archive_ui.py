from pathlib import Path


def test_research_archive_does_not_install_recursive_mutation_observer():
    src = Path("static/lab_research_archive.js").read_text(encoding="utf-8")
    assert "MutationObserver" not in src
    assert "function setText" in src
    assert "x.textContent!==text" in src


def test_lab_loader_cache_busts_archive_fix():
    src = Path("static/lab_dashboard.js").read_text(encoding="utf-8")
    assert "20260816-1" in src
    assert "lab_research_archive.js" in src
