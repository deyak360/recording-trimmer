# c_io.py
"""
I/O and filesystem helpers for the Audio Trimmer Script.
Responsible for listing files, getting durations,
resolving output paths and performing the actual trim using ffmpeg.
"""

import re
import os
import glob
import shutil
import subprocess
import logging
import platform
from datetime import datetime
from typing import Optional, Tuple, Literal, List, NoReturn

from utils import truncate_path

logger = logging.getLogger('recording-trimmer')
LOUDNESS_REGEX = re.compile(r't:\s*(\d+\.?\d*)\s*.*M:\s*(-?\d+\.?\d*)')


def get_files(input_path: str, recursive: bool = False):
    """Get .m4a files from the input path.
    This function handles both single files and directories, with optional recursion."""

    files = []
    if os.path.isfile(input_path):
        if input_path.endswith('.m4a'):
            files = [input_path]
        else:
            logger.light(f"Skipping non-.m4a file: {input_path}", extra={'frmt_type': 'custom1'})
    elif os.path.isdir(input_path):
        if not os.access(input_path, os.R_OK):
            logger.warning(f"No read permission for directory: {input_path}")
            return []
        pattern = '**/*.m4a' if recursive else '*.m4a'
        files = glob.glob(os.path.join(input_path, pattern), recursive=recursive)
    if not files:
        logger.light(f"No .m4a files found in {input_path}", extra={'frmt_type': 'custom1'})
    return sorted(files)


def ensure_dir_writable(path: str, create_if_missing: bool = True) -> str:
    """Validate a directory path (relative or absolute), optionally create it, and ensure it's writable.
    Returns absolute path on success. Raises OSError/PermissionError on failure."""

    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        if not create_if_missing:
            raise OSError(f"Directory does not exist and couldn't be created: {abs_path}") #re-caught
        os.makedirs(abs_path)

    if not os.access(abs_path, os.W_OK):
        raise PermissionError(f"No write permission for directory: {abs_path}") #re-caught

    return abs_path


def resolve_output_path(file: str, naming_scheme: str, output_dir: str, resolution_strategy: str = 'rename') -> str | None:
    """Identifies the output file name and handles existing output file based on resolution_strategy policy.
    This function decides whether to overwrite, fail, or rename if the output file already exists."""

    # building of filename using naming-scheme
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H%M%S")
    unix = int(now.timestamp())
    original_name = os.path.basename(file)[:-4] #assumes it's a .m4a (guaranteed by file io validations)

    output_name = naming_scheme.format(ORIGINAL=original_name, TIMESTAMP=timestamp, UNIX=unix) + ".m4a"
    output_path = os.path.join(output_dir, output_name)

    if not os.path.exists(output_path):
        return output_path

    if resolution_strategy == 'overwrite':
        logger.warning(f"File already exists, replacing (--on-conflict: overwrite): {output_path}")
        return output_path
    elif resolution_strategy == 'fail':
        logger.warning(f"File already exists, skipping (--on-conflict: fail): {output_path}")
        return None
    elif resolution_strategy == 'rename':
        logger.warning(f"File already exists, renaming (--on-conflict: rename): {output_path}")

        base, ext = os.path.splitext(output_path)
        i = 1
        new_path = f"{base}_{i}{ext}"
        while os.path.exists(new_path):
            i += 1
            new_path = f"{base}_{i}{ext}"
        return new_path
    raise ValueError(f"Unrecognized resolution_strategy: {resolution_strategy}. Must be 'overwrite', 'fail', or 'rename'.") #SP-FRMT



ExecutableName = Literal['ffmpeg', 'ffprobe', 'spek']

def _safe_get_cwd() -> str:
    """Return current working directory, or a placeholder if it cannot be determined."""
    try:
        return os.getcwd()
    except OSError:
        return "<unavailable>"

def _map_ffmpeg_error_to_exception(msg: str, file: str) -> NoReturn:
    msg_l = msg.lower()
    if "permission denied" in msg_l:
        raise PermissionError(f"Permission denied reading {file}")
    if "no such file" in msg_l or "no such file or directory" in msg_l:
        raise FileNotFoundError(f"File not found: {file}")
    raise ValueError(f"Invalid file or format: {file}")

def get_executable_path(exe: ExecutableName) -> Tuple[bool, str]:
    """Locate an external executable (ffmpeg/ffprobe/spek) in PATH or script directory."""
    # 1) Try script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    executable_name = f"{exe}.exe" if platform.system() == "Windows" else exe
    executable_in_dir = os.path.join(script_dir, executable_name)

    # 2) Try PATH (and CWD on Windows)
    executable: Optional[str] = shutil.which(exe)
    if executable is not None:
        return True, executable

    if not os.path.exists(executable_in_dir) or not os.access(executable_in_dir, os.X_OK):
        return False, executable_in_dir

    return True, executable_in_dir

def ensure_executable(exe: ExecutableName) -> str:
    """Return executable path or raise FileNotFoundError with debug info.

    Raises:
        FileNotFoundError: If the requested executable cannot be found or is not executable.
    """
    success, path = get_executable_path(exe)
    if success: return path

    exe_ext = exe + (".exe" if platform.system() == 'Windows' else "")
    raise FileNotFoundError(
        f"{exe_ext} was not found in any of the expected locations:\n"
        f"  • System PATH\n"
        f"  • Working directory: {os.path.join(_safe_get_cwd(), exe_ext)}\n"
        f"  • Script directory : {path}"
    )  # re-caught x3

def get_loudness_data(file: str) -> List[Tuple[float, float]]:
    """Run FFmpeg ebur128 filter and parse time (t) and momentary loudness (M).
    This function uses FFmpeg to analyze the audio for EBU R 128 loudness metrics, extracting momentary loudness (M) at ~0.1s intervals.
    The 'peak=true' option is used to include peak measurements, but we only parse M here.
    Note: This can be CPU-intensive for long files, as it processes the entire audio.

    Raises:
        FileNotFoundError: If ffmpeg or the input file is missing.
        PermissionError: If the file cannot be read.
        ValueError: If the file is invalid or unsupported.
        RuntimeError: If ffmpeg cannot be launched.
    """
    ffmpeg_path = ensure_executable('ffmpeg')

    try:
        cmd = [ffmpeg_path, '-i', file, '-af', 'ebur128=peak=true', '-f', 'null', '-']
        output = subprocess.run(cmd, check=True, capture_output=True, text=True).stderr
        data = []
        for line in output.splitlines():
            if line.startswith('[Parsed_ebur128_0'):
                match = LOUDNESS_REGEX.search(line)
                if match:
                    t, m = float(match.group(1)), float(match.group(2))
                    data.append((t, m))
        logger.standard(f"File: {truncate_path(file)} | Extracted {len(data)} loudness samples (~0.1s intervals)")
        return data

    except subprocess.CalledProcessError as e:
        _map_ffmpeg_error_to_exception(e.stderr or e.stdout or "", file)
    except OSError as e:
        raise RuntimeError(f"Error launching {ffmpeg_path} for {file}: {e}") #re-caught

def get_duration(file: str) -> float:
    """Get file duration in seconds using ffprobe.
    This function calls ffprobe to extract duration without loading the entire file.

    Raises:
        FileNotFoundError: If ffprobe or the input file is missing.
        PermissionError: If the file cannot be read.
        ValueError: If the file is invalid or unsupported.
        RuntimeError: If ffprobe cannot be launched.
    """
    ffprobe_path = ensure_executable('ffprobe')

    try:
        cmd = [ffprobe_path, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file]
        duration = float(subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip())
        return duration

    except subprocess.CalledProcessError as e:
        _map_ffmpeg_error_to_exception(e.output.decode(errors="ignore"), file)
    except OSError as e:
        raise RuntimeError(f"Error launching {ffprobe_path} for {file}: {e}") #re-caught


def trim_file(file: str, trim_time: float, output_path: str, ffmpeg_logging_level: str) -> None:
    """Trim the file at the suggested time using stream copy.

    Raises:
        FileNotFoundError: If ffmpeg or the input file is missing.
        PermissionError: If the file cannot be read.
        ValueError: If the file is invalid or unsupported.
        RuntimeError: If ffmpeg cannot be launched.
    """
    ffmpeg_path = ensure_executable('ffmpeg')

    try:
        cmd = [ffmpeg_path, '-y', '-v', ffmpeg_logging_level, '-i', file, '-t', str(trim_time), '-c', 'copy', output_path]
        subprocess.run(cmd, check=True, capture_output=True, text=True)

    except subprocess.CalledProcessError as e:
        _map_ffmpeg_error_to_exception(e.stderr or e.stdout or "", file)
    except OSError as e:
        raise RuntimeError(f"Error launching {ffmpeg_path} for {file}: {e}") #re-caught