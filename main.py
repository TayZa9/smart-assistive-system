import cv2
import time
import config
from src.camera import CameraFeed
from src.detector import ObjectDetector
from src.reasoner import SceneReasoner
from src.audio import AudioFeedback
import threading
import logging
import time

# Configure logging
logging.basicConfig(filename='system.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    print("Initializing Assistive Vision System...")
    
    # Initialize modules
    try:
        # 1. Start Camera Immediately
        camera = CameraFeed().start()
        audio = AudioFeedback()
        reasoner = SceneReasoner()
        
        # 2. Init Detector in Background
        detector = None
        detector_loading = True
        
        def load_detector():
            nonlocal detector, detector_loading
            try:
                print("Loading Object Detector (Background)...")
                detector = ObjectDetector()
                detector_loading = False
                print("Object Detector Loaded.")
                audio.speak("System Ready")
            except Exception as e:
                logging.error(f"Failed to load detector: {e}")
                print(f"Error loading detector: {e}")

        threading.Thread(target=load_detector, daemon=True).start()
        
        print("Camera Started. Waiting for model...")
        
        # Explicitly create window
        cv2.namedWindow("Assistive Vision Feed", cv2.WINDOW_NORMAL)

        frame_count = 0
        last_speech = ""
        current_detections = [] # Persistent storage for rendering

        while True:
            try:
                frame = camera.read()
                
                # If no frame, create a black one with status text
                if frame is None:
                    import numpy as np
                    frame = np.zeros((config.FRAME_HEIGHT, config.FRAME_WIDTH, 3), dtype=np.uint8)
                    cv2.putText(frame, "Waiting for Camera...", (50, 240), cv2.LINE_AA, 1.0, (0, 0, 255), 2)
                    cv2.putText(frame, "Check Console for Errors", (50, 280), cv2.LINE_AA, 0.7, (0, 0, 255), 1)
                    # We still want to show this "error" frame
                    # But we skip detection to save CPU
                else:
                    # Valid frame logic
                    if detector_loading:
                        cv2.putText(frame, "Loading Model...", (20, 50), cv2.LINE_AA, 1.0, (0, 0, 255), 2)
                    
                    elif frame_count % config.DETECTION_INTERVAL == 0:
                         detections = detector.detect(frame)
                         current_detections = detections # Update persistent list
                         
                         message = reasoner.process(detections)
                         if message:
                            print(f"Speaking: {message}")
                            audio.speak(message)
                    
                    # Draw persistent detections on EVERY frame
                    for d in current_detections:
                        box = d['box']
                        label = f"{d['label']} {d['confidence']:.2f}"
                        color = (0, 0, 255) if d['is_dangerous'] else (0, 255, 0)
                        cv2.rectangle(frame, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), color, 2)
                        cv2.putText(frame, label, (int(box[0]), int(box[1]) - 10), cv2.LINE_AA, 0.5, color, 2)

                # Always show and update window
                cv2.imshow("Assistive Vision Feed", frame)
                
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                
                frame_count += 1
            
            except Exception as e:
                logging.error(f"Runtime Error in loop: {e}")
                print(f"Recovering from error: {e}")
                time.sleep(0.1) # Brief pause to avoid log spam if persistent error

    except KeyboardInterrupt:
        pass
    except Exception as e:
        logging.critical(f"Critical System Failure: {e}")
        print(f"Critical Error: {e}")
    finally:
        print("Shutting down...")
        if 'reasoner' in locals():
            summary = reasoner.get_summary()
            print("\n" + "="*30)
            print("SESSION SUMMARY")
            print("="*30)
            print(summary)
            # audio.speak("Session finished.") # Optional
            
        if 'camera' in locals(): camera.stop()
        if 'audio' in locals(): audio.stop()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
