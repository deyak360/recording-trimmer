"""
Logging configuration and utilities.

Implements a structured, colorized, multi-stream logging system with:
- Custom log levels (LIGHT, VERBOSE, STANDARD)
- Color-coded terminal output
- Automatic separation of stdout/stderr
- Optional timestamped file logging
- Custom formatting for consistent, rich log presentation

Supports messages formatted as:
    logger.light(f"Message", extra={'frmt_type': 'custom3', 'prefix': '[TEST1] '}})
    logger.light.config("Config hint", "(extra info)")
    logger.standard("Informational log")
    logger.warning("Warning Information")
    logger.error("Error in reading file")
    logger.exception(e)
"""
import sys
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler


# --- ANSI terminal color codes for pretty terminal logs ---
# These work in most modern terminals. 256-color codes are used where possible.
ANSI_RESET   = "\033[0m"
ANSI_ERROR   = "\033[1;31m"  # bold red
ANSI_WARN    = "\033[33m"    # yellow
ANSI_CUSTOM1 = "\033[1;93m"  # bold yellow
ANSI_CUSTOM2 = "\033[1;96m"  # bold cyan
ANSI_CUSTOM3 = "\033[1;97m"  # bold white
ANSI_CONFIG  = "\033[94m"    # blue
ANSI_CONFIG2 = "\033[34m"    # darker blue

LOG_STYLES = {
    'CRITICAL':{'color': ANSI_ERROR,   'prefix': '[CRITICAL] '},
    'ERROR':   {'color': ANSI_ERROR,   'prefix': '[ERROR] '},
    'WARNING': {'color': ANSI_WARN,    'prefix': '[WARNING] '},
    'LIGHT':   {'color': '',           'prefix': ''},
    'INFO':    {'color': '',           'prefix': ''}, #used by logger.standard(...)
    'VERBOSE': {'color': '',           'prefix': ''},
    'DEBUG':   {'color': '',           'prefix': '[DEBUG] '},
    'CUSTOM1': {'color': ANSI_CUSTOM1, 'prefix': '[INFO] '},
    'CUSTOM2': {'color': ANSI_CUSTOM2, 'prefix': ''},
    'CUSTOM3': {'color': ANSI_CUSTOM3, 'prefix': ''},
}

# --- Formatter utility ---
def format_special(message: str, frmt_type: str, prfx: str = None) -> str:
    """Colorizes and prefixes the message based on frmt_type (from LOG_STYLES).
    'prefix' can override the default prefix for that type.

    Raises ValueError for invalid frmt_type to prevent silent formatting errors.
    Returns the colored and prefixed string. If a style has no color, the returned string contains no ANSI sequences.
    """
    style = LOG_STYLES.get(str.upper(frmt_type))
    if style is None: raise ValueError(f"Unrecognized logging type: {frmt_type}") #SP-FRMT

    color, prefix = style['color'], prfx if prfx is not None else style['prefix']
    color_reset = '' if not color else ANSI_RESET
    return f"{color}{prefix}{message}{color_reset}"


# --- Custom log levels between DEBUG and INFO ---
# Add small convenience levels to the logging module, using numbers between the built-ins:
# CRITICAL(50), ERROR(40), WARNING(30), LIGHT(25) INFO(20), VERBOSE(15), DEBUG(10)
logging.LIGHT = 25
logging.addLevelName(logging.LIGHT, "LIGHT")

logging.VERBOSE = 15
logging.addLevelName(logging.VERBOSE, "VERBOSE")

# CustomLogger subclass
class CustomLogger(logging.Logger):
    """Custom logger that returns the interpolated message from logging methods."""

    def debug(self, msg, **kwargs):
        super().debug(msg, **kwargs)
        return str(msg)

    def info(self, msg, **kwargs):
        super().info(msg, **kwargs)
        return str(msg)

    def warning(self, msg, **kwargs):
        super().warning(msg, **kwargs)
        return str(msg)

    def error(self, msg, **kwargs):
        super().error(msg, **kwargs)
        return str(msg)

    def critical(self, msg, **kwargs):
        super().critical(msg, **kwargs)
        return str(msg)

    def log(self, level, msg, **kwargs):
        super().log(level, msg, **kwargs)
        return str(msg)

    def exception(self, msg, **kwargs):
        super().exception(msg, **kwargs)
        return str(msg)

    def standard(self, msg, **kwargs):
        if self.isEnabledFor(logging.INFO):
            self.log(logging.INFO, msg, **kwargs)
        return str(msg)

    def verbose(self, msg, **kwargs):
        if self.isEnabledFor(logging.VERBOSE):
            self.log(logging.VERBOSE, msg, **kwargs)
        return str(msg)

# LightHelper (updated to return the plain message)
class LightHelper:
    """A helper property returned when calling ``logger.light``.
    This allows chained usage like: logger.light.config("ConfigName", "Hint")"""

    def __init__(self, logger):
        self.logger = logger

    def __call__(self, msg=None, **kws):
        if msg is None:
            return self
        if self.logger.isEnabledFor(logging.LIGHT):
            self.logger.log(logging.LIGHT, msg, **kws)
        return str(msg)

    def config(self, msg: str, hint: str):
        """Prints a blue-colored message (msg + hint), intended for configuration feedback.

        The message will be colorized using ANSI_CONFIG/ANSI_CONFIG2 and
        forwarded to `logger.light(..., extra={'frmt_type': 'as-is'})`. The
        `as-is` frmt_type tells the formatter the message is already fully
        formatted and should not be wrapped again.

        Example:
            logger.light.config("Logging level set to standard", "(use -l to change)")
        """

        formatted_msg = f"🔧 {ANSI_CONFIG}{msg}{ANSI_RESET}"
        formatted_hint = f"{ANSI_CONFIG2}{hint}{ANSI_RESET}" if hint else ""
        message = f"{formatted_msg} {formatted_hint}".strip()
        self.logger.light(message, extra={'frmt_type': 'as-is'})
        return f"{msg} {hint}".strip()  # Return plain version

# Descriptor for light
class _LightDescriptor:
    def __get__(self, instance, owner):
        if instance is None:
            return self
        return LightHelper(instance)

# Attach descriptor to CustomLogger
CustomLogger.light = _LightDescriptor()


# --- Custom formatter class ---
# Controls how each log record is displayed (both console and file handlers).
class CustomFormatter(logging.Formatter):
    def __init__(self, include_timestamp=False):
        super().__init__()
        self.include_timestamp = include_timestamp

    def formatTime(self, record, datefmt=None):
        """Custom time formatter that supports %f (microseconds). Uses self.converter(record.created) for local/UTC control."""
        dt = datetime.fromtimestamp(record.created)
        if datefmt:
            return dt.strftime(datefmt)
        # Fallback if no datefmt is provided
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")

    def format(self, record):
        """Applies color, prefix, optional timestamp, and exception formatting.

        Behavior:
          - Uses record.frmt_type (custom style) if present, otherwise, record.levelname (aka: VERBOSE, ERROR, etc.)
          - Skips re-coloring if frmt_type == 'AS-IS'
          - Adds timestamp if enabled (for file logs)
          - Appends traceback text for exceptions
        """
        frmt_type = getattr(record, 'frmt_type', record.levelname)
        prefix = getattr(record, 'prefix', None)
        msg = record.getMessage()

        # Core colorized message
        if frmt_type != "as-is": # used for config (already pre-formatted)
            msg = format_special(msg, frmt_type, prefix)

        # Add timestamp only if requested
        if self.include_timestamp:
            timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S.%f")
            msg = f"[{timestamp}] {msg}"

        # Handle exception traceback if present
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            msg = f"{msg}\n{exc_text}"

        return msg


# --- Rotating file handler that flushes immediately ---
# Ensures that even in unexpected exits (e.g., sys.exit), logs are written to disk.
class FlushingRotatingFileHandler(RotatingFileHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


# --- Filters for stream separation ---
# Filter for stdout: Only DEBUG ~ WARNING
class StdoutFilter(logging.Filter):
    def filter(self, record):
        return record.levelno < logging.WARNING

# Filter for stderr: WARNING+
class StderrFilter(logging.Filter):
    def filter(self, record):
        return record.levelno >= logging.WARNING


# --- Main setup function ---
def setup_logging(log_level: str, log_dir: str) -> logging.Logger:
    """Configures a unified logger called 'recording_trimmer'.
       Raises ValueError if args.log_level is not a recognized choice.

    Behavior summary:
      • Multiple log levels selectable via args.log_level
      • Clean separation of stdout/stderr
      • Optional file logging with rotation and timestamps
      • Consistent color-coded output
    """
    # Map CLI log-level strings to numeric constants
    level_map = {
        'light': logging.LIGHT, #25
        'standard': logging.INFO, #20
        'verbose': logging.VERBOSE, #15
        'debug': logging.DEBUG, #10
    }
    log_level = level_map.get(log_level)
    if log_level is None: raise ValueError(f"Invalid log level: {log_level!r}") #SP-FRMT

    # Create standard logger and reassign its class to CustomLogger
    logger = logging.getLogger('recording-trimmer')
    logger.__class__ = CustomLogger

    logger.propagate = False
    logger.setLevel(logging.DEBUG)  # Capture all internally

    # Clear any existing handlers to avoid duplicates
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Stdout handler: Normal output (log_level ~ WARNING)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(log_level) # Min level
    ch.addFilter(StdoutFilter()) # Max level
    ch.setFormatter(CustomFormatter())
    logger.addHandler(ch)

    # Stderr handler: Diagnostics only (WARNING+)
    eh = logging.StreamHandler(sys.stderr)
    eh.setLevel(logging.WARNING) # Min level
    eh.addFilter(StderrFilter()) # Max level
    eh.setFormatter(CustomFormatter())
    logger.addHandler(eh)

    # File handler: Everything (VERBOSE+ or DEBUG+ if debug enabled), live flush
    if log_dir:
        fh = FlushingRotatingFileHandler(log_dir, mode='w', encoding='utf-8', maxBytes=10*1024*1024, backupCount=10)
        fh.setLevel(min(log_level, logging.VERBOSE))
        fh.setFormatter(CustomFormatter(include_timestamp=True)) #keep formatting as log should be viewed in terminal
        logger.addHandler(fh)

    return logger