"""Workarounds for bugs in the pinned pyhon-revived release (0.19.6).

Re-check each one when bumping pyhon-revived.
"""

from typing import Any

from pyhon.commands import HonCommand
from pyhon.parameter.fixed import HonParameterFixed
from pyhon.parameter.range import HonParameterRange
from pyhon.rules import HonRuleSet
from pyhon.typedefs import Parameter


def option_count(parameter: Parameter) -> int:
    """Return how many values a parameter allows, without listing them."""
    if isinstance(parameter, HonParameterRange):
        if parameter.max < parameter.min:
            return 0
        return int((parameter.max - parameter.min) // parameter.step) + 1
    return len(parameter.values)


def _more_options(first: Parameter, second: Parameter) -> Parameter:
    # Same choice as pyhon's HonCommand._more_options, which builds the value
    # list of both parameters only to compare their lengths. Ovens report
    # assistedCookingSession as a range from 0 to 9999999999, so "Show Device
    # Info" filled the memory until the system killed Home Assistant.
    if isinstance(first, HonParameterFixed) and not isinstance(
        second, HonParameterFixed
    ):
        return second
    if option_count(second) > option_count(first):
        return second
    return first


def _parse_conditions(
    self: HonRuleSet,
    param_key: str,
    trigger_key: str,
    trigger_data: Any,
    extra: dict[str, str] | None = None,
) -> None:
    # pyhon's HonRuleSet._parse_conditions with two fixes.
    #
    # 1. Some rules hold a dict without "typology", for example ovens with a
    #    probe send tempSel -> {"probe": {"0": {"maximumValue": "250"}}}. pyhon
    #    treated {"maximumValue": "250"} as another condition and called
    #    .items() on "250", which stopped the whole setup (issue #1). Such
    #    values are skipped, as pyhon-revived does since 0.19.3.
    # 2. pyhon shared one `extra` dict between all values of a trigger, so a
    #    rule could carry the conditions of a sibling value. On ovens with a
    #    probe, "probe connected = 1, so set probe = 1" carried "probe
    #    connected = 0" and never applied. Each nested value now gets its own
    #    copy of the conditions.
    if not isinstance(trigger_data, dict):
        return
    trigger_key = trigger_key.replace("@", "")
    trigger_key = self._command.appliance.options.get(trigger_key, trigger_key)
    for multi_trigger_value, param_data in trigger_data.items():
        for trigger_value in multi_trigger_value.split("|"):
            if isinstance(param_data, dict) and "typology" in param_data:
                self._create_rule(
                    param_key, trigger_key, trigger_value, param_data, extra
                )
            elif isinstance(param_data, dict):
                nested = {**(extra or {}), trigger_key: trigger_value}
                for extra_key, extra_data in param_data.items():
                    self._parse_conditions(param_key, extra_key, extra_data, nested)
            else:
                fixed = {"typology": "fixed", "fixedValue": param_data}
                self._create_rule(param_key, trigger_key, trigger_value, fixed, extra)


def apply() -> None:
    """Install the workarounds."""
    setattr(HonCommand, "_more_options", staticmethod(_more_options))
    setattr(HonRuleSet, "_parse_conditions", _parse_conditions)
