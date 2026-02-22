document.addEventListener('DOMContentLoaded', () => {
    // --- DOM Elements ---
    const statusText = document.getElementById('status-text');
    const statusBadge = document.getElementById('system-status');
    const detectionList = document.getElementById('detection-list');
    const detCountText = document.getElementById('det-count-text');
    const llmOutput = document.getElementById('llm-output');
    const logEntries = document.getElementById('log-entries');
    const fpsDisplay = document.getElementById('fps-display');
    const timestampEl = document.getElementById('timestamp');
    const fabAsk = document.getElementById('fab-ask-ai');
    const askModal = document.getElementById('ask-modal');
    const modalClose = document.getElementById('modal-close');
    const modalInput = document.getElementById('modal-input');
    const modalSend = document.getElementById('modal-send-btn');
    const modalAnswer = document.getElementById('modal-answer');
    const modalMicBtn = document.getElementById('modal-mic-btn');
    const overlayToggle = document.getElementById('overlay-toggle');

    // Auth & Profile
    const loginOverlay = document.getElementById('login-overlay');
    const appContent = document.getElementById('app-content');
    const systemToggle = document.getElementById('system-toggle');
    const sysToggleIcon = document.getElementById('sys-toggle-icon');
    const userAvatar = document.getElementById('user-avatar');
    const userNameDisplay = document.getElementById('user-name-display');
    const btnManageFaces = document.getElementById('btn-manage-faces');

    // Faces Modal
    const facesModal = document.getElementById('faces-modal');
    const facesClose = document.getElementById('faces-close');
    const faceNameInput = document.getElementById('face-name-input');
    const faceFileInput = document.getElementById('face-file-input');
    const btnUploadFace = document.getElementById('btn-upload-face');
    const facesList = document.getElementById('faces-list');

    // --- Config ---
    const POLL_INTERVAL = 500; // ms
    const MAX_LOG_ENTRIES = 30;

    // --- State ---
    let lastLogHash = "";
    let lastDetectionsHash = "";
    let guidancePaused = false;


    // --- FPS tracker ---
    let lastPollTime = performance.now();
    let pollCount = 0;

    // --- Timestamp updater ---
    function updateTimestamp() {
        if (timestampEl) {
            const now = new Date();
            timestampEl.textContent = now.toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
        }
    }
    setInterval(updateTimestamp, 1000);
    updateTimestamp();

    // --- Polling ---
    async function fetchStatus() {
        try {
            const response = await fetch('/api/status');
            if (!response.ok) throw new Error('Network response was not ok');

            const data = await response.json();

            // Connection and Activation state
            statusText.textContent = data.status || 'Connected';

            if (systemToggle) {
                // Ensure the switch matches the backend state, but don't fire events
                if (systemToggle.checked !== data.system_active) {
                    systemToggle.checked = data.system_active;
                }
            }
            if (sysToggleIcon) {
                sysToggleIcon.style.color = data.system_active ? 'var(--success)' : 'var(--text-muted)';
            }

            if (data.status === 'Running') {
                statusBadge.classList.add('connected');
                statusBadge.classList.remove('error');
            } else {
                statusBadge.classList.remove('connected');
                statusBadge.classList.add('error'); // Yellow/Gray actually
            }

            // Update detections (with simple dedupe)
            const detHash = JSON.stringify(data.detections || []);
            if (detHash !== lastDetectionsHash) {
                lastDetectionsHash = detHash;
                renderDetections(data.detections || []);
            }

            // Update LLM guidance (graceful fallback)
            renderGuidance(data.llm_response || data.guidance || null);

            // Update FPS display from backend
            if (data.fps !== undefined) {
                if (fpsDisplay) fpsDisplay.textContent = `${data.fps} FPS`;
            }

            // Update reports
            const logCount = data.logs ? data.logs.length : 0;
            // Diagnostic logging (comment out for production)
            // if (logCount > 0 && lastLogHash === "") addLocalLog(`Receiving ${logCount} remote logs...`);

            // Update logs (only if changed)
            if (data.logs && Array.isArray(data.logs)) {
                renderLogs(data.logs);
            }

        } catch (error) {
            console.error('Error fetching status:', error);
            statusText.textContent = 'Disconnected';
            statusBadge.classList.remove('connected');
            statusBadge.classList.add('error');
        }
    }

    // --- Render Detections ---
    function renderDetections(detections) {
        // Update count badge
        const count = detections.length;
        detCountText.textContent = `${count} object${count !== 1 ? 's' : ''}`;

        detectionList.innerHTML = '';

        if (count === 0) {
            detectionList.innerHTML = `
                <li class="empty-state">
                    <span class="material-symbols-rounded empty-icon">search</span>
                    <span>No objects detected</span>
                </li>`;
            return;
        }

        detections.forEach((det, index) => {
            const li = document.createElement('li');
            li.className = 'detection-item';
            // Only animate if list was previously empty or significantly changed
            // For now, keep animation simple
            li.style.animationDelay = `${index * 0.05}s`;

            const confPercent = (det.confidence * 100).toFixed(0);

            // Label
            const labelSpan = document.createElement('span');
            labelSpan.className = 'detection-label';

            // Icon for label
            const icon = document.createElement('span');
            icon.className = 'material-symbols-rounded';
            icon.style.fontSize = '18px';
            icon.style.color = det.is_dangerous ? 'var(--danger)' : 'var(--accent-start)';
            icon.textContent = det.is_dangerous ? 'warning' : 'lens_blur';
            labelSpan.appendChild(icon);

            const nameText = document.createTextNode(det.label);
            labelSpan.appendChild(nameText);

            if (det.is_dangerous) {
                const dangerTag = document.createElement('span');
                dangerTag.className = 'tag-dangerous';
                dangerTag.textContent = 'DANGER';
                labelSpan.appendChild(dangerTag);
            }

            // Confidence bar
            const confBar = document.createElement('div');
            confBar.className = 'detection-conf-bar';

            const track = document.createElement('div');
            track.className = 'conf-track';

            const fill = document.createElement('div');
            fill.className = 'conf-fill';
            fill.style.width = '0%';
            track.appendChild(fill);

            const confText = document.createElement('span');
            confText.className = 'conf-text';
            confText.textContent = `${confPercent}%`;

            confBar.appendChild(track);
            confBar.appendChild(confText);

            li.appendChild(labelSpan);
            li.appendChild(confBar);
            detectionList.appendChild(li);

            // Animate the confidence bar in
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    fill.style.width = `${confPercent}%`;
                });
            });
        });
    }

    // --- Render LLM Guidance ---
    function renderGuidance(text, force = false) {
        if (!llmOutput) return;
        if (guidancePaused && !force) return;

        // If text is same as existing content, skip (basic check)
        const currentText = llmOutput.textContent.trim();
        if (text && currentText === text && text !== "AI reasoning will appear here...") return;

        if (!text) {
            // Only clear if not already cleared
            if (!llmOutput.querySelector('.empty-state')) {
                llmOutput.innerHTML = `
                    <p class="empty-state">
                        <span class="material-symbols-rounded empty-icon">psychology</span>
                        <span>AI reasoning will appear here...</span>
                    </p>`;
            }
            return;
        }

        llmOutput.innerHTML = `<div class="guidance-text">${escapeHtml(text)}</div>`;
    }

    // --- Render Logs ---
    function renderLogs(logs) {
        if (!logEntries) return;

        // Check if changed
        const newHash = JSON.stringify(logs);
        if (newHash === lastLogHash) return;
        lastLogHash = newHash;

        logEntries.innerHTML = '';
        // If logs empty, show empty state or keep old?
        // Backend returns last 20 lines. If empty, file is empty.

        const recent = logs.slice(-MAX_LOG_ENTRIES);

        if (recent.length === 0) {
            const p = document.createElement('p');
            p.className = 'log-entry';
            p.style.fontStyle = 'italic';
            p.textContent = 'No logs available.';
            logEntries.appendChild(p);
            return;
        }

        recent.forEach(log => {
            const p = document.createElement('p');
            p.className = 'log-entry';
            p.textContent = typeof log === 'string' ? log : JSON.stringify(log);
            logEntries.appendChild(p);
        });

        // Auto-scroll to bottom
        logEntries.scrollTop = logEntries.scrollHeight;
    }

    // --- Utilities ---
    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // --- Add local log entry ---
    function addLocalLog(message) {
        if (!logEntries) return;
        const p = document.createElement('p');
        p.className = 'log-entry';
        const now = new Date();
        const time = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        p.innerHTML = `<span class="log-time">[${time}]</span> ${escapeHtml(message)}`;
        logEntries.appendChild(p);
        logEntries.scrollTop = logEntries.scrollHeight;
    }

    // --- Helper ---
    async function setBackendAudioMute(muted) {
        try {
            await fetch('/api/audio/state', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ muted: muted })
            });
        } catch (e) {
            console.error("Failed to set audio state:", e);
        }
    }

    // --- Setup Authentication ---
    async function checkAuth() {
        try {
            const res = await fetch('/api/user/me');
            if (res.ok) {
                const user = await res.json();
                if (loginOverlay) loginOverlay.style.display = 'none';
                if (appContent) appContent.style.display = 'flex';

                userNameDisplay.textContent = user.name;
                if (user.avatar_url) {
                    userAvatar.src = user.avatar_url;
                } else {
                    // Generate initials
                    const nameParts = user.name.trim().split(' ');
                    let initials = nameParts[0].charAt(0).toUpperCase();
                    if (nameParts.length > 1) {
                        initials += nameParts[nameParts.length - 1].charAt(0).toUpperCase();
                    }

                    userAvatar.src = `data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="%236366f1"/><text y="52%" x="50%" font-size="45" font-family="sans-serif" font-weight="600" fill="white" dominant-baseline="middle" text-anchor="middle">${initials}</text></svg>`;
                }

                // Load Settings
                if (user.settings_json) {
                    try {
                        const settings = JSON.parse(user.settings_json);
                        if (overlayToggle) {
                            overlayToggle.checked = settings.show_overlays;
                        }
                    } catch (e) { }
                }

                // Dashboard processes run automatically (polling, etc.)
            } else {
                window.location.href = '/login';
            }
        } catch (e) {
            console.error("Auth check failed", e);
            window.location.href = '/login';
        }
    }

    // --- System Control ---
    if (systemToggle) {
        systemToggle.addEventListener('change', async (e) => {
            const isActive = e.target.checked;
            try {
                const res = await fetch('/api/system/state', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ active: isActive })
                });
                if (!res.ok) throw new Error("Failed to set state");
                addLocalLog(`System ${isActive ? 'Started' : 'Stopped'}.`);
            } catch (err) {
                console.error("Failed to change system state:", err);
                // Revert toggle if failed
                systemToggle.checked = !isActive;
            }
        });
    }

    // --- Faces Management ---
    async function loadFaces() {
        try {
            const res = await fetch('/api/faces');
            if (res.ok) {
                const faces = await res.json();
                facesList.innerHTML = '';
                if (faces.length === 0) {
                    facesList.innerHTML = '<p style="color: #a0a0b0; text-align: center; padding: 1rem;">No faces added yet.</p>';
                    return;
                }
                faces.forEach(f => {
                    const div = document.createElement('div');
                    div.className = 'face-item';
                    div.innerHTML = `
                        <span><strong>${f.name}</strong></span>
                        <button class="btn-delete-face" data-id="${f.id}" title="Delete"><span class="material-symbols-rounded">delete</span></button>
                    `;
                    facesList.appendChild(div);
                });

                // Bind delete buttons
                document.querySelectorAll('.btn-delete-face').forEach(btn => {
                    btn.addEventListener('click', async (e) => {
                        const id = e.currentTarget.getAttribute('data-id');
                        await fetch(`/api/faces/${id}`, { method: 'DELETE' });
                        loadFaces();
                    });
                });
            }
        } catch (e) { console.error("Failed to load faces", e); }
    }

    if (btnManageFaces && facesModal && facesClose) {
        btnManageFaces.addEventListener('click', () => {
            facesModal.classList.remove('hidden');
            loadFaces();
        });
        facesClose.addEventListener('click', () => {
            facesModal.classList.add('hidden');
        });
    }

    if (btnUploadFace) {
        btnUploadFace.addEventListener('click', async () => {
            const name = faceNameInput.value.trim();
            const file = faceFileInput.files[0];
            if (!name || !file) {
                alert("Please provide both a name and an image file.");
                return;
            }

            const formData = new FormData();
            formData.append('name', name);
            formData.append('file', file);

            btnUploadFace.disabled = true;
            btnUploadFace.textContent = "Uploading...";

            try {
                const res = await fetch('/api/faces', {
                    method: 'POST',
                    body: formData
                });
                if (res.ok) {
                    faceNameInput.value = '';
                    faceFileInput.value = '';
                    loadFaces();
                } else {
                    alert("Upload failed.");
                }
            } catch (e) {
                console.error("Upload Error", e);
            } finally {
                btnUploadFace.disabled = false;
                btnUploadFace.innerHTML = '<span class="material-symbols-rounded">upload</span> Upload';
            }
        });
    }

    if (overlayToggle) {
        overlayToggle.addEventListener('change', async (e) => {
            try {
                await fetch('/api/settings/overlays', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                addLocalLog(`Detection overlays ${show ? 'enabled' : 'disabled'}.`);
            } catch (err) {
                console.error("Error toggling overlays:", err);
            }
        });
    }
    addLocalLog('Connecting to detection service...');

    // --- Ask AI Logic (Modal) ---
    if (fabAsk && askModal) {
        // Open
        fabAsk.addEventListener('click', () => {
            setBackendAudioMute(true);
            askModal.classList.remove('hidden');
            setTimeout(() => modalInput.focus(), 100);
        });

        // Close
        const closeModal = () => {
            setBackendAudioMute(false);
            askModal.classList.add('hidden');
        };
        modalClose.addEventListener('click', closeModal);
        askModal.addEventListener('click', (e) => {
            if (e.target === askModal) closeModal();
        });

        // Send
        const handleAsk = async () => {
            const question = modalInput.value.trim();
            if (!question) return;

            // UI Feedback
            modalInput.value = '';

            modalAnswer.innerHTML = '<span class="material-symbols-rounded" style="font-size:16px; vertical-align:middle; animation:spin 1s linear infinite;">sync</span> Thinking...';
            modalAnswer.classList.remove('hidden');

            try {
                const res = await fetch('/api/ask', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ question })
                });
                const data = await res.json();

                modalAnswer.innerHTML = `<strong>Memory:</strong> ${data.answer}`;

                // TTS (Text to Speech)
                if ('speechSynthesis' in window) {
                    window.speechSynthesis.cancel(); // Stop any ongoing speech
                    const utterance = new SpeechSynthesisUtterance(data.answer);
                    window.speechSynthesis.speak(utterance);
                }

            } catch (e) {
                console.error(e);
                modalAnswer.textContent = "Error asking memory.";
            }
        };

        modalSend.addEventListener('click', handleAsk);
        modalInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') handleAsk();
        });

        // --- STT (Speech to Text) Setup ---
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognition && modalMicBtn) {
            const recognition = new SpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = false;
            recognition.lang = 'en-US';

            recognition.onstart = () => {
                modalMicBtn.classList.add('listening');
                modalInput.placeholder = 'Listening...';
            };

            recognition.onresult = (event) => {
                const transcript = event.results[0][0].transcript;
                modalInput.value = transcript;
                handleAsk(); // Auto-submit after voice input
            };

            recognition.onerror = (event) => {
                console.error("Speech recognition error:", event.error);
                modalMicBtn.classList.remove('listening');
                modalInput.placeholder = 'e.g., "Where are my keys?"';
            };

            recognition.onend = () => {
                modalMicBtn.classList.remove('listening');
                modalInput.placeholder = 'e.g., "Where are my keys?"';
            };

            modalMicBtn.addEventListener('click', () => {
                if (modalMicBtn.classList.contains('listening')) {
                    recognition.stop();
                } else {
                    recognition.start();
                }
            });
        } else if (modalMicBtn) {
            modalMicBtn.style.display = 'none'; // Hide if not supported
        }
    }

    // Check auth and initialize on load
    checkAuth();

    // Start polling status
    setInterval(fetchStatus, POLL_INTERVAL);
});
