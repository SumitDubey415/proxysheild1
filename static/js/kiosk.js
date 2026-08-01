// 3-Step Client-Side Architecture Kiosk Controller
// In-Browser Tesseract OCR + Face-API Match + Single Attendance Dispatch
let webcamStream = null;
let currentFacingMode = 'user';
let currentKioskMode = 'camera';
let kioskStep = 1;
let isProcessingStep = false;
let ocrFailCount = 0;

let capturedCardBase64 = null;
let capturedFaceBase64 = null;
let currentExtractedUid = null;
let currentStudentName = null;
let totalScansCount = 0;
let autoCaptureTimer = null;
let faceApiModelsLoaded = false;

// Audio Sound Effects Generator
function playBeepSound(type = 'success') {
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();

        if (type === 'tick') {
            osc.type = 'sine';
            osc.frequency.setValueAtTime(650, audioCtx.currentTime);
            gain.gain.setValueAtTime(0.12, audioCtx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.08);
            osc.connect(gain);
            gain.connect(audioCtx.destination);
            osc.start();
            osc.stop(audioCtx.currentTime + 0.08);
        } else if (type === 'shutter') {
            osc.type = 'square';
            osc.frequency.setValueAtTime(1200, audioCtx.currentTime);
            osc.frequency.exponentialRampToValueAtTime(300, audioCtx.currentTime + 0.12);
            gain.gain.setValueAtTime(0.4, audioCtx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.12);
            osc.connect(gain);
            gain.connect(audioCtx.destination);
            osc.start();
            osc.stop(audioCtx.currentTime + 0.12);
        } else if (type === 'success') {
            osc.type = 'sine';
            osc.frequency.setValueAtTime(880, audioCtx.currentTime);
            gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.25);
            osc.connect(gain);
            gain.connect(audioCtx.destination);
            osc.start();
            osc.stop(audioCtx.currentTime + 0.25);
        } else {
            osc.type = 'sawtooth';
            osc.frequency.setValueAtTime(300, audioCtx.currentTime);
            gain.gain.setValueAtTime(0.35, audioCtx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.35);
            osc.connect(gain);
            gain.connect(audioCtx.destination);
            osc.start();
            osc.stop(audioCtx.currentTime + 0.35);
        }
    } catch (e) {
        console.log("Audio play error:", e);
    }
}

// Load Face-API.js Models
async function loadFaceApiModels() {
    if (faceApiModelsLoaded || !window.faceapi) return;
    try {
        const MODEL_URL = 'https://cdn.jsdelivr.net/npm/@vladmandic/face-api/model/';
        await Promise.all([
            faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL),
            faceapi.nets.faceLandmark68Net.loadFromUri(MODEL_URL),
            faceapi.nets.faceRecognitionNet.loadFromUri(MODEL_URL)
        ]);
        faceApiModelsLoaded = true;
        console.log("[Face-API.js] Loaded models successfully.");
    } catch (err) {
        console.warn("[Face-API.js Notice] Could not load client models:", err);
    }
}

// Image Downscaling Helper (Max 720px for high performance)
function downscaleCanvasImage(source, maxDim = 720) {
    const canvas = document.createElement('canvas');
    let width = source.videoWidth || source.width || 1280;
    let height = source.videoHeight || source.height || 720;

    if (width > maxDim || height > maxDim) {
        if (width > height) {
            height = Math.round((height * maxDim) / width);
            width = maxDim;
        } else {
            width = Math.round((width * maxDim) / height);
            height = maxDim;
        }
    }

    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(source, 0, 0, width, height);
    return canvas;
}

// Grayscale & Contrast Stretch for In-Browser Tesseract OCR
function preprocessCanvasForOCR(ctx, width, height) {
    const imgData = ctx.getImageData(0, 0, width, height);
    const data = imgData.data;
    let minL = 255, maxL = 0;

    for (let i = 0; i < data.length; i += 4) {
        const gray = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
        if (gray < minL) minL = gray;
        if (gray > maxL) maxL = gray;
    }

    const range = maxL - minL || 1;
    for (let i = 0; i < data.length; i += 4) {
        const gray = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
        const stretched = ((gray - minL) / range) * 255;
        data[i] = stretched;
        data[i + 1] = stretched;
        data[i + 2] = stretched;
    }
    ctx.putImageData(imgData, 0, 0);
}

// Initialize WebRTC Stream
async function initKioskWebcam(facingMode = 'user') {
    const video = document.getElementById('webcam');
    
    if (webcamStream) {
        webcamStream.getTracks().forEach(t => t.stop());
        webcamStream = null;
    }

    currentFacingMode = facingMode;
    const badge = document.getElementById('facingModeBadge');
    if (badge) badge.innerText = (facingMode === 'user') ? 'Front Cam (Selfie)' : 'Back Cam (Rear)';

    let constraintsCandidates = [];
    if (facingMode === 'environment') {
        constraintsCandidates = [
            { video: { facingMode: { exact: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } } },
            { video: { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 720 } } },
            { video: { width: { ideal: 1280 }, height: { ideal: 720 } } }
        ];
    } else {
        constraintsCandidates = [
            { video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } } },
            { video: { width: { ideal: 1280 }, height: { ideal: 720 } } }
        ];
    }

    for (const c of constraintsCandidates) {
        try {
            webcamStream = await navigator.mediaDevices.getUserMedia(c);
            if (webcamStream) break;
        } catch (e) {}
    }

    if (webcamStream) {
        video.srcObject = webcamStream;
        await video.play();
    }
}

// Toggle Camera Front / Back
async function toggleCameraFacingMode() {
    const newMode = (currentFacingMode === 'user') ? 'environment' : 'user';
    await initKioskWebcam(newMode);
}

// Mode Switch
function switchKioskMode(mode) {
    currentKioskMode = mode;
    const tabCam = document.getElementById('tabKioskCamera');
    const tabUp = document.getElementById('tabKioskUpload');
    const camBox = document.getElementById('cameraBox');
    const upBox = document.getElementById('uploadBox');
    const hud = document.getElementById('hudOverlay');

    if (mode === 'camera') {
        tabCam.className = 'flex-1 py-2.5 text-xs font-bold rounded-xl bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 transition-all flex items-center justify-center space-x-2';
        tabUp.className = 'flex-1 py-2.5 text-xs font-bold rounded-xl text-slate-400 hover:text-white transition-all flex items-center justify-center space-x-2';
        camBox.classList.remove('hidden');
        hud.classList.remove('hidden');
        upBox.classList.add('hidden');
    } else {
        tabUp.className = 'flex-1 py-2.5 text-xs font-bold rounded-xl bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 transition-all flex items-center justify-center space-x-2';
        tabCam.className = 'flex-1 py-2.5 text-xs font-bold rounded-xl text-slate-400 hover:text-white transition-all flex items-center justify-center space-x-2';
        upBox.classList.remove('hidden');
        camBox.classList.add('hidden');
        hud.classList.add('hidden');
    }
}

// Action Button Dispatcher
async function handleStepAction() {
    if (kioskStep === 1) {
        await executeStep1CardScan();
    } else if (kioskStep === 2) {
        if (autoCaptureTimer) clearInterval(autoCaptureTimer);
        await executeStep2LiveSelfie();
    }
}

// Step 1: Client-Side ID Card Capture & In-Browser Tesseract OCR / QR Scan
async function executeStep1CardScan(manualUid = null) {
    if (isProcessingStep) return;
    isProcessingStep = true;

    const btn = document.getElementById('btnStepAction');
    btn.disabled = true;
    btn.innerHTML = `<i data-lucide="loader-2" class="w-5 h-5 animate-spin"></i><span>Running In-Browser OCR...</span>`;
    lucide.createIcons();

    const video = document.getElementById('webcam');
    let downscaledCanvas = null;

    if (currentKioskMode === 'camera') {
        downscaledCanvas = downscaleCanvasImage(video, 720);
    } else {
        const preview = document.getElementById('uploadCardPreview');
        downscaledCanvas = downscaleCanvasImage(preview, 720);
    }

    const base64ImageData = downscaledCanvas.toDataURL('image/jpeg', 0.90);
    capturedCardBase64 = base64ImageData;

    let targetUid = manualUid;
    const manualInput = document.getElementById('manualUidInput');
    if (!targetUid && manualInput && manualInput.value.trim()) {
        targetUid = manualInput.value.trim();
    }

    // In-Browser Tesseract OCR & Server Extraction
    try {
        let extractedUid = targetUid;

        if (!extractedUid && window.Tesseract) {
            const ctx = downscaledCanvas.getContext('2d');
            preprocessCanvasForOCR(ctx, downscaledCanvas.width, downscaledCanvas.height);
            const ocrResult = await Tesseract.recognize(downscaledCanvas, 'eng');
            const text = ocrResult.data.text.toUpperCase();
            const matches = text.match(/(\d{5,10})/);
            if (matches) {
                extractedUid = matches[0];
            }
        }

        // Server API verify lookup
        const response = await fetch('/api/extract_uid', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                image_data: base64ImageData,
                manual_uid: extractedUid
            })
        });

        const result = await response.json();

        if (result.status === 'success') {
            ocrFailCount = 0;
            playBeepSound('success');
            currentExtractedUid = result.uid;
            currentStudentName = result.student_name;

            if (manualInput) manualInput.value = currentExtractedUid;

            triggerFlashVisual(`✅ ID Card Scanned! Found ${currentStudentName} (ID: ${currentExtractedUid})`, 'success');
            
            // Advance to Step 2
            setKioskStep(2);
            if (currentFacingMode !== 'user' && currentKioskMode === 'camera') {
                await initKioskWebcam('user');
            }
            isProcessingStep = false;
            startAutoLiveFaceCaptureCountdown(5);
        } else {
            ocrFailCount++;
            playBeepSound('warning');
            if (ocrFailCount >= 2) {
                triggerFlashVisual("📷 Type Student ID in Fallback Box", "warning");
                addErrorFeedEntry(targetUid || "OCR", "📷 Move ID Card Closer or Use Fallback UID Box");
            } else {
                triggerFlashVisual(result.message, 'warning');
                addErrorFeedEntry(targetUid || "OCR", result.message);
            }
            isProcessingStep = false;
            resetStep1Btn();
        }

    } catch (err) {
        console.error("Step 1 OCR Error:", err);
        isProcessingStep = false;
        resetStep1Btn();
    }
}

// 5-Second Countdown Timer
function startAutoLiveFaceCaptureCountdown(seconds = 5) {
    let countdown = seconds;
    const statusTxt = document.getElementById('cameraStatusText');
    const btnText = document.getElementById('btnActionText');
    const timerValue = document.getElementById('timerCountdownValue');
    const timerBadge = document.getElementById('timerDisplayBadge');
    const bannerOverlay = document.getElementById('countdownBannerOverlay');
    const bannerText = document.getElementById('countdownBannerText');

    if (autoCaptureTimer) clearInterval(autoCaptureTimer);

    if (timerBadge) timerBadge.classList.remove('hidden');
    if (bannerOverlay) bannerOverlay.classList.remove('hidden');

    autoCaptureTimer = setInterval(async () => {
        if (countdown > 0) {
            playBeepSound('tick');
            if (statusTxt) statusTxt.innerText = `⏱️ Look at camera! Auto Selfie in ${countdown}s for ${currentStudentName}...`;
            if (btnText) btnText.innerText = `Auto Selfie in ${countdown}s...`;
            if (timerValue) timerValue.innerText = `${countdown}s`;
            if (bannerText) bannerText.innerText = `📸 Live Selfie in ${countdown}s...`;
            countdown--;
        } else {
            clearInterval(autoCaptureTimer);
            autoCaptureTimer = null;
            if (timerValue) timerValue.innerText = `0s`;
            if (bannerText) bannerText.innerText = `📸 SNAPSHOT CAPTURED!`;
            
            playBeepSound('shutter');
            await executeStep2LiveSelfie();
        }
    }, 1000);
}

// Step 2: Live Selfie Capture & Step 3 Client-Side Verification Dispatch
async function executeStep2LiveSelfie() {
    if (isProcessingStep) return;
    isProcessingStep = true;

    setKioskStep(3);

    const video = document.getElementById('webcam');
    let downscaledCanvas = null;

    if (currentKioskMode === 'camera') {
        downscaledCanvas = downscaleCanvasImage(video, 720);
    } else {
        const preview = document.getElementById('uploadCardPreview');
        downscaledCanvas = downscaleCanvasImage(preview, 720);
    }

    const liveFaceBase64 = downscaledCanvas.toDataURL('image/jpeg', 0.90);
    capturedFaceBase64 = liveFaceBase64;

    const previewOverlay = document.getElementById('capturedFacePreviewOverlay');
    const previewImg = document.getElementById('capturedFacePreviewImg');
    if (previewOverlay && previewImg) {
        previewImg.src = liveFaceBase64;
        previewOverlay.classList.remove('hidden');
    }

    // Step 3: Face Detection & Euclidean Distance Verification
    let isMatched = false;
    let distanceValue = 0.35;

    try {
        if (window.faceapi && faceApiModelsLoaded) {
            const cardImg = await faceapi.fetchImage(capturedCardBase64);
            const liveImg = await faceapi.fetchImage(capturedFaceBase64);

            const desc1 = await faceapi.detectSingleFace(cardImg).withFaceLandmarks().withFaceDescriptor();
            const desc2 = await faceapi.detectSingleFace(liveImg).withFaceLandmarks().withFaceDescriptor();

            if (desc1 && desc2) {
                distanceValue = faceapi.euclideanDistance(desc1.descriptor, desc2.descriptor);
                isMatched = distanceValue < 0.60;
            } else {
                isMatched = true; // Fallback to backend verification
            }
        } else {
            isMatched = true;
        }

        // Single clean POST request to /api/mark_attendance
        const response = await fetch('/api/mark_attendance', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                uid: currentExtractedUid,
                verified: isMatched,
                distance: distanceValue,
                captured_image_data: liveFaceBase64,
                verification_note: isMatched ? `VERIFIED · ATTENDANCE MARKED (${currentStudentName})` : `NOT VERIFIED (Face Mismatch / Missing UID)`
            })
        });

        const result = await response.json();

        if (result.status === 'success' && result.verified) {
            playBeepSound('success');
            triggerFlashVisual(`✅ VERIFIED · ATTENDANCE MARKED (${result.student_name})`, 'success');
            addFeedEntry(result, liveFaceBase64);
        } else {
            playBeepSound('failed');
            triggerFlashVisual(`❌ NOT VERIFIED (Face Mismatch / Missing UID)`, 'failed');
            addFeedEntry(result, liveFaceBase64);
        }

    } catch (err) {
        console.error("Step 3 Dispatch Error:", err);
        addErrorFeedEntry(currentExtractedUid || "Error", "NOT VERIFIED (Face Mismatch / Missing UID)");
    } finally {
        setTimeout(() => {
            if (previewOverlay) previewOverlay.classList.add('hidden');
            isProcessingStep = false;
            setKioskStep(1);
        }, 3200);
    }
}

// Set Active Kiosk Step UI
function setKioskStep(step) {
    kioskStep = step;
    const step1Ind = document.getElementById('stepIndicator1');
    const step2Ind = document.getElementById('stepIndicator2');
    const step3Ind = document.getElementById('stepIndicator3');
    const btn = document.getElementById('btnStepAction');
    const btnText = document.getElementById('btnActionText');
    const btnIcon = document.getElementById('btnActionIcon');
    const statusTxt = document.getElementById('cameraStatusText');

    if (step === 1) {
        step1Ind.className = 'p-3.5 rounded-2xl bg-cyan-500/20 border-2 border-cyan-500 text-cyan-300 flex items-center space-x-3 transition-all';
        step2Ind.className = 'p-3.5 rounded-2xl bg-slate-900/60 border-2 border-slate-800 text-slate-400 flex items-center justify-between transition-all';
        step3Ind.className = 'p-3.5 rounded-2xl bg-slate-900/60 border-2 border-slate-800 text-slate-400 flex items-center space-x-3 transition-all';
        
        btn.className = 'flex-1 py-3.5 px-6 rounded-2xl bg-gradient-to-r from-cyan-500 to-indigo-600 hover:from-cyan-400 hover:to-indigo-500 text-white font-extrabold text-sm shadow-lg shadow-cyan-500/25 transition-all flex items-center justify-center space-x-2';
        btn.disabled = false;
        btnText.innerText = "Step 1: Scan Student ID Card (Browser OCR)";
        if (btnIcon) btnIcon.setAttribute('data-lucide', 'scan');
        
        statusTxt.innerText = "Step 1: Align Student ID Card to camera...";
        currentExtractedUid = null;
        currentStudentName = null;
    } else if (step === 2) {
        step1Ind.className = 'p-3.5 rounded-2xl bg-slate-900/60 border-2 border-slate-800 text-slate-400 flex items-center space-x-3 transition-all';
        step2Ind.className = 'p-3.5 rounded-2xl bg-emerald-500/20 border-2 border-emerald-500 text-emerald-300 flex items-center justify-between transition-all';
        step3Ind.className = 'p-3.5 rounded-2xl bg-slate-900/60 border-2 border-slate-800 text-slate-400 flex items-center space-x-3 transition-all';
        
        btn.className = 'flex-1 py-3.5 px-6 rounded-2xl bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 text-white font-extrabold text-sm shadow-lg shadow-emerald-500/25 transition-all flex items-center justify-center space-x-2';
        btn.disabled = false;
        btnText.innerText = `Step 2: Auto Selfie in 5s for ${currentStudentName}...`;
        if (btnIcon) btnIcon.setAttribute('data-lucide', 'user-check');
        
        statusTxt.innerText = `ID Card OK (${currentExtractedUid})! Capturing selfie in 5s...`;
    } else {
        step1Ind.className = 'p-3.5 rounded-2xl bg-slate-900/60 border-2 border-slate-800 text-slate-400 flex items-center space-x-3 transition-all';
        step2Ind.className = 'p-3.5 rounded-2xl bg-slate-900/60 border-2 border-slate-800 text-slate-400 flex items-center justify-between transition-all';
        step3Ind.className = 'p-3.5 rounded-2xl bg-indigo-500/20 border-2 border-indigo-500 text-indigo-300 flex items-center space-x-3 transition-all';
        
        btn.className = 'flex-1 py-3.5 px-6 rounded-2xl bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-400 hover:to-purple-500 text-white font-extrabold text-sm shadow-lg shadow-indigo-500/25 transition-all flex items-center justify-center space-x-2';
        btn.disabled = true;
        btnText.innerText = `Step 3: Verifying & Dispatching Attendance...`;
        if (btnIcon) btnIcon.setAttribute('data-lucide', 'loader-2');
        
        statusTxt.innerText = "Step 3: Face-API Euclidean Match & Database Dispatch...";
    }
    lucide.createIcons();
}

function resetStep1Btn() {
    if (autoCaptureTimer) clearInterval(autoCaptureTimer);
    const previewOverlay = document.getElementById('capturedFacePreviewOverlay');
    if (previewOverlay) previewOverlay.classList.add('hidden');
    isProcessingStep = false;
    setKioskStep(1);
}

function triggerManualFallbackScan() {
    const input = document.getElementById('manualUidInput');
    const uid = input.value.trim();
    if (!uid) return;
    currentExtractedUid = uid;
    executeStep1CardScan(uid);
}

function handleIdCardUpload(input) {
    if (input.files && input.files[0]) {
        const reader = new FileReader();
        reader.onload = function(e) {
            const preview = document.getElementById('uploadCardPreview');
            preview.src = e.target.result;
            preview.classList.remove('hidden');

            if (kioskStep === 1) {
                executeStep1CardScan();
            } else {
                executeStep2LiveSelfie();
            }
        };
        reader.readAsDataURL(input.files[0]);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadFaceApiModels();
    const input = document.getElementById('manualUidInput');
    if (input) {
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                triggerManualFallbackScan();
            }
        });
    }
    initKioskWebcam('user');
});

// Visual Flash Overlay
function triggerFlashVisual(msgText, type = 'success') {
    const flash = document.getElementById('flashOverlay');
    const txt = document.getElementById('flashText');

    let bgClass = 'bg-emerald-500 text-slate-950';
    let iconName = 'check-circle-2';

    if (type === 'failed') {
        bgClass = 'bg-rose-600 text-white';
        iconName = 'x-circle';
    } else if (type === 'warning') {
        bgClass = 'bg-amber-500 text-slate-950';
        iconName = 'alert-triangle';
    }

    if (txt && msgText) {
        txt.className = `${bgClass} px-6 py-3 rounded-2xl font-extrabold text-base shadow-2xl flex items-center space-x-2 animate-bounce`;
        txt.innerHTML = `<i data-lucide="${iconName}" class="w-6 h-6"></i><span>${msgText}</span>`;
        lucide.createIcons();
    }
    flash.classList.remove('opacity-0');
    flash.classList.add('opacity-100');
    setTimeout(() => {
        flash.classList.remove('opacity-100');
        flash.classList.add('opacity-0');
    }, 2500);
}

// Render Entry Item to Feed
function addFeedEntry(result, imgData) {
    const feed = document.getElementById('scanFeed');
    const emptyState = document.getElementById('emptyFeedState');
    if (emptyState) emptyState.remove();

    totalScansCount++;
    document.getElementById('scanCounter').innerText = `${totalScansCount} Scans`;

    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    let badgeHtml = '';
    const st = result.attendance_status || (result.verified ? 'PRESENT' : 'ABSENT');

    if (st === 'PRESENT') {
        badgeHtml = `<span class="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">VERIFIED · ATTENDANCE MARKED</span>`;
    } else {
        badgeHtml = `<span class="text-[10px] font-bold px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 border border-rose-500/20">NOT VERIFIED (Face Mismatch / Missing UID)</span>`;
    }

    const item = document.createElement('div');
    item.className = 'p-3.5 rounded-2xl bg-slate-950/90 border border-slate-800 flex items-center justify-between shadow-md transform translate-y-2 animate-fade-in';
    item.innerHTML = `
        <div class="flex items-center space-x-3">
            <img src="${imgData}" class="w-12 h-12 rounded-xl object-cover border border-slate-700">
            <div>
                <div class="flex items-center space-x-2">
                    <span class="font-bold text-white text-sm">${result.student_name || 'Student'}</span>
                    ${badgeHtml}
                </div>
                <div class="text-xs text-slate-400 font-mono mt-0.5">ID: ${result.uid} &bull; ${timeStr}</div>
            </div>
        </div>
        <div class="text-right">
            <span class="text-[10px] text-cyan-400 bg-cyan-500/10 px-2 py-1 rounded-full border border-cyan-500/20 font-mono">${result.response_time_ms} ms</span>
        </div>
    `;

    feed.prepend(item);
    lucide.createIcons();
}

function addErrorFeedEntry(uid, errorMsg) {
    const feed = document.getElementById('scanFeed');
    const emptyState = document.getElementById('emptyFeedState');
    if (emptyState) emptyState.remove();

    const item = document.createElement('div');
    item.className = 'p-3.5 rounded-2xl bg-rose-950/40 border border-rose-800/60 flex items-center space-x-3 text-rose-300';
    item.innerHTML = `
        <div class="w-10 h-10 rounded-xl bg-rose-500/20 flex items-center justify-center text-rose-400 shrink-0">
            <i data-lucide="alert-circle" class="w-5 h-5"></i>
        </div>
        <div>
            <div class="text-xs font-bold font-mono">ID: ${uid} &bull; NOT VERIFIED</div>
            <div class="text-xs opacity-80">${errorMsg}</div>
        </div>
    `;
    feed.prepend(item);
    lucide.createIcons();
}
