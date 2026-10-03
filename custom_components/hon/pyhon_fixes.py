"""Workarounds for bugs in the pinned pyhon-revived release (0.19.2).

Re-check each one when bumping pyhon-revived.
"""

from pyhon.commands import HonCommand
from pyhon.parameter.fixed import HonParameterFixed
from pyhon.parameter.range import HonParameterRange
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


def apply() -> None:
    """Install the workarounds."""
    setattr(HonCommand, "_more_options", staticmethod(_more_options))
