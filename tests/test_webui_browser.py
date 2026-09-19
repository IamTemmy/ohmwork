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
