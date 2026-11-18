"""Tests for the pyhon workarounds."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import PropertyMock, patch

import pytest
from pyhon.commands import HonCommand
from pyhon.parameter.enum import HonParameterEnum
from pyhon.parameter.range import HonParameterRange
from pyhon.rules import HonRuleSet

from custom_components.hon.pyhon_fixes import option_count

# fixedValue rules of an oven's startProgram command with a meat probe,
# as posted in pyhon-revived issue #10
FIXED = {"typology": "fixed", "fixedValue": "0"}
PROBE_RANGE = {
    "typology": "range",
    "defaultValue": "40",
    "minimumValue": "30",
    "maximumValue": "90",
    "incrementValue": "1",
}
OVEN_PROBE_RULES: dict[str, Any] = {
    "probe": {
        "@connectionStatusEmployedProbe1": {
            "0": {
                "@connectionStatusEmployedProbe2": {
                    "0": FIXED,
                    "1": {"typology": "fixed", "fixedValue": "1"},
                    "default": FIXED,
                }
            },
            "1": {"typology": "fixed", "fixedValue": "1"},
        }
    },
    "tempSelEmployedProbe1": {
        "@connectionStatusEmployedProbe1": {"1": PROBE_RANGE, "default": FIXED}
    },
    "tempSelEmployedProbe2": {
        "@connectionStatusEmployedProbe2": {"1": PROBE_RANGE, "default": FIXED}
    },
    "zoneEmployedProbe1": {"@connectionStatusEmployedProbe1": {"0": FIXED}},
    "zoneEmployedProbe2": {"@connectionStatusEmployedProbe2": {"0": FIXED}},
    # A dict without "typology": pyhon 0.19.2 raised AttributeError here
    "tempSel": {"probe": {"0": {"maximumValue": "250"}, "1": {"maximumValue": "200"}}},
}


def make_command(parameters: dict[str, Any] | None = None) -> Any:
    """The parts of HonCommand that HonRuleSet reads."""
    return SimpleNamespace(
        appliance=SimpleNamespace(options={}), parameters=parameters or {}
    )


def binary(key: str) -> HonParameterEnum:
    return HonParameterEnum(key, {"enumValues": ["0", "1"]}, "parameters")


@pytest.mark.parametrize("value", ["250", 250])
def test_rule_without_typology_is_skipped(value: str | int) -> None:
    # Issue #1 (str) and pyhon-revived issue #24 (int)
    rules = HonRuleSet(
        make_command(), {"tempSel": {"probe": {"0": {"maximumValue": value}}}}
    )
    assert rules.rules == {}


def test_oven_probe_rules_load() -> None:
    rules = HonRuleSet(make_command(), OVEN_PROBE_RULES)

    params = {r.param_key for values in rules.rules.values() for r in values}
    assert "tempSel" not in params
    assert len(rules.rules["connectionStatusEmployedProbe1"]) == 4
    assert len(rules.rules["connectionStatusEmployedProbe2"]) == 6


def test_rule_does_not_inherit_conditions_of_a_sibling_value() -> None:
    rules = HonRuleSet(make_command(), OVEN_PROBE_RULES)

    conditions = {
        (rule.param_key, rule.trigger_key, rule.trigger_value): rule.extras
        for values in rules.rules.values()
        for rule in values
    }
    # Nested under "probe 1 not connected", so it keeps that condition
    assert conditions[("probe", "connectionStatusEmployedProbe2", "1")] == {
        "connectionStatusEmployedProbe1": "0"
    }
    # A sibling of that branch: pyhon 0.19.2 gave it the same condition
    assert conditions[("probe", "connectionStatusEmployedProbe1", "1")] is None


def test_connecting_the_probe_selects_it() -> None:
    connected = binary("connectionStatusEmployedProbe1")
    probe = binary("probe")
    command = make_command(
        {"connectionStatusEmployedProbe1": connected, "probe": probe}
    )
    HonRuleSet(command, OVEN_PROBE_RULES).patch()
    assert probe.value == "0"

    connected.value = "1"
    assert probe.value == "1"


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
