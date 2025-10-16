import logging
from typing import Literal

from .config import ServiceSettings

_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_logging(settings: ServiceSettings) -> None:
    """Configure root logging level and format."""

    logging_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = settings.log_level
    logging.basicConfig(level=logging_level, format=_LOG_FORMAT)
