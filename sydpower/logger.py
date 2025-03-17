# logger.py
"""Logging utilities for Sydpower/Fossibot integration."""

import logging
import time
from typing import Dict, Any

class SmartLogger:
    """Smart logging helper that adapts logging level based on system state."""
    
    def __init__(self, logger_name: str, log_level: str = "DEBUG"):
        self._logger = logging.getLogger(logger_name)
        self._logger.setLevel(getattr(logging, log_level))
        self._error_count = 0
        self._last_error_time = 0
        self._error_window = 300  # seconds (5 minutes)
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
        current_time = time.time()
        self._error_count += 1
        self._last_error_time = current_time
        
        if self._error_count >= 3:
            self._verbose_mode = True
        
        self._logger.error(msg, *args, **kwargs)

    def debug(self, msg: str, *args, is_status_update=False, **kwargs):
        """Smart debug logging that reduces redundant status messages."""
        if is_status_update and not self._should_log_verbose():
            status_key = msg
            current_args = str(args)
            if (status_key not in self._last_status or 
                self._last_status[status_key] != current_args):
                self._logger.debug(msg, *args, **kwargs)
                self._last_status[status_key] = current_args
        elif self._should_log_verbose():
            self._logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self._logger.warning(msg, *args, **kwargs)

def setup_logging(log_level="DEBUG", log_format=None):
    """Configure root logging."""
    if log_format is None:
        log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    
    logging.basicConfig(
        level=getattr(logging, log_level),
        format=log_format
    )