import cv2
import time
import logging
import threading
import asyncio
import json
from fastapi import FastAPI, Request, HTTPException, Depends, File, UploadFile, Form
from fastapi.responses import StreamingResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from queue import Queue
from starlette.middleware.sessions import SessionMiddleware
import os
import shutil

import config
from src.camera import CameraFeed
from src.detector import ObjectDetector
from src.reasoner import SceneReasoner
from src.audio import AudioFeedback
from src.database import init_db, get_db, User, ReferenceFace
from src.auth import auth_router
from sqlalchemy.orm import Session

# Configure logging
logging.basicConfig(filename='system.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

init_db()

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY)
app.include_router(auth_router)

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
system_status = "Inactive"
current_fps = 0
lock = threading.Lock()
active_user_id = None # Tracks the physically active user for background detection
system_active = False # Tracks if the camera and detection loop are running
show_overlays = True  # Controls bounding box rendering in video_feed

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
    global current_detections, system_status, latest_frame, latest_llm_response, current_fps, system_active
    
    frame_count = 0
    print("Starting Detection Loop thread...")
    last_loop_time = time.time()
    
    while True:
        try:
            if not system_active:
                time.sleep(0.5)
                last_loop_time = time.time()
                continue
                
            system_status = "Running"
            
            cam = get_camera()
            det = get_detector()
            res = get_reasoner()
            aud = get_audio()
            
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
                    
                    if res:
                        res_text = res.process(detections, frame=frame, user_id=active_user_id)
                        if res_text:
                            with lock:
                                latest_llm_response = res_text
                                
                            # Also speak it
                            if aud:
                                aud.speak(res_text)
            
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
    if not request.session.get('user_id'):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("index.html", {"request": request})

def generate_frames():
    global latest_frame, current_detections, show_overlays, system_active
    
    import numpy as np
    
    # Pre-generate a black placeholder image with text for when inactive
    placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(placeholder, "System Inactive", (200, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    _, placeholder_buffer = cv2.imencode('.jpg', placeholder)
    placeholder_bytes = placeholder_buffer.tobytes()
    # Pre-generate a black placeholder image for camera error
    placeholder_err = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(placeholder_err, "Camera Error / No Feed", (140, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
    _, err_buffer = cv2.imencode('.jpg', placeholder_err)
    err_bytes = err_buffer.tobytes()
    
    while True:
        if not system_active:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + placeholder_bytes + b'\r\n')
            time.sleep(1) # Send placeholder slowly
            continue

        with lock:
            frame_to_send = latest_frame.copy() if latest_frame is not None else None

        if frame_to_send is None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + err_bytes + b'\r\n')
            time.sleep(1) # Send error placeholder slowly
            continue
            
        frame = frame_to_send
        
        # Draw detections
        if show_overlays:
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

class SystemStateRequest(BaseModel):
    active: bool

@app.post("/api/system/state")
async def set_system_state(req: SystemStateRequest, request: Request):
    global system_active, camera, audio, system_status
    user_id = request.session.get('user_id')
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    
    system_active = req.active
    
    if req.active:
        system_status = "Starting..."
    else:
        system_status = "Inactive"
        # Release the hardware components to save power when inactive
        with lock:
            if camera:
                camera.stop()
                camera = None
    
    return {"status": "success", "active": system_active}

@app.get("/api/status")
async def get_status():
    return JSONResponse({
        "status": system_status,
        "detections": current_detections,
        "fps": int(current_fps) if system_active else 0,
        "llm_response": latest_llm_response,
        "logs": get_recent_logs(),
        "system_active": system_active
    })

@app.get("/api/user/me")
async def get_current_user_info(request: Request, db: Session = Depends(get_db)):
    global active_user_id
    user_id = request.session.get('user_id')
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
        
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
        
    # Set this as the active user for the physical system's background thread
    active_user_id = user.id
        
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "avatar_url": user.avatar_url,
        "settings_json": user.settings_json
    }

class QuestionRequest(BaseModel):
    question: str

@app.post("/api/ask")
async def ask_question(request: QuestionRequest):
    res = get_reasoner()
    answer = res.llm.ask(request.question)
    return {"answer": answer}

class AudioStateRequest(BaseModel):
    muted: bool

@app.post("/api/audio/state")
async def set_audio_state(request: AudioStateRequest):
    aud = get_audio()
    if request.muted:
        aud.muted = True
        aud.clear_queue()
    else:
        aud.muted = False
    return {"status": "success", "muted": aud.muted}

class OverlayRequest(BaseModel):
    show: bool

@app.post("/api/settings/overlays")
async def toggle_overlays(request: OverlayRequest, req: Request, db: Session = Depends(get_db)):
    global show_overlays
    show_overlays = request.show
    user_id = req.session.get('user_id')
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        settings = json.loads(user.settings_json) if user.settings_json else {}
        settings['show_overlays'] = request.show
        user.settings_json = json.dumps(settings)
        db.commit()
    return {"status": "success", "show_overlays": request.show}

@app.get("/api/faces")
async def get_my_faces(req: Request, db: Session = Depends(get_db)):
    user_id = req.session.get('user_id')
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    faces = db.query(ReferenceFace).filter(ReferenceFace.user_id == user_id).all()
    return [{"id": f.id, "name": f.name} for f in faces]

@app.post("/api/faces")
async def upload_face(req: Request, name: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    user_id = req.session.get('user_id')
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    
    # Save file
    safe_name = name.replace(" ", "_").lower()
    filename = f"{user_id}_{safe_name}_{file.filename}"
    filepath = os.path.join("src/faces", filename)
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Add to DB
    face = ReferenceFace(user_id=user_id, name=name, file_path=filepath)
    db.add(face)
    db.commit()
    
    return {"status": "success", "id": face.id, "name": face.name}

@app.delete("/api/faces/{face_id}")
async def delete_face(face_id: int, req: Request, db: Session = Depends(get_db)):
    user_id = req.session.get('user_id')
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    
    face = db.query(ReferenceFace).filter(ReferenceFace.id == face_id, ReferenceFace.user_id == user_id).first()
    if not face:
        raise HTTPException(status_code=404, detail="Face not found")
        
    if os.path.exists(face.file_path):
        os.remove(face.file_path)
        
    db.delete(face)
    db.commit()
    return {"status": "success"}


