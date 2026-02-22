import json
import time
import logging
import threading
import io
import os
import cv2
import numpy as np
from PIL import Image
import config
import logging
import threading
import config
from src.data_logger import DataLogger
from src.vector_store import VectorStore
try:
    from google import genai
except ImportError:
    genai = None

class LLMService:
    def __init__(self):
        self.session_data = {
            "objects_seen": {},
            "dangerous_events": 0,
            "start_time": time.time()
        }
        self.logger = DataLogger()
        self.logged_objects = {} # Stores time of last log per label
        
        # Configure Gemini (New SDK)
        self.client = None
        if genai and config.GOOGLE_API_KEY:
            try:
                self.client = genai.Client(api_key=config.GOOGLE_API_KEY)
                self.model_name = 'gemini-2.0-flash' 
            except Exception as e:
                logging.error(f"Failed to init Gemini Client: {e}")
                self.client = None
        elif not genai:
            logging.warning("google-genai library not installed. LLM features disabled.")
            print("⚠️ google-genai library not installed.")
        else:
            logging.warning("No Google API Key found. LLM features disabled.")



        # Initialize VectorStore in background to not block startup if slow
        self.vector_store = None
        threading.Thread(target=self._init_vector_store, daemon=True).start()

    def _init_vector_store(self):
        try:
            self.vector_store = VectorStore()
            logging.info("VectorStore initialized.")
        except Exception as e:
            logging.error(f"VectorStore init failed: {e}")

    def generate_response(self, metadata_json, image_data=None, target_language=config.TARGET_LANGUAGE, user_id=None):
        """
        Generates a spoken response from the LLM based on metadata and optional image using Google Gemini.
        """
        data = json.loads(metadata_json)
        objects = data.get("objects", [])
        timestamp = data.get("timestamp")
        
        # Log & Embed for Session summary and RAG (Keep existing logic)
        if objects:
            for obj in objects:
                label = obj['label']
                # Session Tracking
                self.session_data["objects_seen"][label] = self.session_data["objects_seen"].get(label, 0) + 1
                if obj['is_dangerous']:
                    self.session_data["dangerous_events"] += 1
                
                # Persistent Logging (with cooldown)
                current_time = time.time()
                if current_time - self.logged_objects.get(label, 0) > 60:
                    self.logger.log({
                        "timestamp": timestamp,
                        "type": "detection",
                        "label": label,
                        "metadata": obj
                    })
                    self.logged_objects[label] = current_time

                # Vector Store Embedding (Async) - simplified usage
                if self.vector_store:
                    desc = f"A {obj['distance']} {label} at {obj['position']}."
                    threading.Thread(target=self.vector_store.add, args=(desc, {"label": label, "timestamp": timestamp}), daemon=True).start()

        # Construct Prompt
        object_descriptions = []
        contains_person = False
        
        for obj in objects:
            desc = f"- {obj['label']} at {obj['position']} (distance: {obj['distance']})"
            if obj['is_dangerous']: desc += " [DANGEROUS]"
            object_descriptions.append(desc)
            if 'person' in obj['label'].lower():
                contains_person = True
        
        context_str = "\\n".join(object_descriptions) if object_descriptions else "No specific objects detected by basic sensors."

        prompt_prefix = (
            f"You are an assistive vision assistant for a visually impaired user. "
            f"I will provide an image of what is in front of the user, and a list of objects detected by sensors.\\n"
        )
        
        user_faces = []
        if contains_person and user_id:
            from src.database import SessionLocal, ReferenceFace
            db = SessionLocal()
            try:
                faces = db.query(ReferenceFace).filter(ReferenceFace.user_id == user_id).all()
                for face in faces:
                    if os.path.exists(face.file_path):
                        try:
                            img = Image.open(face.file_path)
                            img.load()
                            user_faces.append({"name": face.name, "image": img})
                        except Exception as e:
                            logging.error(f"Failed to load user face {face.file_path}: {e}")
            finally:
                db.close()
                
        if contains_person and user_faces:
            prompt_prefix += "I've also provided reference images of known people. Compare any faces in the main image to these references. If you recognize them, refer to them by name. Explicitly describe their emotion or expressions.\\n"

        prompt_body = (
            f"Sensor Detections:\\n{context_str}\\n\\n"
            f"Task: Analyze the main image and the detections. Provide a helpful, safety-focused spoken notification in {target_language}. "
            f"If there is text in the image, read it if relevant. Describe important details that sensors might miss. "
            f"Strictly follow this format: 'There is [description]. [Navigational guidance]'. "
            f"Keep it concise, under 2 sentences. Prioritize immediate safety hazards."
        )

        # Call Gemini (Multimodal)
        if self.client:
            try:
                contents = []
                
                # Prepend reference faces if a person is in the scene
                if contains_person and user_faces:
                    for kf in user_faces:
                        contents.append(f"Reference Image: {kf['name']}")
                        contents.append(kf['image'])
                
                contents.append(prompt_prefix + prompt_body)
                
                if image_data is not None:
                    # Convert numpy array (OpenCV) to PIL Image
                    if isinstance(image_data, np.ndarray):
                        # OpenCV is BGR, PIL needs RGB
                        img_rgb = cv2.cvtColor(image_data, cv2.COLOR_BGR2RGB)
                        pil_img = Image.fromarray(img_rgb)
                        contents.append("Main Image:")
                        contents.append(pil_img)
                    else:
                        logging.warning("Image data provided but not a numpy array. Skipping image.")

                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=contents
                )
                return response.text
            except Exception as e:
                logging.error(f"Gemini API Error: {e}")
                print(f"⚠️ Gemini API Error (Using Fallback): {e}")
                return self._fallback_heuristic(objects)
        else:
            return self._fallback_heuristic(objects)


    def _fallback_heuristic(self, objects):
        """Fallback if LLM is unavailable"""
        objects.sort(key=lambda x: (not x['is_dangerous'], x['distance'] != 'near'))
        parts = []
        for obj in objects[:3]: 
            label = obj['label']
            pos = obj['position']
            dist = obj['distance']
            desc = f"{label} on {pos}"
            if obj['is_dangerous']: 
                desc += f", {dist}"
            parts.append(desc)
        return ". ".join(parts)

    def summarize_session(self):
        """
        Returns a session summary string.
        """
        duration = int(time.time() - self.session_data["start_time"])
        top_objects = sorted(self.session_data["objects_seen"].items(), key=lambda x: x[1], reverse=True)[:5]
        top_str = ", ".join([f"{k} ({v})" for k, v in top_objects])
        
        return (f"Session ended. Duration: {duration} seconds. "
                f"Dangerous events: {self.session_data['dangerous_events']}. "
                f"Common objects: {top_str}.")

    def ask(self, question):
        """
        Answers a user question based on past detections (RAG).
        """
        if not self.vector_store:
            return "Memory is not available (Vector Store disabled)."
            
        # 1. Retrieve Context
        try:
            results = self.vector_store.query(question, n_results=5)
            # metadata can contain timestamp, handle empty results
            context_docs = results['documents'][0] if results and 'documents' in results and results['documents'] else []
            context_str = "\\n".join(context_docs) if context_docs else "No relevant past detections found."
        except Exception as e:
            logging.error(f"RAG Query execution failed: {e}")
            context_str = "Error retrieving memory."

        # 2. Construct Prompt
        prompt = (
            f"You are the memory of an assistive vision system. "
            f"The user is asking a question about what has been seen recently.\\n\\n"
            f"Relevant Past Detections (Context):\\n{context_str}\\n\\n"
            f"User Question: {question}\\n\\n"
            f"Answer the question directly and concisely based ONLY on the provided context. "
            f"If the answer is not in the context, say 'I haven't seen that recently.' "
            f"Do not hallucinate. Mention time or location if available in context."
        )
        
        # 3. Call LLM
        if self.client:
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt
                )
                return response.text
            except Exception as e:
                logging.error(f"Gemini Memory Answer Error: {e}")
                return "I'm sorry, I couldn't process your question right now."
        else:
            return "LLM is not connected."
