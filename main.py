import os
import sys
import msvcrt
import tkinter as tk
from tkinter import filedialog
import subprocess
from colorama import init, Fore, Style
import preferences

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
            print("\nESC pressed. Exited program.")
            sys.exit(0)
        elif ch == '\x08':  # Backspace
            if chars:
                chars.pop()
                print('\b \b', end='', flush=True)
        else:
            chars.append(ch)
            print(ch, end='', flush=True)

def pick_video_file():
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Select video file",
        filetypes=[("Video files", "*.mp4;*.avi;*.mov;*.mkv;*.flv;*.wmv;*.webm"), ("All files", "*.*")]
    )
    root.destroy()
    if not file_path:
        print("No file selected. Exiting.")
        sys.exit(0)
    return file_path

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

# -------------------- Splitting -------------------- #
def split_video_ffmpeg(input_path, segment_length, encoder_type, gpu_brand, export_dir="Clips", crop_vertical=False):
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
        crf = "18"
        print(f"{Style.DIM}Using CPU encoding for higher quality.{Style.RESET_ALL}")
    else: # GPU Encoding
        if gpu_brand == '1':
            video_codec = "h264_nvenc"
        elif gpu_brand == '2':
            video_codec = "h264_qsv"
        elif gpu_brand == '3':
            video_codec = "h264_amf"
        else:
            video_codec = "libx264"
            print(f"{Fore.YELLOW}No valid GPU brand selected. Reverting to CPU encoding.{Style.RESET_ALL}")
        crf = "23"
        print(f"{Style.DIM}Using GPU encoding for speed.{Style.RESET_ALL}")
    print()

    # Configure FFmpeg output based on preferences.SHOW_STATS
    if preferences.SHOW_STATS:
        # Show full progress with stats and errors
        log_level = "error"
        stats = ""
    else:
        # Suppress most output and show only errors
        log_level = "quiet"
        stats = "-nostats"
        
    start_time = 0
    clip_count = 0
    total_clips = int(duration // segment_length) + (1 if duration % segment_length != 0 else 0)

    while start_time < duration:
        clip_count += 1
        end_time = min(start_time + segment_length, duration)
        
        start_time_str = f"{int(start_time):02d}"
        end_time_str = f"{int(end_time):02d}"
        
        new_filename = f"{base_name}_{start_time_str}-{end_time_str}.mp4"
        out_path = os.path.join(export_dir, new_filename)

        if os.path.exists(out_path):
            print(f" ✔️ Skipping existing clip: {Style.DIM}{Fore.BLUE}{new_filename}{Style.RESET_ALL}")
            start_time += segment_length
            continue

        # Base FFmpeg command with acceleration
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", log_level,
            stats,
            "-ss", str(start_time),
            "-i", input_path,
            "-t", str(segment_length),
            "-c:v", video_codec,
            "-c:a", "aac",
            "-crf", crf, "-preset", "medium",
            "-y", # Overwrite output files without asking
            out_path
        ]
        
        # Add cropping filter if needed
        if crop_vertical:
            cmd.insert(-1, "-vf")
            cmd.insert(-1, "crop=ih*9/16:ih:(iw-ih*9/16)/2:0")
        try:
            subprocess.run(cmd, check=True)
            print(f"➕ Created clip {Fore.BLUE}{new_filename}{Style.RESET_ALL} ({clip_count}/{total_clips})")
        except subprocess.CalledProcessError as e:
            print(f"{Fore.RED}Error processing clip {Fore.BLUE}{new_filename}{Fore.RED}: {e}{Style.RESET_ALL}")
        start_time += segment_length
    print("\n✅ Processing complete!\n")

# -------------------- Main -------------------- #
if __name__ == "__main__":
    input_path = pick_video_file()
    print(f"\nSelected file: {Fore.BLUE}{os.path.basename(input_path)}{Style.RESET_ALL}")

    seconds_str = get_input_with_escape(f"Enter clip length in seconds:\n> {Fore.BLUE}").strip()
    print(Style.RESET_ALL, end='')  # Reset color after input
    try:
        segment_length = int(seconds_str)
    except ValueError:
        print("Invalid number for clip length. Exiting.")
        sys.exit(0)

    print(f"Crop to Shorts vertical format? {Style.DIM}Cropping requires re-encoding; output size may differ.{Style.RESET_ALL}")
    print(f"{Style.BRIGHT}{Fore.GREEN}[1] {Style.NORMAL}Yes")
    print(f"{Style.BRIGHT}{Fore.RED}[2] {Style.NORMAL}No")
    crop_choice = get_input_with_escape(f"{Style.RESET_ALL}> ").strip().lower()
    crop_vertical = crop_choice == "1"
    
    # --- Preview Info --- #
    duration, size = get_video_info(input_path)
    if duration == 0:
        print("Could not read video info, continuing without preview...")
    else:
        num_clips = int((duration + segment_length - 1) // segment_length)
        est_size = size  # splitting copies streams → size ≈ same as input
        print("\nVideo info:")
        print(f"{Style.DIM}- Duration: {Style.RESET_ALL}{duration/60:.2f} minutes")
        print(f"{Style.DIM}- Clip length: {Style.RESET_ALL}{segment_length/60:.2f} minutes")
        print(f"{Style.DIM}- Number of clips: {Style.RESET_ALL}{num_clips}")
        print(f"{Style.DIM}- Estimated total output size: {Style.RESET_ALL}{est_size/1e6:.2f} MB")
        print(f"{Style.DIM}- Crop: {Style.RESET_ALL}{'Yes' if crop_vertical else 'No'}")

    confirm = get_input_with_escape(
        f"{Fore.GREEN}{Style.BRIGHT}\n[ENTER]{Style.NORMAL} Start processing{Style.RESET_ALL}"
        f"{Fore.RED}{Style.BRIGHT}\n[ESC]{Style.NORMAL} Cancel\n{Style.RESET_ALL}> "
    ).strip()

    split_video_ffmpeg(input_path, segment_length, preferences.ENCODER, preferences.GPU_BRAND, crop_vertical=crop_vertical)