document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const numClipsInput = document.getElementById('num_clips');
    const numClipsVal = document.getElementById('num_clips_val');
    const llmProviderSelect = document.getElementById('llm_provider');
    const openaiKeyWrapper = document.getElementById('openai-key-wrapper');
    const geminiKeyWrapper = document.getElementById('gemini-key-wrapper');
    const saveKeysBtn = document.getElementById('save-keys-btn');
    const keysSaveStatus = document.getElementById('keys-save-status');
    const generateBtn = document.getElementById('generate-btn');
    const videoUrlInput = document.getElementById('video-url');
    const progressContainer = document.getElementById('progress-container');
    const progressStepTitle = document.getElementById('progress-step-title');
    const progressPercentage = document.getElementById('progress-percentage');
    const progressBarFill = document.getElementById('progress-bar-fill');
    const logsOutputText = document.getElementById('logs-output-text');
    const resultsContainer = document.getElementById('results-container');
    const resultsCount = document.getElementById('results-count');
    const shortsGrid = document.getElementById('shorts-grid');
    const serverStatusIndicator = document.querySelector('.status-indicator');
    const serverStatusText = document.querySelector('.server-status span:last-child');
    
    // API State and Polling Config
    let pollInterval = null;
    let autoScrollLogs = true;

    // Initialize UI from .env configuration
    fetchConfig();

    // Num Clips slider update
    numClipsInput.addEventListener('input', (e) => {
        numClipsVal.textContent = e.target.value;
    });

    // Toggle showing correct Local Key input wrapper
    llmProviderSelect.addEventListener('change', (e) => {
        if (e.target.value === 'openai') {
            openaiKeyWrapper.classList.remove('hidden');
            geminiKeyWrapper.classList.add('hidden');
        } else {
            openaiKeyWrapper.classList.add('hidden');
            geminiKeyWrapper.classList.remove('hidden');
        }
    });

    // Custom Radio Toggles: Generation Mode
    const modeBtnApi = document.getElementById('mode-api-btn');
    const modeBtnLocal = document.getElementById('mode-local-btn');
    const modeRadios = document.getElementsByName('mode');

    modeBtnApi.addEventListener('click', () => {
        modeBtnApi.classList.add('active');
        modeBtnLocal.classList.remove('active');
        document.querySelector('input[name="mode"][value="api"]').checked = true;
    });

    modeBtnLocal.addEventListener('click', () => {
        modeBtnLocal.classList.add('active');
        modeBtnApi.classList.remove('active');
        document.querySelector('input[name="mode"][value="local"]').checked = true;
    });

    // Custom Radio Toggles: Aspect Ratio
    const ratioBtns = document.querySelectorAll('.ratio-btn');
    ratioBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            ratioBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            btn.querySelector('input[type="radio"]').checked = true;
        });
    });

    // Save configuration settings
    saveKeysBtn.addEventListener('click', async () => {
        saveKeysBtn.disabled = true;
        saveKeysBtn.textContent = 'Saving...';
        
        const payload = {
            MUAPI_API_KEY: document.getElementById('muapi_key').value.trim(),
            LLM_PROVIDER: llmProviderSelect.value,
            OPENAI_API_KEY: document.getElementById('openai_key').value.trim(),
            GEMINI_API_KEY: document.getElementById('gemini_key').value.trim(),
        };

        try {
            const res = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (data.status === 'success') {
                showSaveStatus();
            } else {
                alert('Failed to save config.');
            }
        } catch (err) {
            console.error(err);
            alert('Error connecting to backend.');
        } finally {
            saveKeysBtn.disabled = false;
            saveKeysBtn.textContent = 'Save API Configuration';
        }
    });

    // Logs Auto-scroll toggle
    const logsScrollBtn = document.getElementById('logs-scroll-btn');
    logsScrollBtn.addEventListener('click', () => {
        autoScrollLogs = !autoScrollLogs;
        logsScrollBtn.style.color = autoScrollLogs ? 'var(--text-primary)' : 'var(--text-muted)';
    });

    // Start Generation Flow
    generateBtn.addEventListener('click', async () => {
        const url = videoUrlInput.value.trim();
        if (!url) {
            alert('Please enter a YouTube video URL or local file path!');
            return;
        }

        const mode = document.querySelector('input[name="mode"]:checked').value;
        const numClips = numClipsInput.value;
        const aspect_ratio = document.querySelector('input[name="aspect_ratio"]:checked').value;
        const format = document.getElementById('format').value;
        const language = document.getElementById('language').value;
        const faceTracking = document.getElementById('face_tracking').checked;

        // Reset progress and hide previous results
        resetProgressSteps();
        resultsContainer.classList.add('hidden');
        progressContainer.classList.remove('hidden');
        
        // Update generate button state
        generateBtn.disabled = true;
        generateBtn.querySelector('.btn-text').textContent = 'Processing...';
        generateBtn.querySelector('.spinner').classList.remove('hidden');
        
        // Update Server Status
        serverStatusIndicator.className = 'status-indicator busy';
        serverStatusText.textContent = 'Generating Shorts';

        try {
            const res = await fetch('/api/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, mode, num_clips: numClips, aspect_ratio, format, language, face_tracking: faceTracking })
            });

            if (res.status === 409) {
                alert('A video generation is already in progress. Please wait for it to complete.');
                resetGenerateBtn();
                return;
            }

            if (!res.ok) {
                const errData = await res.json();
                throw new Error(errData.error || 'Server error starting generation');
            }

            // Start Polling Status
            pollInterval = setInterval(pollStatus, 1000);

        } catch (err) {
            console.error(err);
            logsOutputText.textContent += `\nError starting generation: ${err.message}\n`;
            resetGenerateBtn();
        }
    });

    // Fetch and populate API keys
    async function fetchConfig() {
        try {
            const res = await fetch('/api/config');
            const data = await res.json();
            
            document.getElementById('muapi_key').value = data.MUAPI_API_KEY || '';
            document.getElementById('openai_key').value = data.OPENAI_API_KEY || '';
            document.getElementById('gemini_key').value = data.GEMINI_API_KEY || '';
            
            if (data.LLM_PROVIDER) {
                llmProviderSelect.value = data.LLM_PROVIDER;
                // trigger change visual setup
                llmProviderSelect.dispatchEvent(new Event('change'));
            }
        } catch (err) {
            console.error('Error fetching config:', err);
        }
    }

    // Flash config save indicator badge
    function showSaveStatus() {
        keysSaveStatus.classList.add('show');
        setTimeout(() => {
            keysSaveStatus.classList.remove('show');
        }, 3000);
    }

    // Poll current job status
    async function pollStatus() {
        try {
            const res = await fetch('/api/status');
            const data = await res.json();
            
            // Render logs
            logsOutputText.textContent = data.logs || 'Initializing process...';
            if (autoScrollLogs) {
                logsOutputText.scrollTop = logsOutputText.scrollHeight;
            }

            // Update progress bar & percentage label
            progressBarFill.style.width = `${data.progress}%`;
            progressPercentage.textContent = `${data.progress}%`;
            
            // Set friendly step labels and active classes
            updateProgressSteps(data.status);

            if (data.status === 'completed') {
                clearInterval(pollInterval);
                progressStepTitle.textContent = '🎉 Processing Complete!';
                await loadResults();
                resetGenerateBtn();
            } else if (data.status === 'failed') {
                clearInterval(pollInterval);
                progressStepTitle.textContent = '❌ Generation Failed';
                alert(`Generation Failed: ${data.error_message}`);
                resetGenerateBtn();
            } else {
                progressStepTitle.textContent = getStepFriendlyTitle(data.status);
            }

        } catch (err) {
            console.error('Error polling status:', err);
        }
    }

    // Map backend statuses to friendly text
    function getStepFriendlyTitle(status) {
        switch (status) {
            case 'downloading': return 'Downloading Video source file...';
            case 'transcribing': return 'Transcribing audio to text (Whisper)...';
            case 'analyzing': return 'AI Analysis: Extracting viral highlights...';
            case 'cropping': return 'Cutting video & cropping to aspect ratio...';
            default: return 'Running Shorts Generator...';
        }
    }

    // Manage visual stepper nodes
    function updateProgressSteps(status) {
        const stepDownload = document.getElementById('step-download');
        const stepTranscribe = document.getElementById('step-transcribe');
        const stepAnalyze = document.getElementById('step-analyze');
        const stepCrop = document.getElementById('step-crop');

        // Reset
        const steps = [stepDownload, stepTranscribe, stepAnalyze, stepCrop];
        steps.forEach(s => s.className = 'step');

        if (status === 'downloading') {
            stepDownload.classList.add('active');
        } else if (status === 'transcribing') {
            stepDownload.classList.add('completed');
            stepTranscribe.classList.add('active');
        } else if (status === 'analyzing') {
            stepDownload.classList.add('completed');
            stepTranscribe.classList.add('completed');
            stepAnalyze.classList.add('active');
        } else if (status === 'cropping') {
            stepDownload.classList.add('completed');
            stepTranscribe.classList.add('completed');
            stepAnalyze.classList.add('completed');
            stepCrop.classList.add('active');
        } else if (status === 'completed') {
            steps.forEach(s => s.classList.add('completed'));
        }
    }

    function resetProgressSteps() {
        const steps = ['step-download', 'step-transcribe', 'step-analyze', 'step-crop'];
        steps.forEach(id => {
            document.getElementById(id).className = 'step';
        });
        progressBarFill.style.width = '0%';
        progressPercentage.textContent = '0%';
        progressStepTitle.textContent = 'Initializing...';
        logsOutputText.textContent = '';
    }

    function resetGenerateBtn() {
        generateBtn.disabled = false;
        generateBtn.querySelector('.btn-text').textContent = 'Generate Clips';
        generateBtn.querySelector('.spinner').classList.add('hidden');
        
        serverStatusIndicator.className = 'status-indicator online';
        serverStatusText.textContent = 'System Ready';
    }

    // Load and render generated clips
    async function loadResults() {
        try {
            const res = await fetch('/api/results');
            if (!res.ok) throw new Error('Could not retrieve results');
            const data = await res.json();
            
            const clips = data.shorts || [];
            resultsCount.textContent = `${clips.length} Clip${clips.length === 1 ? '' : 's'}`;
            shortsGrid.innerHTML = '';
            
            if (clips.length === 0) {
                shortsGrid.innerHTML = '<div class="no-results">No clips were generated. Check the logs for details.</div>';
                resultsContainer.classList.remove('hidden');
                return;
            }

            const aspect = data.aspect_ratio || '9:16';
            const aspectClass = aspect === '1:1' ? 'aspect-1-1' : (aspect === '16:9' ? 'aspect-16-9' : 'aspect-9-16');

            clips.forEach((clip, index) => {
                const card = document.createElement('div');
                card.className = 'short-card';

                const score = clip.score || 0;
                const scoreClass = score >= 90 ? 'excellent' : 'good';

                // Render video tags
                const videoSource = clip.clip_url ? `<video src="${clip.clip_url}" controls></video>` : `<div class="video-error">Cropping Failed</div>`;

                card.innerHTML = `
                    <div class="video-container ${aspectClass}">
                        ${videoSource}
                        <div class="score-badge ${scoreClass}">
                            <span class="score-num">${score}</span>
                            <span class="score-lbl">Score</span>
                        </div>
                    </div>
                    <div class="short-info">
                        <h4 class="short-title">${clip.title || `Highlight #${index + 1}`}</h4>
                        
                        <div class="short-details">
                            <div><span class="detail-label">Start:</span><span class="detail-text">${clip.start_time.toFixed(1)}s</span></div>
                            <div><span class="detail-label">End:</span><span class="detail-text">${clip.end_time.toFixed(1)}s</span></div>
                            <div><span class="detail-label">Duration:</span><span class="detail-text">${(clip.end_time - clip.start_time).toFixed(1)}s</span></div>
                        </div>

                        <div class="hook-box">
                            <span class="box-title">Opening Hook</span>
                            <blockquote class="hook-text">"${clip.hook_sentence || 'N/A'}"</blockquote>
                        </div>

                        <div class="reason-box">
                            <span class="box-title reason">Virality Explanation</span>
                            <p class="reason-text">${clip.virality_reason || 'N/A'}</p>
                        </div>
                    </div>
                `;
                shortsGrid.appendChild(card);
            });

            resultsContainer.classList.remove('hidden');

        } catch (err) {
            console.error('Error loading results:', err);
            shortsGrid.innerHTML = `<div class="no-results">Error loading generated clips: ${err.message}</div>`;
            resultsContainer.classList.remove('hidden');
        }
    }
});
