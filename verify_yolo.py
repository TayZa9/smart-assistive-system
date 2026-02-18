from ultralytics import YOLO
import cv2
import numpy as np
import sys

try:
    print("Loading YOLOv26 model...")
    # This should trigger download if not present
    try:
        model = YOLO("yolo26n.pt") 
    except Exception:
        print("yolo26n.pt failed, trying yolov26n.pt...")
        model = YOLO("yolov26n.pt") 
    print("Model loaded successfully.")
    
    # Create a dummy image
    img = np.zeros((640, 640, 3), dtype=np.uint8)
    
    # Run inference
    print("Running inference on dummy image...")
    results = model(img)
    print("Inference successful.")
    
    print("YOLOv26 verification passed!")
except Exception as e:
    print(f"Verification FAILED: {e}")
    sys.exit(1)
