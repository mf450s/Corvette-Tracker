from __future__ import annotations

from enum import Enum

from typing_extensions import override


class StrEnum(str, Enum):
    """String enum that also inherits from str for YAML/JSON compatibility."""

    @override
    def __str__(self) -> str:
        return str(self.value)


class EngineType(StrEnum):
    """Known C6 Corvette engine codes."""

    LS2 = "LS2"
    LS3 = "LS3"
    LS7 = "LS7"
    LS9 = "LS9"
    UNKNOWN = "unknown"


class TrimType(StrEnum):
    """Trim levels for the C6 Corvette."""

    BASE = "Base"
    GRAND_SPORT = "Grand Sport"
    Z06 = "Z06"
    ZR1 = "ZR1"
    SPECIAL_EDITION = "Special Edition"


class TransmissionType(StrEnum):
    """Transmission options for the C6 Corvette."""

    MANUAL = "manual"
    AUTOMATIC = "automatic"
    UNKNOWN = "unknown"


class BodyStyleType(StrEnum):
    """Body styles for the C6 Corvette (German strings for DB compatibility)."""

    CABRIO = "Cabrio"
    COUPE = "Coupé"
    TARGA = "Targa"
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
