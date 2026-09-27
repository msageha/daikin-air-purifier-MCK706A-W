"""Daikin MCK706A の dsiot ローカル API クライアント。FastAPI 層には依存しない。"""

from .client import DaikinClient
from .exceptions import DaikinConnectionError, DaikinError, DaikinUnsupportedError
from .models import (
    AirStatus,
    Course,
    DecodedLeaf,
    DeviceInfo,
    FanSpeed,
    HumiditySetting,
)

__all__ = [
    "AirStatus",
    "Course",
    "DaikinClient",
    "DaikinConnectionError",
    "DaikinError",
    "DaikinUnsupportedError",
    "DecodedLeaf",
    "DeviceInfo",
    "FanSpeed",
    "HumiditySetting",
]
