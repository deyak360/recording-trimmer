# config.py
"""
Configuration: argument parser construction, validators, and cross-argument validation.
"""

import os
import sys
import argparse
import logging
from datetime import datetime
from typing import List

from c_io import ensure_dir_writable
from c_logging import format_special
from display import build_clickable_link


logger = logging.getLogger('recording-trimmer')

# Argument helpers / validators
class ColoredArgumentParser(argparse.ArgumentParser):
    def info(self, message):
        sys.stderr.write(format_special(f"{self.prog}: {message}\n", 'custom2'))

    def warning(self, message):
        sys.stderr.write(format_special(f"{self.prog}: {message}\n", 'custom1'))

    def error(self, message):
        sys.stderr.write(format_special(f"{self.prog}: {message}\n", 'critical'))
        self.exit(2)


def validate_thresholds(args: argparse.Namespace, parser: ColoredArgumentParser):
    """Cross-argument validation; call after parse_args()."""
    # lower bounds computed from current skip values (defaults used if not passed)
    min_sft = min(args.short_skip_mins * 3, 10)
    min_mft = min(args.med_skip_mins * 3, 10)

    if args.short_file_thresh_mins < min_sft:
        parser.error(
            f"SHORT_FILE_THRESH_MINS must be >= min(SHORT_SKIP_MINS*3, 10) = {min_sft} "
            f"(got {args.short_file_thresh_mins})"
        )

    if args.med_file_thresh_mins < min_mft:
        parser.error(
            f"MED_FILE_THRESH_MINS must be >= min(MED_SKIP_MINS*3, 10) = {min_mft} "
            f"(got {args.med_file_thresh_mins})"
        )

    if not (args.short_file_thresh_mins < args.med_file_thresh_mins):
        parser.error(
            f"SHORT_FILE_THRESH_MINS (got {args.short_file_thresh_mins}) must be strictly less than MED_FILE_THRESH_MINS (got {args.med_file_thresh_mins})"
        )

    if not (args.med_file_thresh_mins > args.long_analysis_mins + 10):
        parser.error(
            f"MED_FILE_THRESH_MINS (got {args.med_file_thresh_mins}) must be > LONG_ANALYSIS_MINS+10 "
            f"(LONG_ANALYSIS_MINS={args.long_analysis_mins}, required > {args.long_analysis_mins + 10})"
        )


def validate_confirm_sec(value: str) -> List[int]:
    # Remove spaces and split by comma
    parts = [v.strip() for v in value.split(',')]

    if not parts or any(not v for v in parts):
        raise argparse.ArgumentTypeError(f"Invalid format: '{value}' (empty values or double commas).")

    try:
        numbers = [int(v) for v in parts]
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid number in: '{value}' (all must be integers).")

    if any(n < 1 for n in numbers):
        raise argparse.ArgumentTypeError(f"All numbers must be positive and at least 1 in '{value}'.")

    if sorted(numbers) != numbers:
        raise argparse.ArgumentTypeError(f"Numbers must be in increasing order in '{value}'.")

    if len(numbers) != len(set(numbers)):
        raise argparse.ArgumentTypeError(f"Duplicate numbers not allowed in '{value}'.")

    return numbers


def validate_naming_scheme(value: str) -> str:
    try:
        # Test with dummy values
        value.format(ORIGINAL="test", TIMESTAMP="2025-10-02 000000", UNIX=1759419628)
        return value
    except KeyError as e:
        raise argparse.ArgumentTypeError(f"Invalid placeholder in naming scheme '{value}': {e}. " + "Use '{ORIGINAL}', '{TIMESTAMP}', or '{UNIX}'.")
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Malformed naming scheme '{value}': {e}. " + "Ensure proper '{}' formatting.")


def positive_int(value: str) -> int:
    """argparse type: convert to int and require >= 1."""
    try:
        iv = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}")
    if iv < 1:
        raise argparse.ArgumentTypeError(f"value must be >= 1 (got {iv})")
    return iv

class WideHelp(argparse.RawTextHelpFormatter):
    def __init__(self, *args, **kwargs):
        kwargs['max_help_position'] = 55   # default 24 → too small
        kwargs['width'] = 120              # wider wrap for Windows terminals
        super().__init__(*args, **kwargs)

def setup_parser() -> ColoredArgumentParser:
    """Set up and return the argparse parser."""
    parser = ColoredArgumentParser(
        formatter_class=WideHelp,
        description="""
        
Audio Trimmer Script

This script analyzes M4A audio files (recordings of lectures, meetings, speeches, etc.) to detect and trim any extra loud noise at the end aiming to decrease file size.

Dependencies:
- Python 3.6+ 
- FFmpeg and FFprobe (must be in PATH or script directory)
- Optional: Spek.exe - for spectrogram viewing (must be in PATH or script directory)

Use Cases:
- Batch process recordings to save space by removing unnecessary end noise
- Customizable for different file durations with dynamic or fixed analysis

Caveats:
- Requires FFmpeg & FFprobe
- Only processes .m4a files
- Detection based on loudness jumps; may miss subtle changes—test thresholds
- Trimming is loss-less (stream copy), but always backup originals
""")

    # Logging
    grp_logging = parser.add_argument_group('Logging')
    grp_logging.add_argument('-l', '--log-level',
                             choices=['verbose', 'standard', 'light'],
                             default='verbose',
                             help='Logging level: verbose, standard, or light (default: verbose)'
                             )
    grp_logging.add_argument('--ffmpeg-logging-level',
                             choices=['info', 'warning', 'error'],
                             default='warning',
                             help='Logging level for ffmpeg: info, warning, or error (default: warning)'
                             )
    grp_logging.add_argument('--log-file', type=str, dest='log_dir',
                             default=None,
                             help='Log file directory for parallel logging (default: off)'
                             )

    # Input
    grp_input = parser.add_argument_group('Input')
    grp_input.add_argument('-i', '--input', dest='input_path', type=str,
                           help='File or directory to process (non-recursive, default: .)'
                           )
    grp_input.add_argument('-ir', dest='input_path_recursive', type=str,
                           help='File or directory to process (recursive, default: .)'
                           )

    # Output
    grp_output = parser.add_argument_group('Output')
    grp_output.add_argument('-o', '--output', nargs='?', dest='output_dir', type=str,
                            default='trimmed',
                            help='Output folder directory (default: trimmed)'
                            )
    grp_output.add_argument('--naming-scheme', type=validate_naming_scheme,
                            default='{ORIGINAL}_trimmed', help="""\
Output file name pattern without extension (default: {ORIGINAL}_trimmed)
  Placeholders: {ORIGINAL}, {TIMESTAMP}, {UNIX} 
""")
    grp_output.add_argument('--on-conflict',
                            choices=['overwrite', 'rename', 'fail'],
                            default='rename',
                            help='Handling method for output file conflicts (default: rename)'
                            )

    # Trimming
    grp_trimming = parser.add_argument_group('Trimming')
    # Trimming
    grp_trimming.add_argument('-t', '--trim', nargs='?', type=int, const=0,
                              help='Auto-trim files with offset in seconds (default: 0)'
                              )
    grp_trimming.add_argument('--trim-min-file-dur', type=int, default=600,
                              help='[Auto-trim] Ignore files shorter than this in seconds (default: 600)'
                              )
    grp_trimming.add_argument('--trim-min-seg-dur', type=int, default=180,
                              help='[Auto-trim] Ignore segments shorter than this in seconds (default: 180)'
                              )

    # Analysis Params
    grp_analysis = parser.add_argument_group(
        'Analysis Parameters',
        description="""
File classification by duration (minutes):
  ShortFiles: 0 < duration ≤ SHORT_FILE_THRESH_MINS
  MediumFiles: SHORT_FILE_THRESH_MINS < duration ≤ MED_FILE_THRESH_MINS
  LongFiles: duration > MED_FILE_THRESH_MINS
""")
    grp_analysis.add_argument('-sft', dest='short_file_thresh_mins', type=positive_int, default=25, help="""\
Upper bound for ShortFiles in minutes (default: 25)
""")
    grp_analysis.add_argument('-mft', dest='med_file_thresh_mins', type=positive_int, default=45, help="""\
Upper bound for MediumFiles in minutes (default: 45)

""")

    # todo: add support for negative floats and negative loudness_threshold for 3 below
    grp_analysis.add_argument('-slt', dest='short_loud_thresh_db', type=positive_int, default=12, help="""\
[ShortFiles] Loudness threshold in dB (default: 12)
""")
    grp_analysis.add_argument('-mlt', dest='med_loud_thresh_db', type=positive_int, default=12, help="""\
[MediumFiles] Loudness threshold in dB (default: 12)
""")
    grp_analysis.add_argument('-llt', dest='long_loud_thresh_db', type=positive_int, default=10, help="""\
[LongFiles] Loudness threshold in dB (default: 10)

""")

    grp_analysis.add_argument('-sws', dest='short_win_size_sec', type=positive_int, default=3, help="""\
[ShortFiles] Sample window size in seconds (default: 3)
""")
    grp_analysis.add_argument('-mws', dest='med_win_size_sec', type=positive_int, default=5, help="""\
[MediumFiles] Sample window size in seconds (default: 5)
""")
    grp_analysis.add_argument('-lws', dest='long_win_size_sec', type=positive_int, default=7, help="""\
[LongFiles] Sample window size in seconds (default: 7)
                              
""")

    grp_analysis.add_argument('-sc', dest='short_confirm_secs', type=validate_confirm_sec, default=[3,6], help="""\
[ShortFiles] CSV list for confirmation intervals in seconds (default: 3,6)
""")
    grp_analysis.add_argument('-mc', dest='med_confirm_secs', type=validate_confirm_sec, default=[4,8], help="""\
[MediumFiles] CSV list for confirmation intervals in seconds (default: 4,8)
""")
    grp_analysis.add_argument('-lc', dest='long_confirm_secs', type=validate_confirm_sec, default=[5,10,25], help="""\
[LongFiles] CSV list for confirmation intervals in seconds (default: 5,10,25)
                              
""")

    grp_analysis.add_argument('-ss', dest='short_skip_mins', type=positive_int, default=1, help="""\
[ShortFiles] Minutes to skip from beginning (default: 1)
""")
    grp_analysis.add_argument('-ms', dest='med_skip_mins', type=positive_int, default=5, help="""\
[MediumFiles] Minutes to skip from beginning (default: 5)
""")
    grp_analysis.add_argument('-la', dest='long_analysis_mins', type=positive_int, default=30, help="""\
[LongFiles] Minutes from start used for noise baseline (default: 30)

""")

    return parser


def parse_and_validate_args(parser: ColoredArgumentParser) -> argparse.Namespace:
    """Parse args and run validations."""
    args = parser.parse_args()

    #Handle input path conflicts
    if args.input_path_recursive and args.input_path:
        parser.warning("Warning: Both -i and -ir provided; using recursive (-ir).")
    args.input_path = args.input_path_recursive or args.input_path or '.'
    args.recursive = bool(args.input_path_recursive)

    validate_thresholds(args, parser)

    #Validate output dir (if trim enabled)
    if args.trim is not None:
        try:
            ensure_dir_writable(args.output_dir)
        except OSError as e:
            if isinstance(e, PermissionError): parser.error("No write permission for output directory")
            else: parser.error("Could not create output directory")

    #Check for .debug file in script dir, if found, enable debug logging mode
    script_dir = os.path.dirname(os.path.abspath(__file__))
    debug_path = os.path.join(script_dir, ".debug")
    if os.path.exists(debug_path):
        args.log_level = 'debug'  # Override to debug if file exists
        parser.info("=== 🔧 Debug mode enabled (via .debug file) ===\n")

    #Validate log dir (if enabled)
    if args.log_dir is not None:
        try:
            log_dir_abs = ensure_dir_writable(args.log_dir)
            ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            log_file_name = f"log_{ts}.log"
            args.log_dir = os.path.join(log_dir_abs, log_file_name)
        except OSError as e:
            if isinstance(e, PermissionError): parser.error("No write permission for log file directory")
            else: parser.error("Could not create log file directory")

    return args


def print_configs(args: argparse.Namespace):
    logging_file_state = "OFF" if args.log_dir is None else build_clickable_link(args.log_dir, link_type='folder')
    enabled_str = "enabled" if args.recursive else "disabled"
    enabled_hint = "(use -i or --input to search top-directory only)" if args.recursive else "(use -ir to search sub-directories as well)"
    auto_trim_state = "disabled" if args.trim is None else f"enabled with offset of {args.trim}s"
    auto_trim_hint = "(use -t or -t <offset_seconds> to enable)" if args.trim is None else "(remove -t to disable or use -t <offset_seconds> to change)"
    logger.light.config(f"Logging level set to {args.log_level}", "(use -l or --log-level to change)")
    logger.light.config(f"Logging file directory set to {logging_file_state}", "(use --log-file to change)")
    logger.light.config(f"Input directory set to {build_clickable_link(args.input_path, link_type='folder')}", "(use -i or --input, -ir to change)")
    logger.light.config(f"Recursive file search is {enabled_str}", enabled_hint)
    logger.light.config(f"Auto-trim is {auto_trim_state}", auto_trim_hint)
    logger.light.config(f"Auto-trim: Ignoring files shorter than {args.trim_min_file_dur}s", "(use --trim-min-file-dur to change)")
    logger.light.config(f"Auto-trim: Ignore segments shorter than {args.trim_min_seg_dur}s", "(use --trim-min-seg-dur to change)")
    logger.light.config(f"Auto-trim: Output directory set to: {build_clickable_link(args.output_dir, link_type='folder')}", "(use -o or --output to change)")
    logger.light.config(f"Auto-trim: Output file naming scheme set to: {args.naming_scheme}", "(use --naming-scheme to change)")
    logger.light.config(f"Auto-trim: Output file conflict policy set to: {args.on_conflict}", "(use --on-conflict to change)")