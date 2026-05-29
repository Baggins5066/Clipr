import importlib.util
import os

# Clip length in seconds
CLIP_LENGTH = 60
    # Default: 60

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

LOCAL_PREFERENCES_FILE = "preferences_local.py"


def _load_local_preferences():
    """Load optional local overrides from preferences_local.py if present."""
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), LOCAL_PREFERENCES_FILE)
    if not os.path.isfile(local_path):
        return

    spec = importlib.util.spec_from_file_location("preferences_local", local_path)
    if spec is None or spec.loader is None:
        return

    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:
        return

    # Only known preference keys are allowed to override defaults.
    for key in ("CLIP_LENGTH", "EXPORT_LOCATION", "ENCODER", "GPU_BRAND", "CROP_RATIO", "SHOW_STATS"):
        if hasattr(module, key):
            globals()[key] = getattr(module, key)


_load_local_preferences()