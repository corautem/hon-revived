"""Tests for the pyhon workarounds."""

from unittest.mock import PropertyMock, patch

from pyhon.commands import HonCommand
from pyhon.parameter.enum import HonParameterEnum
from pyhon.parameter.range import HonParameterRange

from custom_components.hon.pyhon_fixes import option_count


def make_range(maximum: str, step: str = "1") -> HonParameterRange:
    return HonParameterRange(
        "assistedCookingSession",
        {"minimumValue": "0", "maximumValue": maximum, "incrementValue": step},
        "parameters",
    )


def test_more_options_does_not_list_range_values() -> None:
    small = make_range("10")
    huge = make_range("9999999999")
    # pyhon's own version lists both ranges; for this one that is 10 billion
    # strings. Listing raises here instead of filling the memory.
    with patch.object(
        HonParameterRange,
        "values",
        new_callable=PropertyMock,
        side_effect=AssertionError("range values were listed"),
    ):
        assert HonCommand._more_options(small, huge) is huge
        assert HonCommand._more_options(huge, small) is huge


def test_option_count_matches_listed_values() -> None:
    for maximum, step in (("10", "1"), ("5", "0.5"), ("0", "0"), ("100", "7")):
        parameter = make_range(maximum, step)
        assert option_count(parameter) == len(parameter.values), (maximum, step)

    enum = HonParameterEnum("mode", {"enumValues": ["1", "2", "3"]}, "parameters")
    assert option_count(enum) == 3
