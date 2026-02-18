import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Fallback to manual parsing if dotenv is missing
    try:
        with open('.env') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'): continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value
    except Exception:
        pass

# Camera Settings
# Use integer 0 for webcam, or string URL for IP Camera
# RTSP Stream URL with Authentication
# REPLACE 'user' and 'password' with your real camera credentials
# CAMERA_ID = "rtsp://admin:admin@192.168.1.111:8554/live"
CAMERA_ID = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
FPS = 30

# Detection Settings
MODEL_PATH = "yolo26n.pt"  # Will be downloaded automatically by ultralytics
CONFIDENCE_THRESHOLD = 0.5
DETECTION_INTERVAL = 30  # Run detection every N frames to save resources

# Audio Settings
TTS_RATE = 150  # Words per minute
TTS_VOLUME = 1.0

# Context Reasoning
# For now, we use a simple heuristic. 
# If you enable an LLM, put the API key here or in env vars.
# If you want to use a real LLM, set logic in llm_service.py to use this key.
USE_LLM = True 
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
LLM_COOLDOWN = 15.0 # Seconds between LLM calls to avoid Rate Limits (Free Tier)

# Advanced Settings
TARGET_LANGUAGE = "English"

# Safety
DANGEROUS_OBJECTS = {"car", "truck", "bus", "motorcycle", "train", "knife", "scissors", "fire hydrant"}
# Heuristic for "Dangerous" if approaching or close.

# Distance Estimation (Naive heuristic based on bbox area relative to frame size)
# These thresholds are fractions of total frame area
AREA_NEAR = 0.30
AREA_MEDIUM = 0.10
# Below 0.10 is "far"
