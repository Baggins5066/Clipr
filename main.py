import importlib.util
import os
import sys
import msvcrt
import subprocess
import threading
from colorama import init, Fore, Style
from tqdm import tqdm
import preferences

def load_local_preferences():
    """Load local overrides from preferences_local.py if present."""
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preferences_local.py")
    if not os.path.isfile(local_path):
        return
    spec = importlib.util.spec_from_file_location("preferences_local", local_path)
    if spec is None or spec.loader is None:
        return
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:
        return
    for key in ("CLIP_LENGTH", "EXPORT_LOCATION", "ENCODER", "GPU_BRAND", "CROP_RATIO", "TARGET_FPS", "SHOW_STATS"):
        if hasattr(module, key):
            setattr(preferences, key, getattr(module, key))
load_local_preferences()

init()

# -------------------- Input Helpers -------------------- #
def get_input_with_escape(prompt):
    print(f"{prompt}", end='', flush=True)
    chars = []
    while True:
        ch = msvcrt.getwch()
        if ch == '\r' or ch == '\n':
            print()
            # Clear the input buffer to prevent it from affecting the next prompt
            while msvcrt.kbhit():
                msvcrt.getch()
            return ''.join(chars)
        elif ch == '\x1b':  # ESC key
            print(f"\n{Fore.YELLOW}Processing cancelled.{Style.RESET_ALL}")
            sys.exit(0)
        elif ch == '\x08':  # Backspace
            if chars:
                chars.pop()
                print('\b \b', end='', flush=True)
        else:
            chars.append(ch)
            print(ch, end='', flush=True)

def get_imported_video_files(imports_dir):
    video_extensions = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm"}

    if not os.path.isdir(imports_dir):
        os.makedirs(imports_dir, exist_ok=True)
        return []

    video_files = []
    for entry in sorted(os.listdir(imports_dir)):
        full_path = os.path.join(imports_dir, entry)
        if os.path.isfile(full_path) and os.path.splitext(entry)[1].lower() in video_extensions:
            video_files.append(full_path)

    return video_files

def get_video_info(input_path):
    """Return duration (seconds) and file size (bytes) using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
             "-of", "default=noprint_wrappers=1:nokey=1", input_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        duration_str, size_str = result.stdout.strip().splitlines()

        # Check for 'N/A' and set to 0
        duration = float(duration_str) if duration_str != 'N/A' else 0
        size = int(size_str) if size_str != 'N/A' else 0

        return duration, size
    except Exception as e:
        print(f"{Fore.RED}ffprobe failed: {e}{Style.RESET_ALL}")
        return 0, 0

def get_video_fps(input_path):
    """Return the FPS of the import video or None if it cannot be determined."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=avg_frame_rate,r_frame_rate",
                "-of", "default=noprint_wrappers=1:nokey=1",
                input_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        rates = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        for rate in rates:
            if rate in ("0/0", "N/A"):
                continue
            if "/" in rate:
                numerator, denominator = rate.split("/", 1)
                denominator_value = float(denominator)
                if denominator_value == 0:
                    continue
                fps = float(numerator) / denominator_value
            else:
                fps = float(rate)
            if fps > 0:
                return fps
    except Exception:
        return None
    return None

def get_video_resolution(input_path):
    """Return (width, height) of the input video or (None, None) on failure."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0:s=x",
                input_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        out = result.stdout.strip()
        if not out:
            return None, None
        parts = out.split('x')
        if len(parts) != 2:
            return None, None
        return int(parts[0]), int(parts[1])
    except Exception:
        return None, None

def fix_video_for_seeking(input_path):
    print(f"Fixing video for seeking. This may take a moment...")
    fixed_path = os.path.splitext(input_path)[0] + "_fixed.mp4"
    cmd = [
        "ffmpeg",
        "-i", input_path,
        "-c", "copy",
        "-movflags", "+faststart",
        fixed_path
    ]
    try:
        subprocess.run(cmd, check=True)
        print(f"Video fixed! New file: {fixed_path}")
        return fixed_path
    except subprocess.CalledProcessError as e:
        print(f"Error fixing video: {e}")
        return None

def format_seconds(seconds):
    """Converts a duration in seconds to HH:MM:SS or MM:SS format with no leading zeros."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"

def watch_for_escape(cancel_event, stop_event):
    while not cancel_event.is_set() and not stop_event.is_set():
        if msvcrt.kbhit():
            if msvcrt.getwch() == '\x1b':
                cancel_event.set()
                while msvcrt.kbhit():
                    msvcrt.getwch()
                return
        else:
            cancel_event.wait(0.05)

def parse_target_fps(value):
    if value in (None, "", 0, "0"):
        return None
    try:
        fps = float(value)
    except (TypeError, ValueError):
        return None
    return fps if fps > 0 else None

# -------------------- Splitting -------------------- #
def split_video_ffmpeg(input_path, segment_length, encoder_type, gpu_brand, export_dir, crop_filter=None):
    os.makedirs(export_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    
    # Check and fix video for seeking
    duration, _ = get_video_info(input_path)
    if duration == 0:
        print(f"{Fore.YELLOW}Warning: Video is not seekable. Attempting to fix...{Style.RESET_ALL}")
        input_path = fix_video_for_seeking(input_path)
        if not input_path:
            return # Exit if fixing fails
        duration, _ = get_video_info(input_path) # Get duration of the new fixed file

    print(f"\nProcessing clips...")

    if encoder_type == '1': # CPU Encoding
        video_codec = "libx264"
        encoder_args = ["-crf", "18", "-preset", "slow"]
        print(f"{Style.DIM}Using CPU encoding{Style.RESET_ALL}")
    else: # GPU Encoding
        if gpu_brand == '1':
            video_codec = "h264_nvenc"
            encoder_args = ["-preset", "p6", "-rc:v", "vbr", "-cq:v", "19", "-b:v", "0"]
            print(f"{Style.DIM}Using NVIDIA GPU encoding{Style.RESET_ALL}")
        elif gpu_brand == '2':
            video_codec = "h264_qsv"
            encoder_args = ["-global_quality", "19", "-preset", "medium"]
            print(f"{Style.DIM}Using Intel GPU encoding{Style.RESET_ALL}")
        elif gpu_brand == '3':
            video_codec = "h264_amf"
            encoder_args = ["-rc", "cqp", "-qp_i", "18", "-qp_p", "18", "-quality", "quality"]
            print(f"{Style.DIM}Using AMD GPU encoding{Style.RESET_ALL}")
        else:
            video_codec = "libx264"
            encoder_args = ["-crf", "18", "-preset", "slow"]
            print(f"{Fore.YELLOW}No valid GPU brand is selected. Reverting to CPU encoding{Style.RESET_ALL}")
    print()
    target_fps = parse_target_fps(getattr(preferences, "TARGET_FPS", None))
    if target_fps is not None:
        print(f"{Style.DIM}Forcing output fps to {target_fps:g}.{Style.RESET_ALL}")
    source_fps = get_video_fps(input_path)
    # The log_level is now constant for the progress bar to work
    log_level = "info"
        
    start_time = 0
    clip_count = 0
    total_clips = int(duration // segment_length) + (1 if duration % segment_length != 0 else 0)

    # The overall progress bar is removed from here
    while start_time < duration:
        clip_count += 1
        end_time = min(start_time + segment_length, duration)
        
        start_time_str = f"{int(start_time):02d}"
        end_time_str = f"{int(end_time):02d}"
        
        new_filename = f"{base_name}_{start_time_str}-{end_time_str}.mp4"
        out_path = os.path.join(export_dir, new_filename)

        if os.path.exists(out_path):
            print(f"✔️ Skipping existing clip {Style.DIM}{Fore.BLUE}{new_filename}{Style.RESET_ALL} ({clip_count}/{total_clips})")
            start_time += segment_length
            continue

        # Base FFmpeg command with acceleration
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", log_level,
            "-ss", str(start_time),
            "-i", input_path,
            "-t", str(segment_length),
            "-c:v", video_codec,
            "-c:a", "aac",
            "-y", # Overwrite output files without asking
        ]
        cmd.extend(encoder_args)
        
        # Add cropping filter if needed
        if crop_filter:
            if source_fps is not None and "color=c=black:s=810x1440" in crop_filter:
                crop_filter = crop_filter.replace("color=c=black:s=810x1440", f"color=c=black:s=810x1440:r={source_fps:g}")
            cmd.extend(["-vf", crop_filter])
        if target_fps is not None:
            cmd.extend(["-r", f"{target_fps:g}"])
        cmd.append(out_path) # Append output path at the very end
        
        try:
            # Use Popen to get real-time output
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            cancel_event = threading.Event()
            stop_event = threading.Event()
            did_cancel = False
            
            # Setup a progress bar for the current clip
            # The description is now an empty string to remove the colon
            with tqdm(total=segment_length, desc="🔄️", unit="s", leave=False, bar_format="{l_bar}{bar}| {percentage:.0f}%") as pbar_clip:
                def read_ffmpeg_output():
                    for line in process.stdout:
                        if "time=" in line:
                            # Parse the output to find the current time
                            parts = line.split()
                            for part in parts:
                                if part.startswith("time="):
                                    time_str = part.split("=")[1]
                                    try:
                                        h, m, s = time_str.split(':')
                                        current_time = float(h) * 3600 + float(m) * 60 + float(s)
                                        pbar_clip.n = min(pbar_clip.total, current_time)
                                        pbar_clip.refresh()
                                    except ValueError:
                                        continue
                output_thread = threading.Thread(target=read_ffmpeg_output, daemon=True)
                cancel_thread = threading.Thread(target=watch_for_escape, args=(cancel_event, stop_event), daemon=True)
                output_thread.start()
                cancel_thread.start()
                while process.poll() is None:
                    if cancel_event.is_set():
                        did_cancel = True
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        break
                    cancel_event.wait(0.1)
            output_thread.join(timeout=1)
            stop_event.set()
            cancel_thread.join(timeout=1)
            return_code = process.returncode if process.returncode is not None else process.wait()
            if did_cancel:
                if return_code != 0 and os.path.exists(out_path):
                    os.remove(out_path)
                print(f"{Fore.YELLOW}Processing cancelled.{Style.RESET_ALL}")
                return False
            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, cmd)
            # This line handles the "➕ Created clip" output
            print(f"➕ Created clip {Fore.BLUE}{new_filename}{Style.RESET_ALL} ({clip_count}/{total_clips})")

        except subprocess.CalledProcessError as e:
            print(f"{Fore.RED}Error processing clip {Fore.BLUE}{new_filename}{Fore.RED}: {e}{Style.RESET_ALL}")
        
        start_time += segment_length
    print("✅ Processing complete!\n")
    return True

# -------------------- Main -------------------- #
if __name__ == "__main__":
    
    # Map crop ratios from preferences.py to FFmpeg filters
    CROP_FILTERS = {
        '1:2': 'crop=ih/2:ih:iw/4:0',
        '9:16': 'crop=ih*9/16:ih:(iw-ih*9/16)/2:0',
        '2:3': 'crop=ih*2/3:ih:(iw-ih*2/3)/2:0',
        '5:7': 'crop=ih*5/7:ih:(iw-ih*5/7)/2:0',
        '3:4': 'crop=ih*3/4:ih:(iw-ih*3/4)/2:0',
        '4:5': 'crop=ih*4/5:ih:(iw-ih*4/5)/2:0',
        '1:1': 'crop=ih:ih:(iw-ih)/2:0',
        '5:4': 'crop=iw:iw*4/5:0:ih/10',
        '4:3': 'crop=iw:iw*3/4:0:ih/8',
        '7:5': 'crop=iw:iw*5/7:0:ih/7',
        '3:2': 'crop=iw:iw*2/3:0:ih/6',
        '16:9': 'crop=iw:iw*9/16:0:ih/8',
        '2.39:1': 'crop=iw:iw*1/2.39:0:ih/2',
        'Call of Duty': 'split=4[minimap_capture_src][gameplay_capture_src][player_status_src][weapon_status_src];[minimap_capture_src]crop=375:350:50:30,scale=405:-1[minimap_capture];[player_status_src]crop=500:150:60:ih-180,scale=405:122[player_status];[weapon_status_src]crop=630:230:iw-680:ih-270,scale=405:-1[weapon_status];[gameplay_capture_src]scale=810:1040:force_original_aspect_ratio=increase,crop=810:1040[gameplay_capture];color=c=black:s=810x1440[canvas];[canvas][gameplay_capture]overlay=0:0[tmp];[tmp][minimap_capture]overlay=W-w:H-h[tmp2];[tmp2][weapon_status]overlay=0:H-h-122[tmp3];[tmp3][player_status]overlay=0:H-h',
            # A custom crop that captures the following areas of a 2560x1440 Call of Duty gameplay video:
                # The gameplay area taking up the top portion of the screen, excluding most of its left and right edges
                # The minimap placed bottom right
                # The weapon status placed above the player status
                # The player status placed bottom left
    }
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    imports_dir = os.path.join(script_dir, "Imports")
    input_paths = get_imported_video_files(imports_dir)

    if not input_paths:
        print(f"No video files found in {imports_dir}. Add videos there and run the script again.")
        sys.exit(0)

    # Use clip length from preferences
    try:
        segment_length = int(preferences.CLIP_LENGTH)
    except Exception:
        print("Invalid CLIP_LENGTH in preferences. Exiting.")
        sys.exit(0)

    # Use crop ratio from preferences
    selected_crop_ratio = preferences.CROP_RATIO
    selected_crop_filter = CROP_FILTERS.get(selected_crop_ratio, None)
    if not selected_crop_filter:
        print(f"{Fore.YELLOW}Warning: Invalid crop ratio '{selected_crop_ratio}' found in preferences. No cropping will be applied.{Style.RESET_ALL}")
        selected_crop_ratio = "Invalid"

    # --- Preview Info --- #
    first_input_path = input_paths[0]
    duration, size = get_video_info(first_input_path)
    if duration == 0:
        print("Could not read video info, continuing without preview...")
    else:
        num_clips = int((duration + segment_length - 1) // segment_length)
        est_size = size  # splitting copies streams → size ≈ same as input
        estimated_clip_size = est_size / num_clips if num_clips > 0 else 0
        print(f"\n{Style.BRIGHT}Video info{Style.RESET_ALL}")
        print(f"{Style.DIM}- Files found: {Style.RESET_ALL}{len(input_paths)}")
        print(f"{Style.DIM}- First file: {Style.NORMAL}{Fore.BLUE}{os.path.basename(first_input_path)}{Style.RESET_ALL}")
        print(f"{Style.DIM}- Video duration: {Style.RESET_ALL}{format_seconds(duration)}")
        print(f"{Style.DIM}- Clip length: {Style.RESET_ALL}{format_seconds(segment_length)}")
        print(f"{Style.DIM}- Number of clips: {Style.RESET_ALL}{num_clips}")
        print(f"{Style.DIM}- Estimated clip size: {Style.RESET_ALL}{estimated_clip_size/1e6:.2f} MB ({est_size/1e6:.2f} MB total)")
        print(f"{Style.DIM}- Crop: {Style.RESET_ALL}{selected_crop_ratio}")

    confirm = get_input_with_escape(
        f"{Fore.GREEN}{Style.BRIGHT}\n[ENTER]{Style.NORMAL} Start processing{Style.RESET_ALL}"
        f"{Fore.RED}{Style.BRIGHT}\n[ESC]{Style.NORMAL} Cancel\n{Style.RESET_ALL}> "
    ).strip()

    for input_path in input_paths:
        print(f"\n{Style.BRIGHT}Processing file:{Style.RESET_ALL} {Fore.BLUE}{os.path.basename(input_path)}{Style.RESET_ALL}")
        # If Call of Duty mode is selected, require source resolution 2560x1440
        if selected_crop_ratio == 'Call of Duty':
            w, h = get_video_resolution(input_path)
            if w is None or h is None:
                print(f"{Fore.YELLOW}Could not determine resolution for {os.path.basename(input_path)}; skipping.{Style.RESET_ALL}")
                continue
            if not (w == 2560 and h == 1440):
                print(f"{Fore.YELLOW}Skipping {os.path.basename(input_path)}: resolution {w}x{h} != 2560x1440 required for Call of Duty mode.{Style.RESET_ALL}")
                continue

        completed = split_video_ffmpeg(input_path, segment_length, preferences.ENCODER, preferences.GPU_BRAND, export_dir=preferences.EXPORT_LOCATION, crop_filter=selected_crop_filter)
        if not completed:
            break