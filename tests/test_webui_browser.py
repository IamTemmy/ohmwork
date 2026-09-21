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

import json
from pathlib import Path
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
    page.wait_for_selector("#tt-result:not(.empty)")


def _open_tt_advanced_exports(page) -> None:
    # tt-format, #tt-copy-formatted, and #tt-preview-details all live
    # inside the collapsed "Advanced exports" <details> now -- open it
    # before interacting with anything inside.
    page.click("#tt-advanced-exports summary")


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


def _submit_via_expression(page, expression: str = "(abc)'") -> None:
    _switch_tab(page, "synth")
    page.check('input[name="synth-mode"][value="expr"]')
    page.fill("#synth-expr", expression)
    page.click("#panel-synth button.submit")
    page.wait_for_selector("#synth-result:not(.empty)")


# --- Real responses + a controllable fetch mock, for the request-race tests ----------
#
# Uses Playwright's own APIRequestContext (page.request) to fetch a real,
# schema-correct response body directly over HTTP -- independent of
# whatever the page's own `window.fetch` has been monkeypatched to, so
# this always reflects the real server, never a hand-maintained fake of
# presenter.py's JSON shape.


def _real_json(page, path: str, payload: dict) -> dict:
    resp = page.request.post(
        page.url.rstrip("/") + path,
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    return resp.json()


def _install_fetch_mock(page) -> None:
    # Replaces window.fetch with one that never resolves on its own --
    # each call is queued, and the test resolves specific queue entries,
    # in whatever order it chooses, via _resolve_fetch below.
    page.evaluate(
        """() => {
            window.__fetchQueue = [];
            window.fetch = (url, opts) => new Promise((resolve) => {
                window.__fetchQueue.push({ url, resolve });
            });
        }"""
    )


def _resolve_fetch(page, index: int, response_body: dict) -> None:
    page.evaluate(
        """({index, body}) => {
            const entry = window.__fetchQueue[index];
            window.__fetchQueue[index] = null;
            entry.resolve({ json: async () => body });
        }""",
        {"index": index, "body": response_body},
    )


# --- Tab / result isolation --------------------------------------------------------
#
# The bug: tt-output/synth-error/synth-result lived outside the .panel
# elements tab-switching toggles, so a result stayed visible after
# switching tabs. Fixed by moving each result container inside its own
# panel; this pins that it stays fixed.


def test_derivation_result_hidden_after_switching_to_synthesis(page):
    _run_derivation(page, "xy + xy'")
    assert page.is_visible("#tt-result")

    _switch_tab(page, "synth")
    assert not page.is_visible("#tt-result")


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
    assert page.text_content("#tt-function-line") == "F = x"

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


def _hijack_rich_clipboard(page) -> None:
    # Stubs the rich, multi-MIME navigator.clipboard.write(ClipboardItem)
    # path specifically -- separate from _hijack_clipboard above, which
    # only stubs the plain writeText() path other copy buttons use.
    page.evaluate(
        """() => {
            window.__richClipboard = null;
            navigator.clipboard.write = async (items) => {
                const item = items[0];
                const html = await (await item.getType("text/html")).text();
                const plain = await (await item.getType("text/plain")).text();
                window.__richClipboard = { html, plain };
            };
        }"""
    )


def _click_and_read_rich_copy(page, button_selector: str) -> dict:
    page.click(button_selector)
    page.wait_for_function("window.__richClipboard !== null")
    return page.evaluate("window.__richClipboard")


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


# --- "New problem" and stale-result prevention ---------------------------------------
#
# Reproduced live before fixing: solve Q1 via expression mode, then edit
# the expression field without resubmitting -- the Q1 answer stayed fully
# displayed as though it belonged to the new (unsubmitted) input, and
# there was no way to clear a solved problem short of reloading the page.


def test_new_problem_clears_all_synthesis_result_sections(page):
    _submit_q1(page)
    assert page.is_visible("#synth-result")

    page.click("#synth-new-problem")

    assert not page.is_visible("#synth-result")
    assert not page.is_visible("#synth-error")
    assert page.text_content("#res-gate-line") == ""
    assert page.text_content("#res-function-line") == ""
    assert page.locator("#res-alternatives li").count() == 0
    assert page.text_content("#res-advanced") == ""


def test_new_problem_restores_synthesis_defaults(page):
    _build_q1_grid(page)
    page.fill("#synth-output-name", "Y")
    page.check("#synth-dual-rail")
    page.fill("#synth-max-stack", "4")  # Q1's AOI/OAI need stack height 3 -- permissive, not excluded
    page.click("#panel-synth button.submit")
    page.wait_for_selector("#synth-result:not(.empty)")

    page.click("#synth-new-problem")

    assert page.input_value("#synth-vars") == ""
    assert page.input_value("#synth-output-name") == ""
    assert page.is_checked("#synth-dual-rail") is False
    assert page.input_value("#synth-max-stack") == ""
    assert page.get_attribute("#synth-manual-details", "open") is None
    assert page.is_checked('input[name="synth-table-mode"][value="minterms"]')
    # the grid itself is gone -- rebuilt empty, showing the "enter variables" hint
    assert page.locator("table.truth-grid").count() == 0


def test_new_problem_preserves_the_selected_input_mode_table(page):
    _submit_q1(page)
    page.click("#synth-new-problem")
    assert page.is_checked('input[name="synth-mode"][value="table"]')
    assert page.is_hidden("#synth-expr-fields")
    assert page.is_visible("#synth-table-fields")


def test_new_problem_preserves_the_selected_input_mode_expression(page):
    _submit_via_expression(page)
    page.click("#synth-new-problem")
    assert page.is_checked('input[name="synth-mode"][value="expr"]')
    assert page.is_visible("#synth-expr-fields")
    assert page.input_value("#synth-expr") == ""


def test_new_problem_focuses_the_first_relevant_field_expression_mode(page):
    _submit_via_expression(page)
    page.click("#synth-new-problem")
    assert page.evaluate("document.activeElement.id") == "synth-expr"


def test_new_problem_focuses_the_first_relevant_field_table_mode(page):
    _submit_q1(page)
    page.click("#synth-new-problem")
    assert page.evaluate("document.activeElement.id") == "synth-vars"


def test_derivation_new_problem_focuses_its_input_field(page):
    _run_derivation(page, "xy + xy'")
    page.click("#tt-new-problem")
    assert page.evaluate("document.activeElement.id") == "tt-expr"
    assert page.input_value("#tt-expr") == ""
    assert not page.is_visible("#tt-result")


def test_new_problem_in_synthesis_does_not_touch_derivation_tab(page):
    _run_derivation(page, "xy + xy'")
    _submit_q1(page)

    page.click("#synth-new-problem")

    _switch_tab(page, "tt")
    assert page.input_value("#tt-expr") == "xy + xy'"
    assert page.text_content("#tt-function-line") == "F = x"


def test_new_problem_in_derivation_does_not_touch_synthesis_tab(page):
    _submit_q1(page)
    _switch_tab(page, "tt")
    _run_derivation(page, "xy + xy'")

    page.click("#tt-new-problem")

    _switch_tab(page, "synth")
    assert page.is_visible("#synth-result")
    assert "3-input NAND" in page.text_content("#res-gate-line")


def test_editing_expression_after_a_result_hides_the_stale_answer(page):
    _submit_via_expression(page)
    assert page.is_visible("#synth-result")

    page.fill("#synth-expr", "a+b+c+d")  # a different, unsubmitted problem

    assert not page.is_visible("#synth-result")
    # the new (unsubmitted) input is untouched -- only the display cleared
    assert page.input_value("#synth-expr") == "a+b+c+d"


def test_editing_a_grid_cell_after_a_result_hides_the_stale_answer(page):
    _submit_q1(page)
    assert page.is_visible("#synth-result")

    page.locator("table.truth-grid button.cell-btn").first.click()

    assert not page.is_visible("#synth-result")


def test_new_problem_button_is_type_button_and_never_submits(page):
    assert page.get_attribute("#tt-new-problem", "type") == "button"
    assert page.get_attribute("#synth-new-problem", "type") == "button"

    _submit_q1(page)
    requests = []
    page.on("request", lambda req: requests.append(req.url))
    page.click("#synth-new-problem")
    page.wait_for_timeout(200)  # give any (incorrect) submit a moment to fire
    assert not any("/api/synth" in url or "/api/tt" in url for url in requests)


# --- Manual-entry disclosure is a material input-mode change --------------------------
#
# The bug: `manualOpen = $("synth-manual-details").open` decides which
# fields the next submit actually reads, so toggling it changes what
# Synthesize would produce -- but nothing invalidated a result already on
# screen when you opened or closed it.


def test_opening_manual_entry_after_a_grid_result_clears_it(page):
    _submit_q1(page)
    assert page.is_visible("#synth-result")

    page.click("#synth-manual-details summary")  # closed -> open
    # <details>'s "toggle" event is fired as an async queued task, not
    # synchronously with the click -- wait for its effect rather than a
    # fixed sleep. (Not wait_for_selector(".empty"): that selector match
    # is exactly what CSS makes invisible, so waiting on visibility for it
    # would never resolve.)
    page.wait_for_function("document.getElementById('synth-result').classList.contains('empty')")

    assert page.get_attribute("#synth-manual-details", "open") is not None
    assert not page.is_visible("#synth-result")
    assert page.text_content("#res-gate-line") == ""


def test_closing_manual_entry_after_a_manual_result_clears_it(page):
    _switch_tab(page, "synth")
    page.check('input[name="synth-mode"][value="table"]')
    page.fill("#synth-vars", _Q1_VARS)
    page.click("#synth-manual-details summary")  # open manual entry
    page.fill("#synth-ones", "0,1,2,3,4,5,6")  # Q1 pattern: everything but row 7
    page.click("#panel-synth button.submit")
    page.wait_for_selector("#synth-result:not(.empty)")
    assert "NAND" in page.text_content("#res-gate-line")

    page.click("#synth-manual-details summary")  # open -> closed
    page.wait_for_function("document.getElementById('synth-result').classList.contains('empty')")  # see the note above

    assert page.get_attribute("#synth-manual-details", "open") is None

    assert not page.is_visible("#synth-result")
    assert page.text_content("#res-gate-line") == ""


# --- New problem preserves manual-entry state (UX adjustment) ------------------------


def test_new_problem_preserves_manual_entry_open_state_and_table_mode(page):
    _switch_tab(page, "synth")
    page.check('input[name="synth-mode"][value="table"]')
    page.click("#synth-manual-details summary")  # open it
    page.check('input[name="synth-table-mode"][value="bits"]')
    page.fill("#synth-table", "1x01")

    page.click("#synth-new-problem")

    assert page.get_attribute("#synth-manual-details", "open") is not None
    assert page.is_checked('input[name="synth-table-mode"][value="bits"]')
    assert page.input_value("#synth-table") == ""  # the value itself is still cleared


# --- Derivation table: same stale-output principle (optional improvement, applied) ----


def test_editing_tt_expression_after_a_result_hides_the_stale_output(page):
    _run_derivation(page, "xy + xy'")
    assert page.is_visible("#tt-result")

    page.fill("#tt-expr", "a+b+c")

    assert not page.is_visible("#tt-result")


def test_changing_tt_format_does_not_hide_the_table(page):
    # M1.3: Terminal/Markdown/LaTeX became copy/export-only preferences --
    # the visible table doesn't depend on them, so changing the radio must
    # NOT clear the table the way editing the expression or columns does
    # (that would previously have been correct, back when the format
    # radios controlled the *visible* output).
    _run_derivation(page, "xy + xy'")
    _open_tt_advanced_exports(page)
    page.check('input[name="tt-format"][value="md"]')
    assert page.is_visible("#tt-result")
    assert page.text_content("#tt-function-line") == "F = x"


# --- In-flight request races -----------------------------------------------------------
#
# The bug: neither submit handler invalidated an outstanding request. If
# you edited the form (or clicked New Problem) while a request was still
# in flight, the eventual response unconditionally rendered -- silently
# repopulating a cleared or changed form with a stale answer. Fixed with a
# per-form monotonic token: a response only renders if its token is still
# the live one. These use a controllable mocked fetch (see
# _install_fetch_mock above) instead of slowing down the real engine.


def test_editing_during_inflight_synth_request_prevents_stale_render(page):
    real_response = _real_json(page, "/api/synth", {"expr": "(abc)'"})

    _switch_tab(page, "synth")
    page.check('input[name="synth-mode"][value="expr"]')
    _install_fetch_mock(page)

    page.fill("#synth-expr", "(abc)'")
    page.click("#panel-synth button.submit")  # request queued, stays pending

    page.fill("#synth-expr", "a+b")  # edited before the response arrives

    _resolve_fetch(page, 0, real_response)
    page.wait_for_timeout(200)

    assert not page.is_visible("#synth-result")
    assert page.text_content("#res-gate-line") == ""
    assert page.input_value("#synth-expr") == "a+b"  # the edit itself is untouched


def test_new_problem_during_inflight_synth_request_prevents_stale_render(page):
    real_response = _real_json(page, "/api/synth", {"expr": "(abc)'"})

    _switch_tab(page, "synth")
    page.check('input[name="synth-mode"][value="expr"]')
    page.fill("#synth-expr", "(abc)'")
    _install_fetch_mock(page)

    page.click("#panel-synth button.submit")  # request queued, stays pending
    page.click("#synth-new-problem")

    _resolve_fetch(page, 0, real_response)
    page.wait_for_timeout(200)

    assert not page.is_visible("#synth-result")
    assert page.input_value("#synth-expr") == ""
    assert page.text_content("#res-gate-line") == ""


def test_later_submission_wins_regardless_of_response_order(page):
    response_a = _real_json(page, "/api/synth", {"expr": "(abc)'"})
    response_b = _real_json(page, "/api/synth", {"expr": "a+b"})
    assert response_a["result"]["gate_name"] != response_b["result"]["gate_name"]

    _switch_tab(page, "synth")
    page.check('input[name="synth-mode"][value="expr"]')
    _install_fetch_mock(page)

    page.fill("#synth-expr", "(abc)'")
    page.click("#panel-synth button.submit")  # request A, index 0

    page.fill("#synth-expr", "a+b")
    page.click("#panel-synth button.submit")  # request B, index 1

    _resolve_fetch(page, 1, response_b)  # B resolves first
    page.wait_for_timeout(200)
    assert page.text_content("#res-gate-line") == (
        f"{response_b['result']['gate_name']} — {response_b['result']['total_transistors']} transistors"
    )

    _resolve_fetch(page, 0, response_a)  # A (stale) resolves second -- must not overwrite B
    page.wait_for_timeout(200)
    assert page.text_content("#res-gate-line") == (
        f"{response_b['result']['gate_name']} — {response_b['result']['total_transistors']} transistors"
    )


def test_editing_during_inflight_tt_request_prevents_stale_render(page):
    real_response = _real_json(page, "/api/tt", {"expression": "xy + xy'"})

    page.fill("#tt-expr", "xy + xy'")
    _install_fetch_mock(page)

    page.click("#panel-tt button.submit")  # request queued, stays pending
    page.fill("#tt-expr", "a+b")  # edited before the response arrives

    _resolve_fetch(page, 0, real_response)
    page.wait_for_timeout(200)

    assert not page.is_visible("#tt-result")
    assert page.input_value("#tt-expr") == "a+b"


def test_new_problem_during_inflight_tt_request_prevents_stale_render(page):
    real_response = _real_json(page, "/api/tt", {"expression": "xy + xy'"})

    page.fill("#tt-expr", "xy + xy'")
    _install_fetch_mock(page)

    page.click("#panel-tt button.submit")  # request queued, stays pending
    page.click("#tt-new-problem")

    _resolve_fetch(page, 0, real_response)
    page.wait_for_timeout(200)

    assert not page.is_visible("#tt-result")
    assert page.input_value("#tt-expr") == ""


# --- M1.3: structured derivation table -------------------------------------------
#
# The Derivation table tab used to render its output as a monospace
# box-drawing <pre> (like `ohmwork tt` itself), while the Synthesis tab's
# input grid was already a clean HTML table -- a real inconsistency a user
# pointed out after dogfooding all three exam questions. Fixed by giving
# `tt` the same presenter-layer treatment `synth` got in M1.2: the table
# is now always the visible result; Terminal/Markdown/LaTeX became
# copy/export-only formats (covered above), fetched fresh on demand.


def _tt_table_header_labels(page) -> list[str]:
    return page.locator("#tt-table-head th").all_text_contents()


def _tt_table_row_cells(page, row_index: int) -> list[str]:
    return page.locator("#tt-table-body tr").nth(row_index).locator("td").all_text_contents()


def test_tt_table_shows_the_full_breakout_by_default(page):
    _run_derivation(page, "xy + xy'")
    assert _tt_table_header_labels(page) == ["x", "y", "y'", "xy", "xy'", "F"]
    assert _tt_table_row_cells(page, 0) == ["0", "0", "1", "0", "0", "0"]
    assert page.text_content("#tt-function-line") == "F = x"


def test_tt_table_terse_columns(page):
    page.check('input[name="tt-cols"][value="terse"]')
    _run_derivation(page, "ab+c")
    assert _tt_table_header_labels(page) == ["ab", "c", "F"]


def test_tt_table_custom_columns(page):
    page.check('input[name="tt-cols"][value="custom"]')
    page.fill("#tt-cols-input", "x, x'")
    _run_derivation(page, "x'y + xy'")
    assert _tt_table_header_labels(page) == ["x", "x'", "F"]


def test_tt_table_output_column_is_visually_distinguished(page):
    _run_derivation(page, "xy + xy'")
    output_th = page.locator("#tt-table-head th").last
    assert "tt-output-col" in (output_th.get_attribute("class") or "")
    output_td = page.locator("#tt-table-body tr").first.locator("td").last
    assert "tt-output-col" in (output_td.get_attribute("class") or "")


def test_tt_table_is_accessible(page):
    _run_derivation(page, "xy + xy'")
    assert page.get_attribute("#tt-table", "aria-label")
    header_cells = page.locator("#tt-table-head th")
    for i in range(header_cells.count()):
        assert header_cells.nth(i).get_attribute("scope") == "col"


def test_tt_table_wrapper_scrolls_horizontally(page):
    _run_derivation(page, "xy + xy'")
    overflow_x = page.evaluate(
        "getComputedStyle(document.querySelector('.tt-table-wrap')).overflowX"
    )
    assert overflow_x == "auto"


def test_tt_copy_formatted_output_terminal(page):
    _run_derivation(page, "xy + xy'")
    _open_tt_advanced_exports(page)
    _hijack_clipboard(page)
    copied = _click_and_read_copy(page, "#tt-copy-formatted")
    assert copied.startswith("+---+")  # ASCII box-drawing
    assert "F = x" in copied


def test_tt_copy_formatted_output_markdown(page):
    _run_derivation(page, "xy + xy'")
    _open_tt_advanced_exports(page)
    page.check('input[name="tt-format"][value="md"]')
    _hijack_clipboard(page)
    copied = _click_and_read_copy(page, "#tt-copy-formatted")
    assert copied.startswith("|")
    assert "F = x" in copied


def test_tt_copy_formatted_output_latex(page):
    _run_derivation(page, "xy + xy'")
    _open_tt_advanced_exports(page)
    page.check('input[name="tt-format"][value="latex"]')
    _hijack_clipboard(page)
    copied = _click_and_read_copy(page, "#tt-copy-formatted")
    assert r"\begin{array}" in copied
    assert "F = x" in copied


def test_tt_copy_formatted_output_updates_the_preview(page):
    _run_derivation(page, "xy + xy'")
    _open_tt_advanced_exports(page)
    page.check('input[name="tt-format"][value="md"]')
    _hijack_clipboard(page)
    _click_and_read_copy(page, "#tt-copy-formatted")
    page.click("#tt-preview-details summary")
    assert page.text_content("#tt-formatted-preview").startswith("|")


def test_tt_copy_formatted_output_shows_copied_feedback(page):
    _run_derivation(page, "xy + xy'")
    _open_tt_advanced_exports(page)
    _hijack_clipboard(page)
    page.click("#tt-copy-formatted")
    page.wait_for_selector("#tt-copy-formatted.copied")
    assert page.text_content("#tt-copy-formatted") == "Copied!"


def test_editing_during_inflight_tt_copy_prevents_stale_clipboard_write(page):
    _run_derivation(page, "xy + xy'")
    real_response = _real_json(page, "/api/tt", {"expression": "xy + xy'", "md": True})

    _open_tt_advanced_exports(page)
    page.check('input[name="tt-format"][value="md"]')
    _hijack_clipboard(page)
    _install_fetch_mock(page)

    page.click("#tt-copy-formatted")  # copy request queued, stays pending
    page.fill("#tt-expr", "a+b")  # edits mid-flight -- invalidates the pending copy

    _resolve_fetch(page, 0, real_response)
    page.wait_for_timeout(200)

    assert page.evaluate("window.__copiedText") is None
    assert page.text_content("#tt-copy-formatted") == "Copy formatted output"


def test_new_problem_during_inflight_tt_copy_resets_the_button(page):
    _run_derivation(page, "xy + xy'")
    real_response = _real_json(page, "/api/tt", {"expression": "xy + xy'"})

    _open_tt_advanced_exports(page)
    _hijack_clipboard(page)
    _install_fetch_mock(page)

    page.click("#tt-copy-formatted")  # copy request queued, stays pending
    page.click("#tt-new-problem")

    _resolve_fetch(page, 0, real_response)
    page.wait_for_timeout(200)

    assert page.evaluate("window.__copiedText") is None
    assert page.text_content("#tt-copy-formatted") == "Copy formatted output"
    assert page.input_value("#tt-expr") == ""


# --- Export-state race: changing tt-format mid-copy ------------------------------------
#
# The bug (ChatGPT review of d9a1e03): changing tt-format didn't bump
# ttCopyRequestToken, so a Terminal copy fetch still in flight when the
# user switched to Markdown could land afterward and silently overwrite
# the clipboard/preview with the wrong format's text. Separately, even
# with nothing in flight, switching format left the preview showing
# whatever was last copied in the *previous* format. Fixed by
# resetTtExportState(), wired to tt-format's own change event -- it must
# NOT touch #tt-result, which is an unrelated, still-valid table.


def test_changing_format_during_inflight_copy_prevents_stale_clipboard_write(page):
    _run_derivation(page, "xy + xy'")
    terminal_response = _real_json(page, "/api/tt", {"expression": "xy + xy'"})

    _open_tt_advanced_exports(page)
    _hijack_clipboard(page)
    _install_fetch_mock(page)

    page.click("#tt-copy-formatted")  # Terminal copy queued, stays pending
    page.check('input[name="tt-format"][value="md"]')  # switched before it resolves

    _resolve_fetch(page, 0, terminal_response)
    page.wait_for_timeout(200)

    assert page.evaluate("window.__copiedText") is None
    assert page.text_content("#tt-formatted-preview") == ""
    assert page.text_content("#tt-copy-formatted") == "Copy formatted output"
    # the table itself -- unrelated to the export/copy race -- must stay untouched
    assert page.is_visible("#tt-result")
    assert page.text_content("#tt-function-line") == "F = x"


def test_changing_format_after_a_completed_copy_clears_the_stale_preview(page):
    _run_derivation(page, "xy + xy'")
    _open_tt_advanced_exports(page)
    _hijack_clipboard(page)
    _click_and_read_copy(page, "#tt-copy-formatted")  # Terminal, completes fully
    assert page.text_content("#tt-formatted-preview") != ""

    page.check('input[name="tt-format"][value="md"]')

    assert page.text_content("#tt-formatted-preview") == ""
    assert page.is_visible("#tt-result")  # the table itself is untouched


def test_two_copy_requests_resolved_out_of_order_leave_only_the_newest_format(page):
    # Genuinely out-of-order: the *newer* (Markdown) request resolves
    # first, and the *stale* (Terminal) one only arrives afterward -- the
    # case that actually exercises the token guard, unlike resolving
    # index 0 then index 1 (which is just normal request order and would
    # pass even with a naive "last resolved wins" bug).
    _run_derivation(page, "xy + xy'")
    terminal_response = _real_json(page, "/api/tt", {"expression": "xy + xy'"})
    markdown_response = _real_json(page, "/api/tt", {"expression": "xy + xy'", "md": True})
    assert terminal_response["output"] != markdown_response["output"]

    _open_tt_advanced_exports(page)
    _hijack_clipboard(page)
    _install_fetch_mock(page)

    page.click("#tt-copy-formatted")  # Terminal copy, index 0, stays pending
    page.check('input[name="tt-format"][value="md"]')  # invalidates it
    page.click("#tt-copy-formatted")  # Markdown copy, index 1, stays pending

    _resolve_fetch(page, 1, markdown_response)  # newer request resolves first
    page.wait_for_timeout(200)
    assert page.evaluate("window.__copiedText") == markdown_response["output"]
    assert page.text_content("#tt-formatted-preview") == markdown_response["output"]

    _resolve_fetch(page, 0, terminal_response)  # stale request arrives last
    page.wait_for_timeout(200)
    assert page.evaluate("window.__copiedText") == markdown_response["output"]  # unchanged
    assert page.text_content("#tt-formatted-preview") == markdown_response["output"]  # unchanged
    assert page.is_visible("#tt-result")  # the table itself is untouched throughout
    assert page.text_content("#tt-function-line") == "F = x"


# --- "Copy table for Word/Docs" -------------------------------------------------------
#
# The problem: Terminal/Markdown/LaTeX are technically correct, but pasting
# any of them into Word or Google Docs produces raw pipes/dashes/LaTeX
# commands, not a table -- because writeText() only ever offers a
# text/plain clipboard representation. Reproduced live before
# implementing: hijacking navigator.clipboard.writeText/write and clicking
# the old "Copy formatted output" button showed exactly one writeText()
# call (the raw ASCII table) and zero write() calls -- the rich,
# multi-MIME API was never used at all. "Copy table for Word/Docs" now
# writes both text/html (a real bordered table) and text/plain (tab-
# separated) in one clipboard.write([ClipboardItem]) call, built from
# lastTtView (the already-computed structured result) and a clone of the
# already-rendered #tt-table DOM -- no second table implementation, no
# extra /api/tt request.


def test_advanced_exports_collapsed_by_default(page):
    _run_derivation(page, "xy + xy'")
    assert page.get_attribute("#tt-advanced-exports", "open") is None


def test_advanced_export_labels_are_renamed(page):
    _run_derivation(page, "xy + xy'")
    page.click("#tt-advanced-exports summary")
    labels = page.locator("#tt-advanced-exports .row label").all_text_contents()
    assert any("Plain text / Terminal" in label for label in labels)
    assert any("Markdown source" in label for label in labels)
    assert any("LaTeX fragment" in label for label in labels)


def test_rich_copy_supplies_both_html_and_plain_text(page):
    _run_derivation(page, "xy + xy'")
    _hijack_rich_clipboard(page)
    data = _click_and_read_rich_copy(page, "#tt-copy-rich")
    assert data["html"]
    assert data["plain"]


def test_rich_copy_html_matches_current_headers_rows_and_function(page):
    _run_derivation(page, "xy + xy'")
    _hijack_rich_clipboard(page)
    data = _click_and_read_rich_copy(page, "#tt-copy-rich")
    html = data["html"]

    for header in ["x", "y", "y'", "xy", "xy'", "F"]:
        assert f">{header}<" in html
    assert "F = x" in html
    assert 'class="tt-output-col"' in html  # the output column, carried from the live table
    assert html.count("<td") == 24  # 4 rows x 6 columns


def test_rich_copy_html_has_portable_inline_styling(page):
    # Word/Docs strip a pasted page's own <style> rules -- the borders and
    # header shading must travel as inline styles/attributes, not rely on
    # Ohmwork's own .tt-grid CSS class alone.
    _run_derivation(page, "xy + xy'")
    _hijack_rich_clipboard(page)
    data = _click_and_read_rich_copy(page, "#tt-copy-rich")
    html = data["html"]
    assert 'border="1"' in html
    assert "border-collapse" in html
    assert "border: 1px solid" in html
    assert "padding: 4px 10px" in html


def test_rich_copy_plain_text_is_tab_separated(page):
    _run_derivation(page, "xy + xy'")
    _hijack_rich_clipboard(page)
    data = _click_and_read_rich_copy(page, "#tt-copy-rich")
    plain = data["plain"]
    lines = plain.split("\n")
    assert lines[0] == "x\ty\ty'\txy\txy'\tF"
    assert lines[1] == "0\t0\t1\t0\t0\t0"
    assert plain.rstrip().endswith("F = x")


def test_rich_copy_makes_no_additional_api_request(page):
    _run_derivation(page, "xy + xy'")
    _hijack_rich_clipboard(page)
    requests = []
    page.on("request", lambda req: requests.append(req.url))
    _click_and_read_rich_copy(page, "#tt-copy-rich")
    page.wait_for_timeout(150)
    assert not any("/api/tt" in url for url in requests)


def test_editing_expression_hides_the_rich_copy_button(page):
    _run_derivation(page, "xy + xy'")
    assert page.is_visible("#tt-copy-rich")
    page.fill("#tt-expr", "a+b")
    assert not page.is_visible("#tt-copy-rich")


def test_new_problem_hides_the_rich_copy_button(page):
    _run_derivation(page, "xy + xy'")
    assert page.is_visible("#tt-copy-rich")
    page.click("#tt-new-problem")
    assert not page.is_visible("#tt-copy-rich")


def test_changing_advanced_format_leaves_table_and_rich_copy_intact(page):
    _run_derivation(page, "xy + xy'")
    page.click("#tt-advanced-exports summary")
    page.check('input[name="tt-format"][value="md"]')

    assert page.is_visible("#tt-result")
    assert page.text_content("#tt-function-line") == "F = x"

    _hijack_rich_clipboard(page)
    data = _click_and_read_rich_copy(page, "#tt-copy-rich")
    assert "F = x" in data["html"]
    assert "F = x" in data["plain"]


def test_advanced_exports_still_copy_valid_terminal_markdown_latex(page):
    # Terminal/Markdown/LaTeX must remain byte-identical to before this
    # change -- same content already pinned by the pre-existing
    # test_tt_copy_formatted_output_{terminal,markdown,latex} tests above;
    # this just re-confirms it still works from inside the now-collapsed
    # Advanced exports section with the renamed labels.
    _run_derivation(page, "xy + xy'")
    page.click("#tt-advanced-exports summary")

    _hijack_clipboard(page)
    terminal_copy = _click_and_read_copy(page, "#tt-copy-formatted")
    assert terminal_copy.startswith("+---+")

    page.check('input[name="tt-format"][value="latex"]')
    _hijack_clipboard(page)
    latex_copy = _click_and_read_copy(page, "#tt-copy-formatted")
    assert r"\begin{array}" in latex_copy


def test_rich_copy_falls_back_when_clipboard_write_is_rejected(page):
    _run_derivation(page, "xy + xy'")
    page.evaluate(
        """() => {
            window.__copiedText = null;
            navigator.clipboard.write = () => Promise.reject(new Error("simulated rejection"));
            navigator.clipboard.writeText = (t) => { window.__copiedText = t; return Promise.resolve(); };
        }"""
    )
    page.click("#tt-copy-rich")
    page.wait_for_function("window.__copiedText !== null")
    copied = page.evaluate("window.__copiedText")
    assert "\t" in copied
    assert copied.rstrip().endswith("F = x")
    page.wait_for_selector("#tt-copy-rich.copied")


def test_rich_copy_falls_back_when_clipboarditem_is_unavailable(page):
    _run_derivation(page, "xy + xy'")
    page.evaluate(
        """() => {
            window.__copiedText = null;
            window.ClipboardItem = undefined;
            navigator.clipboard.writeText = (t) => { window.__copiedText = t; return Promise.resolve(); };
        }"""
    )
    page.click("#tt-copy-rich")
    page.wait_for_function("window.__copiedText !== null")
    copied = page.evaluate("window.__copiedText")
    assert "\t" in copied


# --- Fallback-box ownership is button-specific -----------------------------------------
#
# The bug (ChatGPT review of 3fcde44): resetTtExportState() removed every
# .copy-fallback anywhere inside #tt-result -- so changing the Advanced
# export format silently deleted a visible "Copy table for Word/Docs"
# fallback the user hadn't touched at all, even though changing an
# Advanced export format must not affect the rich-table copy. Reproduced
# live before fixing: forced all four copy strategies to fail, clicked
# "Copy table for Word/Docs" (its fallback box appeared), then just
# switched the Advanced export format radio -- the fallback disappeared
# with zero interaction with that button. Fixed by scoping fallback
# removal to a specific button's own parent (removeCopyFallbackFor),
# used by resetTtExportState for #tt-copy-formatted only, while
# clearTtOutputDisplay (the complete-result-is-stale case) still clears
# both.


def _force_all_copy_paths_to_fallback(page) -> None:
    # All four strategies copyText()/the rich-copy handler try, in order,
    # must fail for the visible-fallback box to appear at all.
    page.evaluate(
        """() => {
            navigator.clipboard.write = () => Promise.reject(new Error("no rich clipboard"));
            navigator.clipboard.writeText = () => Promise.reject(new Error("no writeText"));
            document.execCommand = () => false;
            window.prompt = () => { throw new Error("no prompt"); };
        }"""
    )


def test_rich_copy_fallback_survives_an_advanced_format_change(page):
    _run_derivation(page, "xy + xy'")
    _force_all_copy_paths_to_fallback(page)

    page.click("#tt-copy-rich")
    page.wait_for_selector("#tt-copy-rich ~ .copy-fallback")
    fallback = page.locator("#tt-copy-rich ~ .copy-fallback")
    fallback_text = fallback.text_content()
    assert "\t" in fallback_text  # tab-separated table
    assert fallback_text.rstrip().endswith("F = x")

    _open_tt_advanced_exports(page)
    page.check('input[name="tt-format"][value="md"]')

    assert fallback.count() == 1  # still there
    assert fallback.text_content() == fallback_text  # unchanged
    assert page.is_visible("#tt-result")  # the table itself, also unaffected


def test_rich_copy_fallback_is_removed_by_editing_the_expression(page):
    _run_derivation(page, "xy + xy'")
    _force_all_copy_paths_to_fallback(page)
    page.click("#tt-copy-rich")
    page.wait_for_selector("#tt-copy-rich ~ .copy-fallback")

    page.fill("#tt-expr", "a+b")
    assert page.locator("#tt-copy-rich ~ .copy-fallback").count() == 0


def test_rich_copy_fallback_is_removed_by_new_problem(page):
    _run_derivation(page, "xy + xy'")
    _force_all_copy_paths_to_fallback(page)
    page.click("#tt-copy-rich")
    page.wait_for_selector("#tt-copy-rich ~ .copy-fallback")

    page.click("#tt-new-problem")
    assert page.locator("#tt-copy-rich ~ .copy-fallback").count() == 0


def test_advanced_format_change_removes_only_the_advanced_fallback(page):
    _run_derivation(page, "xy + xy'")
    _force_all_copy_paths_to_fallback(page)

    page.click("#tt-copy-rich")
    page.wait_for_selector("#tt-copy-rich ~ .copy-fallback")

    _open_tt_advanced_exports(page)
    page.click("#tt-copy-formatted")
    page.wait_for_selector("#tt-copy-formatted ~ .copy-fallback")

    assert page.locator(".copy-fallback").count() == 2

    page.check('input[name="tt-format"][value="md"]')

    assert page.locator("#tt-copy-formatted ~ .copy-fallback").count() == 0  # its own, gone
    assert page.locator("#tt-copy-rich ~ .copy-fallback").count() == 1  # Word/Docs, untouched


def test_copy_buttons_have_independent_feedback(page):
    _run_derivation(page, "xy + xy'")
    _hijack_clipboard(page)
    _hijack_rich_clipboard(page)

    page.click("#tt-copy-rich")
    page.wait_for_selector("#tt-copy-rich.copied")
    assert page.text_content("#tt-copy-rich") == "Copied!"
    assert page.text_content("#tt-copy-formatted") == "Copy formatted output"  # untouched

    page.click("#tt-advanced-exports summary")
    page.click("#tt-copy-formatted")
    page.wait_for_selector("#tt-copy-formatted.copied")
    assert page.text_content("#tt-copy-formatted") == "Copied!"


# --- Schematic (D17 Phase B, acceptance tests 8 and 10) -----------------------------
#
# Test 8, the semantic model-to-SVG bridge: every device/net/wire/junction
# the layout model declares must appear exactly once in the rendered SVG,
# at its own stable identifier, with the model's own coordinates -- not a
# pixel/snapshot comparison, and not just trusting `data-*` labels without
# checking the geometry they sit on. Ground truth is the real server's own
# `/api/synth` response (`_real_json`, already used elsewhere in this file
# for the same reason: it reflects the actual presenter/schematic code
# path, never a hand-maintained fake of its JSON shape).
#
# This section also covers a ChatGPT review round on the first Phase B cut
# (commit 3b97e18) that found four real gaps, closed here: (1) the visible
# gate-connector line started exactly on the channel, depicting a gate/
# channel short rather than an insulated MOSFET gate; (2) the downloaded SVG
# had no styling of its own (all stroke/fill rules lived in the page's
# stylesheet, not the file), so a standalone open showed invisible wires and
# visible "invisible" terminal-anchor dots; (3) the bridge test only checked
# elements already tagged data-role="wire"/used set equality (missing an
# untagged extra conductive line or a duplicate id) and never checked nets
# at all; (4) "responsive" meant shrinking a wide, many-transistor circuit
# down to illegible labels rather than keeping symbols a constant, legible
# size and letting the wrapper scroll.

_AOI21_EXPR = "(a'b+c)'"  # D17 acceptance test 4's case: one shared inverter (a')

# 4 shared inverters (a,b,c,d each complemented at least once), 40
# transistors, a 16-cell-wide layout -- the wide/many-transistor case issue
# 4's fix (a constant on-screen symbol/label size, wrapper scrolling instead
# of shrinking) is specifically for.
_WIDE_MULTI_INVERTER_EXPR = "a'b'c'd + a'b'cd' + a'bc'd' + ab'c'd'"


_SCHEMATIC_SNAPSHOT_JS = """(rootSelector) => {
  const root = document.querySelector(rootSelector);

  function lineCoords(el) {
    return {
      x1: Number(el.getAttribute('x1')), y1: Number(el.getAttribute('y1')),
      x2: Number(el.getAttribute('x2')), y2: Number(el.getAttribute('y2')),
    };
  }

  const wires = Array.from(root.querySelectorAll('[data-role="wire"]')).map(el => ({
    id: el.getAttribute('data-wire-id'),
    net_id: el.getAttribute('data-net-id'),
    ...lineCoords(el),
  }));
  const junctions = Array.from(root.querySelectorAll('[data-role="junction"]')).map(el => ({
    id: el.getAttribute('data-junction-id'),
    net_id: el.getAttribute('data-net-id'),
    x: Number(el.getAttribute('cx')), y: Number(el.getAttribute('cy')),
  }));
  const nets = Array.from(root.querySelectorAll('[data-role="net-inventory"] [data-role="net"]')).map(el => ({
    id: el.getAttribute('data-net-id'),
    kind: el.getAttribute('data-net-kind'),
    label: el.getAttribute('data-net-label'),
  }));
  const devices = Array.from(root.querySelectorAll('.ow-device')).map(g => {
    const terminals = {};
    g.querySelectorAll('[data-role="terminal"]').forEach(t => {
      terminals[t.getAttribute('data-terminal')] = {
        net_id: t.getAttribute('data-net-id'),
        x: Number(t.getAttribute('cx')), y: Number(t.getAttribute('cy')),
      };
    });
    const channelEl = g.querySelector('[data-role="channel"]');
    const electrodeEl = g.querySelector('[data-role="gate-electrode"]');
    const connectorEl = g.querySelector('[data-role="gate-connector"]');
    const labelEl = g.querySelector('[data-role="device-label"]');
    return {
      id: g.getAttribute('data-device-id'),
      kind: g.getAttribute('data-kind'),
      role: g.getAttribute('data-device-role'),
      gate_var: g.getAttribute('data-gate-var'),
      gate_complemented: g.getAttribute('data-gate-complemented') === 'true',
      has_gate_bubble: !!g.querySelector('[data-role="gate-bubble"]'),
      bubbles: Array.from(g.querySelectorAll('[data-role="gate-bubble"]')).map(b => ({
        x:Number(b.getAttribute('cx')),y:Number(b.getAttribute('cy')),r:Number(b.getAttribute('r')),
      })),
      terminal_count:g.querySelectorAll('[data-role="terminal"]').length,
      label: labelEl ? labelEl.textContent : null,
      channel: channelEl ? lineCoords(channelEl) : null,
      gate_electrode: electrodeEl ? lineCoords(electrodeEl) : null,
      gate_connector: connectorEl ? lineCoords(connectorEl) : null,
      leads: ['source', 'drain'].map(t => {
        const el = g.querySelector(`[data-role="${t}-lead"]`);
        return el ? Array.from(el.points).map(p => [p.x, p.y]) : null;
      }),
      terminals,
    };
  });

  // Every conductive primitive anywhere in the SVG, classified by its own
  // data-role and (for a device-symbol part) the data-device-id of its
  // containing .ow-device group -- lets a test reject anything untagged or
  // unclassified, not just count the ones it already expects to find.
  const primitives = Array.from(root.querySelectorAll('line, path, polyline, circle')).map(el => {
    const deviceGroup = el.closest('.ow-device');
    return {
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('data-role'),
      wire_id: el.getAttribute('data-wire-id'),
      device_id: deviceGroup ? deviceGroup.getAttribute('data-device-id') : null,
      boundary_id: el.closest('[data-role="boundary"]')?.getAttribute('data-boundary-id'),
    };
  });

  const ports = Array.from(root.querySelectorAll('[data-role="port"]')).map(g => ({
    id:g.getAttribute('data-port-id'), net_id:g.getAttribute('data-net-id'),
    device_id:g.getAttribute('data-device-id'), terminal:g.getAttribute('data-terminal'),
    label:g.querySelector('[data-role="port-label"]').textContent,
    point:{x:Number(g.getAttribute('data-x')),y:Number(g.getAttribute('data-y'))},
    text_x:Number(g.querySelector('text').getAttribute('x')),
    text_y:Number(g.querySelector('text').getAttribute('y')),
    text_anchor:g.querySelector('text').getAttribute('text-anchor'),
    text_left:g.querySelector('text').getBBox().x,
    visible: g.querySelector('text').getBoundingClientRect().width > 0 &&
      getComputedStyle(g.querySelector('text')).visibility === 'visible' &&
      getComputedStyle(g.querySelector('text')).opacity !== '0',
  }));
  const boundaries = Array.from(root.querySelectorAll('[data-role="boundary"]')).map(g => ({
    id:g.getAttribute('data-boundary-id'),net_id:g.getAttribute('data-net-id'),
    bars:Array.from(g.querySelectorAll('line')).map(lineCoords),
  }));
  const annotations = Array.from(root.querySelectorAll('[data-role="network-annotation"]')).map(g => ({
    role:g.getAttribute('data-network'), devices:g.getAttribute('data-device-ids').split(' '),
    bracket:Array.from(g.querySelector('polyline').points).map(p=>[p.x,p.y]),
    captions:Array.from(g.querySelectorAll('text')).map(t=>({text:t.textContent,x:Number(t.getAttribute('x')),y:Number(t.getAttribute('y'))})),
    dashed:getComputedStyle(g.querySelector('polyline')).strokeDasharray,
    box:(()=>{const b=g.getBBox();return {x:b.x,y:b.y,width:b.width,height:b.height};})(),
  }));
  return { wires, junctions, nets, devices, primitives, ports, boundaries, annotations };

}"""


def _schematic_dom_snapshot(page, root_selector: str = "#schematic-svg") -> dict:
    return page.evaluate(_SCHEMATIC_SNAPSHOT_JS, root_selector)


def _seg(coords: dict) -> tuple:
    return (coords["x1"], coords["y1"], coords["x2"], coords["y2"])


def _segments_overlap(a: tuple, b: tuple) -> bool:
    """Every line this renderer draws is horizontal or vertical, so a plain
    bounding-box overlap test is an exact intersection test: an
    axis-aligned segment's own bounding box IS the segment (zero-width in
    the perpendicular direction), so two such boxes overlap iff the
    segments themselves actually meet or cross."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    a_xs, a_ys = sorted((ax1, ax2)), sorted((ay1, ay2))
    b_xs, b_ys = sorted((bx1, bx2)), sorted((by1, by2))
    return a_xs[0] <= b_xs[1] and b_xs[0] <= a_xs[1] and a_ys[0] <= b_ys[1] and b_ys[0] <= a_ys[1]


def _assert_snapshot_matches_model(snapshot: dict, schematic: dict) -> None:
    """The full test-8 bridge check: every wire/net/device/junction the
    model declares appears exactly once (by count, not just by set, so a
    duplicated id can't slip through) in `snapshot` (a DOM read of either
    the live #schematic-svg or a parsed Download-SVG file), at the model's
    own id, with the model's own coordinates -- and every conductive
    primitive drawn anywhere is accounted for, with nothing extra/
    untagged."""
    model_wires = {w["id"]: w for w in schematic["wires"]}
    wire_ids = [w["id"] for w in snapshot["wires"]]
    assert len(wire_ids) == len(model_wires)
    assert set(wire_ids) == set(model_wires)  # no unmodeled wire, none missing
    for w in snapshot["wires"]:
        mw = model_wires[w["id"]]
        assert w["net_id"] == mw["net_id"]
        assert (w["x1"], w["y1"]) == (mw["p1"]["x"], mw["p1"]["y"])
        assert (w["x2"], w["y2"]) == (mw["p2"]["x"], mw["p2"]["y"])

    model_junctions = {j["id"]: j for j in schematic["junctions"]}
    junction_ids = [j["id"] for j in snapshot["junctions"]]
    assert len(junction_ids) == len(model_junctions)
    assert set(junction_ids) == set(model_junctions)
    for j in snapshot["junctions"]:
        mj = model_junctions[j["id"]]
        assert j["net_id"] == mj["net_id"]
        assert (j["x"], j["y"]) == (mj["point"]["x"], mj["point"]["y"])

    # Net *presence* is checked through the dedicated inventory, not
    # inferred from scattered data-net-id attributes -- a net touched by
    # only one device and no bus wire (a single-transistor VDD, say) would
    # never otherwise appear on any wire element.
    model_nets = {n["id"]: n for n in schematic["nets"]}
    net_ids = [n["id"] for n in snapshot["nets"]]
    assert len(net_ids) == len(model_nets)
    assert set(net_ids) == set(model_nets)
    for n in snapshot["nets"]:
        mn = model_nets[n["id"]]
        assert n["kind"] == mn["kind"]
        assert n["label"] == mn["label"]

    model_devices = {d["id"]: d for d in schematic["devices"]}
    model_ports = {p["id"]: p for p in schematic["ports"]}
    assert len(snapshot["ports"]) == len(model_ports)
    assert {p["id"] for p in snapshot["ports"]} == set(model_ports)
    for p in snapshot["ports"]:
        mp = model_ports[p["id"]]
        assert {k:p[k] for k in mp} == mp
        assert p["text_x"] == mp["point"]["x"] + (-9 if mp["terminal"] == "gate" else 9)
        assert p["text_y"] == mp["point"]["y"] + 8
        assert p["text_anchor"] == ("end" if mp["terminal"] == "gate" else "start")
        assert p["visible"]
    model_boundaries = {b["id"]: b for b in schematic["boundaries"]}
    assert len(snapshot["boundaries"]) == len(model_boundaries) == 3
    assert {b["id"] for b in snapshot["boundaries"]} == set(model_boundaries)
    for b in snapshot["boundaries"]:
        mb = model_boundaries[b["id"]]
        assert b["net_id"] == mb["net_id"]
        x,y = mb["point"]["x"],mb["point"]["y"]
        offsets = [(-22,22,0)] if b["net_id"] == "VDD" else [(-24,24,0),(-16,16,9),(-7,7,18)] if b["net_id"] == "GND" else []
        assert [_seg(bar) for bar in b["bars"]] == [(x+a,y+dy,x+c,y+dy) for a,c,dy in offsets]
    pun_bottom = max(d[t+"_point"]["y"] for d in schematic["devices"] if d["role"] == "pun" for t in ("source","drain"))
    pdn_top = min(d[t+"_point"]["y"] for d in schematic["devices"] if d["role"] == "pdn" for t in ("source","drain"))
    output_wire = next(w for w in snapshot["wires"] if w["id"] == "LEAD_OUT")
    assert pun_bottom < output_wire["y1"] == output_wire["y2"] < pdn_top
    # Measure the rendered network silhouette, not invisible model anchors:
    # the last channel shoulder or an actual horizontal OUT bus bounds the gap.
    tap_y = output_wire["y1"]
    buses = [w["y1"] for w in snapshot["wires"] if w["net_id"] == "OUT"
             and w["id"] != "LEAD_OUT" and w["y1"] == w["y2"] and w["x1"] != w["x2"]]
    upper = max([d["channel"]["y2"] for d in snapshot["devices"] if d["role"] == "pun"]
                + [y for y in buses if y < tap_y])
    lower = min([d["channel"]["y1"] for d in snapshot["devices"] if d["role"] == "pdn"]
                + [y for y in buses if y > tap_y])
    assert tap_y - upper == lower - tap_y
    assert len(snapshot["annotations"]) == 2
    assert {a["role"] for a in snapshot["annotations"]} == {"pun", "pdn"}
    for annotation in snapshot["annotations"]:
        members = [d for d in snapshot["devices"] if d["role"] == annotation["role"]]
        assert sorted(annotation["devices"]) == sorted(d["id"] for d in members)
        first = min(d["channel"]["y1"] for d in members)
        last = max(d["channel"]["y2"] for d in members)
        gate_ports = [p for p in snapshot["ports"] if p["device_id"] in annotation["devices"] and p["terminal"] == "gate"]
        bx = min(p["point"]["x"] for p in gate_ports) - 90
        assert annotation["bracket"] == [[bx+15,first],[bx,first],[bx,last],[bx+15,last]]
        type_, description = ("PMOS", "pull-up network") if annotation["role"] == "pun" else ("NMOS", "pull-down network")
        assert annotation["captions"] == [dict(text=type_,x=bx-25,y=(first+last)/2-8),
                                           dict(text=description,x=bx-25,y=(first+last)/2+18)]
        assert annotation["box"]["x"] + annotation["box"]["width"] + 10 < min(p["text_left"] for p in gate_ports)
        assert annotation["dashed"] != "none"
    assert any(j["net_id"] == "OUT" and (j["x"],j["y"]) == (output_wire["x1"],output_wire["y1"]) for j in snapshot["junctions"])
    device_ids = [d["id"] for d in snapshot["devices"]]
    assert len(device_ids) == len(model_devices)
    assert set(device_ids) == set(model_devices)
    assert len(snapshot["devices"]) == schematic["total_transistors"]
    for d in snapshot["devices"]:
        md = model_devices[d["id"]]
        assert d["kind"] == md["kind"]
        assert d["role"] == md["role"]
        assert d["gate_var"] == md["gate_var"]
        assert d["gate_complemented"] == md["gate_complemented"]
        assert next(p["label"] for p in snapshot["ports"] if p["device_id"] == d["id"] and p["terminal"] == "gate") == md["literal"]
        # PMOS gate-bubble present, NMOS absent -- structurally, not visually.
        assert d["has_gate_bubble"] == (md["kind"] == "p")
        assert d["terminal_count"] == 3
        assert d["bubbles"] == ([{"x":md["source_point"]["x"]-40,"y":md["gate_point"]["y"],"r":6}] if md["kind"] == "p" else [])

        for term in ("gate", "source", "drain"):
            snap_term = d["terminals"][term]
            model_point = md[f"{term}_point"]
            model_net = md[f"{term}_net"]
            assert snap_term["net_id"] == model_net
            assert (snap_term["x"], snap_term["y"]) == (model_point["x"], model_point["y"])

        # The complete symbol, including its bent source/drain leads,
        # joins the model's exact terminals to the insulated channel.
        assert d["channel"] is not None
        channel_seg = _seg(d["channel"])
        cx,cy = md["source_point"]["x"]-16,md["gate_point"]["y"]
        assert channel_seg == (cx,cy-28,cx,cy+28)
        for term,lead in zip(("source","drain"),d["leads"]):
            p = md[term+"_point"]
            shoulder = cy-28 if p["y"] < cy else cy+28
            assert lead == [[p["x"],p["y"]],[p["x"],shoulder],[cx,shoulder]]

        # The visible gate connector's far endpoint is exactly the model's
        # own gate_point -- the external, model-declared gate connection.
        assert d["gate_connector"] is not None
        connector_seg = _seg(d["gate_connector"])
        assert (connector_seg[2], connector_seg[3]) == (md["gate_point"]["x"], md["gate_point"]["y"])

        # The gate path (electrode + connector) never intersects the
        # visible channel -- an insulated gate, not a gate/channel short.
        assert d["gate_electrode"] is not None
        electrode_seg = _seg(d["gate_electrode"])
        assert not _segments_overlap(channel_seg, electrode_seg)
        assert not _segments_overlap(channel_seg, connector_seg)

    # Every line/path/polyline anywhere in the SVG is classified as either a
    # model-backed wire or one recognized part of exactly one model-backed
    # device symbol -- an accidental untagged conductive primitive is
    # rejected, not silently ignored.
    recognized_device_roles = {"channel", "gate-electrode", "gate-connector", "source-lead", "drain-lead"}
    for device_id in model_devices:
        roles = [p["role"] for p in snapshot["primitives"] if p["device_id"] == device_id]
        expected = list(recognized_device_roles) + ["terminal"] * 3
        if model_devices[device_id]["kind"] == "p": expected.append("gate-bubble")
        assert sorted(roles) == sorted(expected)
    for prim in snapshot["primitives"]:
        if prim["role"] == "wire":
            assert prim["wire_id"] in model_wires
        elif prim["role"] in recognized_device_roles:
            assert prim["device_id"] in model_devices
        elif prim["role"] == "supply-symbol":
            assert prim["boundary_id"] in model_boundaries
        elif prim["role"] in ("gate-bubble", "terminal"):
            assert prim["device_id"] in model_devices
        elif prim["role"] == "junction":
            pass  # already compared one-for-one above, including coordinates
        elif prim["role"] == "network-bracket":
            assert prim["device_id"] is None and prim["wire_id"] is None
            assert len([p for p in snapshot["primitives"] if p["role"] == "network-bracket"]) == 2
        elif prim["role"] == "output-endpoint":
            assert model_boundaries[prim["boundary_id"]]["net_id"] == "OUT"
        else:
            pytest.fail(f"unclassified conductive primitive in the schematic SVG: {prim!r}")


def test_schematic_svg_matches_the_layout_model_exactly(page):
    _submit_via_expression(page, _AOI21_EXPR)
    schematic = _real_json(page, "/api/synth", {"expr": _AOI21_EXPR})["schematic"]
    assert schematic["total_transistors"] == 8  # sanity: this is really the shared-inverter case

    snapshot = _schematic_dom_snapshot(page)
    _assert_snapshot_matches_model(snapshot, schematic)


@pytest.mark.parametrize("expr", ["(abc)'", "(a+b+c+d)'", "(abc+d)'", "a", "a'", "(A0'b1+C2)'"])
def test_schematic_svg_matches_the_layout_model_for_a_flat_nand(page, expr):
    # A second, structurally different shape (flat parallel/series, no
    # inverter) -- guards against the bridge only happening to work for the
    # nested AOI case above.
    _submit_via_expression(page, expr)
    schematic = _real_json(page, "/api/synth", {"expr": expr})["schematic"]

    snapshot = _schematic_dom_snapshot(page)
    _assert_snapshot_matches_model(snapshot, schematic)


@pytest.mark.parametrize("name,expr,dual", [
    ("nand3", "(abc)'", False), ("nor4", "(a+b+c+d)'", False),
    ("aoi31", "(abc+d)'", False), ("shared-inverter", "(a'b+c)'", False),
    ("dual-rail", "(a'b+c)'", True), ("buffer", "a", False),
    ("inverter", "a'", False), ("long-labels", "(A0'b1+C2)'", False),
    ("four-inverters", "a'b'c'd + a'b'cd' + a'bc'd' + ab'c'd'", False),
    ("aoi22", "(ab+cd)'", False), ("oai31", "((a+b+c)d)'", False),
    ("nor2", "(a+b)'", False), ("nand4", "(abcd)'", False),
])
def test_textbook_visual_and_export_acceptance(page, name, expr, dual):
    _switch_tab(page, "synth")
    page.check('input[name="synth-mode"][value="expr"]')
    page.fill("#synth-expr", expr)
    if dual:
        page.check("#synth-dual-rail")
    page.click("#panel-synth button.submit")
    page.wait_for_selector("#synth-result:not(.empty)")
    schematic = _real_json(page, "/api/synth", {"expr":expr,"dual_rail":dual})["schematic"]
    _assert_snapshot_matches_model(_schematic_dom_snapshot(page), schematic)
    size_script = """() => {
        const label = document.querySelector('.ow-port-label').getBoundingClientRect();
        const channel = document.querySelector('[data-role="channel"]').getBoundingClientRect();
        return {label:label.height,channel:channel.height};
    }"""
    inline_size = page.evaluate(size_script)
    artifact_dir = Path("test-artifacts/schematics")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    page.locator("#schematic-svg").screenshot(path=str(artifact_dir / (name+"-inline.png")))
    clipped = page.evaluate("""() => {
        const svg = document.querySelector('#schematic-svg'), vb = svg.viewBox.baseVal;
        return Array.from(svg.querySelectorAll('text')).filter(t => {
            const b = t.getBBox();
            return b.x < vb.x || b.y < vb.y || b.x+b.width > vb.x+vb.width || b.y+b.height > vb.y+vb.height;
        }).map(t => t.textContent);
    }""")
    assert not clipped, f"clipped schematic labels: {clipped}"
    if name == "shared-inverter":
        page.emulate_media(color_scheme="dark")
        page.locator("#schematic-svg").screenshot(path=str(artifact_dir / (name+"-dark.png")))
        page.emulate_media(color_scheme="light")
    with page.expect_download() as info:
        page.click("#download-svg-btn")
    target = (artifact_dir / (name+".svg")).resolve()
    info.value.save_as(str(target))
    page.goto(target.as_uri())
    _assert_snapshot_matches_model(page.evaluate(_SCHEMATIC_SNAPSHOT_JS, "svg"), schematic)
    assert page.evaluate(size_script) == pytest.approx(inline_size, abs=0.1)
    page.locator("svg").screenshot(path=str(artifact_dir / (name+".png")))


def test_download_svg_passes_the_same_semantic_assertions(page, tmp_path):
    _submit_via_expression(page, _AOI21_EXPR)
    schematic = _real_json(page, "/api/synth", {"expr": _AOI21_EXPR})["schematic"]

    with page.expect_download() as download_info:
        page.click("#download-svg-btn")
    download = download_info.value
    saved_path = tmp_path / "schematic.svg"
    download.save_as(str(saved_path))
    svg_text = saved_path.read_text(encoding="utf-8")

    assert svg_text.strip().startswith("<svg")
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg_text

    # Parse the downloaded file itself (not the live page) via the same
    # DOM-shaped extraction, by navigating straight to it -- this is what
    # proves "Download SVG" produced the SAME checked representation, not a
    # separately-serialized copy that could have drifted. This test's own
    # page is done with the live app at this point, so reusing it is fine.
    page.goto(saved_path.as_uri())
    snapshot = page.evaluate(_SCHEMATIC_SNAPSHOT_JS, "svg")
    _assert_snapshot_matches_model(snapshot, schematic)


def test_download_svg_is_self_contained_with_visible_standalone_styles(page, tmp_path):
    # The bug this pins: the downloaded file had no styling of its own (all
    # stroke/fill rules lived only in the page's stylesheet), so opened
    # standalone its wires/channels defaulted to invisible (SVG's own
    # default stroke is "none") while the "invisible" terminal-anchor dots
    # defaulted to solid visible black circles (SVG's own default fill).
    _submit_via_expression(page, _AOI21_EXPR)

    with page.expect_download() as download_info:
        page.click("#download-svg-btn")
    saved_path = tmp_path / "schematic.svg"
    download_info.value.save_as(str(saved_path))
    assert "<style" in saved_path.read_text(encoding="utf-8")  # the stylesheet travels with the file

    page.goto(saved_path.as_uri())

    def stroke(selector: str) -> str:
        return page.evaluate(f"getComputedStyle(document.querySelector('{selector}')).stroke")

    def fill(selector: str) -> str:
        return page.evaluate(f"getComputedStyle(document.querySelector('{selector}')).fill")

    for selector in (
        '[data-role="wire"]',
        '[data-role="channel"]',
        '[data-role="gate-electrode"]',
        '[data-role="gate-connector"]',
        '.ow-device[data-kind="p"] [data-role="gate-bubble"]',
    ):
        assert stroke(selector) not in ("none", "")

    assert fill('[data-role="junction"]') not in ("none", "", "rgba(0, 0, 0, 0)")  # junction dots stay visible
    assert fill('[data-role="terminal"]') == "rgba(0, 0, 0, 0)"  # terminal anchors stay invisible
    assert fill("text") not in ("none", "", "rgba(0, 0, 0, 0)")  # labels stay visible


def test_schematic_output_label_follows_a_custom_output_name(page):
    _switch_tab(page, "synth")
    page.check('input[name="synth-mode"][value="expr"]')
    page.fill("#synth-expr", "(abc)'")
    page.fill("#synth-output-name", "Y")
    page.click("#panel-synth button.submit")
    page.wait_for_selector("#synth-result:not(.empty)")

    label = page.locator('#schematic-svg [data-role="net-label"][data-net-id="OUT"]')
    assert label.text_content() == "Y"


# --- Test 10: browser-level coverage -------------------------------------------------


def test_schematic_appears_for_a_result(page):
    _submit_via_expression(page, "(abc)'")
    assert page.locator("#schematic-svg .ow-device").count() == 6


def test_schematic_disappears_on_new_problem(page):
    _submit_via_expression(page, "(abc)'")
    assert page.locator("#schematic-svg .ow-device").count() == 6

    page.click("#synth-new-problem")
    assert page.locator("#schematic-svg .ow-device").count() == 0
    assert page.locator("#schematic-svg *").count() == 0  # actually cleared, not just hidden


def test_schematic_disappears_when_the_result_goes_stale(page):
    _submit_via_expression(page, "(abc)'")
    assert page.locator("#schematic-svg .ow-device").count() == 6

    page.fill("#synth-expr", "a+b")  # edited, unsubmitted -- the shown result is now stale
    assert page.locator("#schematic-svg .ow-device").count() == 0


def test_schematic_symbol_count_matches_the_reported_transistor_count(page):
    _submit_via_expression(page, _AOI21_EXPR)
    gate_line = page.text_content("#res-gate-line")
    assert "8 transistors" in gate_line
    assert page.locator("#schematic-svg .ow-device").count() == 8


def test_schematic_wide_circuit_scrolls_instead_of_shrinking_at_mobile_width(page):
    # The bug this pins: the old fixed `width: 100%` rule shrank a wide,
    # many-transistor circuit to fit the viewport, shrinking labels down to
    # ~4-5px at a 360px viewport for this exact case. The fix renders every
    # circuit at a fixed, content-driven pixel scale (constant symbol/label
    # size) and lets .schematic-wrap scroll horizontally instead.
    _submit_via_expression(page, _WIDE_MULTI_INVERTER_EXPR)
    gate_line = page.text_content("#res-gate-line")
    assert "40 transistors" in gate_line  # sanity: this really is the wide, multi-inverter case

    page.set_viewport_size({"width": 360, "height": 800})

    overflow = page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"
    )
    assert not overflow  # the document itself never needs to scroll horizontally

    wrap_scroll = page.evaluate(
        """() => {
            const wrap = document.querySelector('.schematic-wrap');
            return { scrollWidth: wrap.scrollWidth, clientWidth: wrap.clientWidth };
        }"""
    )
    assert wrap_scroll["scrollWidth"] > wrap_scroll["clientWidth"]  # the wrapper itself scrolls internally

    label_height = page.evaluate(
        "document.querySelector('.ow-port-label').getBoundingClientRect().height"
    )
    assert label_height >= 10  # legible -- not shrunk to the ~4-5px the old shrink-to-fit produced

    channel_length_px = page.evaluate(
        """() => {
            const r = document.querySelector('[data-role="channel"]').getBoundingClientRect();
            return Math.max(r.width, r.height);
        }"""
    )
    assert channel_length_px >= 20  # transistor symbols stay a distinguishable on-screen size

    any_text_clipped = page.evaluate(
        """() => {
            const svg = document.getElementById('schematic-svg');
            const vb = svg.viewBox.baseVal;
            return Array.from(svg.querySelectorAll('text')).some(t => {
                const b = t.getBBox();
                return b.x < vb.x || (b.x + b.width) > (vb.x + vb.width)
                    || b.y < vb.y || (b.y + b.height) > (vb.y + vb.height);
            });
        }"""
    )
    assert not any_text_clipped  # no label spills outside the SVG's own viewBox


def test_schematic_has_an_accessible_name(page):
    _submit_via_expression(page, _AOI21_EXPR)
    svg = page.locator("#schematic-svg")
    assert svg.get_attribute("role") == "img"
    label = svg.get_attribute("aria-label")
    assert label and "8 transistors" in label


def test_schematic_adapts_to_dark_mode(page):
    _submit_via_expression(page, "(abc)'")
    light_color = page.evaluate("getComputedStyle(document.querySelector('#schematic-svg .ow-wire')).stroke")

    page.emulate_media(color_scheme="dark")
    dark_color = page.evaluate("getComputedStyle(document.querySelector('#schematic-svg .ow-wire')).stroke")

    assert light_color != dark_color  # currentColor actually follows the color-scheme flip
    # still structurally intact in dark mode, not just recolored
    assert page.locator("#schematic-svg .ow-device").count() == 6


@pytest.mark.parametrize("width", [390, 1280])
def test_spice_download_bytes_labels_and_clearing(page, width):
    from ohmwork.api import synthesize_from_input
    from ohmwork.schematic import build_textbook_schematic
    from ohmwork.spice import render_spice_example, render_spice_template
    page.set_viewport_size({"width": width, "height": 900})
    _switch_tab(page, "synth")
    page.fill("#synth-expr", "(abc+d)'")
    page.fill("#synth-output-name", "Y")
    with page.expect_response("**/api/synth") as response:
        page.click("#panel-synth button.submit")
    payload = response.value.json()
    page.wait_for_selector("#synth-result:not(.empty)")
    layout = build_textbook_schematic(synthesize_from_input(expr="(abc+d)'"), "Y")
    toggle = page.locator("#spice-help-toggle")
    panel = page.locator("#spice-export-help")
    assert not panel.is_visible()
    assert toggle.get_attribute("aria-controls") == "spice-export-help"
    assert toggle.get_attribute("aria-expanded") == "false"
    toggle.click()
    assert panel.is_visible()
    assert toggle.get_attribute("aria-expanded") == "true"
    assert panel.get_attribute("aria-labelledby") == "spice-help-toggle"
    assert panel.locator("h3").count() == 0
    close = panel.get_by_role("button", name="Close", exact=True)
    assert close.inner_text() == "×"
    assert panel.evaluate("el => getComputedStyle(el).borderTopStyle") == "solid"
    box = panel.bounding_box()
    close_box = close.bounding_box()
    text_box = page.locator("#spice-template-note").bounding_box()
    assert close_box["width"] >= 44 and close_box["height"] >= 44
    assert box["x"] <= close_box["x"]
    assert close_box["x"] + close_box["width"] <= box["x"] + box["width"]
    assert box["y"] <= close_box["y"]
    assert close_box["y"] + close_box["height"] <= text_box["y"]
    close.click()
    assert not panel.is_visible()
    assert toggle.get_attribute("aria-expanded") == "false"
    assert toggle.evaluate("el => el === document.activeElement")
    toggle.press("Enter")
    assert panel.is_visible()
    page.locator("#spice-help-close").press("Escape")
    assert not panel.is_visible()
    assert toggle.evaluate("el => el === document.activeElement")
    toggle.press("Space")
    assert panel.is_visible()
    toggle.click()
    assert not panel.is_visible()
    toggle.click()
    toggle.press("Escape")
    assert not panel.is_visible()
    toggle.click()
    assert panel.is_visible()
    assert panel.evaluate("el => el.getBoundingClientRect().right <= window.innerWidth")
    assert "not runnable as-is" in page.locator("#spice-template-note").inner_text()
    assert "All logical inputs start at 0" in page.locator("#spice-example-note").inner_text()
    for kind, render in [("template", render_spice_template), ("example", render_spice_example)]:
        with page.expect_download() as download:
            page.click("#download-spice-" + kind)
        file = download.value
        assert file.suggested_filename == payload["spice"][kind]["filename"]
        assert Path(file.path()).read_bytes() == render(layout).encode() == payload["spice"][kind]["text"].encode()
    artifacts = Path("test-artifacts/schematics")
    artifacts.mkdir(parents=True, exist_ok=True)
    page.locator("#spice-export-help").scroll_into_view_if_needed()
    page.screenshot(path=str(artifacts / f"spice-downloads-{width}.png"))
    # Actual data is removed, not merely hidden by the result container.
    page.fill("#synth-expr", "ab")
    assert page.evaluate("lastSpiceExports === null")
    assert page.locator("#download-spice-template").is_disabled()
    assert page.locator("#download-spice-example").is_disabled()
    assert not page.locator("#spice-export-help").is_visible()
    assert not toggle.is_visible()
    assert toggle.get_attribute("aria-expanded") == "false"
    assert page.locator("#synth-expr").evaluate("el => el === document.activeElement")
    page.click("#panel-synth button.submit")
    page.wait_for_selector("#synth-result:not(.empty)")
    assert toggle.is_visible()
    assert not panel.is_visible()
    assert toggle.get_attribute("aria-expanded") == "false"
    toggle.click()
    page.click("#synth-new-problem")
    assert not toggle.is_visible()
    assert not panel.is_visible()
    assert toggle.get_attribute("aria-expanded") == "false"
    assert page.evaluate("lastSpiceExports === null")
    assert page.locator("#download-spice-example").is_disabled()


def test_spice_inflight_result_cannot_restore_stale_downloads(page):
    _switch_tab(page, "synth")
    page.fill("#synth-expr", "a")
    page.click("#panel-synth button.submit")
    page.wait_for_selector("#synth-result:not(.empty)")
    # Deliver a genuine response only after an input edit invalidates it.
    def respond_late(route):
        reply = route.fetch()
        assert page.evaluate("lastSpiceExports === null")
        page.fill("#synth-expr", "ab")
        route.fulfill(response=reply)
    page.route("**/api/synth", respond_late)
    with page.expect_response("**/api/synth"):
        page.click("#panel-synth button.submit")
    page.wait_for_load_state("networkidle")
    assert page.evaluate("lastSpiceExports === null")
    assert page.locator("#download-spice-example").is_disabled()
    assert not page.locator("#synth-result").is_visible()


@pytest.mark.parametrize("width", [390, 1280])
def test_derivation_csv_download_and_stale_clearing(page, width):
    import csv
    import io
    from ohmwork.api import render_tt
    page.set_viewport_size({"width": width, "height": 900})
    page.fill("#tt-expr", "xy+xy'")
    with page.expect_response("**/api/tt") as response:
        page.click("#panel-tt button.submit")
    payload = response.value.json()
    page.wait_for_selector("#tt-result:not(.empty)")
    with page.expect_download() as download:
        page.click("#tt-download-csv")
    assert download.value.suggested_filename == "ohmwork-derivation.csv"
    data = Path(download.value.path()).read_bytes()
    assert data == payload["csv"].encode() == render_tt("xy+xy'", csv=True).encode()
    rows = list(csv.reader(io.StringIO(data.decode())))
    assert rows[0] == page.locator("#tt-table-head th").all_text_contents()
    assert rows[1:] == [[str(int(v)) for v in row] for row in payload["result"]["rows"]]
    page.fill("#tt-expr", "a")
    assert page.evaluate("lastTtCsv === null")
    assert page.locator("#tt-download-csv").is_disabled()
    page.click("#panel-tt button.submit")
    page.wait_for_selector("#tt-result:not(.empty)")
    # A genuine delayed response must not restore a download after an edit.
    def delayed(route):
        reply = route.fetch()
        assert page.evaluate("lastTtCsv === null")
        page.fill("#tt-expr", "ab")
        route.fulfill(response=reply)
    page.route("**/api/tt", delayed)
    with page.expect_response("**/api/tt"):
        page.click("#panel-tt button.submit")
    page.wait_for_load_state("networkidle")
    assert page.evaluate("lastTtCsv === null")
    assert page.locator("#tt-download-csv").is_disabled()
