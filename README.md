# Smart Anti-Proxy Attendance System

A production-ready, full-stack **Smart Anti-Proxy Attendance System** built with **FastAPI (Python)**, **SQLite**, **OpenCV / Face Recognition**, and **HTML5/Tailwind CSS/JavaScript**.

---

## 🎯 Architectural Highlights (Scan Fast, Verify Later)

### 1. Step 1 (Instant Kiosk Scan - Sub-Second)
- **WebRTC Camera Stream**: Live camera preview with client-side barcode detection via `html5-qrcode` / `ZXingJS`.
- **Instant Silent Snapshot**: Upon Barcode/UID detection, an off-screen HTML5 Canvas silently captures a high-resolution snapshot.
- **Immediate User Feedback**: Plays an instant audio synth beep and displays a green visual confirmation (`✅ Scan Registered`) in **< 1 second**.
- **Lock-Free Database Queue**: Inserts scan record with status `PENDING` into SQLite (WAL mode enabled) and immediately returns control to the client.

### 2. Step 2 (Async Background AI Verification)
- **Asynchronous Worker Thread**: FastAPI `BackgroundTasks` processes the captured snapshot image asynchronously without blocking the user queue.
- **Anti-Proxy Rules Engine**:
  1. **Duplicate Face Rule**: If the same physical face vector is detected under two different UIDs on the same date ($YYYY-MM-DD$), **BOTH** records are flagged as `PROXY_ALERT`.
  2. **Empty Frame Rule**: If 0 human faces are detected in the image, status is set to `FLAGGED_NO_FACE`.
  3. **Upper-Facial Landmark Tolerance**: Emphasizes eyes/forehead landmarks for high tolerance against facial hair changes, glasses, and lighting.
  4. **Baseline Matching**: Compares 128-d face embedding vector against enrolled baseline. If distance $\le \text{threshold}$, status becomes `PRESENT`, else `ABSENT`.

---

## 🛠️ Tech Stack

- **Backend**: Python 3.10+, FastAPI, Uvicorn, SQLite3 (WAL Mode), OpenCV (`cv2`), `face-recognition` (with OpenCV fallback), `Pillow`, `numpy`.
- **Frontend**: HTML5, Tailwind CSS, JavaScript (WebRTC MediaDevices API, Canvas API, Web Audio API, `html5-qrcode`).
- **Reports & Housekeeping**: `ReportLab` (PDF grid), `openpyxl` (Excel grid matrix), 30-day background image purge script.

---

## 📁 Code Structure

```
smart_anti_proxy_system/
├── app.py                     # FastAPI web server and API routes
├── database.py                # SQLite schema definition, WAL mode & helper queries
├── ai_engine.py               # AI Face Matching, Embedding Extractor & Proxy Rule Engine
├── seed_data.py               # Sample data generator for instant testing
├── requirements.txt           # Python dependencies
├── README.md                  # System Documentation
├── static/
│   ├── css/
│   │   └── styles.css         # Glassmorphism styling and custom animations
│   ├── js/
│   │   ├── kiosk.js           # WebRTC camera, audio synth beep, barcode auto-capture
│   │   ├── admin.js           # Faculty table, side-by-side proxy review & overrides
│   │   └── student.js         # Student portal attendance query & radial progress ring
│   └── uploads/
│       ├── enrolled/          # Baseline student reference photos
│       └── captured/          # Instant camera snapshots captured at kiosk
├── templates/
│   ├── base.html              # Base layout template
│   ├── index.html             # System overview landing page
│   ├── enroll.html            # Student enrollment form (baseline photo capture)
│   ├── kiosk.html             # Kiosk scanning mode dashboard
│   ├── admin.html             # Faculty admin attendance & proxy control panel
│   └── student.html           # Student portal (< 75% warning indicator)
└── utils/
    ├── report_generator.py    # Weekly PDF and Excel attendance grid generator
    └── cleanup_cron.py        # 30-day image purge housekeeping script
```

---

## 🚀 Quick Start Guide

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Seed Sample Data (Optional)
Populates initial sample students (e.g. `STU1001`, `STU1002`) and demo proxy alert logs for instant testing:
```bash
python seed_data.py
```

### 3. Launch Web Server
```bash
python app.py
# OR
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Open your browser and navigate to:
- **Home Landing Page**: `http://localhost:8000/`
- **Kiosk Scan Mode**: `http://localhost:8000/kiosk`
- **Student Enrollment**: `http://localhost:8000/enroll`
- **Faculty Admin Panel**: `http://localhost:8000/admin`
- **Student Portal**: `http://localhost:8000/student`

---

## 📊 Generating Reports & Running Cleanup

### Generate Grid PDF / Excel Reports
Access the Faculty Admin Panel (`/admin`) and click:
- **Export PDF Grid**: Downloads printable 7-day attendance grid with checkmarks ($\checkmark$) and crossmarks ($\times$).
- **Export Excel Grid**: Downloads color-coded matrix spreadsheet.

### Run 30-Day Image Cleanup Script
To purge raw snapshot images older than 30 days while retaining database logs:
```bash
python utils/cleanup_cron.py
```
