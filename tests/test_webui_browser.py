"""Headless-browser smoke test for the M1.2 frontend (``webui.py``'s
embedded ``_PAGE`` JS) -- covers exactly what pytest structurally can't:
real clicking, real tab switching, real clipboard behavior. Written after
a ChatGPT review round caught bugs in precisely this territory (tab
result-leakage, a rendering guard that hid a real result) that the
existing structural tests in ``test_presenter.py``/``test_webui.py`` never
could have seen.

Chromium only (no cross-browser coverage yet) and deliberately its own
test file: it needs ``playwright install chromium`` first, which the
plain ``pytest -q`` matrix jobs don't run, so this whole file skips
cleanly via ``pytest.importorskip`` when the ``browser`` extra isn't
installed -- see ``pyproject.toml``. CI runs it as its own job, once, not
per Python version.
"""

from __future__ import annotations

import threading
from wsgiref.simple_server import make_server

import pytest

playwright_sync_api = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright_sync_api.sync_playwright

from ohmwork.webui import _QuietWSGIRequestHandler, app

# Q1 from the M1b/M1.2 acceptance set (docs/CHARTER.md): A,B,C; F=0 only
# when A=B=C=1. AOI and OAI both land on F'=ABC -- the canonical
# deduplication case presenter.py's `_group_candidates` exists for.
_Q1_VARS = "A,B,C"
_Q1_ONES_ROW_COUNT = 7  # rows 0-6 -> output 1, row 7 (111) stays 0


@pytest.fixture(scope="module")
def server_url():
    httpd = make_server("127.0.0.1", 0, app, handler_class=_QuietWSGIRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.fixture
def page(server_url):
    # Tracks uncaught JS exceptions across every test that uses this
    # fixture (not just a dedicated one) -- the manual checklist's own
    # cross-cutting requirement is "no uncaught console errors at any
    # point," and asserting it here covers that for every scenario the
    # rest of this file already exercises.
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        page_errors: list[str] = []
        pg.on("pageerror", lambda exc: page_errors.append(str(exc)))
        pg.goto(server_url + "/")
        yield pg
        assert not page_errors, f"uncaught JS error(s) during test: {page_errors}"
        browser.close()


def _switch_tab(page, tab: str) -> None:
    page.click(f'button.tab[data-tab="{tab}"]')


def _run_derivation(page, expression: str) -> None:
    page.fill("#tt-expr", expression)
    page.click("#panel-tt button.submit")
    page.wait_for_selector("#tt-output:not(.empty)")


def _build_q1_grid(page) -> None:
    _switch_tab(page, "synth")
    page.check('input[name="synth-mode"][value="table"]')
    page.fill("#synth-vars", _Q1_VARS)
    page.wait_for_selector("table.truth-grid")
    cells = page.locator("table.truth-grid button.cell-btn")
    for i in range(_Q1_ONES_ROW_COUNT):
        cells.nth(i).click()  # 0 -> 1, one click each; row 7 stays "0"


def _submit_q1(page) -> None:
    _build_q1_grid(page)
    page.click("#panel-synth button.submit")
    page.wait_for_selector("#synth-result:not(.empty)")


# --- Tab / result isolation --------------------------------------------------------
#
# The bug: tt-output/synth-error/synth-result lived outside the .panel
# elements tab-switching toggles, so a result stayed visible after
# switching tabs. Fixed by moving each result container inside its own
# panel; this pins that it stays fixed.


def test_derivation_result_hidden_after_switching_to_synthesis(page):
    _run_derivation(page, "xy + xy'")
    assert page.is_visible("#tt-output")

    _switch_tab(page, "synth")
    assert not page.is_visible("#tt-output")


def test_synth_result_hidden_after_switching_to_derivation(page):
    _submit_q1(page)
    assert page.is_visible("#synth-result")

    _switch_tab(page, "tt")
    assert not page.is_visible("#synth-result")


def test_each_panel_keeps_its_own_result_across_tab_switches(page):
    _run_derivation(page, "xy + xy'")
    _switch_tab(page, "synth")
    _submit_q1(page)

    _switch_tab(page, "tt")
    assert "F = x" in page.text_content("#tt-output")

    _switch_tab(page, "synth")
    assert page.is_visible("#synth-result")
    assert "3-input NAND" in page.text_content("#res-gate-line")


# --- Q1's single combined AOI/OAI row ------------------------------------------------
#
# The bug: webui.py only rendered `reasoning.alternatives` list items when
# there were 2+ groups, so Q1's single deduplicated AOI/OAI group rendered
# nothing at all.


def test_q1_shows_exactly_one_combined_alternative_row(page):
    _submit_q1(page)
    rows = page.locator("#res-alternatives li")
    assert rows.count() == 1
    text = rows.first.text_content()
    assert "AOI" in text and "OAI" in text
    assert "chosen" in text


# --- Grid cycling and submission ----------------------------------------------------


def test_grid_cell_cycles_0_1_x_0(page):
    _switch_tab(page, "synth")
    page.check('input[name="synth-mode"][value="table"]')
    page.fill("#synth-vars", "A,B")
    page.wait_for_selector("table.truth-grid")
    cell = page.locator("table.truth-grid button.cell-btn").first

    assert cell.get_attribute("data-val") == "0"
    cell.click()
    assert cell.get_attribute("data-val") == "1"
    cell.click()
    assert cell.get_attribute("data-val") == "X"
    cell.click()
    assert cell.get_attribute("data-val") == "0"


def test_changing_variables_rebuilds_the_grid(page):
    _switch_tab(page, "synth")
    page.check('input[name="synth-mode"][value="table"]')
    page.fill("#synth-vars", "A,B")
    page.wait_for_selector("table.truth-grid")
    page.locator("table.truth-grid button.cell-btn").first.click()  # -> "1"

    page.fill("#synth-vars", "A,B,C")
    page.wait_for_selector("table.truth-grid")
    cells = page.locator("table.truth-grid button.cell-btn")
    assert cells.count() == 8
    assert cells.first.get_attribute("data-val") == "0"  # rebuilt, not carried over


def test_grid_submission_gives_the_q1_acceptance_result(page):
    _submit_q1(page)
    assert "6" in page.text_content("#res-gate-line")
    assert "NAND" in page.text_content("#res-gate-line")


# --- Collapse behavior --------------------------------------------------------------


def test_manual_entry_collapsed_by_default(page):
    _switch_tab(page, "synth")
    page.check('input[name="synth-mode"][value="table"]')
    assert page.get_attribute("#synth-manual-details", "open") is None


def test_advanced_details_collapsed_by_default(page):
    _submit_q1(page)
    details = page.locator("#synth-result details.section")
    assert details.get_attribute("open") is None
    assert not page.is_visible("#res-advanced")


def test_advanced_details_expands_to_the_exact_legacy_report(page):
    _submit_q1(page)
    page.click("#synth-result details.section summary")
    assert page.get_attribute("#synth-result details.section", "open") is not None
    assert page.is_visible("#res-advanced")

    advanced_text = page.text_content("#res-advanced")
    # The exact legacy CLI report: candidates, chosen realization, and the
    # D7 verification block -- unaffected by the student-facing view above it.
    assert "F' = ABC" in advanced_text
    assert "Verification" in advanced_text
    assert "AOI" in advanced_text and "OAI" in advanced_text


# --- Error-state cleanup -------------------------------------------------------------
#
# Checklist requirement: an invalid input shows a clear inline error with
# no partial/stale result left visible.


def test_invalid_output_name_shows_error_and_clears_stale_result(page):
    _submit_q1(page)
    assert page.is_visible("#synth-result")

    page.fill("#synth-output-name", "Out")
    page.click("#panel-synth button.submit")
    page.wait_for_selector("#synth-error:not(.empty)")

    assert not page.is_visible("#synth-result")
    assert "error" in page.text_content("#synth-error").lower()

    page.fill("#synth-output-name", "")
    page.click("#panel-synth button.submit")
    page.wait_for_selector("#synth-result:not(.empty)")
    assert not page.is_visible("#synth-error")


# --- Copy Solution content -----------------------------------------------------------
#
# The bug: "Copy solution" only copied 4 summary lines, omitting
# PDN/PUN/transistor breakdown/stack heights/reasoning.


def _hijack_clipboard(page) -> None:
    page.evaluate(
        """() => {
            window.__copiedText = null;
            navigator.clipboard.writeText = (t) => {
                window.__copiedText = t;
                return Promise.resolve();
            };
        }"""
    )


def _click_and_read_copy(page, button_selector: str) -> str:
    page.click(button_selector)
    page.wait_for_function("window.__copiedText !== null")
    return page.evaluate("window.__copiedText")


def test_copy_solution_includes_the_full_student_facing_solution(page):
    _submit_q1(page)
    _hijack_clipboard(page)
    copied = _click_and_read_copy(page, "#copy-solution")

    for expected in [
        "3-input NAND",
        "6 transistors",
        "F = (ABC)'",
        "PDN (NMOS)",
        "PUN (PMOS)",
        "NMOS count: 3",
        "PMOS count: 3",
        "Stack heights",
        "Reasoning:",
        "AOI/OAI",
    ]:
        assert expected in copied, f"missing {expected!r} in copied solution text:\n{copied}"


def test_copy_advanced_report_is_unchanged_legacy_text(page):
    _submit_q1(page)
    _hijack_clipboard(page)
    copied = _click_and_read_copy(page, "#copy-advanced")

    assert "F' = ABC" in copied or "F'=ABC" in copied
    assert "Verification" in copied or "verified" in copied.lower()


def test_copy_solution_uses_the_custom_output_name(page):
    # checklist requirement: "Copy solution"'s text uses the chosen output
    # name (Advanced Details/Copy advanced report must NOT -- that's
    # covered by test_copy_advanced_report_is_unchanged_legacy_text above).
    _build_q1_grid(page)
    page.fill("#synth-output-name", "Y")
    page.click("#panel-synth button.submit")
    page.wait_for_selector("#synth-result:not(.empty)")

    _hijack_clipboard(page)
    solution_copy = _click_and_read_copy(page, "#copy-solution")
    assert "Y = (ABC)'" in solution_copy
    assert "F = (ABC)'" not in solution_copy

    _hijack_clipboard(page)
    advanced_copy = _click_and_read_copy(page, "#copy-advanced")
    assert "F' = ABC" in advanced_copy  # advanced report always says F/F', regardless of output name
