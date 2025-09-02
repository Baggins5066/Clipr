# Clipr: An app that takes a video and converts it to clips of equal length
from moviepy.editor import VideoFileClip
import os
from tqdm import tqdm
from colorama import init, Fore, Style

init()

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
    print(f"{Fore.WHITE}Exporting{Style.RESET_ALL} {Fore.LIGHTWHITE_EX}{output_name} ({start:.0f}s - {end:.0f}s)...{Style.RESET_ALL}")
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
        print(f"{Fore.WHITE}{prompt}{Style.RESET_ALL}", end='', flush=True)
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
            print(f"{Fore.WHITE}No file selected.{Style.RESET_ALL} {Fore.LIGHTWHITE_EX}Exiting.{Style.RESET_ALL}")
            sys.exit(0)
        return file_path

    import preferences
    while True:
        # Open file picker automatically
        input_path = pick_video_file()
        print(f"\n{Fore.WHITE}Selected file: {Fore.BLUE}{os.path.basename(input_path)}{Style.RESET_ALL}")
        seconds_str = get_input_with_escape("Enter clip length in seconds:\n> ").strip()
        try:
            seconds = float(seconds_str)
        except ValueError:
            print(f"{Fore.WHITE}Invalid number for clip length.{Style.RESET_ALL} {Fore.LIGHTWHITE_EX}Try again.{Style.RESET_ALL}")
            continue
        segment_length = int(seconds)
        export_dir = preferences.EXPORT_LOCATION

        # Gather video info
        try:
            video = VideoFileClip(input_path)
            duration = video.duration
        except Exception as e:
            print(f"{Fore.WHITE}Error loading video:{Style.RESET_ALL} {Fore.LIGHTWHITE_EX}{e}{Style.RESET_ALL}")
            continue

        num_clips = int((duration + segment_length - 1) // segment_length)
        est_time = duration  # rough estimate: 1x video duration
        print(f"{Fore.WHITE}\nVideo info:")
        print(f"{Fore.WHITE}- Duration:{Style.RESET_ALL} {Fore.LIGHTWHITE_EX}{duration:.2f} seconds{Style.RESET_ALL}")
        print(f"{Fore.WHITE}- Clip length:{Style.RESET_ALL} {Fore.LIGHTWHITE_EX}{segment_length} seconds{Style.RESET_ALL}")
        print(f"{Fore.WHITE}- Number of clips:{Style.RESET_ALL} {Fore.LIGHTWHITE_EX}{num_clips}{Style.RESET_ALL}")
        print(f"{Fore.WHITE}- Estimated processing time:{Style.RESET_ALL} {Fore.LIGHTWHITE_EX}{est_time:.1f} seconds (actual may vary){Style.RESET_ALL}")
        print(f"{Fore.WHITE}- Export directory:{Style.RESET_ALL} {Fore.LIGHTWHITE_EX}{export_dir}{Style.RESET_ALL}")

        confirm = get_input_with_escape("\n[ENTER] Start splitting\n[ESC] Cancel\n>").strip().lower()
        if confirm == "cancel":
            print(f"{Fore.WHITE}Restarting...{Style.RESET_ALL}\n")
            continue
        elif confirm != "":
            print(f"{Fore.WHITE}No confirmation received.{Style.RESET_ALL} {Fore.LIGHTWHITE_EX}Exiting.{Style.RESET_ALL}")
            sys.exit(0)
        else:
            split_video(input_path, segment_length, export_dir)
            print(f"{Fore.WHITE}✅ Splitting complete!{Style.RESET_ALL}")
            break