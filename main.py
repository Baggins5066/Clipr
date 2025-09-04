# Clipr (Optimized MoviePy Version)
import os
import sys
import msvcrt
import tkinter as tk
from tkinter import filedialog
from moviepy.editor import VideoFileClip
from colorama import init, Fore, Style
from concurrent.futures import ProcessPoolExecutor
import multiprocessing

init()

# -------------------- Splitting -------------------- #
def export_clip(input_path, start, end, output_name):
    video = VideoFileClip(input_path).subclip(start, end)
    video.write_videofile(
        output_name,
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast",
        threads=os.cpu_count(),
        verbose=False,
        logger=None
    )
    video.close()
    return output_name


def split_video(input_path, segment_length, export_dir="Clips", output_prefix="clip"):
    os.makedirs(export_dir, exist_ok=True)

    video = VideoFileClip(input_path)
    duration = video.duration
    video.close()

    start = 0
    part = 1
    jobs = []
    with ProcessPoolExecutor(max_workers=max(1, multiprocessing.cpu_count() // 2)) as executor:
        while start < duration:
            end = min(start + segment_length, duration)
            output_name = os.path.join(export_dir, f"{output_prefix}_{part}.mp4")
            print(f"Queued {Fore.BLUE}{output_name} ({start:.1f}s - {end:.1f}s){Style.RESET_ALL}")
            jobs.append(executor.submit(export_clip, input_path, start, end, output_name))
            start += segment_length
            part += 1

        for job in jobs:
            job.result()  # Wait for all exports

    print("\n✅ Splitting complete!\n")


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


# -------------------- Main -------------------- #
if __name__ == "__main__":
    import time

    while True:
        input_path = pick_video_file()
        print(f"\nSelected file: {Fore.BLUE}{os.path.basename(input_path)}{Style.RESET_ALL}")

        seconds_str = get_input_with_escape("Enter clip length in seconds:\n> ").strip()
        try:
            segment_length = float(seconds_str)
        except ValueError:
            print("Invalid number for clip length. Try again.")
            continue

        export_dir = "Clips"

        # Get video duration
        video = VideoFileClip(input_path)
        duration = video.duration
        video.close()

        num_clips = int((duration + segment_length - 1) // segment_length)

        # --- Estimate processing time --- #
        print("\nEstimating processing time...")

        first_clip = VideoFileClip(input_path).subclip(0, min(segment_length, duration))
        temp_output = os.path.join(export_dir, "__temp_estimate__.mp4")
        os.makedirs(export_dir, exist_ok=True)

        t0 = time.time()
        try:
            first_clip.write_videofile(
                temp_output,
                codec="libx264",
                audio_codec="aac",
                preset="ultrafast",
                threads=os.cpu_count(),
                verbose=False,
                logger=None
            )
        except Exception as e:
            print(f"{Fore.RED}Estimation failed: {e}{Style.RESET_ALL}")
            est_time = duration / 60
        else:
            t1 = time.time()
            est_time = (t1 - t0) * num_clips / 60  # in minutes
        finally:
            first_clip.close()
            if os.path.exists(temp_output):
                os.remove(temp_output)

        print("\nVideo info:")
        print(f"{Style.DIM}- Duration: {Style.RESET_ALL}{duration/60:.2f} minutes")
        print(f"{Style.DIM}- Clip length: {Style.RESET_ALL}{segment_length/60:.2f} minutes")
        print(f"{Style.DIM}- Number of clips: {Style.RESET_ALL}{num_clips}")
        print(f"{Style.DIM}- Estimated processing time: {Style.RESET_ALL}~{est_time:.2f} minutes")
        print(f"{Style.DIM}- Export directory: {Style.RESET_ALL}{export_dir}")

        confirm = get_input_with_escape(
            f"{Fore.BLUE}{Style.BRIGHT}\n[ENTER]{Style.NORMAL} Start processing"
            f"\n[ESC]{Style.NORMAL} Cancel\n>{Style.RESET_ALL}"
        ).strip()

        if confirm == "cancel":
            print("Restarting...\n")
            continue
        elif confirm != "":
            print("No confirmation received. Exiting.")
            sys.exit(0)
        else:
            split_video(input_path, segment_length, export_dir)
            break