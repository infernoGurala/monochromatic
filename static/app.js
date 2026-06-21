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
    const serverStatusIndicator = document.getElementById('status-dot') || document.querySelector('.status-indicator');
    const serverStatusText = document.getElementById('status-text') || document.querySelector('.server-status span:last-child');
    const terminateBtn = document.getElementById('terminate-btn');
    
    // API State and Polling Config
    let pollInterval = null;
    let autoScrollLogs = true;
    let lastClips = []; // store last results for re-sorting

    // Sort selector
    const sortSelect = document.getElementById('sort-select');
    if (sortSelect) {
        sortSelect.addEventListener('change', () => {
            if (lastClips.length) renderClips(lastClips);
        });
    }

    // Clear results button
    const clearResultsBtn = document.getElementById('clear-results-btn');
    if (clearResultsBtn) {
        clearResultsBtn.addEventListener('click', () => {
            lastClips = [];
            shortsGrid.innerHTML = '';
            resultsContainer.classList.add('hidden');
            progressContainer.classList.add('hidden');
            document.getElementById('total-clips-stat').textContent = '0 clips generated';
        });
    }

    // Initialize UI from .env configuration
    fetchConfig();
    checkRunningJob();

    // Num Clips slider update
    numClipsInput.addEventListener('input', (e) => {
        numClipsVal.textContent = e.target.value;
    });

    // Sensitivity slider live value
    const sensitivityInput = document.getElementById('highlight_sensitivity');
    const sensitivityVal = document.getElementById('sensitivity_val');
    if (sensitivityInput && sensitivityVal) {
        sensitivityInput.addEventListener('input', (e) => {
            sensitivityVal.textContent = e.target.value;
        });
    }

    // Toggle showing correct Local Key input wrapper
    llmProviderSelect.addEventListener('change', (e) => {
        const val = e.target.value;
        openaiKeyWrapper.classList.add('hidden');
        geminiKeyWrapper.classList.add('hidden');
        document.getElementById('ollama-model-wrapper').classList.add('hidden');
        document.getElementById('ollama-url-wrapper').classList.add('hidden');
        document.getElementById('groq-keys-wrapper').classList.add('hidden');
        document.getElementById('groq-model-wrapper').classList.add('hidden');

        if (val === 'openai') {
            openaiKeyWrapper.classList.remove('hidden');
        } else if (val === 'gemini') {
            geminiKeyWrapper.classList.remove('hidden');
        } else if (val === 'ollama') {
            document.getElementById('ollama-model-wrapper').classList.remove('hidden');
            document.getElementById('ollama-url-wrapper').classList.remove('hidden');
        } else if (val === 'groq') {
            document.getElementById('groq-keys-wrapper').classList.remove('hidden');
            document.getElementById('groq-model-wrapper').classList.remove('hidden');
        }
    });

    // Custom Radio Toggles: Generation Mode (API vs Local)
    const modeBtnApi = document.getElementById('mode-api-btn');
    const modeBtnLocal = document.getElementById('mode-local-btn');


    // ── 3-Way Generation Mode Selector ────────────────────────────────────
    const genModeStandardBtn = document.getElementById('gen-mode-standard-btn');
    const genModeRankingBtn  = document.getElementById('gen-mode-ranking-btn');
    const genModeMovieBtn    = document.getElementById('gen-mode-movie-btn');
    const rankingPanel       = document.getElementById('ranking-panel');
    const moviePanel         = document.getElementById('movie-panel');
    const apiModeGroup       = document.getElementById('api-mode-group');
    const clipsLabel         = document.getElementById('clips-label');
    const pipelineStepOcr    = document.getElementById('step-ocr');
    const pipelineStepScene  = document.getElementById('step-scene');
    const pipelineStepViral  = document.getElementById('step-viral');
    const pipeLineOcr        = document.getElementById('pipe-line-ocr');
    const pipeLineScene      = document.getElementById('pipe-line-scene');
    const pipeLineViral      = document.getElementById('pipe-line-viral');
    const pipelineStepper    = document.getElementById('pipeline-stepper');

    function setGenMode(mode) {
        // Update radio checked state
        const radio = document.querySelector(`input[name="gen_mode"][value="${mode}"]`);
        if (radio) radio.checked = true;

        // Update pill active classes
        [genModeStandardBtn, genModeRankingBtn, genModeMovieBtn].forEach(b => b && b.classList.remove('active'));
        if (mode === 'standard' && genModeStandardBtn) genModeStandardBtn.classList.add('active');
        if (mode === 'ranking' && genModeRankingBtn)   genModeRankingBtn.classList.add('active');
        if (mode === 'movie' && genModeMovieBtn)        genModeMovieBtn.classList.add('active');

        // Show/hide mode panels
        if (rankingPanel) rankingPanel.classList.toggle('hidden', mode !== 'ranking');
        if (moviePanel)   moviePanel.classList.toggle('hidden', mode !== 'movie');

        // Show/hide API/Local engine toggle (not relevant for ranking/movie — always local)
        if (apiModeGroup) apiModeGroup.classList.toggle('hidden', mode !== 'standard');

        // Update clips label
        if (clipsLabel) {
            if (mode === 'ranking') clipsLabel.textContent = 'Ranks to Extract';
            else if (mode === 'movie') clipsLabel.textContent = 'Movie Clips';
            else clipsLabel.textContent = 'Clips to Extract';
        }

        // Show/hide extra stepper steps
        const isRanking = mode === 'ranking';
        const isMovie   = mode === 'movie';
        if (pipelineStepOcr)   pipelineStepOcr.classList.toggle('hidden', !isRanking);
        if (pipelineStepOcr)   pipelineStepOcr.classList.toggle('visible', isRanking);
        if (pipeLineOcr)        pipeLineOcr.classList.toggle('hidden', !isRanking);
        if (pipeLineOcr)        pipeLineOcr.classList.toggle('visible', isRanking);
        if (pipelineStepScene)  pipelineStepScene.classList.toggle('hidden', !isMovie);
        if (pipelineStepScene)  pipelineStepScene.classList.toggle('visible', isMovie);
        if (pipeLineScene)      pipeLineScene.classList.toggle('hidden', !isMovie);
        if (pipeLineScene)      pipeLineScene.classList.toggle('visible', isMovie);
        if (pipelineStepViral)  pipelineStepViral.classList.toggle('hidden', !isMovie);
        if (pipelineStepViral)  pipelineStepViral.classList.toggle('visible', isMovie);
        if (pipeLineViral)      pipeLineViral.classList.toggle('hidden', !isMovie);
        if (pipeLineViral)      pipeLineViral.classList.toggle('visible', isMovie);
        if (pipelineStepper)    pipelineStepper.classList.toggle('extended', isRanking || isMovie);

        // Update URL bar placeholder
        const urlInput = document.getElementById('video-url');
        if (urlInput) {
            if (mode === 'movie') urlInput.placeholder = 'Paste local movie file path (e.g. /home/user/movie.mp4)…';
            else if (mode === 'ranking') urlInput.placeholder = 'Paste YouTube URL or local ranking video path…';
            else urlInput.placeholder = 'Paste YouTube URL, file:// path, or local file…';
        }
    }

    if (genModeStandardBtn) genModeStandardBtn.addEventListener('click', () => setGenMode('standard'));
    if (genModeRankingBtn)  genModeRankingBtn.addEventListener('click',  () => setGenMode('ranking'));
    if (genModeMovieBtn)    genModeMovieBtn.addEventListener('click',    () => setGenMode('movie'));

    // Clip length slider for ranking panel
    const clipLengthInput = document.getElementById('target_clip_length');
    const clipLengthVal   = document.getElementById('clip_length_val');
    if (clipLengthInput && clipLengthVal) {
        clipLengthInput.addEventListener('input', (e) => {
            clipLengthVal.textContent = e.target.value + 's';
        });
    }

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
            LLM_PROVIDER: llmProviderSelect.value,
            OPENAI_API_KEY: document.getElementById('openai_key').value.trim(),
            GEMINI_API_KEY: document.getElementById('gemini_key').value.trim(),
            OLLAMA_MODEL: document.getElementById('ollama_model').value.trim(),
            OLLAMA_BASE_URL: document.getElementById('ollama_url').value.trim(),
            GROQ_KEYS: document.getElementById('groq_keys').value.trim(),
            GROQ_MODEL: document.getElementById('groq_model').value.trim(),
            GROQ_API_KEY: (document.getElementById('groq_key') || {value:''}).value.trim(),
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

    // Copy Logs to Clipboard
    const copyLogBtn = document.getElementById('copy-log-btn');
    if (copyLogBtn) {
        copyLogBtn.addEventListener('click', () => {
            const logsText = logsOutputText.textContent;
            navigator.clipboard.writeText(logsText).then(() => {
                const originalText = copyLogBtn.textContent;
                copyLogBtn.textContent = 'Copied!';
                copyLogBtn.style.color = 'var(--accent-color)';
                setTimeout(() => {
                    copyLogBtn.textContent = originalText;
                    copyLogBtn.style.color = 'var(--text-muted)';
                }, 2000);
            }).catch(err => {
                console.error('Failed to copy logs: ', err);
            });
        });
    }

    // Cancel Button Handler
    const cancelGenBtn = document.getElementById('cancel-gen-btn');
    if (cancelGenBtn) {
        cancelGenBtn.addEventListener('click', async () => {
            cancelGenBtn.disabled = true;
            cancelGenBtn.textContent = 'Cancelling...';
            try {
                const res = await fetch('/api/cancel', { method: 'POST' });
                if (res.ok) {
                    logsOutputText.textContent += '\n[UI] Cancellation request sent to server...\n';
                }
            } catch (err) {
                console.error('Error cancelling generation:', err);
            }
        });
    }

    // Caption Size Slider
    const captionSizeInput = document.getElementById('caption_size');
    const captionSizeVal = document.getElementById('caption_size_val');
    if (captionSizeInput && captionSizeVal) {
        captionSizeInput.addEventListener('input', () => {
            captionSizeVal.textContent = captionSizeInput.value;
        });
    }

    // Start Generation Flow
    generateBtn.addEventListener('click', async () => {
        const url = videoUrlInput.value.trim();
        if (!url) {
            alert('Please enter a YouTube video URL or local file path!');
            return;
        }

        const genMode = (document.querySelector('input[name="gen_mode"]:checked') || {value: 'standard'}).value;
        const mode = (document.querySelector('input[name="mode"]:checked') || {value: 'local'}).value;
        const numClips = numClipsInput.value;
        const aspect_ratio = document.querySelector('input[name="aspect_ratio"]:checked').value;
        const format = document.getElementById('format').value;
        const language = document.getElementById('language').value;
        const faceTracking = document.getElementById('face_tracking').checked;
        const clipDuration = document.getElementById('clip_duration').value;
        const cropStart = document.getElementById('crop_start').value.trim();
        const cropEnd = document.getElementById('crop_end').value.trim();

        const captionFont = document.getElementById('caption_font').value;
        const captionSize = document.getElementById('caption_size').value;
        const captionColor = document.getElementById('caption_color').value;
        const captionCase = document.getElementById('caption_case').value;
        const enableSubtitles = document.getElementById('enable_subtitles').value === 'true';

        const minDuration = document.getElementById('min_duration').value;

        // Ranking params
        const rankingOverlay = (document.getElementById('ranking_overlay') || {value: 'large'}).value;
        const ocrEnabled = (document.getElementById('ocr_enabled') || {checked: true}).checked;
        const targetClipLength = parseFloat((document.getElementById('target_clip_length') || {value: 5}).value);
        const maxDuration = parseFloat((document.getElementById('max_duration') || {value: 60}).value);

        // Movie params
        const sceneThreshold = parseFloat((document.getElementById('scene_threshold') || {value: 30}).value);
        const minSceneLength = parseFloat((document.getElementById('min_scene_length') || {value: 10}).value);
        const movieFaceTracking = (document.getElementById('movie_face_tracking') || {checked: true}).checked;
        const effectiveFaceTracking = genMode === 'movie' ? movieFaceTracking : faceTracking;

        // Reset progress and hide previous results
        resetProgressSteps();
        resultsContainer.classList.add('hidden');
        progressContainer.classList.remove('hidden');
        terminateBtn.classList.remove('hidden');
        
        // Update generate button state
        generateBtn.disabled = true;
        generateBtn.querySelector('.btn-text').textContent = 'Processing...';
        generateBtn.querySelector('.spinner').classList.remove('hidden');

        if (cancelGenBtn) {
            cancelGenBtn.disabled = false;
            cancelGenBtn.textContent = 'Cancel Job';
        }
        
        // Update Server Status
        serverStatusIndicator.className = 'status-dot busy';
        serverStatusText.textContent = 'Generating…';

        try {
            const res = await fetch('/api/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    url,
                    mode,
                    gen_mode: genMode,
                    num_clips: numClips,
                    aspect_ratio,
                    format,
                    language,
                    face_tracking: effectiveFaceTracking,
                    clip_duration: clipDuration,
                    crop_start: cropStart,
                    crop_end: cropEnd,
                    caption_font: captionFont,
                    caption_size: captionSize,
                    caption_color: captionColor,
                    caption_case: captionCase,
                    min_duration: minDuration,
                    enable_subtitles: enableSubtitles,
                    // Ranking
                    ranking_overlay: rankingOverlay,
                    ocr_enabled: ocrEnabled,
                    target_clip_length: targetClipLength,
                    max_duration: maxDuration,
                    // Movie
                    scene_threshold: sceneThreshold,
                    min_scene_length: minSceneLength,
                })
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
            if (document.getElementById('muapi_key')) document.getElementById('muapi_key').value = data.MUAPI_API_KEY || '';
            if (document.getElementById('openai_key')) document.getElementById('openai_key').value = data.OPENAI_API_KEY || '';
            if (document.getElementById('gemini_key')) document.getElementById('gemini_key').value = data.GEMINI_API_KEY || '';
            if (document.getElementById('ollama_model')) document.getElementById('ollama_model').value = data.OLLAMA_MODEL || 'gemma4:e4b';
            if (document.getElementById('ollama_url')) document.getElementById('ollama_url').value = data.OLLAMA_BASE_URL || 'http://localhost:11434';
            if (document.getElementById('groq_keys')) document.getElementById('groq_keys').value = data.GROQ_KEYS || '';
            if (document.getElementById('groq_model')) document.getElementById('groq_model').value = data.GROQ_MODEL || 'llama-3.3-70b-versatile';
            const groqEl = document.getElementById('groq_key');
            if (groqEl) groqEl.value = data.GROQ_API_KEY || '';
            if (data.LLM_PROVIDER) {
                llmProviderSelect.value = data.LLM_PROVIDER;
                llmProviderSelect.dispatchEvent(new Event('change'));
            }
        } catch (err) {
            console.error('Error fetching config:', err);
        }
    }

    // Check if a job is already running on page load
    async function checkRunningJob() {
        try {
            const res = await fetch('/api/status');
            const data = await res.json();
            if (data.status && !['idle', 'completed', 'failed'].includes(data.status)) {
                // Restore UI to busy/processing state
                progressContainer.classList.remove('hidden');
                terminateBtn.classList.remove('hidden');
                generateBtn.disabled = true;
                generateBtn.querySelector('.btn-text').textContent = 'Processing...';
                generateBtn.querySelector('.spinner').classList.remove('hidden');
                serverStatusIndicator.className = 'status-indicator busy';
                serverStatusText.textContent = 'Generating Shorts';
                
                // Start status polling immediately
                if (!pollInterval) {
                    pollInterval = setInterval(pollStatus, 1000);
                }
            }
        } catch (err) {
            console.error('Error checking active job on load:', err);
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
                terminateBtn.classList.add('hidden');
            } else if (data.status === 'failed') {
                clearInterval(pollInterval);
                progressStepTitle.textContent = '❌ Generation Failed';
                alert(`Generation Failed: ${data.error_message}`);
                resetGenerateBtn();
                terminateBtn.classList.add('hidden');
            } else {
                progressStepTitle.textContent = getStepFriendlyTitle(data.status);
                terminateBtn.classList.remove('hidden');
            }

        } catch (err) {
            console.error('Error polling status:', err);
        }
    }

    // Map backend statuses to friendly text
    function getStepFriendlyTitle(status) {
        switch (status) {
            case 'downloading':   return 'Downloading video source file…';
            case 'transcribing':  return 'Transcribing audio with Whisper…';
            case 'ocr':           return 'OCR: Detecting rank numbers in frames…';
            case 'scene_detect':  return 'Scene Intelligence: Detecting cut boundaries…';
            case 'viral_score':   return 'Viral Engine: Scoring scenes for engagement…';
            case 'analyzing':     return 'AI Analysis: Extracting highlights…';
            case 'cropping':      return 'Rendering clips…';
            default:              return 'Running pipeline…';
        }
    }

    // Manage visual stepper nodes
    function updateProgressSteps(status) {
        const stepDownload   = document.getElementById('step-download');
        const stepTranscribe = document.getElementById('step-transcribe');
        const stepOcr        = document.getElementById('step-ocr');
        const stepScene      = document.getElementById('step-scene');
        const stepViral      = document.getElementById('step-viral');
        const stepAnalyze    = document.getElementById('step-analyze');
        const stepCrop       = document.getElementById('step-crop');

        // Reset (only reset visible steps)
        [stepDownload, stepTranscribe, stepOcr, stepScene, stepViral, stepAnalyze, stepCrop]
            .filter(Boolean)
            .forEach(s => { s.classList.remove('active', 'completed'); });

        if (status === 'downloading') {
            stepDownload.classList.add('active');
        } else if (status === 'transcribing') {
            stepDownload.classList.add('completed');
            stepTranscribe.classList.add('active');
        } else if (status === 'ocr') {
            stepDownload.classList.add('completed');
            stepTranscribe.classList.add('completed');
            if (stepOcr && !stepOcr.classList.contains('hidden')) stepOcr.classList.add('active');
        } else if (status === 'scene_detect') {
            stepDownload.classList.add('completed');
            stepTranscribe.classList.add('completed');
            if (stepScene && !stepScene.classList.contains('hidden')) stepScene.classList.add('active');
        } else if (status === 'viral_score') {
            stepDownload.classList.add('completed');
            stepTranscribe.classList.add('completed');
            if (stepScene && !stepScene.classList.contains('hidden')) stepScene.classList.add('completed');
            if (stepViral && !stepViral.classList.contains('hidden')) stepViral.classList.add('active');
        } else if (status === 'analyzing') {
            stepDownload.classList.add('completed');
            stepTranscribe.classList.add('completed');
            if (stepOcr && !stepOcr.classList.contains('hidden')) stepOcr.classList.add('completed');
            stepAnalyze.classList.add('active');
        } else if (status === 'cropping') {
            stepDownload.classList.add('completed');
            stepTranscribe.classList.add('completed');
            if (stepOcr && !stepOcr.classList.contains('hidden')) stepOcr.classList.add('completed');
            if (stepScene && !stepScene.classList.contains('hidden')) stepScene.classList.add('completed');
            if (stepViral && !stepViral.classList.contains('hidden')) stepViral.classList.add('completed');
            stepAnalyze.classList.add('completed');
            stepCrop.classList.add('active');
        } else if (status === 'completed') {
            [stepDownload, stepTranscribe, stepOcr, stepScene, stepViral, stepAnalyze, stepCrop]
                .filter(Boolean)
                .filter(s => !s.classList.contains('hidden'))
                .forEach(s => s.classList.add('completed'));
        }
    }

    function resetProgressSteps() {
        const allStepIds = ['step-download', 'step-transcribe', 'step-ocr', 'step-scene', 'step-viral', 'step-analyze', 'step-crop'];
        allStepIds.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.classList.remove('active', 'completed');
        });
        progressBarFill.style.width = '0%';
        progressPercentage.textContent = '0%';
        progressStepTitle.textContent = 'Initializing...';
        logsOutputText.textContent = '';
        terminateBtn.classList.add('hidden');
    }

    function resetGenerateBtn() {
        generateBtn.disabled = false;
        generateBtn.querySelector('.btn-text').textContent = 'Generate';
        generateBtn.querySelector('.spinner').classList.add('hidden');
        serverStatusIndicator.className = 'status-dot';
        serverStatusText.textContent = 'System Ready';
        terminateBtn.classList.add('hidden');
        if (cancelGenBtn) {
            cancelGenBtn.disabled = false;
            cancelGenBtn.textContent = 'Cancel Job';
        }
    }

    // Terminate button click handler
    terminateBtn.addEventListener('click', async () => {
        if (!confirm('Are you sure you want to terminate all active processing for this video?')) {
            return;
        }

        terminateBtn.disabled = true;
        terminateBtn.textContent = 'Terminating...';

        try {
            const res = await fetch('/api/terminate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await res.json();
            if (data.status === 'terminated') {
                logsOutputText.textContent += '\n🛑 [System] Termination signal sent.\n';
            } else {
                alert('Termination request failed.');
            }
        } catch (err) {
            console.error('Error terminating processes:', err);
            alert('Error connecting to backend to terminate processes.');
        } finally {
            terminateBtn.disabled = false;
            terminateBtn.textContent = 'Terminate';
        }
    });

    // Load and render generated clips
    async function loadResults() {
        try {
            const res = await fetch('/api/results');
            if (!res.ok) throw new Error('Could not retrieve results');
            const data = await res.json();
            
            // Store results globally to slice transcripts
            window.lastResultsData = data;
            
            const clips = data.shorts || [];
            lastClips = clips;
            resultsCount.textContent = `${clips.length} Clip${clips.length === 1 ? '' : 's'}`;
            document.getElementById('total-clips-stat').textContent = `${clips.length} clip${clips.length === 1 ? '' : 's'} generated`;

            // Populate Movie Analytics card if in movie mode
            if (data.mode === 'movie') {
                const analyticsCard = document.getElementById('movie-analytics');
                if (analyticsCard) {
                    analyticsCard.classList.remove('hidden');
                    const fmt = (v) => v !== undefined && v !== null ? String(v) : '—';
                    const fmtTime = (s) => {
                        if (!s && s !== 0) return '—';
                        const m = Math.floor(s / 60);
                        const sec = Math.floor(s % 60);
                        return `${m}:${sec.toString().padStart(2, '0')}`;
                    };
                    document.getElementById('movie-scenes-found').textContent = fmt(data.scenes_found);
                    document.getElementById('movie-avg-viral').textContent = data.avg_viral_score !== undefined ? data.avg_viral_score.toFixed(1) : '—';
                    document.getElementById('movie-top-ts').textContent = fmtTime(data.top_scene_timestamp);
                    document.getElementById('movie-proc-time').textContent = data.processing_time ? data.processing_time + 's' : '—';
                }
            }

            if (clips.length === 0) {
                shortsGrid.innerHTML = '<div class="no-results">No clips were generated. Check the logs for details.</div>';
                resultsContainer.classList.remove('hidden');
                return;
            }

            renderClips(clips);

            // store aspect ratio on data for re-use
            data.__aspect = data.aspect_ratio || '9:16';

            bindUploadTriggers();
            resultsContainer.classList.remove('hidden');

        } catch (err) {
            console.error('Error loading results:', err);
            shortsGrid.innerHTML = `<div class="no-results">Error loading generated clips: ${err.message}</div>`;
            resultsContainer.classList.remove('hidden');
        }
    }

    function renderClips(clips) {
        // Sort
        const sortVal = sortSelect ? sortSelect.value : 'score';
        const sorted = [...clips].sort((a, b) => {
            if (sortVal === 'duration') return (b.end_time - b.start_time) - (a.end_time - a.start_time);
            if (sortVal === 'start') return a.start_time - b.start_time;
            return (b.score || 0) - (a.score || 0);
        });

        shortsGrid.innerHTML = '';
        sorted.forEach((clip, index) => {
            const aspect = clip.__aspect || '9:16';
            const aspectClass = aspect === '1:1' ? 'aspect-1-1' : (aspect === '16:9' ? 'aspect-16-9' : 'aspect-9-16');
            const score = clip.score || 0;
            const scoreClass = score >= 90 ? 'excellent' : 'good';
            const dur = (clip.end_time - clip.start_time).toFixed(1);
            const videoSource = clip.clip_url
                ? `<video src="${clip.clip_url}" controls></video>`
                : `<div class="video-error">Rendering failed</div>`;

            const card = document.createElement('div');
            card.className = 'short-card';

            let modeBadge = '';
            if (clip.mode === 'ranking') {
                modeBadge = `<div style="margin-bottom: 8px;"><span class="viral-score-badge low">Rank Countdown</span></div>`;
            } else if (clip.mode === 'movie') {
                const isHigh = score >= 75;
                modeBadge = `<div style="margin-bottom: 8px;"><span class="viral-score-badge ${isHigh ? 'high' : 'low'}">Viral Score: ${score}/100</span></div>`;
            }

            card.innerHTML = `
                <div class="video-container ${aspectClass}">
                    ${videoSource}
                    <div class="score-badge ${scoreClass}">
                        <span class="score-num">${score}</span>
                        <span class="score-lbl">Score</span>
                    </div>
                </div>
                <div class="short-info">
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; gap: 10px;">
                        <h4 class="short-title" style="margin: 0; flex: 1;">${clip.title || `Highlight #${index + 1}`}</h4>
                        <input type="checkbox" class="bulk-clip-checkbox" 
                               data-clip-url="${clip.clip_url || ''}"
                               data-title="${(clip.title || `Highlight #${index + 1}`).replace(/"/g, '&quot;')}"
                               data-hook="${(clip.hook_sentence || '').replace(/"/g, '&quot;')}"
                               data-reason="${(clip.virality_reason || '').replace(/"/g, '&quot;')}"
                               data-score="${clip.score || 0}"
                               data-start="${clip.start_time}"
                               data-end="${clip.end_time}"
                               checked 
                               style="width: 18px; height: 18px; accent-color: var(--t1); cursor: pointer; flex-shrink: 0;">
                    </div>
                    ${modeBadge}
                    <div class="short-details">
                        <div class="detail-item">
                            <span class="detail-label">Start</span>
                            <span class="detail-text">${clip.start_time.toFixed(1)}s</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">End</span>
                            <span class="detail-text">${clip.end_time.toFixed(1)}s</span>
                        </div>
                        <div class="detail-item">
                            <span class="detail-label">Duration</span>
                            <span class="detail-text">${dur}s</span>
                        </div>
                    </div>
                    <div class="hook-box">
                        <span class="box-title">Opening Hook</span>
                        <blockquote class="hook-text">&ldquo;${clip.hook_sentence || 'N/A'}&rdquo;</blockquote>
                    </div>
                    <div class="reason-box">
                        <span class="box-title">Virality Reason</span>
                        <p class="reason-text">${clip.virality_reason || 'N/A'}</p>
                    </div>
                    <button type="button" class="btn-youtube yt-upload-trigger"
                            data-clip-url="${clip.clip_url || ''}"
                            data-title="${(clip.title || `Highlight #${index + 1}`).replace(/"/g, '&quot;')}"
                            data-hook="${(clip.hook_sentence || '').replace(/"/g, '&quot;')}"
                            data-reason="${(clip.virality_reason || '').replace(/"/g, '&quot;')}"
                            data-score="${clip.score || 0}"
                            data-start="${clip.start_time}"
                            data-end="${clip.end_time}">
                        Upload to YouTube
                    </button>
                </div>
            `;
            shortsGrid.appendChild(card);
        });
        bindUploadTriggers();
    }

    function bindUploadTriggers() {
        shortsGrid.querySelectorAll('.yt-upload-trigger').forEach(btn => {
            btn.addEventListener('click', () => {
                openUploadModal(
                    btn.getAttribute('data-clip-url'),
                    btn.getAttribute('data-title'),
                    btn.getAttribute('data-hook'),
                    btn.getAttribute('data-reason'),
                    btn.getAttribute('data-score'),
                    document.getElementById('video-url').value.trim(),
                    btn.getAttribute('data-start'),
                    btn.getAttribute('data-end')
                );
            });
        });
    }

    // === YouTube Integration Module ===
    // Account 1 elements
    const ytStatusBadge1 = document.getElementById('yt-status-badge-1');
    const ytChannelInfo1 = document.getElementById('yt-channel-info-1');
    const ytChannelThumb1 = document.getElementById('yt-channel-thumb-1');
    const ytChannelTitle1 = document.getElementById('yt-channel-title-1');
    const ytHelpText1 = document.getElementById('yt-help-text-1');

    // Account 2 elements
    const ytStatusBadge2 = document.getElementById('yt-status-badge-2');
    const ytChannelInfo2 = document.getElementById('yt-channel-info-2');
    const ytChannelThumb2 = document.getElementById('yt-channel-thumb-2');
    const ytChannelTitle2 = document.getElementById('yt-channel-title-2');
    const ytHelpText2 = document.getElementById('yt-help-text-2');

    // Modal elements
    const ytUploadModal = document.getElementById('yt-upload-modal');
    const ytModalCloseBtn = document.getElementById('yt-modal-close-btn');
    const ytModalCancelBtn = document.getElementById('yt-modal-cancel-btn');
    const ytModalSubmitBtn = document.getElementById('yt-modal-submit-btn');
    const ytModalVideo = document.getElementById('yt-modal-video');
    const ytUploadTitleInput = document.getElementById('yt-upload-title');
    const ytTitleCharCount = document.getElementById('yt-title-char-count');
    const suggestShortsTag = document.getElementById('suggest-shorts-tag');
    const ytUploadDescriptionInput = document.getElementById('yt-upload-description');
    const ytUploadAccountSelect = document.getElementById('yt-upload-account');
    const ytUploadPrivacySelect = document.getElementById('yt-upload-privacy');
    const ytUploadTypeSelect = document.getElementById('yt-upload-type');
    const ytUploadProgressContainer = document.getElementById('yt-upload-progress-container');
    const ytUploadStatusText = document.getElementById('yt-upload-status-text');
    const ytUploadPercentage = document.getElementById('yt-upload-percentage');
    const ytUploadBarFill = document.getElementById('yt-upload-bar-fill');
    const ytUploadLogs = document.getElementById('yt-upload-logs');

    // Bulk upload elements
    const bulkUploadModal = document.getElementById('bulk-upload-modal');
    const bulkModalCloseBtn = document.getElementById('bulk-modal-close-btn');
    const bulkModalCancelBtn = document.getElementById('bulk-modal-cancel-btn');
    const bulkModalSubmitBtn = document.getElementById('bulk-modal-submit-btn');
    const bulkUploadAccountSelect = document.getElementById('bulk-upload-account');
    const bulkUploadPrivacySelect = document.getElementById('bulk-upload-privacy');
    const bulkUploadTypeSelect = document.getElementById('bulk-upload-type');
    const bulkSelectedList = document.getElementById('bulk-selected-list');
    const bulkUploadProgressContainer = document.getElementById('bulk-upload-progress-container');
    const bulkUploadStatusText = document.getElementById('bulk-upload-status-text');
    const bulkUploadPercentage = document.getElementById('bulk-upload-percentage');
    const bulkUploadBarFill = document.getElementById('bulk-upload-bar-fill');
    const bulkUploadLogs = document.getElementById('bulk-upload-logs');
    const bulkUploadBtn = document.getElementById('bulk-upload-btn');

    let isYoutubeConnected = false;
    let connectedAccounts = [];
    let currentUploadJobId = null;
    let currentUploadPollInterval = null;
    let currentModalClipUrl = '';

    // Fetch initial status
    fetchYoutubeStatus();

    // YouTube Status function
    async function fetchYoutubeStatus() {
        try {
            const res = await fetch('/api/youtube/status');
            const data = await res.json();
            
            connectedAccounts = data.accounts || [];
            isYoutubeConnected = connectedAccounts.some(acc => acc.connected);
            
            // Render Account 1
            const acc1 = connectedAccounts.find(a => a.account_id === 1);
            if (acc1 && acc1.connected) {
                ytStatusBadge1.textContent = 'Connected';
                ytStatusBadge1.className = 'badge-status connected';
                ytChannelInfo1.classList.remove('hidden');
                ytChannelTitle1.textContent = acc1.channel?.title || 'Account 1';
                ytChannelThumb1.src = acc1.channel?.thumbnail || '';
                ytHelpText1.style.display = 'none';
            } else {
                ytStatusBadge1.textContent = 'Disconnected';
                ytStatusBadge1.className = 'badge-status not-connected';
                ytChannelInfo1.classList.add('hidden');
                ytHelpText1.style.display = 'block';
            }

            // Render Account 2
            const acc2 = connectedAccounts.find(a => a.account_id === 2);
            if (acc2 && acc2.connected) {
                ytStatusBadge2.textContent = 'Connected';
                ytStatusBadge2.className = 'badge-status connected';
                ytChannelInfo2.classList.remove('hidden');
                ytChannelTitle2.textContent = acc2.channel?.title || 'Account 2';
                ytChannelThumb2.src = acc2.channel?.thumbnail || '';
                ytHelpText2.style.display = 'none';
            } else {
                ytStatusBadge2.textContent = 'Disconnected';
                ytStatusBadge2.className = 'badge-status not-connected';
                ytChannelInfo2.classList.add('hidden');
                ytHelpText2.style.display = 'block';
            }

            // Populate account selector dropdown in the modal
            ytUploadAccountSelect.innerHTML = '';
            bulkUploadAccountSelect.innerHTML = '';
            const connected = connectedAccounts.filter(a => a.connected);
            if (connected.length === 0) {
                const opt = document.createElement('option');
                opt.value = '';
                opt.textContent = 'No connected accounts';
                ytUploadAccountSelect.appendChild(opt);

                const opt2 = document.createElement('option');
                opt2.value = '';
                opt2.textContent = 'No connected accounts';
                bulkUploadAccountSelect.appendChild(opt2);
            } else {
                connected.forEach(acc => {
                    const opt = document.createElement('option');
                    opt.value = acc.account_id;
                    opt.textContent = `Account ${acc.account_id}: ${acc.channel?.title || 'YouTube Channel'}`;
                    ytUploadAccountSelect.appendChild(opt);

                    const opt2 = document.createElement('option');
                    opt2.value = acc.account_id;
                    opt2.textContent = `Account ${acc.account_id}: ${acc.channel?.title || 'YouTube Channel'}`;
                    bulkUploadAccountSelect.appendChild(opt2);
                });
            }

        } catch (err) {
            console.error('Error fetching YouTube status:', err);
        }
    }

    // Open Video Upload Modal function
    // Store metadata for Groq
    let currentModalHook = '';
    let currentModalReason = '';
    let currentModalScore = '';
    let currentModalSourceUrl = '';
    let currentModalStartTime = null;
    let currentModalEndTime = null;

    function openUploadModal(clipUrl, title, hook, reason, score, sourceUrl, startTime, endTime) {
        if (!isYoutubeConnected) {
            alert('Please connect at least one YouTube integration first by placing your token files in the workspace.');
            return;
        }

        currentModalClipUrl = clipUrl;
        currentModalHook = hook || '';
        currentModalReason = reason || '';
        currentModalScore = score || '';
        currentModalSourceUrl = sourceUrl || document.getElementById('video-url').value.trim();
        currentModalStartTime = startTime ? parseFloat(startTime) : null;
        currentModalEndTime = endTime ? parseFloat(endTime) : null;

        // Reset modal state
        ytModalVideo.src = clipUrl;
        ytModalVideo.load();

        ytUploadTitleInput.value = title || '';
        updateTitleCharCount();

        // Construct description
        let desc = '';
        if (hook) desc += `Hook: "${hook}"\n\n`;
        if (reason) desc += `Why it works: ${reason}\n\n`;
        desc += `Generated by AI Shorts Generator. #shorts #viral #ai`;
        ytUploadDescriptionInput.value = desc;

        // Reset groq status
        const groqStatus = document.getElementById('groq-status');
        if (groqStatus) { groqStatus.textContent = ''; groqStatus.classList.add('hidden'); groqStatus.className = 'groq-status hidden'; }

        // Reset progress views
        ytUploadProgressContainer.classList.add('hidden');
        ytUploadLogs.textContent = 'Ready to upload...';
        ytUploadBarFill.style.width = '0%';
        ytUploadPercentage.textContent = '0%';
        ytUploadStatusText.textContent = 'Uploading to YouTube...';

        // Enable buttons
        ytModalSubmitBtn.disabled = false;

        // Setup initial submit button text/state
        const newSubmitBtn = ytModalSubmitBtn.cloneNode(true);
        ytModalSubmitBtn.parentNode.replaceChild(newSubmitBtn, ytModalSubmitBtn);

        // Re-get element reference since it was replaced
        const updatedSubmitBtn = document.getElementById('yt-modal-submit-btn');
        updatedSubmitBtn.querySelector('.btn-text').textContent = 'Publish to YouTube';
        updatedSubmitBtn.querySelector('.spinner').classList.add('hidden');

        // Attach normal submit handler
        updatedSubmitBtn.addEventListener('click', startPublishFlow);

        ytModalCancelBtn.disabled = false;
        ytModalCancelBtn.textContent = 'Cancel';
        ytModalCloseBtn.disabled = false;

        currentUploadJobId = null;
        if (currentUploadPollInterval) {
            clearInterval(currentUploadPollInterval);
            currentUploadPollInterval = null;
        }

        // Show modal
        ytUploadModal.classList.remove('hidden');
    }

    // Modal Events
    ytModalCloseBtn.addEventListener('click', closeUploadModal);
    ytModalCancelBtn.addEventListener('click', closeUploadModal);

    function closeUploadModal() {
        ytModalVideo.pause();
        ytModalVideo.src = '';
        ytUploadModal.classList.add('hidden');
        if (currentUploadPollInterval) {
            clearInterval(currentUploadPollInterval);
            currentUploadPollInterval = null;
        }
    }

    // Helper to extract segments matching the clip timeline
    function getClipTranscriptText(start, end) {
        if (!window.lastResultsData || !window.lastResultsData.transcript || !window.lastResultsData.transcript.segments) {
            return '';
        }
        if (start === null || end === null) return '';
        return window.lastResultsData.transcript.segments
            .filter(seg => seg.start >= start - 1.0 && seg.end <= end + 1.0)
            .map(seg => seg.text)
            .join(' ')
            .trim();
    }

    // ── Groq AI Generate ──────────────────────────────────────────────────────
    const groqGenerateBtn = document.getElementById('groq-generate-btn');
    if (groqGenerateBtn) {
        groqGenerateBtn.addEventListener('click', async () => {
            const groqStatus = document.getElementById('groq-status');
            const btnText = groqGenerateBtn.querySelector('.btn-text');
            const spinner = groqGenerateBtn.querySelector('.spinner');

            // Loading state
            groqGenerateBtn.disabled = true;
            btnText.textContent = 'Generating…';
            spinner.classList.remove('hidden');
            groqStatus.className = 'groq-status';
            groqStatus.textContent = '⚡ Calling Groq AI…';

            try {
                // Get slice of transcript for this clip
                const transcriptText = getClipTranscriptText(currentModalStartTime, currentModalEndTime) || currentModalHook;
                
                const res = await fetch('/api/groq/generate-metadata', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        transcript: transcriptText,
                        video_topic: ytUploadTitleInput.value || currentModalHook || "YouTube Highlight Clip",
                        video_summary: currentModalReason,
                        keywords: `${ytUploadTitleInput.value} ${currentModalHook}`.trim()
                    })
                });
                const data = await res.json();

                if (!res.ok || data.error) {
                    throw new Error(data.error || 'Groq request failed');
                }

                // Fill in the fields
                if (data.title) {
                    ytUploadTitleInput.value = data.title.substring(0, 100);
                    updateTitleCharCount();
                }
                if (data.description) {
                    ytUploadDescriptionInput.value = data.description;
                }

                groqStatus.className = 'groq-status success';
                groqStatus.textContent = '✓ Generated successfully — review and edit before publishing.';

            } catch (err) {
                groqStatus.className = 'groq-status error';
                groqStatus.textContent = `✕ ${err.message}`;
            } finally {
                groqGenerateBtn.disabled = false;
                btnText.textContent = '✦ Generate';
                spinner.classList.add('hidden');
            }
        });
    }

    // Character counter
    ytUploadTitleInput.addEventListener('input', updateTitleCharCount);

    function updateTitleCharCount() {
        const len = ytUploadTitleInput.value.length;
        ytTitleCharCount.textContent = `${len}/100`;
        if (len > 90) {
            ytTitleCharCount.style.color = 'var(--accent-danger)';
        } else {
            ytTitleCharCount.style.color = 'var(--text-muted)';
        }
    }

    // Suggest Shorts Tag
    suggestShortsTag.addEventListener('click', () => {
        let currentTitle = ytUploadTitleInput.value.trim();
        if (!currentTitle.toLowerCase().includes('#shorts')) {
            if (currentTitle.length + 8 <= 100) {
                ytUploadTitleInput.value = currentTitle + ' #shorts';
                updateTitleCharCount();
            } else {
                alert('Title is too long to append #shorts. Please make title shorter first.');
            }
        }
    });

    // Handle Publish Submit Click
    async function startPublishFlow() {
        const title = ytUploadTitleInput.value.trim();
        if (!title) {
            alert('Please enter a title for your video.');
            return;
        }

        const accountId = ytUploadAccountSelect.value;
        if (!accountId) {
            alert('Please select a connected YouTube account to upload to.');
            return;
        }
        
        const description = ytUploadDescriptionInput.value;
        const privacyStatus = ytUploadPrivacySelect.value;
        const uploadType = ytUploadTypeSelect.value;
        const updatedSubmitBtn = document.getElementById('yt-modal-submit-btn');
        
        // Update UI state
        updatedSubmitBtn.disabled = true;
        updatedSubmitBtn.querySelector('.btn-text').textContent = 'Uploading...';
        updatedSubmitBtn.querySelector('.spinner').classList.remove('hidden');
        
        ytModalCancelBtn.disabled = true;
        ytModalCloseBtn.disabled = true;
        
        ytUploadProgressContainer.classList.remove('hidden');
        ytUploadLogs.textContent = 'Starting background upload process...\n';
        ytUploadBarFill.style.width = '5%';
        ytUploadPercentage.textContent = '5%';
        
        try {
            const res = await fetch('/api/youtube/upload', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    account_id: accountId,
                    clip_url: currentModalClipUrl,
                    title: title,
                    description: description,
                    privacy_status: privacyStatus,
                    upload_type: uploadType
                })
            });
            
            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.error || 'Failed to start upload.');
            }
            
            currentUploadJobId = data.job_id;
            ytUploadLogs.textContent += `Upload job initialized. Job ID: ${currentUploadJobId}\nWaiting for progress updates...\n`;
            
            // Poll progress
            if (currentUploadPollInterval) clearInterval(currentUploadPollInterval);
            currentUploadPollInterval = setInterval(pollUploadStatus, 1000);
            
        } catch (err) {
            ytUploadLogs.textContent += `❌ Initialization Error: ${err.message}\n`;
            resetModalButtons();
        }
    }

    async function pollUploadStatus() {
        if (!currentUploadJobId) return;
        
        try {
            const res = await fetch(`/api/youtube/upload/status/${currentUploadJobId}`);
            if (!res.ok) throw new Error('Failed to query upload status.');
            const data = await res.json();
            
            ytUploadBarFill.style.width = `${data.progress}%`;
            ytUploadPercentage.textContent = `${data.progress}%`;
            
            if (data.status === 'uploading') {
                ytUploadStatusText.textContent = 'Uploading bytes to YouTube API...';
                ytUploadLogs.textContent += `Progress: ${data.progress}%\n`;
                ytUploadLogs.scrollTop = ytUploadLogs.scrollHeight;
            } else if (data.status === 'completed') {
                clearInterval(currentUploadPollInterval);
                currentUploadPollInterval = null;
                
                ytUploadStatusText.textContent = '🎉 Upload Successful!';
                ytUploadLogs.textContent += `\n🎉 Video successfully uploaded to YouTube!\nVideo ID: ${data.video_id}\nURL: https://youtu.be/${data.video_id}\n`;
                ytUploadLogs.scrollTop = ytUploadLogs.scrollHeight;
                
                // Done actions
                const updatedSubmitBtn = document.getElementById('yt-modal-submit-btn');
                updatedSubmitBtn.disabled = false;
                updatedSubmitBtn.querySelector('.spinner').classList.add('hidden');
                updatedSubmitBtn.querySelector('.btn-text').textContent = 'Open Video on YouTube';
                
                // Replace event listener dynamically to open the video
                const openVideoFn = () => {
                    window.open(`https://youtu.be/${data.video_id}`, '_blank');
                };
                
                const newSubmitBtn = updatedSubmitBtn.cloneNode(true);
                updatedSubmitBtn.parentNode.replaceChild(newSubmitBtn, updatedSubmitBtn);
                newSubmitBtn.addEventListener('click', openVideoFn);
                
                // Re-enable cancel button as "Close"
                ytModalCancelBtn.disabled = false;
                ytModalCancelBtn.textContent = 'Close';
                ytModalCloseBtn.disabled = false;
            } else if (data.status === 'failed') {
                clearInterval(currentUploadPollInterval);
                currentUploadPollInterval = null;
                
                ytUploadStatusText.textContent = '❌ Upload Failed';
                ytUploadLogs.textContent += `\n❌ Upload failed: ${data.error}\n`;
                ytUploadLogs.scrollTop = ytUploadLogs.scrollHeight;
                
                resetModalButtons();
            }
        } catch (err) {
            console.error('Error polling upload status:', err);
        }
    }

    function resetModalButtons() {
        const updatedSubmitBtn = document.getElementById('yt-modal-submit-btn');
        updatedSubmitBtn.disabled = false;
        updatedSubmitBtn.querySelector('.btn-text').textContent = 'Publish to YouTube';
        updatedSubmitBtn.querySelector('.spinner').classList.add('hidden');
        
        ytModalCancelBtn.disabled = false;
        ytModalCancelBtn.textContent = 'Cancel';
        ytModalCloseBtn.disabled = false;
    }

    // === Bulk Upload Logic ===
    if (bulkUploadBtn) {
        bulkUploadBtn.addEventListener('click', () => {
            const selectedBoxes = shortsGrid.querySelectorAll('.bulk-clip-checkbox:checked');
            if (selectedBoxes.length === 0) {
                alert('Please select at least one generated clip to auto-upload.');
                return;
            }

            // Populate selected list in modal
            bulkSelectedList.innerHTML = '';
            selectedBoxes.forEach((box, i) => {
                const title = box.getAttribute('data-title');
                const start = parseFloat(box.getAttribute('data-start'));
                const end = parseFloat(box.getAttribute('data-end'));
                const dur = (end - start).toFixed(0);
                
                const item = document.createElement('div');
                item.style.fontSize = '12px';
                item.style.padding = '4px 8px';
                item.style.background = 'rgba(255, 255, 255, 0.05)';
                item.style.border = '1px solid var(--border)';
                item.style.borderRadius = '3px';
                item.textContent = `${i + 1}. ${title} (${dur}s)`;
                bulkSelectedList.appendChild(item);
            });

            // Reset modal states
            bulkUploadLogs.textContent = 'Waiting to start...';
            bulkUploadStatusText.textContent = 'Ready to bulk upload...';
            bulkUploadPercentage.textContent = '0%';
            bulkUploadBarFill.style.width = '0%';
            bulkUploadProgressContainer.classList.add('hidden');
            
            bulkModalSubmitBtn.disabled = false;
            bulkModalSubmitBtn.querySelector('.btn-text').textContent = 'Start Bulk Upload';
            bulkModalSubmitBtn.querySelector('.spinner').classList.add('hidden');
            bulkModalCancelBtn.disabled = false;
            bulkModalCancelBtn.textContent = 'Cancel';
            bulkModalCloseBtn.disabled = false;

            bulkUploadModal.classList.remove('hidden');
        });
    }

    // Modal Close actions
    const closeBulkModal = () => {
        bulkUploadModal.classList.add('hidden');
    };
    if (bulkModalCloseBtn) bulkModalCloseBtn.addEventListener('click', closeBulkModal);
    if (bulkModalCancelBtn) bulkModalCancelBtn.addEventListener('click', closeBulkModal);

    if (bulkModalSubmitBtn) {
        bulkModalSubmitBtn.addEventListener('click', async () => {
            const selectedBoxes = shortsGrid.querySelectorAll('.bulk-clip-checkbox:checked');
            if (selectedBoxes.length === 0) return;

            const accountId = bulkUploadAccountSelect.value;
            if (!accountId) {
                alert('Please select a connected YouTube account to upload to.');
                return;
            }

            const privacyStatus = bulkUploadPrivacySelect.value;
            const uploadType = bulkUploadTypeSelect.value;

            // Update UI state
            bulkModalSubmitBtn.disabled = true;
            bulkModalSubmitBtn.querySelector('.btn-text').textContent = 'Uploading...';
            bulkModalSubmitBtn.querySelector('.spinner').classList.remove('hidden');
            bulkModalCancelBtn.disabled = true;
            bulkModalCloseBtn.disabled = true;

            bulkUploadProgressContainer.classList.remove('hidden');
            bulkUploadLogs.textContent = `Starting bulk upload of ${selectedBoxes.length} videos...\n\n`;
            bulkUploadBarFill.style.width = '0%';
            bulkUploadPercentage.textContent = '0%';

            for (let i = 0; i < selectedBoxes.length; i++) {
                const box = selectedBoxes[i];
                const clipUrl = box.getAttribute('data-clip-url');
                const title = box.getAttribute('data-title');
                const hook = box.getAttribute('data-hook');
                const reason = box.getAttribute('data-reason');
                const score = box.getAttribute('data-score');
                const start = box.getAttribute('data-start');
                const end = box.getAttribute('data-end');

                const videoNum = i + 1;
                bulkUploadLogs.textContent += `[${videoNum}/${selectedBoxes.length}] Processing "${title}"...\n`;
                bulkUploadLogs.scrollTop = bulkUploadLogs.scrollHeight;
                bulkUploadStatusText.textContent = `Optimizing metadata for video ${videoNum}/${selectedBoxes.length}...`;

                let finalTitle = title;
                let finalDescription = `Check out this viral moment!\n\n#shorts`;

                // Try generating metadata with Groq API
                try {
                    const groqRes = await fetch('/api/groq/generate-metadata', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            transcript: hook,
                            video_topic: title,
                            video_summary: reason,
                            keywords: `${title} ${hook}`
                        })
                    });

                    if (groqRes.ok) {
                        const groqData = await groqRes.json();
                        finalTitle = groqData.title || title;
                        finalDescription = groqData.description || finalDescription;
                        if (groqData.hashtags) {
                            finalDescription += `\n\n${groqData.hashtags}`;
                        }
                        bulkUploadLogs.textContent += `  → Groq AI optimized title: "${finalTitle}"\n`;
                    } else {
                        bulkUploadLogs.textContent += `  → (Groq API returned an error, using fallback title)\n`;
                    }
                } catch (groqErr) {
                    bulkUploadLogs.textContent += `  → (Failed to connect to Groq AI: ${groqErr.message})\n`;
                }

                bulkUploadLogs.scrollTop = bulkUploadLogs.scrollHeight;
                bulkUploadStatusText.textContent = `Uploading video ${videoNum}/${selectedBoxes.length} to YouTube...`;

                // Call YouTube Upload
                try {
                    const uploadRes = await fetch('/api/youtube/upload', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            account_id: accountId,
                            clip_url: clipUrl,
                            title: finalTitle,
                            description: finalDescription,
                            privacy_status: privacyStatus,
                            upload_type: uploadType
                        })
                    });

                    const uploadData = await uploadRes.json();
                    if (!uploadRes.ok) {
                        throw new Error(uploadData.error || 'Upload initialization failed');
                    }

                    const jobId = uploadData.job_id;
                    bulkUploadLogs.textContent += `  → Upload job initialized (ID: ${jobId}). Waiting for progress...\n`;
                    bulkUploadLogs.scrollTop = bulkUploadLogs.scrollHeight;

                    // Poll status for this job
                    let done = false;
                    let pollErrorCount = 0;
                    while (!done) {
                        await new Promise(r => setTimeout(r, 2000));
                        try {
                            const statusRes = await fetch(`/api/youtube/upload/status/${jobId}`);
                            if (!statusRes.ok) throw new Error('Status check failed');
                            const statusData = await statusRes.json();

                            bulkUploadStatusText.textContent = `Uploading video ${videoNum}/${selectedBoxes.length}... (${statusData.progress}%)`;
                            
                            // Overall Progress Calculation
                            const currentClipBase = i * 100;
                            const overallPct = Math.round((currentClipBase + statusData.progress) / selectedBoxes.length);
                            bulkUploadBarFill.style.width = `${overallPct}%`;
                            bulkUploadPercentage.textContent = `${overallPct}%`;

                            if (statusData.status === 'completed') {
                                bulkUploadLogs.textContent += `  → 🎉 Success! Video ID: ${statusData.video_id}\n\n`;
                                done = true;
                            } else if (statusData.status === 'failed') {
                                throw new Error(statusData.error || 'Upload failed');
                            }
                            pollErrorCount = 0; // reset error count on success
                        } catch (pollErr) {
                            pollErrorCount++;
                            if (pollErrorCount > 5) {
                                throw new Error(`Polling failed consecutively: ${pollErr.message}`);
                            }
                        }
                    }
                } catch (uploadErr) {
                    bulkUploadLogs.textContent += `  → ❌ Error uploading: ${uploadErr.message}\n\n`;
                }
                bulkUploadLogs.scrollTop = bulkUploadLogs.scrollHeight;
            }

            // Finish bulk flow
            bulkUploadStatusText.textContent = '🎉 Bulk Upload Complete!';
            bulkUploadBarFill.style.width = '100%';
            bulkUploadPercentage.textContent = '100%';
            bulkUploadLogs.textContent += `\n*** ALL UPLOADS COMPLETED ***\n`;
            bulkUploadLogs.scrollTop = bulkUploadLogs.scrollHeight;

            bulkModalSubmitBtn.querySelector('.spinner').classList.add('hidden');
            bulkModalSubmitBtn.querySelector('.btn-text').textContent = 'Bulk Upload Finished';
            
            bulkModalCancelBtn.disabled = false;
            bulkModalCancelBtn.textContent = 'Close';
            bulkModalCloseBtn.disabled = false;
        });
    }
});

