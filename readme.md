# 🎙️Recording Trimmer ![Python](https://img.shields.io/badge/Python-3.6%2B-orange) ![License](https://img.shields.io/badge/License-MIT-green) 
A smart batch processor for lecture/meeting/speech recordings (.m4a) that automatically detects the loud “end noise” (applause, shuffling, packing, etc.) and trims everything after it — potentially saving gigabytes of space with zero quality loss.

It works amazingly well on typical university lecture recordings where the actual content ends but the recording keeps running for minutes of loud post-lecture noise.

## Quick Start: Why Use This?
You record a 2-hour lecture → file is 200–400 MB. The lecture actually ended at 1h 38m, the last 22 minutes are just chair shuffling, clapping, and people chatting. Manually finding the exact end and trimming tens/hundreds of files is tedious and time-consuming.

This script finds that loud spike quickly, trims losslessly (stream copy), and optionally opens the spectrogram so you can verify with your own eyes.

## Features
- Fully automatic detection of the “loud end noise” spike using EBU R128 loudness analysis
- Three tuned profiles for short (<30 min), medium (30–90 min), and long (≥90 min) recordings — works well out of the box
- Lossless trimming (`-c copy`) — no re-encoding, keeps original quality and metadata
- Customizable trim offset (`-t +5` or `-t -3`) to keep/tweak a few seconds
- Highly configurable parameters: loudness thresholds, window sizes, confirmation intervals, skip times, and more
- Conflict handling: overwrite / rename / fail
- Beautiful color-coded, structured logging with light/standard/verbose levels
- Clickable file/folder/spectrogram links in supported terminals — click the 📊 icon and visually confirm where the spike is on the spectrogram

## Installation
This is primarily a Windows utility (tested on Windows 10+), but core analysis/trimming should work on other OSes. Requires Python 3.6+, FFmpeg, and FFprobe. Spek is highly recommended for spectrogram viewing but optional.

### Step 1: Install Dependencies
#### 1. Get Python (if you don't have it)
- Windows: https://www.python.org/downloads/ (get 3.6+)
- macOS/Linux: you almost certainly already have it. Verify with `python --version`.
#### 2. Download FFmpeg + FFprobe (essential for analysis and trimming)
https://www.gyan.dev/ffmpeg/builds/ → Download `ffmpeg-release-essentials.zip`  
Extract `ffmpeg.exe` and `ffprobe.exe` and put them in the same folder as the scripts or in your system PATH.

#### 3. Get Spek for spectrogram viewing (highly recommended) 
https://www.spek.cc/p/download → Download `spek-X.Y.Z.zip`  
Extract `spek.exe` and put it in the same folder as the scripts or in your system PATH.

If spek.exe is detected, the script will create clickable 📊 links that instantly open the file in Spek so you can visually confirm loudness spikes.

### Step 2: Download the Scripts
Download as ZIP and extract scripts to `recording_trimmer/`

## Usage
0. Download and install the dependencies as above.
1. Prepare your M4A files in a folder.
2. Open a terminal in the folder that contains `recording_trimmer/`.
3. Run the script with desired parameters (see below).
4. Review the console report: It lists all files, detection times, and trim results with clickable links (on supported terminals).
5. If auto-trim is enabled (`-t`), trimmed files are saved to the output directory (default: same as input).

#### Example Commands
```bash
# Basic: process current folder, show what it would do (dry run because no -t)
py recording_trimmer 

# Keep 5 seconds after detected spike
py recording_trimmer -t +5

# Recursive, output to "Trimmed" subfolder, name with suffix, rename on conflict
py recording_trimmer -t +5 -ir -o Trimmed --naming-scheme "{ORIGINAL}_Trimmed" --on-conflict rename 
```
For all parameters: `py recording_trimmer -h`

#### Example Output
```bash
📁 📊 📄 .\Recordings\Rec1.m4a [01:18:28.989]: Detected/Trimmed at 01:13:51.199          📁 FOLDER 📊 SPECTROGRAM 📄 trimmed\Rec1_trimmed.m4a
```
Clicking the icons opens:
- 📁 → Explorer at the file
- 📊 → The file in Spek
- 📄 → The file for listening

### Advanced Tuning
Internally, the script scans EBU R128 momentary loudness and looks for a sustained increase above the pre-lecture baseline by the configured threshold. The script ships with three configurable profiles:

| Profile | Duration range | Loudness threshold | Window | Confirmation seconds | Skip start |
|--------|----------------|-------------------|--------|-------------------|-----------|
| Short  | < 30 min      | 12 dB           | 3 s   | 3, 6 s           | 1 min    |
| Medium | 30–90 min      | 11 dB           | 5 s   | 4, 8 s           | 5 min    |
| Long   | ≥ 90 min      | 10 dB           | 7 s   | 5, 10, 25 s       | 30 min   |


#### Advanced usage examples:
```bash
# Process a specific subfolder non-recursively, trim only if we save at least 2 minutes, keep 10 seconds buffer, skip tiny files (<10 min)
py recording_trimmer -i 'Meetings (October)' -o 'Recordings (Archive)' --trim-min-seg-dur 120 --trim-min-file-dur 600 -t +10

# For LongFiles, increase loudness threshold to 15dB, use 10s window size, confirm at 6/12/30s, analyze first 45min for baseline.
py recording_trimmer --long-loud-thresh-db 15 --long-win-size-sec 10 --long-confirm-secs 6,12,30 --long-analysis-mins 45 --on-conflict overwrite -t

# For in-depth analysis and debugging
py recording_trimmer -i . -l debug --log-dir ./debug_logs --ffmpeg-logging-level info 
```

## Risks and Warnings 
This script reads audio metadata but writes trimmed files, similar to audio editing tools. **Potential Data Loss/Damage:**
- Trimming creates new files; originals are untouched. However, if output dir is the same and `--on-conflict overwrite` is set, it could replace files.
- False detections might trim content—review trimmed files before deleting sources.
Use at your own risk; not liable for data loss/damage. Backup recordings before batch-trimming.

## Troubleshooting and Issue Reporting 
Common issues:
- "FFmpeg not found": Add to PATH or place in script dir.
- No detection: Adjust thresholds (e.g., lower `-slt`, `-mlt`, `-llt` for quiet spikes). Check logs for detection details.
- Links not clickable: Ctrl+Click them (or Cmd+Click on macOS). Terminal may not support OSC 8, use a modern terminal like Windows Terminal.
- Permission errors: Run as admin.

**Reporting Issues:** Open an issue on this repo with details. Use this template:
```
### Issue Description
[Briefly describe the problem, e.g., "No spike detected on file X despite noise."]
### Steps to Reproduce
1. [Step 1]
2. [Step 2]
...
### Expected Behavior
[What should happen?]
### Actual Behavior
[What happened instead?]
### Environment
- OS: [e.g., Windows 11]
- Python Version: [Run `python --version`]
- FFmpeg Version: [Run `ffmpeg -version`]
- Script Args: [e.g., -i folder -t 20]
### Log Output
[Attach --log-dir file or paste relevant lines from console.]
### Screenshots (if applicable)
[Add images of output or spectrograms.]
### Additional Context
[Any other info, e.g., file media-info or sample file...]
```

## Final Notes 
- **Security**: Python scripts are readable—review before use. No external calls beyond FFmpeg, FFprobe, and cscript (for shortcut creation on Windows).
- **License**: MIT—free to use, modify, and share.
- **Credits**: Built with Python and FFmpeg; inspired by audio archiving needs.

If searching for tools like this, terms such as — audio trimmer script, end noise trimmer, ffmpeg loudness analyzer, voice note jump detector, batch audio cleaner, speech memo clipper, lecture recording optimizer, loud end cutter, spike detection trim, auto trim recordings, loudness-based trim, meeting audio trimmer, m4a file size reducer — might help.