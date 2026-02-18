import cv2
import time
import logging
import threading
import asyncio
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from queue import Queue

import config
from src.camera import CameraFeed
from src.detector import ObjectDetector
from src.reasoner import SceneReasoner
from src.audio import AudioFeedback

# Configure logging
logging.basicConfig(filename='system.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="src/static"), name="static")

# Templates
templates = Jinja2Templates(directory="src/templates")

# Global State
camera = None
detector = None
reasoner = None
audio = None
current_detections = []
latest_frame = None
latest_llm_response = "Welcome. System is listening."  # Store the latest LLM text
system_status = "Initializing..."
current_fps = 0
lock = threading.Lock()

def get_camera():
    global camera
    if camera is None:
        camera = CameraFeed().start()
    return camera

def get_detector():
    global detector
    if detector is None:
        try:
            print("Loading Object Detector...")
            detector = ObjectDetector()
            print("Object Detector Loaded.")
        except Exception as e:
            logging.error(f"Failed to load detector: {e}")
            print(f"Error loading detector: {e}")
    return detector

def get_reasoner():
    global reasoner
    if reasoner is None:
        reasoner = SceneReasoner()
    return reasoner

def get_audio():
    global audio
    if audio is None:
        audio = AudioFeedback()
    return audio

def get_recent_logs(n=20):
    """Reads the last n lines from detections.jsonl and formats them."""
    log_file = "detections.jsonl"
    logs = []
    try:
        with open(log_file, "r") as f:
            # Efficiently read last n lines (for small files readlines is fine, 
            # for huge files we'd use seek, but this is simple enough for now)
            lines = f.readlines()
            last_n = lines[-n:]
            
            for line in last_n:
                try:
                    data = json.loads(line)
                    timestamp = data.get("timestamp", "").split("T")[-1].split(".")[0] # Extract HH:MM:SS
                    label = data.get("label", "unknown")
                    conf = data.get("metadata", {}).get("confidence", 0)
                    logs.append(f"[{timestamp}] Detected {label} ({conf:.2f})")
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        logs.append("Log file not found.")
    except Exception as e:
        logs.append(f"Error reading logs: {e}")
    # print(f"DEBUG LOGS: {len(logs)} entries found")
    return logs

# Background Task for Detection
def detection_loop():
    global current_detections, system_status, latest_frame, latest_llm_response, current_fps
    
    cam = get_camera()
    det = get_detector()
    res = get_reasoner()
    aud = get_audio()
    
    system_status = "Running"
    frame_count = 0
    
    print("Starting Detection Loop...")
    last_loop_time = time.time()
    
    while True:
        try:
            frame = cam.read()
            if frame is None:
                time.sleep(0.1)
                continue
            
            # Update latest frame for streaming
            with lock:
                latest_frame = frame.copy()

            if frame_count % config.DETECTION_INTERVAL == 0:
                if det:
                    detections = det.detect(frame)
                    current_detections = detections
                    
                    # Reason and Speak
                    message = res.process(detections, frame=frame)
                    if message:
                        print(f"Speaking: {message}")
                        with lock:
                             latest_llm_response = message # Store for Web UI
                        aud.speak(message)
            
            frame_count += 1
            
            # FPS Calculation
            current_time = time.time()
            elapsed = current_time - last_loop_time
            if elapsed > 0:
                fps = 1.0 / elapsed
                current_fps = 0.9 * current_fps + 0.1 * fps # Smoothing
            last_loop_time = current_time

            time.sleep(0.01) # Small sleep to prevent tight loop
            
        except Exception as e:
            logging.error(f"Error in detection loop: {e}")
            time.sleep(1)

# Start detection in background
@app.on_event("startup")
async def startup_event():
    threading.Thread(target=detection_loop, daemon=True).start()

@app.on_event("shutdown")
async def shutdown_event():
    print("Shutting down...")
    if camera: camera.stop()
    if audio: audio.stop()

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

def generate_frames():
    global latest_frame, current_detections
    
    while True:
        with lock:
            if latest_frame is None:
                time.sleep(0.1)
                continue
            
            frame = latest_frame.copy()
        
        # Draw detections
        for d in current_detections:
            box = d['box']
            label = f"{d['label']} {d['confidence']:.2f}"
            color = (0, 0, 255) if d.get('is_dangerous') else (0, 255, 0)
            cv2.rectangle(frame, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), color, 2)
            cv2.putText(frame, label, (int(box[0]), int(box[1]) - 10), cv2.LINE_AA, 0.5, color, 2)
            
        ret, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        
        time.sleep(0.03) # ~30 FPS

@app.get("/video_feed")
async def video_feed():
    return StreamingResponse(generate_frames(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/api/status")
async def get_status():
    return JSONResponse({
        "status": system_status,
        "detections": current_detections,
        "fps": int(current_fps),
        "llm_response": latest_llm_response,
        "llm_response": latest_llm_response,
        "logs": get_recent_logs()
    })

class QuestionRequest(BaseModel):
    question: str

@app.post("/api/ask")
async def ask_question(request: QuestionRequest):
    res = get_reasoner()
    answer = res.llm.ask(request.question)
    return {"answer": answer}
