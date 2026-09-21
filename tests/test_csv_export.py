import csv
import io
import contextlib

import pytest

from ohmwork.api import derive_from_input, render_tt
from ohmwork.cli import main
from ohmwork.render import format_csv


@pytest.mark.parametrize("expression,options", [
    ("xy + xy'", {}), ("a^b", {}), ("a+a'", {}), ("aa'", {}),
    ("abcde", {}), ("xy + xy'", {"terse": True}),
    ("xy + xy'", {"cols": ["y", "x", "xy"]}),
])
def test_csv_round_trip_matches_derivation(expression, options):
    table = derive_from_input(expression, **options).table
    text = render_tt(expression, csv=True, **options)
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == [c.label for c in table.columns]
    assert rows[1:] == [[str(int(c.values[i])) for c in table.columns] for i in range(len(table.rows))]
    assert text == format_csv(table)
    assert not text.startswith("\ufeff")
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_cli_csv_has_no_footer_or_blank_record():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(["tt", "a^b", "--csv", "--cols", "b,a"]) == 0
    assert out.getvalue() == render_tt("a^b", csv=True, cols=["b", "a"])


@pytest.mark.parametrize("flag", ["--md", "--latex"])
def test_csv_format_conflicts_rejected(flag):
    with pytest.raises(SystemExit) as exc:
        main(["tt", "ab", "--csv", flag])
    assert exc.value.code == 2
    with pytest.raises(ValueError):
        render_tt("ab", csv=True, **{flag[2:]: True})
