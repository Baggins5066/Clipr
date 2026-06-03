import importlib.util
import json
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
    for key in ("CLIP_LENGTH", "EXPORT_LOCATION", "ENCODER", "GPU_BRAND", "CROP_RATIO", "BLUR_CROP", "BLUR_STRENGTH", "TARGET_FPS", "SHOW_STATS"):
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
    """Return duration (seconds), file size (bytes), width, and height using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "format=duration,size:stream=width,height",
                "-of",
                "json",
                input_path,
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        data = json.loads(result.stdout)
        format_data = data.get("format", {})
        streams = data.get("streams", [])
        stream_data = streams[0] if streams else {}

        duration_text = format_data.get("duration", "0")
        size_text = format_data.get("size", "0")

        duration = float(duration_text) if duration_text not in (None, "N/A") else 0
        size = int(size_text) if size_text not in (None, "N/A") else 0
        width = int(stream_data.get("width", 0) or 0)
        height = int(stream_data.get("height", 0) or 0)

        return duration, size, width, height
    except Exception as e:
        print(f"{Fore.RED}ffprobe failed: {e}{Style.RESET_ALL}")
        return 0, 0, 0, 0

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

def parse_aspect_ratio(value, source_aspect_ratio=None):
    if value in (None, "", 0, "0", "Off", "off"):
        return None
    if isinstance(value, str) and value.lower() == "source":
        return source_aspect_ratio
    try:
        if isinstance(value, str) and ":" in value:
            numerator, denominator = value.split(":", 1)
            ratio = float(numerator) / float(denominator)
        else:
            ratio = float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return ratio if ratio > 0 else None

def even_dimension(value):
    value = int(round(value))
    if value < 2:
        return 2
    return value if value % 2 == 0 else value - 1

def build_center_crop_filter(source_width, source_height, target_aspect_ratio):
    if source_width <= 0 or source_height <= 0 or target_aspect_ratio is None:
        return None

    source_aspect_ratio = source_width / source_height
    if abs(source_aspect_ratio - target_aspect_ratio) < 1e-6:
        crop_width = source_width
        crop_height = source_height
        crop_x = 0
        crop_y = 0
    elif source_aspect_ratio > target_aspect_ratio:
        crop_height = source_height
        crop_width = min(source_width, even_dimension(source_height * target_aspect_ratio))
        crop_x = max((source_width - crop_width) // 2, 0)
        crop_y = 0
    else:
        crop_width = source_width
        crop_height = min(source_height, even_dimension(source_width / target_aspect_ratio))
        crop_x = 0
        crop_y = max((source_height - crop_height) // 2, 0)

    return f"crop={crop_width}:{crop_height}:{crop_x}:{crop_y}"

def build_blur_canvas_filter(source_width, source_height, canvas_aspect_ratio, video_aspect_ratio):
    if source_width <= 0 or source_height <= 0 or canvas_aspect_ratio is None or video_aspect_ratio is None:
        return None

    crop_filter = build_center_crop_filter(source_width, source_height, video_aspect_ratio)
    if not crop_filter:
        return None

    if canvas_aspect_ratio >= 1:
        canvas_width = even_dimension(source_width)
        canvas_height = even_dimension(source_width / canvas_aspect_ratio)
    else:
        canvas_height = even_dimension(source_height)
        canvas_width = even_dimension(source_height * canvas_aspect_ratio)

    canvas_width = max(canvas_width, 2)
    canvas_height = max(canvas_height, 2)

    if video_aspect_ratio >= canvas_aspect_ratio:
        scaled_width = canvas_width
        scaled_height = even_dimension(canvas_width / video_aspect_ratio)
    else:
        scaled_height = canvas_height
        scaled_width = even_dimension(canvas_height * video_aspect_ratio)

    scaled_width = min(max(scaled_width, 2), canvas_width)
    scaled_height = min(max(scaled_height, 2), canvas_height)

    return (
        f"{crop_filter},"
        f"scale={scaled_width}:{scaled_height},"
        f"pad={canvas_width}:{canvas_height}:(ow-iw)/2:(oh-ih)/2:color=black"
    )

# -------------------- Splitting -------------------- #
def split_video_ffmpeg(input_path, segment_length, encoder_type, gpu_brand, export_dir, crop_filter=None, blur_crop_ratio=None, canvas_ratio=None):
    os.makedirs(export_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    
    # Check and fix video for seeking
    duration, _, source_width, source_height = get_video_info(input_path)
    if duration == 0:
        print(f"{Fore.YELLOW}Warning: Video is not seekable. Attempting to fix...{Style.RESET_ALL}")
        input_path = fix_video_for_seeking(input_path)
        if not input_path:
            return # Exit if fixing fails
        duration, _, source_width, source_height = get_video_info(input_path) # Get duration of the new fixed file

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
    # The log_level is now constant for the progress bar to work
    log_level = "info"
    blur_filter = None
    if blur_crop_ratio not in (None, "", "Off", "off"):
        blur_filter = build_blur_canvas_filter(
            source_width,
            source_height,
            parse_aspect_ratio(canvas_ratio, source_width / source_height),
            parse_aspect_ratio(blur_crop_ratio),
        )
        if not blur_filter:
            print(f"{Fore.RED}Unable to build Blur Crop filter for {os.path.basename(input_path)}.{Style.RESET_ALL}")
            return False
        
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
        if blur_filter:
            cmd.extend(["-vf", blur_filter])
        elif crop_filter:
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
    if selected_crop_ratio == "Source":
        selected_crop_filter = None
    else:
        selected_crop_filter = CROP_FILTERS.get(selected_crop_ratio, None)
        if not selected_crop_filter:
            print(f"{Fore.YELLOW}Warning: Invalid crop ratio '{selected_crop_ratio}' found in preferences. No cropping will be applied.{Style.RESET_ALL}")
            selected_crop_ratio = "Invalid"
    selected_blur_crop = getattr(preferences, "BLUR_CROP", None)
    # --- Preview Info --- #
    first_input_path = input_paths[0]
    duration, size, _, _ = get_video_info(first_input_path)
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
        if selected_blur_crop not in (None, "", "Off", "off"):
            print(f"{Style.DIM}- Blur crop: {Style.RESET_ALL}{selected_blur_crop}")
    confirm = get_input_with_escape(
        f"{Fore.GREEN}{Style.BRIGHT}\n[ENTER]{Style.NORMAL} Start processing{Style.RESET_ALL}"
        f"{Fore.RED}{Style.BRIGHT}\n[ESC]{Style.NORMAL} Cancel\n{Style.RESET_ALL}> "
    ).strip()

    for input_path in input_paths:
        print(f"\n{Style.BRIGHT}Processing file:{Style.RESET_ALL} {Fore.BLUE}{os.path.basename(input_path)}{Style.RESET_ALL}")
        completed = split_video_ffmpeg(
            input_path,
            segment_length,
            preferences.ENCODER,
            preferences.GPU_BRAND,
            export_dir=preferences.EXPORT_LOCATION,
            crop_filter=selected_crop_filter,
            blur_crop_ratio=selected_blur_crop,
            canvas_ratio=preferences.CROP_RATIO,
        )
        if not completed:
            break