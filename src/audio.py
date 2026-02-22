import subprocess
import threading
import queue
import config

class AudioFeedback:
    def __init__(self):
        self.q = queue.Queue()
        self.stopped = False
        self.muted = False
        
        # Start processing thread
        t = threading.Thread(target=self.worker)
        t.daemon = True
        t.start()
        
    def clear_queue(self):
        with self.q.mutex:
            self.q.queue.clear()

    def speak(self, text):
        if self.muted: return
        # We assume if new text comes, it's relevant.
        # Check if queue already has similar item?
        if self.q.qsize() < 2: # Don't build up a huge backlog
            self.q.put(text)

    def worker(self):
        print("Audio Worker Started (PowerShell TTS)")
        while not self.stopped:
            try:
                text = self.q.get(timeout=1)
                print(f"[Audio] Saying: {text}")
                
                # Escape single quotes for PowerShell
                safe_text = text.replace("'", "''").replace('"', '')
                
                # PowerShell Command
                # Rate: -10 to 10. We use 1 for a natural but efficient speed.
                ps_command = (
                    f"Add-Type -AssemblyName System.Speech; "
                    f"$speak = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    f"$speak.Rate = 1; "
                    f"$speak.Speak('{safe_text}');"
                )
                
                # Run PowerShell (blocking until speech finishes)
                # creationflags=0x08000000 (CREATE_NO_WINDOW) prevents console popup
                subprocess.run(
                    ["powershell", "-Command", ps_command], 
                    check=False,
                    creationflags=0x08000000 
                )
                
                self.q.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[Audio] Error: {e}")

    def stop(self):
        self.stopped = True
