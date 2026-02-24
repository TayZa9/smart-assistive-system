# Smart Assistive System – Codebase Analysis

## High-level architecture

The project is structured around a real-time assistive vision pipeline:

- **Capture**: `CameraFeed` continuously reads frames from OpenCV (`src/camera.py`).
- **Perception**: `ObjectDetector` runs YOLO and enriches detections with distance/position/safety metadata (`src/detector.py`).
- **Reasoning + narration**: `SceneReasoner` filters events with cooldown logic and forwards relevant detections to `LLMService` (`src/reasoner.py`, `src/llm_service.py`).
- **Output**: spoken feedback is queued through `AudioFeedback` (`src/audio.py`).
- **Serving/UI**: FastAPI web app exposes stream/state/auth endpoints and runs detection in a background thread (`src/web_server.py`).
- **Persistence**: SQLite for users/faces/settings (`src/database.py`), JSONL for event logs (`src/data_logger.py`), Chroma for retrieval memory (`src/vector_store.py`).

This is a practical and understandable architecture for a prototype: clear modules with mostly single responsibilities.

## What is strong

1. **Reasonable pipeline decomposition**  
   Modules map to pipeline stages and are easy to locate.

2. **Real-time safeguards are present**  
   Detection throttling (`DETECTION_INTERVAL`) and LLM cooldown (`LLM_COOLDOWN`) reduce resource cost and API churn.

3. **Good fallback strategy in LLM path**  
   When Gemini is unavailable or errors, `_fallback_heuristic` still returns useful text.

4. **Useful user-state persistence**  
   User auth + per-user face references + overlay settings provide a solid product direction.

5. **Graceful optional dependency handling (partly)**  
   `VectorStore` and Gemini imports degrade to disabled behavior when libraries or credentials are missing.

## Main risks / code quality issues

### 1) Concurrency and global-state race conditions (high)
`src/web_server.py` relies on many mutable globals (`latest_frame`, `current_detections`, `system_active`, `active_user_id`, etc.) updated/read by multiple threads with inconsistent locking.

- `latest_frame` is protected by `lock`, but `current_detections`, `system_status`, `show_overlays`, and `active_user_id` are often not.
- Audio mutate/read paths are also shared across request handlers and background loop.

**Impact:** occasional stale reads, partial updates, nondeterministic behavior under concurrent requests.

### 2) Multi-user data leakage through single `active_user_id` (high)
`active_user_id` is global. The first or most recent user calling `/api/user/me` sets identity used by background reasoning.

**Impact:** in multi-user sessions, face recognition context and spoken personalization can mix users.

### 3) Duplicate endpoint definition risk (medium)
`/api/user/me` exists in both `src/auth.py` and `src/web_server.py`. Since router inclusion order and duplicate route handling can be subtle, this can produce maintenance ambiguity.

**Impact:** hard-to-debug behavior drift if one endpoint changes and the other does not.

### 4) Platform-coupled TTS implementation (medium)
`AudioFeedback` invokes `powershell` for TTS, with Windows-only semantics.

**Impact:** breaks on Linux/macOS deployments and most containers unless custom setup is added.

### 5) Missing input hardening on uploaded face filenames (medium)
Face upload uses `file.filename` in final path. While prefixing with user id helps organization, filename normalization/sanitization is minimal.

**Impact:** unsafe characters / path oddities can cause filesystem issues.

### 6) Password verification not constant-time (medium)
`verify_password` compares hashes using `==`.

**Impact:** theoretical timing side-channel (small in many deployments, but easy to fix with `hmac.compare_digest`).

### 7) Repeated imports / minor hygiene issues (low)
`src/llm_service.py` duplicates imports (`logging`, `threading`, `config`), and some variables in `main.py` are unused (`last_speech`).

**Impact:** not critical, but signals maintainability debt.

### 8) Dependency file duplication/inconsistency (low)
`python-dotenv` appears twice in `requirements.txt`; there is both `google-generativeai` and `google-genai` listed.

**Impact:** environment reproducibility confusion.

## Priority recommendations

### P0 (should do first)
1. **Create a centralized runtime state object**
   - Replace module-level globals in `web_server.py` with a `RuntimeState` dataclass/class.
   - Protect all shared mutable fields with one lock or per-field locks.
   - Pass this state to loop/handlers to make ownership explicit.

2. **Fix user scoping in background loop**
   - Avoid single `active_user_id` global for all sessions.
   - Either: (a) run one analysis context per session/client, or (b) enforce single active session explicitly and surface it in UI/admin.

3. **Unify `/api/user/me` endpoint ownership**
   - Keep only one implementation and remove duplicate route to prevent future divergence.

### P1 (next)
4. **Harden auth + upload paths**
   - Use `hmac.compare_digest` for hash check.
   - Sanitize uploaded filenames (e.g., `pathlib.Path(file.filename).name`, whitelist chars, optional generated UUID filenames).
   - Validate MIME/type/size for face uploads.

5. **Make audio backend pluggable**
   - Add provider abstraction: `powershell` (Windows), `pyttsx3`, or no-op backend by platform.

6. **Introduce structured logging**
   - Add request ids/session ids to logs.
   - Standardize log fields for detection, LLM, and audio events.

### P2 (cleanup)
7. **Refactor startup lifecycle**
   - Move thread startup/shutdown resource management into a dedicated service class.

8. **Dependency cleanup**
   - Remove duplicates, pin versions, verify which Google SDK is actually used.

9. **Add tests around critical logic**
   - Unit tests: reasoner cooldown, dangerous prioritization, fallback generation.
   - API tests: auth routes, face upload validations, system state transitions.

## Suggested immediate low-risk patches

- Replace password equality with constant-time comparison.
- Sanitize face upload filename and enforce extension whitelist.
- Remove duplicated `/api/user/me` route.
- De-duplicate imports and requirements entries.

These four can be landed without changing product behavior significantly, and they reduce operational/security risk quickly.
