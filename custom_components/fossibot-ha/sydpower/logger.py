"""Logging utilities for Sydpower/Fossibot integration."""

import logging
import time
from typing import Any, Dict


class SmartLogger:
    """Smart logging helper that deduplicates status messages and auto-enables
    verbose mode after repeated errors."""

    def __init__(self, logger_name: str):
        self._logger = logging.getLogger(logger_name)
        self._error_count = 0
        self._last_error_time = 0
        self._error_window = 300  # 5 minutes
        self._verbose_mode = False
        self._last_status: Dict[str, Any] = {}

    def _should_log_verbose(self) -> bool:
        """Determine if we should log verbose information."""
        current_time = time.time()
        if current_time - self._last_error_time > self._error_window:
            self._error_count = 0
            self._verbose_mode = False
        return self._verbose_mode or self._error_count >= 3

    def error(self, msg: str, *args, **kwargs):
        """Log error and increase error tracking."""
        self._error_count += 1
        self._last_error_time = time.time()
        if self._error_count >= 3:
            self._verbose_mode = True
        self._logger.error(msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        """Log exception with traceback."""
        self._logger.exception(msg, *args, **kwargs)

    def debug(self, msg: str, *args, is_status_update=False, **kwargs):
        """Smart debug logging that deduplicates repeated status messages.

        Regular debug calls always pass through. Status updates (is_status_update=True)
        are deduplicated unless verbose mode is active.
        """
        if is_status_update and not self._should_log_verbose():
            status_key = msg
            current_args = str(args)
            if (status_key not in self._last_status
                    or self._last_status[status_key] != current_args):
                self._logger.debug(msg, *args, **kwargs)
                self._last_status[status_key] = current_args
        else:
            self._logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        """Log info message."""
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        """Log warning message."""
        self._logger.warning(msg, *args, **kwargs)
