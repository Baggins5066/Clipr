from moviepy.editor import VideoFileClip

def split_video(input_path, segment_length, output_prefix="clip"):
    # Load video
    video = VideoFileClip(input_path)
    duration = video.duration  # total length in seconds
    
    # Loop through segments
    start = 0
    part = 1
    while start < duration:
        end = min(start + segment_length, duration)
        clip = video.subclip(start, end)
        output_name = f"{output_prefix}_{part}.mp4"
        print(f"Exporting {output_name} ({start:.0f}s - {end:.0f}s)...")
        clip.write_videofile(output_name, codec="libx264", audio_codec="aac", verbose=False, logger=None)
        start += segment_length
        part += 1

if __name__ == "__main__":
    # Ask user for inputs
    input_path = input("Enter the path to your video file: ").strip()
    minutes = float(input("Enter clip length in minutes: "))
    segment_length = int(minutes * 60)  # convert to seconds
    
    split_video(input_path, segment_length)
    print("✅ Splitting complete!")