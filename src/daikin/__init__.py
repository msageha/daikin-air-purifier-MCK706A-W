"""Standalone client for the Daikin MCK706A local (dsiot) API.

This subpackage is independent of the FastAPI layer and can be used on its own.
"""

from .client import DaikinClient
from .exceptions import DaikinConnectionError, DaikinError
from .protocol import flatten, hex_to_ascii, hex_to_int, hex_to_temp

__all__ = [
    "DaikinClient",
    "DaikinError",
    "DaikinConnectionError",
    "flatten",
    "hex_to_int",
    "hex_to_temp",
    "hex_to_ascii",
]
