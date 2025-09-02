# Clipr: An app that takes a video and converts it to clips of equal length
from moviepy.editor import VideoFileClip
import os
from tqdm import tqdm

def split_video(input_path, segment_length, export_dir="Clips", output_prefix="clip"):
    # Load video
    video = VideoFileClip(input_path)
    duration = video.duration  # total length in seconds
    
    # Loop through segments
    start = 0
    part = 1
    os.makedirs(export_dir, exist_ok=True)
    while start < duration:
        end = min(start + segment_length, duration)
        clip = video.subclip(start, end)
        output_name = os.path.join(export_dir, f"{output_prefix}_{part}.mp4")
        print(f"\033[97mExporting\033[0m \033[37m{output_name} ({start:.0f}s - {end:.0f}s)...\033[0m")
        clip_duration = end - start
        class TqdmLogger:
            def __init__(self, total):
                self.pbar = tqdm(total=total, desc=f"Trimming {output_name}", unit="sec")
            def __call__(self, **kwargs):
                if 'progress' in kwargs:
                    self.pbar.n = int(kwargs['progress'] * self.pbar.total)
                    self.pbar.refresh()
                if kwargs.get('progress') == 1:
                    self.pbar.n = self.pbar.total
                    self.pbar.refresh()
                    self.pbar.close()
            def iter_bar(self, **kwargs):
                # MoviePy passes the iterable as a keyword argument, e.g. t=...
                iterable = None
                if 'chunk' in kwargs:
                    iterable = kwargs['chunk']
                elif 't' in kwargs:
                    iterable = kwargs['t']
                else:
                    # fallback: get the first value
                    iterable = next(iter(kwargs.values()))
                for i in iterable:
                    self.pbar.update(1)
                    yield i
                self.pbar.close()
        logger = TqdmLogger(int(clip_duration))
        clip.write_videofile(output_name, codec="libx264", audio_codec="aac", verbose=False, logger=logger)
        start += segment_length
        part += 1

if __name__ == "__main__":
    import sys
    import msvcrt

    def get_input_with_escape(prompt):
        print(f"\033[97m{prompt}\033[0m", end='', flush=True)
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

    import tkinter as tk
    from tkinter import filedialog

    def pick_video_file():
        root = tk.Tk()
        root.withdraw()
        file_path = filedialog.askopenfilename(
            title="Select video file",
            filetypes=[("Video files", "*.mp4;*.avi;*.mov;*.mkv;*.flv;*.wmv"), ("All files", "*.*")]
        )
        root.destroy()
        if not file_path:
            print("\033[97mNo file selected.\033[0m \033[37mExiting.\033[0m")
            sys.exit(0)
        return file_path

    import preferences
    while True:
        # Open file picker automatically
        input_path = pick_video_file()
        print(f"\n\033[97mSelected file: \033[94m{os.path.basename(input_path)}\033[0m")
        seconds_str = get_input_with_escape("Enter clip length in seconds:\n> ").strip()
        try:
            seconds = float(seconds_str)
        except ValueError:
            print("\033[97mInvalid number for clip length.\033[0m \033[37mTry again.\033[0m")
            continue
        segment_length = int(seconds)
        export_dir = preferences.EXPORT_LOCATION

        # Gather video info
        try:
            video = VideoFileClip(input_path)
            duration = video.duration
        except Exception as e:
            print(f"\033[97mError loading video:\033[0m \033[37m{e}\033[0m")
            continue

        num_clips = int((duration + segment_length - 1) // segment_length)
        est_time = duration  # rough estimate: 1x video duration
        print(f"\n\033[97mVideo info:\033[0m")
        print(f"\033[97m- Duration:\033[0m \033[37m{duration:.2f} seconds\033[0m")
        print(f"\033[97m- Clip length:\033[0m \033[37m{segment_length} seconds\033[0m")
        print(f"\033[97m- Number of clips:\033[0m \033[37m{num_clips}\033[0m")
        print(f"\033[97m- Estimated processing time:\033[0m \033[37m{est_time:.1f} seconds (actual may vary)\033[0m")
        print(f"\033[97m- Export directory:\033[0m \033[37m{export_dir}\033[0m")

        confirm = get_input_with_escape("\n[ENTER] Start splitting\n[ESC] Cancel\n>").strip().lower()
        if confirm == "cancel":
            print("\033[97mRestarting...\033[0m\n")
            continue
        elif confirm != "":
            print("\033[97mNo confirmation received.\033[0m \033[37mExiting.\033[0m")
            sys.exit(0)
        else:
            split_video(input_path, segment_length, export_dir)
            print("\033[97m✅ Splitting complete!\033[0m")
            break