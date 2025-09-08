# Export location for clips
EXPORT_LOCATION = r"Exports"
    # Default: "Exports" in current directory

# Encoding method
ENCODER = '1'
    # [1] High quality CPU encoding
    # [2] Fast GPU encoding
# GPU brand (If using GPU encoding)
GPU_BRAND = '1'
    # [1] NVIDIA
    # [2] Intel
    # [3] AMD

# Crop ratio
CROP_RATIO = '9:16'
    # Common aspect ratios:
        # 1:2 (Vertical)
        # 9:16 (Vertical)
        # 2:3 (Vertical)
        # 5:7 (Vertical)
        # 3:4 (Vertical)
        # 4:5 (Vertical)
        # 1:1 (Square)
        # 5:4 (Horizontal)
        # 4:3 (Horizontal)
        # 7:5 (Horizontal)
        # 3:2 (Horizontal)
        # 16:9 (Horizontal)
        # 2.39:1 (Cinematic Horizontal)

# Show stats during processing
SHOW_STATS = False
    # [True] Advanced information will be shown during processing
    # [False] Only essential information will be shown during processing