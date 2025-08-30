import os
import subprocess
import math
def get_video_duration(video_path):
    # Use ffprobe to get video duration
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', video_path
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        return float(result.stdout)
    except Exception:
        print('Could not get video duration.')
        return None

def split_video_ffmpeg(video_path, clip_length, output_folder):
    duration = get_video_duration(video_path)
    if duration is None:
        print('Error: Unable to get video duration.')
        return
    num_clips = math.ceil(duration / clip_length)
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    os.makedirs(output_folder, exist_ok=True)
    for i in range(num_clips):
        start = i * clip_length
        out_file = os.path.join(output_folder, f"{base_name}_part{i+1}.mp4")
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-ss', str(start), '-t', str(clip_length),
            '-c', 'copy', out_file
        ]
        print(f"Creating clip {i+1}/{num_clips}: {out_file}")
        subprocess.run(cmd)
    print('Splitting complete!')

def main():
    video_path = input('Enter path to video file: ')
    clip_length = float(input('Enter clip length in seconds: '))
    output_folder = input('Enter output folder for clips: ')
    split_video_ffmpeg(video_path, clip_length, output_folder)

if __name__ == "__main__":
    main()