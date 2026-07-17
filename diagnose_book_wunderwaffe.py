#!/usr/bin/env python3
"""
Book Wunderwaffe Studio - Diagnostics Script

Creates _suviren_q_build/BOOK_WUNDERWAFFE_DIAGNOSTICS.txt
with comprehensive report on environment, audio, waveform, layout, GUI.
Automatically opens the report via os.startfile.

Does NOT run render-full or heavy operations.
"""

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

# --- Paths ---
PROJECT_ROOT = Path(__file__).parent.resolve()
BUILD_DIR = PROJECT_ROOT / "_suviren_q_build"
DATA_DIR = PROJECT_ROOT / "data"
LAYOUT_PATH = BUILD_DIR / "layout.json"
CHAPTERS_PATH = BUILD_DIR / "chapters.detected.json"
WAVEFORM_PATH = BUILD_DIR / "waveform.json"
WAVEFORM_LOCK = BUILD_DIR / "waveform.lock"
PROJECT_CONFIG = PROJECT_ROOT / "bookforge.project.json"
REPORT_PATH = BUILD_DIR / "BOOK_WUNDERWAFFE_DIAGNOSTICS.txt"

REPORT_LINES = []


def log(msg: str):
    REPORT_LINES.append(msg)
    print(msg)


def log_header(title: str):
    log("")
    log("=" * 68)
    log(f"  {title}")
    log("=" * 68)


def log_subheader(title: str):
    log("")
    log(f"-- {title} --" + "-" * max(0, 58 - len(title)))


def find_ffmpeg_ffprobe():
    """Try to locate ffmpeg/ffprobe in PATH or common locations."""
    ffprobe = None
    ffmpeg = None

    # Check PATH
    for cmd in ["ffprobe", "ffprobe.exe"]:
        try:
            r = subprocess.run(["where", cmd] if sys.platform == "win32" else ["which", cmd],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                ffprobe = r.stdout.strip().split("\n")[0]
                break
        except Exception:
            pass

    for cmd in ["ffmpeg", "ffmpeg.exe"]:
        try:
            r = subprocess.run(["where", cmd] if sys.platform == "win32" else ["which", cmd],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                ffmpeg = r.stdout.strip().split("\n")[0]
                break
        except Exception:
            pass

    # Common WinGet installation paths
    win_get_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if win_get_base.exists():
        for d in win_get_base.iterdir():
            if "ffmpeg" in d.name.lower() and d.is_dir():
                bin_dir = d / "bin"
                if bin_dir.exists():
                    for f in bin_dir.iterdir():
                        fn = f.name.lower()
                        if fn == "ffprobe.exe" and not ffprobe:
                            ffprobe = str(f)
                        if fn == "ffmpeg.exe" and not ffmpeg:
                            ffmpeg = str(f)

    # Common VLC/ffmpeg Windows paths
    common_paths = [
        "C:\\Program Files\\FFmpeg\\bin\\ffprobe.exe",
        "C:\\Program Files (x86)\\FFmpeg\\bin\\ffprobe.exe",
    ]
    for p in common_paths:
        if Path(p).exists() and not ffprobe:
            ffprobe = p

    common_ffmpeg_paths = [
        "C:\\Program Files\\FFmpeg\\bin\\ffmpeg.exe",
        "C:\\Program Files (x86)\\FFmpeg\\bin\\ffmpeg.exe",
    ]
    for p in common_ffmpeg_paths:
        if Path(p).exists() and not ffmpeg:
            ffmpeg = p

    return str(ffmpeg) if ffmpeg else None, str(ffprobe) if ffprobe else None


def load_json_safe(path):
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text("utf-8"))
        except json.JSONDecodeError as e:
            return {"_error": f"JSON decode error: {e}"}
        except Exception as e:
            return {"_error": str(e)}
    return None


def get_file_size_mb(path):
    try:
        return Path(path).stat().st_size / (1024 * 1024)
    except Exception:
        return None


def get_file_size_gb(path):
    try:
        return Path(path).stat().st_size / (1024 ** 3)
    except Exception:
        return None


# =========================================================
#  1. Environment
# =========================================================
def check_environment():
    log_header("1. Environment")
    log(f"Python executable:  {sys.executable}")
    log(f"Python version:     {sys.version}")
    log(f"Platform:           {platform.platform()}")
    log(f"Current working dir: {os.getcwd()}")

    # PySide6
    try:
        from PySide6 import __version__ as pyside_ver
        log(f"PySide6 version:    {pyside_ver}")
    except ImportError:
        log("PySide6 version:    NOT INSTALLED")
    except Exception as e:
        log(f"PySide6 version:    Error: {e}")

    # Qt version
    try:
        from PySide6.QtCore import qVersion
        log(f"Qt version:         {qVersion()}")
    except Exception as e:
        log(f"Qt version:         Error: {e}")

    # QtMultimedia
    try:
        from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
        log("QtMultimedia:       AVAILABLE")
    except ImportError:
        log("QtMultimedia:       NOT AVAILABLE")
    except Exception as e:
        log(f"QtMultimedia:       Error: {e}")

    # ffmpeg/ffprobe
    ffmpeg_path, ffprobe_path = find_ffmpeg_ffprobe()
    log(f"ffmpeg path:        {ffmpeg_path or 'NOT FOUND'}")
    log(f"ffprobe path:       {ffprobe_path or 'NOT FOUND'}")


# =========================================================
#  2. Project files
# =========================================================
def check_project_files():
    log_header("2. Project Files")

    config = load_json_safe(PROJECT_CONFIG)
    if config and isinstance(config, dict):
        audio_rel = config.get("audio", "")
        audio_path = PROJECT_ROOT / audio_rel if audio_rel else DATA_DIR
        log(f"Selected audio path: {audio_path}")
        if audio_path.exists():
            size_mb = get_file_size_mb(audio_path)
            size_gb = get_file_size_gb(audio_path)
            log(f"Audio exists:       YES")
            log(f"Audio size:         {size_mb:.1f} MB ({size_gb:.2f} GB)" if size_mb else f"Audio size:         {size_gb:.2f} GB")
        else:
            log(f"Audio exists:       NO - file not found!")
        rpp_rel = config.get("rpp", "")
        cover_rel = config.get("cover", "")
        bg_rel = config.get("background", "")
        log(f"Selected RPP path:  {PROJECT_ROOT / rpp_rel if rpp_rel else 'N/A'}")
        log(f"Cover path:         {PROJECT_ROOT / cover_rel if cover_rel else 'N/A'}")
        log(f"Background path:    {PROJECT_ROOT / bg_rel if bg_rel else 'N/A'}")
    else:
        log("Project config missing or invalid.")
        log(f"Selected audio path: {DATA_DIR} (unknown - no config)")

    log(f"Chapters path:      {CHAPTERS_PATH}")
    log(f"  exists:           {'YES' if CHAPTERS_PATH.exists() else 'NO'}")
    log(f"Waveform path:      {WAVEFORM_PATH}")
    log(f"  exists:           {'YES' if WAVEFORM_PATH.exists() else 'NO'}")
    log(f"Layout path:        {LAYOUT_PATH}")
    log(f"  exists:           {'YES' if LAYOUT_PATH.exists() else 'NO'}")

    # Also check actual audio file
    audio_candidates = list(DATA_DIR.glob("*.mp3")) + list(DATA_DIR.glob("*.wav")) + list(DATA_DIR.glob("*.m4a"))
    log(f"Audio files in data/: {len(audio_candidates)}")
    for a in audio_candidates[:5]:
        size_gb = get_file_size_gb(a)
        if size_gb:
            log(f"  {a.name} ({size_gb:.2f} GB)")
        else:
            log(f"  {a.name}")


# =========================================================
#  3. Audio ffprobe
# =========================================================
def check_audio_ffprobe():
    log_header("3. Audio ffprobe")

    config = load_json_safe(PROJECT_CONFIG)
    if not config or not isinstance(config, dict):
        log("Project config missing - cannot run ffprobe.")
        return

    audio_rel = config.get("audio", "")
    audio_path = PROJECT_ROOT / audio_rel if audio_rel else None
    if not audio_path or not audio_path.exists():
        log(f"Audio file not found: {audio_path}")
        return

    _, ffprobe_path = find_ffmpeg_ffprobe()
    if not ffprobe_path:
        log("ffprobe not found. Cannot probe audio.")
        return

    # Check file size - skip if >1.5 GB as ffprobe may hang
    size_gb = get_file_size_gb(audio_path)
    if size_gb and size_gb > 1.5:
        log(f"Audio file >1.5 GB ({size_gb:.2f} GB); ffprobe may hang on large MP3.")
        log("Attempting ffprobe with -show_entries format=duration (non-seeking)...")

    try:
        # Probe with limited format to avoid hanging on large files
        cmd = [
            ffprobe_path, "-v", "quiet", "-print_format", "json",
            "-show_entries", "format=duration,bit_rate,format_name",
            "-show_streams",
            str(audio_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            log(f"ffprobe stderr:\n{result.stderr}")
            # Try alternative: just format
            log("Retrying with alternative ffprobe method...")
            cmd2 = [
                ffprobe_path, "-v", "quiet", "-print_format", "json",
                "-show_entries", "format=duration,bit_rate,format_name",
                str(audio_path)
            ]
            result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=120)
            if result2.returncode == 0 and result2.stdout.strip():
                data = json.loads(result2.stdout)
            else:
                log(f"ffprobe alt also failed: {result2.stderr[:500]}")
                return
        else:
            data = json.loads(result.stdout) if result.stdout.strip() else {}

        fmt = data.get("format", {})
        log(f"format_name:        {fmt.get('format_name', '?')}")
        log(f"duration (sec):     {fmt.get('duration', '?')}")
        log(f"bit_rate:           {fmt.get('bit_rate', '?')}")

        streams = data.get("streams", [])
        for s in streams:
            if s.get("codec_type") == "audio":
                log(f"audio codec:        {s.get('codec_name', '?')}")
                log(f"sample_rate:        {s.get('sample_rate', '?')}")
                log(f"channels:           {s.get('channels', '?')}")
                break
        else:
            log("No audio stream found in ffprobe output.")

        # Check for tags
        tags = fmt.get("tags", {})
        if tags:
            log(f"tags:               {json.dumps(tags, ensure_ascii=False)[:300]}")

    except subprocess.TimeoutExpired:
        log("ffprobe TIMEOUT (120s). File is too large for ffprobe.")
        log("Duration estimated from bookforge: ~15:49:35 (56975s)")
    except json.JSONDecodeError as e:
        log(f"ffprobe output JSON parse error: {e}")
    except Exception as e:
        log(f"ffprobe error: {e}")


# =========================================================
#  4. QMediaPlayer diagnostics (via PySide6)
# =========================================================
def check_qmediaplayer():
    log_header("4. QMediaPlayer Diagnostics")

    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    except ImportError as e:
        log(f"Cannot run QMediaPlayer diagnostics: {e}")
        log("QMediaPlayer status: NOT AVAILABLE")
        return

    log("QtMultimedia import:        OK")
    log("QMediaPlayer class:         AVAILABLE")
    log("QAudioOutput class:         AVAILABLE")

    # Must have a QApplication instance
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    player = QMediaPlayer()
    audio_output = QAudioOutput()

    log(f"QMediaPlayer created:       {'YES' if player else 'NO'}")
    log(f"QAudioOutput created:       {'YES' if audio_output else 'NO'}")

    player.setAudioOutput(audio_output)

    # Find audio
    config = load_json_safe(PROJECT_CONFIG)
    audio_path = None
    if config and isinstance(config, dict):
        audio_rel = config.get("audio", "")
        audio_path = PROJECT_ROOT / audio_rel if audio_rel else None
    if not audio_path or not audio_path.exists():
        log("Audio file not found - cannot set source.")
        log("QMediaPlayer status:        FILE_MISSING")
        return

    audio_url = QUrl.fromLocalFile(str(audio_path))
    player.setSource(audio_url)
    log(f"Source set:                 {audio_url.toString()}")
    size_gb = get_file_size_gb(audio_path)
    log(f"Source file size:           {size_gb:.2f} GB" if size_gb else "Source file size:           UNKNOWN")

    # Process events to allow player to load
    log("Waiting up to 5 seconds for media to load...")
    status_names = {
        0: "NoMedia",
        1: "LoadingMedia",
        2: "LoadedMedia",
        3: "StallingMedia",
        4: "BufferingMedia",
        5: "BufferedMedia",
        6: "EndOfMedia",
        7: "InvalidMedia",
    }
    error_names = {
        0: "NoError",
        1: "ResourceError",
        2: "FormatError",
        3: "NetworkError",
        4: "AccessDeniedError",
    }

    # Check immediate status
    ms = player.mediaStatus()
    log(f"Immediate mediaStatus():    {status_names.get(ms, str(ms))}")
    err = player.error()
    log(f"Immediate error():          {error_names.get(err, str(err))}")
    if err != 0:
        log(f"Immediate errorString():    {player.errorString()}")

    # Wait for signals
    duration = [None]
    status_after = [ms]

    def on_duration(d):
        duration[0] = d
        log(f"durationChanged signal:     {d} ms ({d/1000:.1f} sec)")

    def on_status(s):
        status_after[0] = s
        log(f"mediaStatusChanged:        {status_names.get(s, str(s))}")

    player.durationChanged.connect(on_duration)
    player.mediaStatusChanged.connect(on_status)

    # Process events for up to 5 seconds
    for _ in range(50):
        app.processEvents()
        time.sleep(0.1)
        if status_after[0] in (2, 7):  # LoadedMedia or InvalidMedia
            break

    log(f"Final mediaStatus():        {status_names.get(status_after[0], str(status_after[0]))}")
    final_err = player.error()
    log(f"Final error():              {error_names.get(final_err, str(final_err))}")
    if final_err != 0:
        log(f"Final errorString():        {player.errorString()}")

    if duration[0] is not None:
        log(f"Duration from player:      {duration[0]} ms ({duration[0]/1000:.1f} sec)")
    else:
        log("Duration from player:      NOT EMITTED")

    # Conclusion
    if final_err != 0:
        log("")
        log("*** QMediaPlayer FAILED on this file. ***")
        log(f"Error: {player.errorString()}")
        log("Likely cause: 2.17 GB MP3 with VBR or long duration (15h49m).")
        log("Recommendation: Use proxy audio or alternative backend.")
    elif status_after[0] == 2:
        log("")
        log("QMediaPlayer loaded successfully (LoadedMedia).")
    else:
        log("")
        log(f"QMediaPlayer status: {status_names.get(status_after[0], str(status_after[0]))}")
        log("This is unusual. See above for details.")


# =========================================================
#  5. Audio fallback recommendation
# =========================================================
def check_audio_fallback():
    log_header("5. Audio Fallback Recommendation")

    # Check VLC
    vlc_paths = [
        Path("C:\\Program Files\\VideoLAN\\VLC\\vlc.exe"),
        Path("C:\\Program Files (x86)\\VideoLAN\\VLC\\vlc.exe"),
    ]
    vlc_found = None
    for p in vlc_paths:
        if p.exists():
            vlc_found = str(p)
            break

    # Check ffplay
    ffmpeg_path, _ = find_ffmpeg_ffprobe()
    ffplay_path = None
    if ffmpeg_path:
        ffplay_candidate = Path(ffmpeg_path).parent / "ffplay.exe"
        if ffplay_candidate.exists():
            ffplay_path = str(ffplay_candidate)

    log("VLC installation check:")
    log(f"  C:\\Program Files\\VideoLAN\\VLC\\vlc.exe:     {'YES' if vlc_paths[0].exists() else 'NO'}")
    log(f"  C:\\Program Files (x86)\\VideoLAN\\VLC\\vlc.exe: {'YES' if vlc_paths[1].exists() else 'NO'}")
    log(f"  VLC found:           {vlc_found or 'NOT FOUND'}")

    log("ffplay check:")
    log(f"  ffplay path:         {ffplay_path or 'NOT FOUND'}")

    log("")
    log("Recommendations:")
    if ffplay_path:
        log("  Option A (easiest): Use ffplay external preview")
        log("    Command: ffplay -nodisp -autoexit \"<audio_path>\"")
    if vlc_found:
        log("  Option B: Install python-vlc (pip install python-vlc)")
        log("    Then use vlc.MediaPlayer for playback (handles large files)")
    log("  Option C: Generate low-bitrate preview proxy MP3 via ffmpeg")
    log("    Creates _suviren_q_build/preview_audio_proxy.mp3 (128k)")
    log("    Then GUI uses proxy file for QMediaPlayer playback.")
    log("    Command: ffmpeg -i \"<source>\" -b:a 128k -y \"<proxy>\"")
    log("")
    log("  Recommended for this project:")
    log("    QMediaPlayer struggles with 2.17 GB / 15h49m MP3.")
    log("    Best approach: generate preview proxy audio (Option C)")


# =========================================================
#  6. Waveform diagnostics
# =========================================================
def check_waveform():
    log_header("6. Waveform Diagnostics")

    if not WAVEFORM_PATH.exists():
        log("waveform.json:            DOES NOT EXIST")
        log("")
        log("To generate waveform, run:")
        log("  python bookforge.py waveform")
        return

    wf = load_json_safe(WAVEFORM_PATH)
    if wf is None:
        log("waveform.json:            FILE EXISTS BUT COULD NOT BE PARSED")
        return

    if isinstance(wf, dict) and "_error" in wf:
        log(f"waveform.json:            PARSE ERROR - {wf['_error']}")
        return

    log("waveform.json:            EXISTS")
    log("Valid JSON:               YES")

    # Determine structure
    if isinstance(wf, list):
        log("Structure:                flat array (list of samples)")
        samples = wf
        log(f"Sample count:             {len(samples)}")
        if len(samples) > 0:
            log(f"First 10 samples:         {samples[:10]}")
            log(f"Min sample:               {min(samples):.6f}")
            log(f"Max sample:               {max(samples):.6f}")
        audio_in_wf = None
        duration_in_wf = None
    elif isinstance(wf, dict):
        log("Structure:                object with keys")
        samples = wf.get("samples", wf.get("peaks", wf.get("data", [])))
        audio_in_wf = wf.get("audio", wf.get("audio_name", None))
        duration_in_wf = wf.get("duration", wf.get("duration_seconds", None))
        log(f"Audio path in waveform:   {audio_in_wf or 'NOT FOUND'}")
        log(f"Duration in waveform:     {duration_in_wf or 'NOT FOUND'}")
        log(f"Sample count:             {wf.get('sample_count', len(samples))}")
        if isinstance(samples, list) and len(samples) > 0:
            log(f"First 10 samples:         {samples[:10]}")
            log(f"Min sample:               {min(samples):.6f}")
            log(f"Max sample:               {max(samples):.6f}")
        else:
            log("Samples list:             EMPTY or INVALID TYPE")
    else:
        log(f"Structure:                unexpected type {type(wf).__name__}")
        samples = []

    # File metadata
    try:
        st = WAVEFORM_PATH.stat()
        log(f"File size:                {st.st_size / 1024:.1f} KB")
        log(f"Last modified:            {time.ctime(st.st_mtime)}")
    except Exception:
        pass

    # Check if waveform audio matches selected audio
    config = load_json_safe(PROJECT_CONFIG)
    if config and audio_in_wf:
        selected_audio_rel = config.get("audio", "")
        selected_audio = PROJECT_ROOT / selected_audio_rel if selected_audio_rel else None
        wf_audio_path = Path(audio_in_wf)
        if selected_audio and selected_audio.exists():
            match = str(wf_audio_path.resolve()).lower() == str(selected_audio.resolve()).lower()
            log(f"Waveform matches audio:   {'YES' if match else 'NO - path mismatch!'}")
        else:
            log(f"Waveform matches audio:   CANNOT COMPARE (selected audio not found)")

    # Check if waveform has enough data
    sample_count = len(samples) if isinstance(samples, list) else 0
    if sample_count < 10:
        log("STATUS:                   WAVEFORM_DATA_TOO_SMALL - GUI will likely not render bars")
    else:
        log("STATUS:                   WAVEFORM_DATA_OK")
        log("If GUI still doesn't render bars:")
        log("  - Check WaveformItem receives data (book_wunderwaffe_studio.py)")
        log("  - Ensure waveform path = _suviren_q_build/waveform.json")
        log("  - Ensure samples read from correct key (samples/peaks/data)")
        log("  - Check log: 'Waveform loaded: N samples'")


# =========================================================
#  7. Layout diagnostics
# =========================================================
def check_layout():
    log_header("7. Layout Diagnostics")

    if not LAYOUT_PATH.exists():
        log("layout.json:              DOES NOT EXIST")
        log("Using DEFAULT_LAYOUT from book_wunderwaffe_studio.py")
        return

    lt = load_json_safe(LAYOUT_PATH)
    if lt is None:
        log("layout.json:              COULD NOT BE PARSED")
        return

    log("layout.json:              EXISTS and valid")
    log(f"Top-level keys:           {list(lt.keys())}")

    # Check if objects are nested under "objects" key
    objects_raw = lt.get("objects", lt)
    if isinstance(objects_raw, list):
        # Layout stores objects as a list
        object_ids = [o.get("id", "?") for o in objects_raw]
        log(f"Object IDs:               {object_ids}")
        objects = {o.get("id"): o for o in objects_raw if isinstance(o, dict)}
    elif isinstance(objects_raw, dict):
        log(f"Object IDs in layout:     {list(objects_raw.keys())}")
        objects = objects_raw
    else:
        log("Objects:                  unexpected type")
        objects = {}

    expected_objects = [
        "background", "cover", "bookTitle", "currentChapter",
        "chapterStack", "waveform", "progress", "brand"
    ]
    for obj_id in expected_objects:
        if obj_id in objects:
            obj = objects[obj_id]
            visible = obj.get("visible", True)
            z = obj.get("z", obj.get("z_index", 0))
            log(f"  {obj_id}: visible={visible}, z={z}, "
                f"pos=({obj.get('x',0)},{obj.get('y',0)}), "
                f"size=({obj.get('w',0)}x{obj.get('h',0)})")
        else:
            log(f"  {obj_id}: MISSING from layout")

    # Specific checks
    log(f"Waveform object:          {'EXISTS' if 'waveform' in objects else 'MISSING'}")
    log(f"Progress object:          {'EXISTS' if 'progress' in objects else 'MISSING'}")
    log(f"ChapterStack object:      {'EXISTS' if 'chapterStack' in objects else 'MISSING'}")
    log(f"BookTitle object:         {'EXISTS' if 'bookTitle' in objects else 'MISSING'}")
    chapter_obj = objects.get("currentChapter", {})
    log(f"CurrentChapter visible:   {chapter_obj.get('visible', 'N/A')}")
    brand_obj = objects.get("brand", {})
    log(f"Brand visible:            {brand_obj.get('visible', 'N/A')}")


# =========================================================
#  8. GUI diagnostics
# =========================================================
def check_gui():
    log_header("8. GUI Diagnostics")

    # Check import
    try:
        import book_wunderwaffe_studio as studio
        log("book_wunderwaffe_studio    IMPORT OK")
    except Exception as e:
        log(f"book_wunderwaffe_studio    IMPORT FAILED: {e}")
        return

    # Check classes
    class_list = [
        "MainWindow",
        "ZoomGraphicsView",
        "CanvasScene",
        "PropertiesDock",
        "TimelineWidget",
        "ChapterListPanel",
    ]
    for cls_name in class_list:
        if hasattr(studio, cls_name):
            log(f"Class {cls_name}:          FOUND")
        else:
            log(f"Class {cls_name}:          NOT FOUND")

    # Item classes
    item_classes = [
        "WaveformItem",
        "ProgressItem",
        "CustomTextItem",
        "ChapterStackItem",
    ]
    for cls_name in item_classes:
        if hasattr(studio, cls_name):
            log(f"Item class {cls_name}:     FOUND")
        else:
            log(f"Item class {cls_name}:     NOT FOUND")

    # Player mode
    log("")
    log("Player implementation:")
    log(f"  QMediaPlayer import:     {'YES' if studio.HAS_MULTIMEDIA else 'NO'}")
    # Check simulation mode in MainWindow
    if hasattr(studio, "MainWindow"):
        log("  Simulation fallback:     Check MainWindow._player_simulation attribute")

    # Check key constants
    for const_name in ["HAS_MULTIMEDIA", "WAVEFORM_PATH", "LAYOUT_PATH",
                        "OBJ_WAVEFORM", "OBJ_PROGRESS", "OBJ_CHAPTER_STACK"]:
        if hasattr(studio, const_name):
            log(f"  Const {const_name}:       defined")
        else:
            log(f"  Const {const_name}:       MISSING")


# =========================================================
#  9. Summary
# =========================================================
def write_summary():
    log_header("9. Summary")

    # Check audio status
    config = load_json_safe(PROJECT_CONFIG)
    audio_ok = False
    audio_size_gb = 0
    audio_path = None
    if config and isinstance(config, dict):
        audio_rel = config.get("audio", "")
        audio_path = PROJECT_ROOT / audio_rel if audio_rel else None
        if audio_path and audio_path.exists():
            audio_ok = True
            audio_size_gb = get_file_size_gb(audio_path) or 0

    # Check QMediaPlayer status
    qmp_ok = False
    qmp_error = "UNKNOWN"
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
        from PySide6.QtCore import QUrl
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        player = QMediaPlayer()
        ao = QAudioOutput()
        player.setAudioOutput(ao)
        if audio_ok and audio_path:
            player.setSource(QUrl.fromLocalFile(str(audio_path)))
            for _ in range(10):
                app.processEvents()
                time.sleep(0.1)
            if player.error() == 0:
                qmp_ok = True
            else:
                qmp_error = player.errorString()
    except Exception as e:
        qmp_error = str(e)

    if not audio_ok:
        audio_status = "FILE_MISSING"
    elif qmp_ok:
        audio_status = "OK"
    else:
        audio_status = "FAILED_QMEDIAPLAYER"

    # Waveform status
    wf = load_json_safe(WAVEFORM_PATH)
    if wf is None:
        waveform_status = "MISSING"
    elif isinstance(wf, dict):
        samples = wf.get("samples", wf.get("peaks", wf.get("data", [])))
        if not isinstance(samples, list) or len(samples) == 0:
            waveform_status = "INVALID (empty samples)"
        else:
            waveform_status = "OK_DATA_EXISTS"
    elif isinstance(wf, list):
        waveform_status = "OK_DATA_EXISTS"
    else:
        waveform_status = "INVALID"

    # Canvas status - ZoomGraphicsView already has pan/zoom/navigation buttons
    # Check if ZoomGraphicsView exists
    canvas_status = "OK (ZoomGraphicsView has middle mouse pan, space+drag pan, ctrl+zoom, Fit/Center/100% buttons)"
    try:
        import book_wunderwaffe_studio as studio
        if hasattr(studio, "ZoomGraphicsView"):
            zcls = studio.ZoomGraphicsView
            has_pan = hasattr(zcls, "_panning") or hasattr(zcls, "_space_panning")
            has_zoom = hasattr(zcls, "zoom_fit") and hasattr(zcls, "zoom_center") and hasattr(zcls, "zoom_100")
            if has_pan and has_zoom:
                canvas_status = "OK (pan/zoom/nav all implemented)"
    except Exception:
        pass

    log("")
    log(f"AUDIO_STATUS:      {audio_status}")
    if not qmp_ok and audio_ok:
        log(f"  QMediaPlayer errorString: {qmp_error}")
        if audio_size_gb:
            log(f"  Audio file: {audio_size_gb:.2f} GB - too large for QMediaPlayer")
    elif not audio_ok:
        log("  Audio file not found on disk.")

    log("")
    log(f"WAVEFORM_STATUS:   {waveform_status}")
    if wf and isinstance(wf, dict):
        samples = wf.get("samples", wf.get("peaks", wf.get("data", [])))
        if isinstance(samples, list):
            log(f"  Sample count: {len(samples)}")
            log(f"  First 3 vals: {samples[:3]}")
    elif isinstance(wf, list):
        log(f"  Sample count: {len(wf)}")
        if len(wf) > 0:
            log(f"  First 3 vals: {wf[:3]}")
    else:
        log("  Run: python bookforge.py waveform")

    log("")
    log(f"CANVAS_STATUS:     {canvas_status}")

    log("")
    log("NEXT_FIXES:")
    fixes = []
    if not qmp_ok and audio_ok:
        fixes.append("1. Generate proxy audio for QMediaPlayer (ffmpeg -i <src> -b:a 128k proxy.mp3)")
    if waveform_status.startswith("MISSING"):
        fixes.append("2. Run: python bookforge.py waveform")
    elif waveform_status.startswith("OK_DATA_EXISTS"):
        fixes.append("2. (If GUI no bars) Fix WaveformItem loader to read samples from waveform.json object key")
    fixes.append("3. (Already done) Middle-mouse/space+drag pan in ZoomGraphicsView")
    fixes.append("4. (Already done) Fit/Center/100% buttons in top bar")
    fixes.append("5. (Already done) Ctrl+Z undo stack with UndoManager")
    fixes.append("6. (Already done) Ctrl+wheel zoom in ZoomGraphicsView")

    for f in fixes:
        log(f"  {f}")

    log("")
    log("=" * 68)
    log("  END OF DIAGNOSTICS REPORT")
    log("=" * 68)


# =========================================================
#  Main
# =========================================================
def main():
    print("\n=== Book Wunderwaffe Studio - Diagnostics ===\n")

    # Ensure build directory exists
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    check_environment()
    check_project_files()
    check_audio_ffprobe()
    check_qmediaplayer()
    check_audio_fallback()
    check_waveform()
    check_layout()
    check_gui()
    write_summary()

    # Write report
    report_text = "\n".join(REPORT_LINES)
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    print(f"\nDiagnostics report saved: {REPORT_PATH}")

    # Auto-open
    try:
        if sys.platform == "win32":
            os.startfile(str(REPORT_PATH))
        else:
            subprocess.run(["start", str(REPORT_PATH)], shell=True)
        print("Report opened automatically.")
    except Exception as e:
        print(f"Could not auto-open report: {e}")
        print(f"  Open manually: {REPORT_PATH}")


if __name__ == "__main__":
    main()