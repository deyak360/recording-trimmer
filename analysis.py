# analysis.py
"""
Analysis module: loudness extraction and spike detection algorithms.
Contains both dynamic and fixed-end scanning modes and the main analyze_file entrypoint.
"""

import logging
from typing import List, Tuple, Optional

from c_io import get_duration, get_loudness_data
from utils import seconds_to_hms, truncate_path


logger = logging.getLogger('recording-trimmer')


def log_buffer(file: str, buffer: List[dict], confirmed: bool = False) -> None:
    """Log buffered spikes, summarizing fails (best by pass_count), or all passes in verbose mode."""
    if not buffer:
        return

    if all(item['status'] == "Fail" for item in buffer) and not confirmed:
        best_fail = max(buffer, key=lambda x: x['pass_count'])
        logger.verbose(
            f"File: {truncate_path(file)} | [Fail] {seconds_to_hms(best_fail['time'])[:-3] + '*'} — P-Spike at {int(best_fail['time'])}.*s | "
            f"[✓] 0s: {best_fail['spike_avg']:.2f} | {' | '.join(best_fail['confirm_results'])} "
            f"(Pass = {best_fail['pass_val']:.2f})"
        )
    else:
        for item in buffer:
            logger.verbose(
                f"File: {truncate_path(file)} | [{item['status']}] {item['hms']} — P-Spike at {item['time']:.1f}s | "
                f"[✓] 0s: {item['spike_avg']:.2f} | {' | '.join(item['confirm_results'])} "
                f"(Pass = {item['pass_val']:.2f})"
            )


# noinspection PyDefaultArgument
def analyze_file_dynamic_scan(file: str, data: List[Tuple[float, float]], loudness_threshold: float = 12,
                              window_size: int = 30, confirm_seconds: List[int] = [3, 6], skip_mins: int = 1) -> \
        Tuple[Optional[str], Optional[float]]:
    """Optimized dynamic scan approach for short/medium files using O(n) sliding-window averages and incremental pre-average (O(n)).
    This method scans the entire file, computing rolling averages and comparing each potential spike against the average loudness before it.
    It's 'dynamic' because the reference average updates for each point, making it suitable for files with variable loudness patterns."""

    samples_per_sec = 10  # input from ebur128 ~= 0.1s per sample
    if window_size <= 0 or window_size >= len(data):
        msg = f"File: {file} | Skipping: Invalid window_size {window_size} for data length {len(data)}"
        logger.warning(msg)
        return msg, None

    # split time (t) and loudness (m) arrays
    times = [t for t, _ in data]
    vals = [m for _, m in data]
    total_windows = len(vals) - window_size + 1
    if total_windows <= 0:
        msg = f"File: {file} | Skipping: not enough samples for window"
        logger.warning(msg)
        return msg, None

    # compute rolling averages with sliding sum (O(n))
    rolling_avgs = [0.0] * total_windows
    win_sum = sum(vals[0:window_size])
    rolling_avgs[0] = win_sum / window_size
    for i in range(1, total_windows):
        win_sum += vals[i + window_size - 1] - vals[i - 1]
        rolling_avgs[i] = win_sum / window_size
    rolling_times = times[0:total_windows]
    logger.standard(f"File: {truncate_path(file)} | Computed {len(rolling_avgs)} rolling avgs (window={window_size / samples_per_sec:.1f}s)")

    # define scan starting point
    min_start_sample = int(skip_mins * 60 * samples_per_sec)
    logger.standard(f"File: {truncate_path(file)} | Scanning from sample {min_start_sample} (t~{min_start_sample / samples_per_sec:.1f}s)")
    if min_start_sample >= len(rolling_avgs):
        msg = f"File: {file} | Skipping: Set minutes to skip from beginning ({skip_mins}) exceeds file duration"
        logger.warning(msg)
        return msg, None

    # prepare incremental avg_before (sum/count) so we don't recompute repeatedly
    sum_before = sum(rolling_avgs[0:min_start_sample]) if min_start_sample > 0 else 0.0
    count_before = min_start_sample

    trim_time = None
    buffer = []
    current_second = None

    # scan through rolling averages
    for i in range(min_start_sample, len(rolling_avgs)):
        spike_time = rolling_times[i]
        spike_second = int(spike_time)
        spike_avg = rolling_avgs[i]

        # avg_before = average of all previous rolling_avgs
        avg_before = (sum_before / count_before) if count_before > 0 else float('-inf')

        # detect spike: loudness higher than earlier average by threshold
        if spike_avg > avg_before + loudness_threshold:
            confirm_results = []
            confirmed = True
            status = "Pass"
            pass_count = 0

            # confirm sustained loudness
            for offset in confirm_seconds:
                confirm_i = i + int(round(offset * samples_per_sec))
                if confirm_i >= len(rolling_avgs):
                    confirm_results.append(f"[✗] +{offset:.0f}s: out of range")
                    confirmed = False
                    status = "Fail"
                    break
                confirm_avg = rolling_avgs[confirm_i]
                if confirm_avg < spike_avg:
                    confirm_results.append(f"[✗] +{offset:.0f}s: {confirm_avg:.2f} < {spike_avg:.2f}")
                    confirmed = False
                    status = "Fail"
                    break
                confirm_results.append(f"[✓] +{offset:.0f}s: {confirm_avg:.2f}")
                pass_count += 1

            # log candidate
            buffer.append({
                'status': status,
                'hms': seconds_to_hms(spike_time),
                'time': spike_time,
                'spike_avg': spike_avg,
                'confirm_results': confirm_results,
                'pass_val': avg_before + loudness_threshold if avg_before != float('-inf') else '-inf',
                'pass_count': pass_count
            })

            # avoid spam: only log once per second
            if spike_second != current_second:
                log_buffer(file, buffer[:-1])
                buffer = [buffer[-1]]
                current_second = spike_second

            # if confirmed, stop scanning and set trim point
            if confirmed:
                log_buffer(file, buffer, True)
                buffer = []
                trim_time = spike_time
                break

        # update sum_before/count_before for next iteration (avg_before uses data up to i)
        sum_before += spike_avg
        count_before += 1

    log_buffer(file, buffer)

    if trim_time is None:
        logger.light(f"File: {truncate_path(file)} | No confirmed spike detected")
        return None, None

    logger.light(f"File: {truncate_path(file)} | Confirmed trim point: {trim_time:.1f}s ({seconds_to_hms(trim_time)})")
    return None, trim_time


# noinspection PyDefaultArgument
def analyze_file_fixed_end(file: str, data: List[Tuple[float, float]], duration: float, loudness_threshold: float = 8,
                           window_size: int = 50, confirm_seconds: List[int] = [5, 10], analysis_minutes: int = 30) -> \
        Tuple[Optional[str], Optional[float]]:
    """Optimized fixed-end scan approach for long files (>= specified medium threshold) using sliding-window and O(n) operations.
    This method analyzes only the last portion (defined by analysis_minutes) of the file, comparing loudness against the average of the earlier part.
    It's designed for long files to reduce CPU usage by not scanning the entire file dynamically.
    Uses a static lecture_avg from the non-analysis part to detect spikes, assuming the lecture is quieter than the commuting noise at the end."""

    samples_per_sec = 10
    analysis_start = max(0.0, duration - (analysis_minutes * 60.0))

    # compute lecture average efficiently (sum/count) for t < analysis_start
    sum_lecture = 0.0
    count_lecture = 0
    end_part = []
    for t, m in data:
        if t < analysis_start:
            sum_lecture += m
            count_lecture += 1
        else:
            end_part.append((t, m))

    lecture_avg = (sum_lecture / count_lecture) if count_lecture > 0 else float('-inf')
    logger.standard(f"File: {truncate_path(file)} | Recording avg (0 to {analysis_start:.1f}s): {lecture_avg:.2f} LUFS | Threshold: ({lecture_avg:.2f} + {loudness_threshold}) = {lecture_avg + loudness_threshold:.2f} LUFS")
    logger.standard(f"File: {truncate_path(file)} | Analysis start: {analysis_start:.1f}s ({seconds_to_hms(analysis_start)}) for last {analysis_minutes} min")

    if not end_part:
        msg = f"File: {file} | Skipping: No end part data"
        logger.warning(msg)
        return msg, None

    end_times = [t for t, _ in end_part]
    end_ms = [m for _, m in end_part]
    logger.standard(f"File: {truncate_path(file)} | Processing {len(end_ms)} samples from t={end_times[0]:.1f}s to {end_times[-1]:.1f}s")

    # compute rolling averages for end part
    if window_size <= 0 or window_size >= len(end_ms):
        msg = f"File: {truncate_path(file)} | Skipping: Invalid window_size {window_size} for end part length {len(end_ms)}"
        logger.warning(msg)
        return msg, None

    total_windows = len(end_ms) - window_size + 1
    rolling_avgs = [0.0] * total_windows
    win_sum = sum(end_ms[0:window_size])
    rolling_avgs[0] = win_sum / window_size
    for i in range(1, total_windows):
        win_sum += end_ms[i + window_size - 1] - end_ms[i - 1]
        rolling_avgs[i] = win_sum / window_size
    rolling_times = end_times[0:total_windows]
    logger.standard(f"File: {truncate_path(file)} | Computed {len(rolling_avgs)} rolling avgs (window={window_size / samples_per_sec:.1f}s)")

    # scan through rolling averages
    trim_time = None
    buffer = []
    current_second = None
    for i, spike_avg in enumerate(rolling_avgs):
        spike_time = rolling_times[i]
        spike_second = int(spike_time)

        # detect spike: loudness higher than earlier lecture_avg by threshold
        if spike_avg > lecture_avg + loudness_threshold:
            confirm_results = []
            confirmed = True
            status = "Pass"
            pass_count = 0

            # confirm sustained loudness
            for offset in confirm_seconds:
                confirm_i = i + int(round(offset * samples_per_sec))
                if confirm_i >= len(rolling_avgs):
                    confirm_results.append(f"[✗] +{offset:.0f}s: out of range")
                    confirmed = False
                    status = "Fail"
                    break
                confirm_avg = rolling_avgs[confirm_i]
                if confirm_avg < spike_avg:
                    confirm_results.append(f"[✗] +{offset:.0f}s: {confirm_avg:.2f} < {spike_avg:.2f}")
                    confirmed = False
                    status = "Fail"
                    break
                confirm_results.append(f"[✓] +{offset:.0f}s: {confirm_avg:.2f}")
                pass_count += 1

            # record candidate
            buffer.append({
                'status': status,
                'hms': seconds_to_hms(spike_time),
                'time': spike_time,
                'spike_avg': spike_avg,
                'confirm_results': confirm_results,
                'pass_val': lecture_avg + loudness_threshold,
                'pass_count': pass_count
            })

            # avoid spam: only log once per second
            if spike_second != current_second:
                log_buffer(file, buffer[:-1])
                buffer = [buffer[-1]]
                current_second = spike_second

            # if confirmed, stop scanning and set trim point
            if confirmed:
                log_buffer(file, buffer, True)
                buffer = []
                trim_time = spike_time
                break

    log_buffer(file, buffer)

    if trim_time is None:
        logger.light(f"File: {truncate_path(file)} | No confirmed spike detected")
        return None, None

    logger.light(f"File: {truncate_path(file)} | Confirmed trim point: {trim_time:.1f}s ({seconds_to_hms(trim_time)})")
    return None, trim_time


def analyze_file(file: str, args):
    """Main analyze function: Chooses the appropriate analysis approach based on file duration.
    This is the entry point for analysis, handling errors and routing to dynamic or fixed methods."""
    try:
        duration = get_duration(file)
        logger.light(f"File: {truncate_path(file)} | Duration: {duration:.1f}s ({seconds_to_hms(duration)})")

    except (RuntimeError, FileNotFoundError, ValueError, PermissionError) as e:
        msg = f"Error getting duration: {e}"
        logger.exception(msg)
        return msg, None, 0

    try:
        data = get_loudness_data(file)
    except (RuntimeError, FileNotFoundError, ValueError, PermissionError) as e:
        msg = f"Error getting loudness: {e}"
        logger.exception(msg)
        return msg, None, 0

    if not data:
        msg = f"File: {file} | No loudness data - skipping"
        logger.warning(msg)
        return msg, None, duration

    prefix = f"File: {truncate_path(file)} |"
    if duration < (args.short_file_thresh_mins * 60):
        logger.standard(f"{prefix} Duration < {args.short_file_thresh_mins} min - using short approach")
        error_str, trim_time = analyze_file_dynamic_scan(file, data, args.short_loud_thresh_db, args.short_win_size_sec * 10, args.short_confirm_secs, args.short_skip_mins)
    elif duration < (args.med_file_thresh_mins * 60):
        logger.standard(f"{prefix} Duration between {args.short_file_thresh_mins} min & {args.med_file_thresh_mins} min - using medium approach")
        error_str, trim_time = analyze_file_dynamic_scan(file, data, args.med_loud_thresh_db, args.med_win_size_sec * 10, args.med_confirm_secs, args.med_skip_mins)
    else:
        logger.standard(f"{prefix} Duration >= {args.med_file_thresh_mins} min - using long approach")
        error_str, trim_time = analyze_file_fixed_end(file, data, duration, args.long_loud_thresh_db, args.long_win_size_sec*10, args.long_confirm_secs, args.long_analysis_mins)

    return error_str, trim_time, duration