import importlib.util
import os
import sys
import msvcrt
import subprocess
import threading
import time
import json
from colorama import init, Fore, Style
from tqdm import tqdm
from google import genai
from google.genai import types
from pydantic import BaseModel
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
    for key in ("CLIP_LENGTH", "EXPORT_LOCATION", "ENCODER", "GPU_BRAND", "CROP_RATIO", "TARGET_FPS", "SHOW_STATS", "AI_MODE", "GEMINI_API_KEY"):
        if hasattr(module, key):
            setattr(preferences, key, getattr(module, key))
load_local_preferences()

init()

# -------------------- AI Processing -------------------- #
def create_proxy_video(input_path):
    print(f"\n{Style.DIM}Creating proxy video for AI analysis...{Style.RESET_ALL}")
    proxy_path = os.path.splitext(input_path)[0] + "_proxy.mp4"
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-i", input_path,
        "-vf", "scale=-2:480", # Downscale to 480p height
        "-r", "15",            # 15 fps
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "35",
        "-c:a", "aac",
        "-b:a", "64k",
        "-y",
        proxy_path
    ]
    try:
        subprocess.run(cmd, check=True)
        print(f"{Style.DIM}Proxy video created: {os.path.basename(proxy_path)}{Style.RESET_ALL}")
        return proxy_path
    except subprocess.CalledProcessError as e:
        print(f"{Fore.RED}Error creating proxy video: {e}{Style.RESET_ALL}")
        return None

class Highlight(BaseModel):
    start_time: float
    end_time: float
    description: str

class VideoHighlights(BaseModel):
    highlights: list[Highlight]

def analyze_video_with_gemini(proxy_path, api_key):
    print(f"{Style.DIM}Uploading proxy video to Gemini...{Style.RESET_ALL}")
    client = genai.Client(api_key=api_key)

    try:
        video_file = client.files.upload(file=proxy_path)
        print(f"{Style.DIM}Uploaded as {video_file.name}. Waiting for processing...{Style.RESET_ALL}")

        while video_file.state.name == "PROCESSING":
            time.sleep(5)
            video_file = client.files.get(name=video_file.name)

        if video_file.state.name == "FAILED":
            print(f"{Fore.RED}Gemini video processing failed.{Style.RESET_ALL}")
            client.files.delete(name=video_file.name)
            return None

        print(f"{Style.DIM}Video processing complete. Analyzing...{Style.RESET_ALL}")

        prompt = """
        You are an expert video editor. Analyze this gameplay video and identify the most notable, exciting, or funny moments.
        Return a list of these highlights. For each highlight, provide the start_time (in seconds), end_time (in seconds), and a brief description.
        Try to keep clips between 10 and 60 seconds long.
        """

        response = client.models.generate_content(
            model='gemini-2.0-flash-lite',
            contents=[video_file, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=VideoHighlights,
                temperature=0.2,
                max_output_tokens=8192
            )
        )

        # Clean up
        client.files.delete(name=video_file.name)

        try:
            return json.loads(response.text)
        except json.JSONDecodeError as e:
            print(f"{Fore.YELLOW}Warning: JSON Decode Error from Gemini (possibly truncated): {e}{Style.RESET_ALL}")
            print(f"{Style.DIM}Attempting to salvage valid highlights...{Style.RESET_ALL}")
            import re

            highlights = []
            # Match any valid JSON object block inside the response
            pattern = r'\{[^{}]*\}'
            for match in re.finditer(pattern, response.text):
                try:
                    obj = json.loads(match.group(0))
                    if 'start_time' in obj and 'end_time' in obj:
                        highlights.append(obj)
                except json.JSONDecodeError:
                    pass

            if highlights:
                print(f"{Fore.GREEN}Salvaged {len(highlights)} highlights!{Style.RESET_ALL}")
                return {"highlights": highlights}
            else:
                print(f"{Fore.RED}Could not salvage any highlights.{Style.RESET_ALL}")
                return None

    except Exception as e:
        print(f"{Fore.RED}Error during Gemini analysis: {e}{Style.RESET_ALL}")
        return None

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

def split_video_ai(input_path, highlights, encoder_type, gpu_brand, export_dir, crop_filter=None):
    os.makedirs(export_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_path))[0]

    # Check and fix video for seeking
    duration, _ = get_video_info(input_path)
    if duration == 0:
        print(f"{Fore.YELLOW}Warning: Video is not seekable. Attempting to fix...{Style.RESET_ALL}")
        input_path = fix_video_for_seeking(input_path)
        if not input_path:
            return # Exit if fixing fails
        duration, _ = get_video_info(input_path)

    print(f"\nProcessing AI clips...")

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

    log_level = "info"

    clip_count = 0
    total_clips = len(highlights)

    for highlight in highlights:
        clip_count += 1
        start_time = max(0, highlight['start_time'])
        end_time = min(duration, highlight['end_time'])
        segment_length = max(0, end_time - start_time)

        if segment_length <= 0:
            print(f"{Fore.YELLOW}Skipping invalid clip {clip_count}/{total_clips} (length <= 0){Style.RESET_ALL}")
            continue

        start_time_str = f"{int(start_time):02d}"
        end_time_str = f"{int(end_time):02d}"

        new_filename = f"{base_name}_ai_{start_time_str}-{end_time_str}.mp4"
        out_path = os.path.join(export_dir, new_filename)

        if os.path.exists(out_path):
            print(f"✔️ Skipping existing clip {Style.DIM}{Fore.BLUE}{new_filename}{Style.RESET_ALL} ({clip_count}/{total_clips})")
            continue

        print(f"{Style.DIM}Clip {clip_count}: {highlight.get('description', 'Highlight')}{Style.RESET_ALL}")

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", log_level,
            "-ss", str(start_time),
            "-i", input_path,
            "-t", str(segment_length),
            "-c:v", video_codec,
            "-c:a", "aac",
            "-y",
        ]
        cmd.extend(encoder_args)

        if crop_filter:
            cmd.extend(["-vf", crop_filter])
        if target_fps is not None:
            cmd.extend(["-r", f"{target_fps:g}"])
        cmd.append(out_path)

        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            cancel_event = threading.Event()
            stop_event = threading.Event()
            did_cancel = False

            with tqdm(total=segment_length, desc="🔄️", unit="s", leave=False, bar_format="{l_bar}{bar}| {percentage:.0f}%") as pbar_clip:
                def read_ffmpeg_output():
                    for line in process.stdout:
                        if "time=" in line:
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

            print(f"➕ Created clip {Fore.BLUE}{new_filename}{Style.RESET_ALL} ({clip_count}/{total_clips})")

        except subprocess.CalledProcessError as e:
            print(f"{Fore.RED}Error processing clip {Fore.BLUE}{new_filename}{Fore.RED}: {e}{Style.RESET_ALL}")

    print("✅ AI Processing complete!\n")
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
    selected_crop_filter = CROP_FILTERS.get(selected_crop_ratio, None)
    if not selected_crop_filter:
        print(f"{Fore.YELLOW}Warning: Invalid crop ratio '{selected_crop_ratio}' found in preferences. No cropping will be applied.{Style.RESET_ALL}")
        selected_crop_ratio = "Invalid"

    ai_mode_enabled = getattr(preferences, "AI_MODE", False)
    api_key = getattr(preferences, "GEMINI_API_KEY", "")

    if ai_mode_enabled and not api_key:
        print(f"{Fore.RED}Error: AI_MODE is enabled but GEMINI_API_KEY is not set in preferences.py.{Style.RESET_ALL}")
        sys.exit(0)

    # --- Preview Info --- #
    first_input_path = input_paths[0]
    duration, size = get_video_info(first_input_path)
    if duration == 0:
        print("Could not read video info, continuing without preview...")
    else:
        print(f"\n{Style.BRIGHT}Video info{Style.RESET_ALL}")
        print(f"{Style.DIM}- Files found: {Style.RESET_ALL}{len(input_paths)}")
        print(f"{Style.DIM}- First file: {Style.NORMAL}{Fore.BLUE}{os.path.basename(first_input_path)}{Style.RESET_ALL}")
        print(f"{Style.DIM}- Video duration: {Style.RESET_ALL}{format_seconds(duration)}")
        print(f"{Style.DIM}- AI Mode: {Style.RESET_ALL}{'Enabled' if ai_mode_enabled else 'Disabled'}")

        if not ai_mode_enabled:
            num_clips = int((duration + segment_length - 1) // segment_length)
            est_size = size  # splitting copies streams → size ≈ same as input
            estimated_clip_size = est_size / num_clips if num_clips > 0 else 0
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

        if ai_mode_enabled:
            proxy_path = create_proxy_video(input_path)
            if not proxy_path:
                print(f"{Fore.RED}Skipping {os.path.basename(input_path)} due to proxy creation failure.{Style.RESET_ALL}")
                continue

            highlights_data = analyze_video_with_gemini(proxy_path, api_key)

            # Clean up proxy file immediately after upload/analysis is complete
            if os.path.exists(proxy_path):
                try:
                    os.remove(proxy_path)
                except Exception as e:
                    print(f"{Fore.YELLOW}Warning: Could not delete proxy video {proxy_path}: {e}{Style.RESET_ALL}")

            if not highlights_data or 'highlights' not in highlights_data or not highlights_data['highlights']:
                print(f"{Fore.YELLOW}No highlights identified for {os.path.basename(input_path)}. Skipping.{Style.RESET_ALL}")
                continue

            highlights = highlights_data['highlights']
            print(f"{Fore.GREEN}Found {len(highlights)} highlights!{Style.RESET_ALL}")

            completed = split_video_ai(input_path, highlights, preferences.ENCODER, preferences.GPU_BRAND, export_dir=preferences.EXPORT_LOCATION, crop_filter=selected_crop_filter)
        else:
            completed = split_video_ffmpeg(input_path, segment_length, preferences.ENCODER, preferences.GPU_BRAND, export_dir=preferences.EXPORT_LOCATION, crop_filter=selected_crop_filter)

        if not completed:
            break