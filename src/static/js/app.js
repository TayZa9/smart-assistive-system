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

    // --- Config ---
    const POLL_INTERVAL = 500; // ms
    const MAX_LOG_ENTRIES = 30;

    // --- State ---
    let lastLogHash = "";
    let lastDetectionsHash = "";

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

            // Connection state
            statusText.textContent = data.status || 'Connected';
            statusBadge.classList.add('connected');
            statusBadge.classList.remove('error');

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
    function renderGuidance(text) {
        if (!llmOutput) return;

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

    // --- Init ---
    addLocalLog('Dashboard initialized');
    addLocalLog('Connecting to detection service...');

    // Start polling
    setInterval(fetchStatus, POLL_INTERVAL);
});
