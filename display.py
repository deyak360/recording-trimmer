# display.py
"""
Utility functions for formatting and displaying information, including path truncation, colored messages, and structured reports.
"""

import os
import platform
import tempfile
import logging
from dataclasses import dataclass
from typing import Literal, overload, Optional, Tuple

from c_io import get_executable_path, ensure_executable
from utils import seconds_to_hms, truncate_path

logger = logging.getLogger('recording-trimmer')


def create_shortcut(target_path: str, arguments: str, shortcut_name: str, shortcut_dir: str) -> str:
    """Create a Windows shortcut using VBScript in a temporary folder.The shortcut will run spek.exe with the .m4a file as an argument.
    This is a hacky workaround, since file:// URLs don't accept arguments and won't start spek, and setting spek.exe as the default program isn't feasible."""
    # Ensure the shortcut directory exists
    if not os.path.exists(shortcut_dir):
        os.makedirs(shortcut_dir)

    # Path for the shortcut (.lnk file)
    shortcut_path = os.path.join(shortcut_dir, f"{shortcut_name}.lnk")

    # Normalize paths for VBScript (replace backslashes with double backslashes)
    target_path = target_path.replace("\\", "\\\\")
    shortcut_path2 = shortcut_path.replace("\\", "\\\\")
    working_dir = os.path.dirname(target_path).replace("\\", "\\\\")
    # Quote the arguments explicitly for VBScript
    quoted_arguments = f'"""{arguments.replace("\\", "\\\\")}"""'

    # Using VBScript as it allows natively creating shortcut on windows without external libs.
    # VBScript code to create the shortcut
    vbscript = f"""
Set WShell = CreateObject("WScript.Shell")
Set Shortcut = WShell.CreateShortcut("{shortcut_path2}")
Shortcut.TargetPath = "{target_path}"
Shortcut.Arguments = {quoted_arguments}
Shortcut.WorkingDirectory = "{working_dir}"
Shortcut.WindowStyle = 3
Shortcut.Description = "Shortcut to {shortcut_name}"
Shortcut.Save
"""

    # Write VBScript to a temporary file
    vbscript_path = os.path.join(tempfile.gettempdir(), "temp_shortcut.vbs")
    try:
        with open(vbscript_path, "w") as f:
            f.write(vbscript)

        # Execute the VBScript using Windows' built-in cscript
        os.system(f'cscript //NoLogo "{vbscript_path}"')
        logger.debug(f"Shortcut created/overwritten at: {shortcut_path}")
    except Exception as e:
        logger.debug(f"Failed to create shortcut: {e}", extra={'frmt_type': 'error', 'prefix': '[DEBUG] '}) #log on debug level, but format as error
    finally:
        # Clean up the temporary VBScript file
        if os.path.exists(vbscript_path):
            os.remove(vbscript_path)

    return shortcut_path


@dataclass
class Link:
    text: str #text can be ""
    icon: Optional[str] = None
    url: Optional[str] = None

    def __str__(self) -> str:
        if self.icon is None or self.url is None:
            return self.text

        # OSC 8 escape sequence
        padding = "" if self.text == "" else " "
        link_str = f"\033]8;;{self.url.rstrip()}\033\\{self.icon}{padding}{self.text}\033]8;;\033\\"
        logger.debug(repr(link_str))
        return link_str

@overload
def build_clickable_link(
        file: str,
        link_type: Literal['file', 'folder'] = 'file',
        *,
        display_text: str = None,
) -> str: ...

@overload
def build_clickable_link(
        file: str,
        link_type: Literal['spectrogram'],
        *,
        display_text: str = None,
        spectrogram_supported: bool,
        reuse_shortcut: bool = False,
) -> str: ...

def build_clickable_link(
        file: str,
        link_type: str = 'file',
        *,
        display_text: str = None,
        # --- below relevant only for spectrogram link_type ---
        spectrogram_supported: bool = False,
        reuse_shortcut: bool = False,
) -> str:
    """Create a clickable file link for terminals that support OSC 8: link_type: 'file', 'folder', or 'spectrogram'"""

    link = Link(text=display_text if display_text is not None else f"{truncate_path(file)}") #text can be ""
    abs_path = os.path.abspath(file)

    if link_type == 'file':
        link.icon = '📄'
        link.url = f'file://{abs_path}'

    elif link_type == 'folder':
        link.icon = '📁'

        # Check if the path is a directory
        if os.path.isdir(abs_path):
            link.url = f'file://{abs_path}'  # Use the directory itself

        # elif platform.system() == 'Windows':
        #     # Create a shortcut to run explorer.exe with /select to highlight the file
        #     shortcut_name = f"Select_{os.path.basename(file).replace('.m4a', '')}"
        #     shortcut_dir = tempfile.gettempdir()
        #
        #     shortcut_path = create_shortcut(
        #         target_path="explorer.exe",
        #         arguments=f'/select,"{abs_path}"',
        #         shortcut_name=shortcut_name,
        #         shortcut_dir=shortcut_dir  # Use Windows TEMP folder
        #     )

        else:
            link.url = f'file://{os.path.dirname(abs_path)}'  # Use parent directory

    elif link_type == 'spectrogram' and spectrogram_supported:
        link.icon = '📊'

        # Create shortcut and make url point to it
        success, spek_path = get_executable_path('spek')
        if success:
            shortcut_name = f"Spek_{os.path.basename(file)}"
            shortcut_dir = tempfile.gettempdir()
            shortcut_path = (
                os.path.join(shortcut_dir, f"{shortcut_name}.lnk") if reuse_shortcut
                else create_shortcut(
                    target_path=spek_path, arguments=abs_path,
                    shortcut_name=shortcut_name, shortcut_dir=shortcut_dir
                )
            )
            link.url = f'file://{shortcut_path}'

    return str(link)



def _spectrogram_viewing_support() -> Tuple[bool, Optional[str]]:
    """Check if spectrogram viewing is supported and return None or info message."""
    if platform.system() != 'Windows': #spectrogram shortcut integration is only implemented on Windows
        return False, f"Spectrogram viewing not supported on {platform.system()}"

    try:
        ensure_executable('spek')
    except FileNotFoundError as e:
        return False, f"Spectrogram viewing not available, {e}"

    return True, None

def print_reports(all_files: list[dict], trim_offset: bool):
    # Check if spectrogram viewing is possible
    is_spectro_supported, spectro_msg = _spectrogram_viewing_support()
    if not is_spectro_supported:
        logger.light(spectro_msg, extra={'frmt_type': 'custom1'})

    # All-files report
    logger.light(f"\nProcessed {len(all_files)} files (file, loudness spike time, notes):",
                 extra={'frmt_type': 'custom2'})
    for item in all_files:
        file, detect_time, trim_note = item['file'], item['detect_time'], item['trim_note']

        clickable_in_links = (
            f"{build_clickable_link(file, link_type='folder', display_text='')} "
            f"{build_clickable_link(file, link_type='spectrogram', display_text='', spectrogram_supported=is_spectro_supported)} "
            f"{build_clickable_link(file)}"
        )
        content = "-/-" if detect_time is None else f"Detected at {detect_time}"
        note = trim_note if trim_note else item['error_note']
        note_suffix = f"*{note}" if note else ""

        logger.light(f"{clickable_in_links} [{item['duration']}]: {content} {note_suffix}")

    # Candidates report
    logger.light(f"\n\nCandidates for trimming:", extra={'frmt_type': 'custom2'})
    candidate_count = 0
    for item in (f for f in all_files if f['detect_time'] is not None and f['error_note'] is None):
        candidate_count += 1

        file, output_path, trim_note = item['file'], item['new_path'], item['trim_note']

        clickable_in_links = (
            f"{build_clickable_link(file, link_type='folder', display_text='')} "
            f"{build_clickable_link(file, link_type='spectrogram', display_text='', spectrogram_supported=is_spectro_supported, reuse_shortcut=True)} "
            f"{build_clickable_link(file)}"
        )
        clickable_out_links = "" if output_path is None else (
            f"\t\t {build_clickable_link(output_path, link_type='folder', display_text='FOLDER')} "
            f"{build_clickable_link(output_path, link_type='spectrogram', display_text='SPECTROGRAM', spectrogram_supported=is_spectro_supported)} "
            f"{build_clickable_link(output_path)}"
        )

        trim_trimmed = "Trimmed" if trim_note is None else "Trim"
        trim_offset_sign = "+" if trim_offset > 0 else ""
        prefix = f"Detected/{trim_trimmed} at" if (trim_offset == 0 and trim_note is None) else "Detected at"
        trim_info = "" if trim_offset is None or trim_offset == 0 else f" | {trim_trimmed} at ({trim_offset_sign}{trim_offset}s): {seconds_to_hms(item['adjusted_trim_time'])}"

        logger.light(
            f"{clickable_in_links} [{item['duration']}]: {prefix} {item['detect_time']}{trim_info}{clickable_out_links}")

    logger.light(f"\nFound {candidate_count} candidates.", extra={'frmt_type': 'custom3'})
    if candidate_count == 0:
        logger.light(f"For better detection, try tuning analysis parameters (see more --help)", extra={'frmt_type': 'custom3'})
