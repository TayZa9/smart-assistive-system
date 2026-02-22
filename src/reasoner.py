import time
import json
import config
from src.llm_service import LLMService

class SceneReasoner:
    def __init__(self):
        self.llm = LLMService()
        self.cache = {} # {label: {'last_time': t, 'distance': d, 'position': p}}
        self.cooldown_normal = 10.0 # Don't repeat normal objects for 10s
        self.cooldown_danger = 3.0  # Repeat dangerous objects more often
        self.last_llm_call = 0.0    # Timestamp of last actual LLM API call

    def process(self, detections, frame=None, user_id=None):
        """
        Filters detections and sends to LLMService.
        """
        if not detections:
            return None

        current_time = time.time()
        relevant_objects = []

        for d in detections:
            label = d['label']
            is_dangerous = d['is_dangerous']
            distance = d['distance']
            
            # Check Cache
            should_announce = False
            
            if label not in self.cache:
                should_announce = True
            else:
                last_data = self.cache[label]
                time_diff = current_time - last_data['last_time']
                
                # Rule 1: Time expiration
                cooldown = self.cooldown_danger if is_dangerous else self.cooldown_normal
                if time_diff > cooldown:
                    should_announce = True
                
                # Rule 2: Distance change (Approaching)
                # near > medium > far
                dist_map = {'far': 0, 'medium': 1, 'near': 2}
                if dist_map[distance] > dist_map[last_data['distance']]:
                    should_announce = True
                
                # Rule 3: Dangerous and Approaching (Already covered by dist change, but prioritize)
            
            if should_announce:
                relevant_objects.append(d)
                # Update Cache
                self.cache[label] = {
                    'last_time': current_time, 
                    'distance': distance,
                    'position': d['position']
                }

        if not relevant_objects:
            return None
        
        # Check Global LLM Cooldown
        time_since_last_call = current_time - self.last_llm_call
        if time_since_last_call < config.LLM_COOLDOWN:
            # Skip LLM call if too frequent
            print(f"Skipping LLM call (Cooldown: {config.LLM_COOLDOWN - time_since_last_call:.1f}s remaining)")
            return None

        # Prepare JSON for "LLM"
        metadata = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "objects": relevant_objects
        }
        
        # Call LLM
        response = self.llm.generate_response(json.dumps(metadata), image_data=frame, user_id=user_id)
        if response:
            self.last_llm_call = time.time()
        return response

    def get_summary(self):
        return self.llm.summarize_session()
