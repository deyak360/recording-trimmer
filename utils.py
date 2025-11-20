# utils.py
"""
Utility functions and related helpers.
"""
import os
import re
from typing import Tuple, List


def seconds_to_hms(seconds: float) -> str:
    """Convert seconds to HH:MM:SS.mmm format.
    This function is used to format timestamps in a human-readable way for logs and reports.
    Note: Milliseconds are calculated from the fractional part of seconds."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    ms = int((secs - int(secs)) * 1000)
    secs = int(secs)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


ELLIP = '...'


def _ellipsize_segment(seg: str, left: int, right: int) -> str:
    """Ellipsize a folder segment. Keeps `left` chars at start and `right` at end; replaces middle with '...'."""
    if left < 0 or right < 0:
        raise ValueError("left and right must be non-negative")  # SP-FRMT

    if len(seg) <= left + right + len(ELLIP):
        return seg
    return seg[:left] + ELLIP + (seg[-right:] if right > 0 else '')

def _ellipsize_ext(ext: str, ext_left: int = 2, ext_right: int = 3) -> str:
    """Ellipsize a long extension."""
    if len(ext) <= ext_left + ext_right + len(ELLIP) + 1:
        return ext
    if not ext.startswith('.'):
        return ext
    base_ext = ext[1:]
    return '.' + base_ext[:ext_left] + ELLIP + base_ext[-ext_right:]

def _ellipsize_filename(name: str, left: int, right: int) -> str:
    """Ellipsize a filename while keeping its extension intact.
    Handles hidden files starting with dot (e.g., '.bashrc').
    """
    if left < 0 or right < 0:
        raise ValueError("left and right must be non-negative")  # SP-FRMT
    base, ext = os.path.splitext(name)
    if ext == '' and base.startswith('.') and len(base) > 1:  # hidden file: treat entire name as base
        base = name
        ext = ''
    if len(base) <= left + right + len(ELLIP):
        return base + _ellipsize_ext(ext)
    base_ellip = base[:left] + ELLIP + (base[-right:] if right > 0 else '')
    return base_ellip + _ellipsize_ext(ext)

# noinspection RegExpRedundantEscape
def _detect_anchor_and_sep(path: str) -> Tuple[str, str, str]:
    """Detect path anchor (drive letter, UNC, or root) and the separator, returning (anchor, sep, rest).
    Examples:
        'C:\\Users\\John' -> ('C:', '\\', 'Users\\John')
        '/home/user' -> ('/', '/', 'home/user')
        '\\\\server\\share\\folder' -> ('\\\\server\\share', '\\', 'folder')
    """

    if path.startswith('\\\\'):  # UNC: \\server\share\rest
        m = re.match(r'(\\\\[^\\\/]+\\[^\\\/]+)([\\\/]?)(.*)', path)
        if m:
            return m.group(1), '\\', m.group(3)
        return '\\\\', '\\', path[2:]
    if re.match(r'^[A-Za-z]:[\\\/]', path):  # Windows drive
        drive = path[:2]
        rest = path[2:].lstrip('\\/')
        return drive, '\\', rest
    if path.startswith('/'):  # POSIX absolute
        return '/', '/', path.lstrip('/')
    # relative path: choose separator heuristically
    sep = '\\' if '\\' in path and '/' not in path else '/'
    return '', sep, path.strip(sep)

def _make_candidate(display_parts: List[str], anchor: str, sep: str, is_root_anchor: bool) -> str:
    joined = sep.join(display_parts)
    if anchor:
        if is_root_anchor:
            return anchor + joined
        else:
            anchor_clean = anchor.rstrip(sep)
            if joined.startswith(anchor_clean):
                return joined
            else:
                return anchor_clean + sep + joined
    return joined

def truncate_path(path: str,  # The full path string to truncate
                  max_len: int = 50,  # Maximum allowed display length of full path
                  keep_front: int = 1,  # Number of leading folders to preserve
                  keep_back: int = 1,  # Number of trailing folders to preserve
                  seg_left: int = 6,  # Number of chars to keep at start of a truncated folder seg
                  seg_right: int = 4  # Number of chars to keep at end of a truncated folder seg
                  ) -> str:
    """Truncate a file or folder path for display in a "smart" compact way.
      - Preserves the anchor (drive, UNC, or root).
      - For small overflows, trims the filename or last folder slightly without collapsing middle folders.
      - For larger overflows, keeps the first 'keep_front' and last 'keep_back' folders, ellipsizing the middle with '...'.
      - Further ellipsizes individual segments if needed to fit within 'max_len'.
      - Handles Unicode, different OS separators, relative/absolute paths, and network drives.

    Examples:
        >>> truncate_path('C:\\Users\\John\\Documents\\Projects\\Reports\\Final2025.docx', 55)
        'C:\\Users\\...\\Reports\\Fin...025.docx'
        >>> truncate_path('/home/user/projects/myproject/subfolder/verylongfilename.txt', 50)
        '/home/.../subfolder/very...ame.txt'
    """
    if not path:
        return path

    # Already fits; no truncation needed
    path = path.strip()
    if len(path) <= max_len:
        return path

    # Detect anchor (drive letter, UNC, POSIX root) and separator
    anchor, sep, rest = _detect_anchor_and_sep(path)
    is_root_anchor = anchor == '/'

    # Split the rest of path into segments/folders
    parts = [p for p in re.split(r'[\\/]+', rest) if p != '']

    # Determine if path represents a directory (ends with separator)
    is_dir = path.endswith(sep) or path.endswith('/') or path.endswith('\\')

    filename = None
    if parts and not is_dir:
        last = parts[-1]
        # Treat last segment as filename if it contains a dot or starts with dot
        if '.' in last or last.startswith('.') or not path.endswith(sep):
            filename = last
            parts = parts[:-1]  # separate folders from filename

    # Save original last for fallback
    original_last = filename if filename else (parts[-keep_back:] if keep_back and parts else [''])[-1] if parts else ''

    # Build display parts based on keep_front and keep_back
    display_parts: List[str] = []
    if anchor and not is_root_anchor:
        display_parts.append(anchor.rstrip(sep))

    if len(parts) > keep_front + keep_back:
        display_parts.extend(parts[:keep_front])
        display_parts.append(ELLIP)
        display_parts.extend(parts[-keep_back:])
    else:
        display_parts.extend(parts)

    if filename:
        display_parts.append(filename)

    def make_candidate() -> str:
        return _make_candidate(display_parts, anchor, sep, is_root_anchor)

    candidate = make_candidate()
    if len(candidate) <= max_len:
        return candidate  # fits without further truncation

    # If the overflow is small, try a minimal, targeted ellipsize (prefer filename first)
    excess = len(candidate) - max_len
    small_threshold = 6  # margin considered "not substantial"

    if excess <= small_threshold and filename:
        base, ext = os.path.splitext(filename)
        ext_len = len(ext)
        allowed_fname_len = len(filename) - excess

        # Respect seg_left/seg_right even for small truncation:
        min_possible = seg_left + len(ELLIP) + seg_right + ext_len
        if allowed_fname_len >= min_possible:
            core_chars = allowed_fname_len - len(ELLIP) - ext_len  # chars available for base (left+right)
            min_core = seg_left + seg_right
            # distribute extra while ensuring minimums seg_left/seg_right are respected
            extra = core_chars - min_core
            left = seg_left + (extra + 1) // 2
            right = seg_right + extra // 2
            if left < 1:
                left = 1
            # Ellipsize filename slightly
            new_fname = _ellipsize_filename(filename, left, right)
            display_parts[-1] = new_fname
            new_candidate = make_candidate()
            if len(new_candidate) <= max_len:
                return new_candidate  # success with minimal filename truncation

    # If filename minimal approach failed or not applicable, try minimal shrink on last folder (if exists)
    if excess <= small_threshold and not filename and len(display_parts) > (1 if anchor and not is_root_anchor else 0):
        # find last folder idx
        last_folder_idx = len(display_parts) - 1
        while last_folder_idx >= 0 and display_parts[last_folder_idx] == ELLIP:
            last_folder_idx -= 1
        if last_folder_idx >= 0:
            seg = display_parts[last_folder_idx]
            allowed_seg_len = len(seg) - excess

            # Respect seg_left/seg_right for folder truncation too
            min_seg_needed = seg_left + len(ELLIP) + seg_right
            if allowed_seg_len >= min_seg_needed:
                core = allowed_seg_len - len(ELLIP)  # chars available for left+right
                min_core = seg_left + seg_right
                extra = core - min_core
                left = seg_left + (extra + 1) // 2
                right = seg_right + extra // 2
                display_parts[last_folder_idx] = _ellipsize_segment(seg, left, right)
                new_candidate = make_candidate()
                if len(new_candidate) <= max_len:
                    return new_candidate

    # Iteratively shrink the longest shrinkable segment (skip anchor and ELLIP)
    anchor_idx = 0 if display_parts and display_parts[0] == (
        anchor.rstrip(sep) if anchor and not is_root_anchor else '') else -1
    indices = [i for i in range(len(display_parts)) if i != anchor_idx and display_parts[i] != ELLIP]
    while len(candidate) > max_len:
        max_len_seg = -1
        idx = None
        for i in indices:
            seg = display_parts[i]
            if seg == '':
                continue
            seglen = len(seg)
            if seglen > max_len_seg:
                max_len_seg = seglen
                idx = i
        if idx is None or max_len_seg <= (seg_left + seg_right + len(ELLIP)):
            break  # cannot shrink further
        seg_original = display_parts[idx]  # save original for ellipsize
        if filename and idx == len(display_parts) - 1:
            display_parts[idx] = _ellipsize_filename(seg_original, seg_left, seg_right)
        else:
            display_parts[idx] = _ellipsize_segment(seg_original, seg_left, seg_right)
        new_candidate = make_candidate()
        if len(new_candidate) >= len(candidate):
            break
        candidate = new_candidate

    # Merged post-iterative trim and fallback
    if len(candidate) > max_len:
        excess = len(candidate) - max_len
        if excess <= small_threshold:
            last_idx = len(display_parts) - 1
            last_seg = display_parts[last_idx]
            ellip_pos = last_seg.rfind(ELLIP)
            if ellip_pos != -1:
                right_start = ellip_pos + len(ELLIP)
                if filename and '.' in last_seg:
                    dot_pos = last_seg.rfind('.')
                    ext = last_seg[dot_pos:]
                    right_end = len(last_seg) - len(ext)
                    right = last_seg[right_start: right_end]
                    new_right_len = max(0, len(right) - excess)
                    new_last = last_seg[:right_start] + right[:new_right_len] + ext
                else:
                    # folder or no ext
                    ext = ''
                    right_end = len(last_seg)
                    right = last_seg[right_start: right_end]
                    new_right_len = max(0, len(right) - excess)
                    new_last = last_seg[:right_start] + right[:new_right_len] + ext
                display_parts[last_idx] = new_last
                candidate = make_candidate()
        if len(candidate) > max_len:
            # Final fallback: keep anchor + '...' + last segment
            last = _ellipsize_filename(original_last, max(4, seg_left),
                                       max(2, seg_right)) if filename else _ellipsize_segment(original_last,
                                                                                              max(4, seg_left),
                                                                                              max(2, seg_right))
            fallback_parts = [ELLIP, last]
            if anchor and anchor.startswith('\\\\'):
                # Ellipsize UNC components
                server_start = 2
                server_end = anchor.find('\\', server_start)
                if server_end != -1:
                    server = anchor[server_start:server_end]
                    share_start = server_end + 1
                    share_end = anchor.find('\\', share_start)
                    if share_end != -1:
                        share = anchor[share_start:share_end]
                    else:
                        share = anchor[share_start:]
                    server_ellip = _ellipsize_segment(server, 3, 3)
                    share_ellip = _ellipsize_segment(share, 3, 3)
                    anchor_ellip = '\\\\' + server_ellip + '\\' + share_ellip
                    joined = sep.join(fallback_parts)
                    candidate = anchor_ellip.rstrip(sep) + sep + joined
                else:
                    candidate = _make_candidate(fallback_parts, anchor, sep, is_root_anchor)
            else:
                candidate = _make_candidate(fallback_parts, anchor, sep, is_root_anchor)

    return candidate
