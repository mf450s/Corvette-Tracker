from __future__ import annotations

from enum import Enum


class EngineType(str, Enum):
    """Known C6 Corvette engine codes."""

    LS2 = "LS2"
    LS3 = "LS3"
    LS7 = "LS7"
    LS9 = "LS9"
    UNKNOWN = "unknown"


class SourceType(str, Enum):
    """Known marketplace sources."""

    AUTOSCOUT24 = "autoscout24"
    KLEINANZEIGEN = "kleinanzeigen"
    AUTOUNCLE = "autouncle"
    CLASSIC_TRADER = "classic_trader"
    MOBILE_DE = "mobile_de"


class ExportFormat(str, Enum):
    """Supported feed export formats."""

    MARKDOWN = "markdown"
    JSON = "json"
    CSV = "csv"
    HTML = "html"


class LogLevel(str, Enum):
    """Log verbosity levels."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
