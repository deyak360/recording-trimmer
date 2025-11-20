# main.py
"""
Main entrypoint: argument parsing, validation, orchestration and reporting.
This module wires together io, config, analysis and utils.
"""
import os
import sys

from analysis import analyze_file
from c_io import get_files, trim_file, resolve_output_path, ensure_executable
from c_logging import setup_logging
from config import setup_parser, parse_and_validate_args, print_configs
from display import build_clickable_link, print_reports
from utils import seconds_to_hms, truncate_path


#TODO: propper logging via Logger module + write to file
#TODO: report printing with f- string alignments
#TODO: allow negative loudness thresholds to measure quietness in the end
#TODO: make shortcuts for folder links as well, inorder to have the file highlighted in explorer
#TODO: print out analysis configs along with other [CONFIG]
#TODO: add option to keep old file system meta-data after trimming/conversion (File create/modify date&time)
#TODO: add option to accept .mp3 files, convert them to .m4a during processing
#TODO: add option to just convert file(s) ^^^^
#TODO: add param-option to convert fies using ffmpeg (acc vbr at q2 - roughly outputs ~96kbps & metadata preserving)
#TODO: add option to just trim file(s) with specific [from] and [to]
#TODO: in env.temp, place shortcuts in a project-named folder to avoid over-flooding

def main():
    parser = setup_parser()
    args = parse_and_validate_args(parser)
    logger = setup_logging(args.log_level, args.log_dir) #must run after args are parsed and validated for log_level
    print_configs(args)

    # Essential dependency presence check
    try:
        ensure_executable('ffmpeg')
        ensure_executable('ffprobe')
    except FileNotFoundError as e:
        logger.error("Exiting: Main dependency missing:")
        logger.error(e)
        sys.exit(1)

    # Main orchestration
    all_files = []
    files = get_files(args.input_path, args.recursive)
    if not files:
        logger.error("Exiting: No files to process.")
        sys.exit(1)

    for file in files:
        logger.light(f"\n=== Starting analysis for {truncate_path(file)} ===", extra={'frmt_type': 'custom3'})

        error_str, detect_time, duration = analyze_file(file, args)
        report_item = {
            'file': file,
            'duration': ("#N/A" if duration == 0 else seconds_to_hms(duration)),
            'detect_time': detect_time,
            'adjusted_trim_time': None,
            'error_note': error_str,
            'trim_note': None,
            'new_path': None
        }

        if detect_time is not None: #also means, error_str is None as they're always in sync
            report_item['detect_time'] = seconds_to_hms(detect_time) #above check detect_time is not None

            trim_offset = args.trim or 0
            segment_length = duration - (detect_time + trim_offset)

            if segment_length < args.trim_min_seg_dur:
                if segment_length > 0:
                    report_item['error_note'] = f"Trim point is a mere {segment_length:.1f}s from current end (negligible savings)"
                else:
                    report_item['error_note'] = f"Trim point is {segment_length*-1:.1f}s beyond current end (no savings)"

            elif duration < args.trim_min_file_dur:
                try:
                    file_size_mb = f"{(os.path.getsize(file) / (1024 * 1024)):.1f}"
                except OSError as e:
                    logger.debug(f"Unable to get size for {file}: {e}")
                    file_size_mb = "#N/A"
                report_item['error_note'] = f"File is only {file_size_mb} MB (negligible savings)"

            if args.trim is not None and report_item['error_note'] is None:
                adjusted_trim_time = max(0, min(duration, detect_time + trim_offset))
                report_item['adjusted_trim_time'] = adjusted_trim_time

                output_path = resolve_output_path(file, args.naming_scheme, args.output_dir, args.on_conflict)
                report_item['new_path'] = output_path

                if output_path:
                    try:
                        trim_file(file, adjusted_trim_time, output_path, args.ffmpeg_logging_level)
                        logger.light(f"File: {truncate_path(file)} | Trimmed to {adjusted_trim_time:.1f}s ({seconds_to_hms(adjusted_trim_time)}) and saved to {build_clickable_link(output_path)}")

                    except (RuntimeError, FileNotFoundError, ValueError, PermissionError) as e:
                        logger.exception(e)
                        report_item['trim_note'] = e
                        continue

                else:
                    report_item['trim_note'] = "Trimmed file was not able to be created/saved" #Due to file existing and --on-conflict == fail


        all_files.append(report_item)
        logger.light(f"=== Finished analysis for {truncate_path(file)} ===\n", extra={'frmt_type': 'custom3'})

    print_reports(all_files, args.trim)