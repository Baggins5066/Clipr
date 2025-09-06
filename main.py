# Clipr (FFmpeg version with preview)
import os
import sys
import msvcrt
import tkinter as tk
from tkinter import filedialog
import subprocess
from colorama import init, Fore, Style

init()

# -------------------- Input Helpers -------------------- #
def get_input_with_escape(prompt):
    print(f"{prompt}", end='', flush=True)
    chars = []
    while True:
        ch = msvcrt.getwch()
        if ch == '\r' or ch == '\n':
            print()
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
        filetypes=[("Video files", "*.mp4;*.avi;*.mov;*.mkv;*.flv;*.wmv"),
                   ("All files", "*.*")]
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
        duration, size = result.stdout.strip().splitlines()
        return float(duration), int(size)
    except Exception as e:
        print(f"{Fore.RED}ffprobe failed: {e}{Style.RESET_ALL}")
        return 0, 0

# -------------------- Splitting -------------------- #
def split_video_ffmpeg(input_path, segment_length, encoder_type, gpu_brand, export_dir="Clips", crop_vertical=False):
    os.makedirs(export_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    duration, _ = get_video_info(input_path)

    if duration == 0:
        print(f"{Fore.YELLOW}Warning: Could not get video duration. Cannot proceed with splitting.{Style.RESET_ALL}")
        return

    print(f"{Fore.BLUE}Processing clips...{Style.RESET_ALL}")

    if encoder_type == '1': # CPU Encoding
        video_codec = "libx264"
        crf = "18"
        print(f"{Fore.CYAN}Using CPU encoding for high quality. This may take longer.{Style.RESET_ALL}")
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
        print(f"{Fore.CYAN}Using GPU encoding for speed. Quality may vary.{Style.RESET_ALL}")

    start_time = 0
    clip_count = 0
    while start_time < duration:
        clip_count += 1
        end_time = min(start_time + segment_length, duration)
        
        start_time_str = f"{int(start_time):02d}"
        end_time_str = f"{int(end_time):02d}"
        
        new_filename = f"{base_name}_{start_time_str}-{end_time_str}.mp4"
        out_path = os.path.join(export_dir, new_filename)

        # Base FFmpeg command with acceleration
        cmd = [
            "ffmpeg",
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
            cmd.insert(-1, "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920")

        try:
            subprocess.run(cmd, check=True)
            print(f"✅ Created clip: {new_filename}")
        except subprocess.CalledProcessError as e:
            print(f"{Fore.RED}Error processing clip {new_filename}: {e}{Style.RESET_ALL}")
        
        start_time += segment_length

    print("\n✅ Processing complete!\n")

# -------------------- Main -------------------- #
if __name__ == "__main__":
    input_path = pick_video_file()
    print(f"\nSelected file: {Fore.BLUE}{os.path.basename(input_path)}{Style.RESET_ALL}")

    seconds_str = get_input_with_escape("Enter clip length in seconds:\n> ").strip()
    try:
        segment_length = int(seconds_str)
    except ValueError:
        print("Invalid number for clip length. Exiting.")
        sys.exit(0)

    crop_choice = get_input_with_escape("Crop to Shorts vertical format? (y/n):\n> ").strip().lower()
    crop_vertical = crop_choice == "y"
    
    encoder_choice = get_input_with_escape("Choose encoding type:\n[1] High quality (CPU)\n[2] GPU encoding\n> ").strip()

    gpu_brand = None
    if encoder_choice == '2':
        gpu_brand = get_input_with_escape("Choose your GPU brand:\n[1] NVIDIA\n[2] Intel\n[3] AMD\n> ").strip()

    # --- Preview Info --- #
    duration, size = get_video_info(input_path)
    if duration == 0:
        print("Could not read video info, continuing without preview...")
    else:
        num_clips = int((duration + segment_length - 1) // segment_length)
        est_size = size  # splitting copies streams → size ≈ same as input
        if crop_vertical:
            print(f"\n{Fore.YELLOW}Note: Cropping requires re-encoding, output size may differ significantly.{Style.RESET_ALL}")

        print("\nVideo info:")
        print(f"{Style.DIM}- Duration: {Style.RESET_ALL}{duration/60:.2f} minutes")
        print(f"{Style.DIM}- Clip length: {Style.RESET_ALL}{segment_length/60:.2f} minutes")
        print(f"{Style.DIM}- Number of clips: {Style.RESET_ALL}{num_clips}")
        print(f"{Style.DIM}- Estimated total output size: {Style.RESET_ALL}{est_size/1e6:.2f} MB")

    split_video_ffmpeg(input_path, segment_length, encoder_choice, gpu_brand, crop_vertical=crop_vertical)