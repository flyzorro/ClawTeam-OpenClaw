from pathlib import Path


def test_board_static_ui_parses_structured_result_statuses():
    html = Path("clawteam/board/static/index.html").read_text(encoding="utf-8")

    assert "function parseStructuredResult(content)" in html
    assert "pass_with_risk" in html
    assert "resultTone(parsed.value)" in html
