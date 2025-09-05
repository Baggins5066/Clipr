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
def split_video_ffmpeg(input_path, segment_length, export_dir="Clips", crop_vertical=False):
    os.makedirs(export_dir, exist_ok=True)

    # Step 1: Split into equal chunks (super fast, no re-encode)
    split_pattern = os.path.join(export_dir, "part%03d.mp4")
    split_cmd = [
        "ffmpeg", "-i", input_path,
        "-c", "copy", "-map", "0",
        "-f", "segment", "-segment_time", str(segment_length),
        split_pattern
    ]
    print(f"{Fore.BLUE}Splitting video...{Style.RESET_ALL}")
    subprocess.run(split_cmd, check=True)

    if crop_vertical:
        print(f"{Fore.BLUE}Cropping to vertical 9:16...{Style.RESET_ALL}")
        for file in sorted(os.listdir(export_dir)):
            if file.startswith("part") and file.endswith(".mp4"):
                in_path = os.path.join(export_dir, file)
                out_path = os.path.join(export_dir, f"vertical_{file}")
                crop_cmd = [
                    "ffmpeg", "-i", in_path,
                    "-vf", "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920",
                    "-c:a", "aac", out_path
                ]
                subprocess.run(crop_cmd, check=True)

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

    confirm = get_input_with_escape(
        f"{Fore.BLUE}{Style.BRIGHT}\n[ENTER]{Style.NORMAL} Start processing"
        f"\n[ESC]{Style.NORMAL} Cancel\n>{Style.RESET_ALL}"
    ).strip()

    if confirm != "":
        print("No confirmation received. Exiting.")
        sys.exit(0)
    else:
        split_video_ffmpeg(input_path, segment_length, crop_vertical=crop_vertical)
