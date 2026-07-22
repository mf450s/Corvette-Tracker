from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """String enum that also inherits from str for YAML/JSON compatibility."""

    def __str__(self) -> str:
        return self.value


class EngineType(StrEnum):
    """Known C6 Corvette engine codes."""

    LS2 = "LS2"
    LS3 = "LS3"
    LS7 = "LS7"
    LS9 = "LS9"
    UNKNOWN = "unknown"


class SourceType(StrEnum):
    """Supported marketplace source identifiers."""

    AUTOSCOUT24 = "autoscout24"
    KLEINANZEIGEN = "kleinanzeigen"
    AUTOUNCLE = "autouncle"
    CLASSIC_TRADER = "classic_trader"
    MOBILE_DE = "mobile_de"


class ExportFormat(StrEnum):
    """Supported export output formats."""

    MARKDOWN = "markdown"
    JSON = "json"
    CSV = "csv"
    HTML = "html"


class LogLevel(StrEnum):
    """Logging verbosity levels."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
