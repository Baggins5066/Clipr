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
        print(f"Exporting {output_name} ({start:.0f}s - {end:.0f}s)...")
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
            def iter_bar(self, chunk):
                for i in chunk:
                    self.pbar.update(1)
                    yield i
                self.pbar.close()
        logger = TqdmLogger(int(clip_duration))
        clip.write_videofile(output_name, codec="libx264", audio_codec="aac", verbose=False, logger=logger)
        start += segment_length
        part += 1

if __name__ == "__main__":
    # Ask user for inputs
    input_path = input("Enter the path to your video file: ").strip()
    seconds = float(input("Enter clip length in seconds: "))
    segment_length = int(seconds)  # convert to seconds
    export_dir = input("Enter export directory for clips (default: Clips): ").strip()
    if not export_dir:
        export_dir = "Clips"
    split_video(input_path, segment_length, export_dir)
    print("✅ Splitting complete!")