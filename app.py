import os
import sys

# Force all cache directories to /tmp for Vercel Serverless read-only filesystem
os.environ["HOME"] = "/tmp"
os.environ["NUMBA_CACHE_DIR"] = "/tmp"
os.environ["MPLCONFIGDIR"] = "/tmp"
os.environ["RAPIDOCR_CACHE_DIR"] = "/tmp"
os.environ["TMPDIR"] = "/tmp"

import base64
import json
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, Form, File, UploadFile, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import database
import ai_engine
try:
    from utils.report_generator import generate_weekly_excel_report, generate_weekly_pdf_report
except ModuleNotFoundError:
    try:
        from report_generator import generate_weekly_excel_report, generate_weekly_pdf_report
    except ModuleNotFoundError:
        def generate_weekly_excel_report(output_path, branch_filter=None): pass
        def generate_weekly_pdf_report(output_path, branch_filter=None): pass

# Initialize FastAPI App
app = FastAPI(
    title="Smart Anti-Proxy Attendance System",
    description="High-Speed Hybrid Barcode & Async AI Anti-Proxy Attendance Platform",
    version="1.0.0"
)

# Directories setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

UPLOAD_ENROLLED_DIR = os.path.join(STATIC_DIR, "uploads", "enrolled")
UPLOAD_CAPTURED_DIR = os.path.join(STATIC_DIR, "uploads", "captured")

os.makedirs(UPLOAD_ENROLLED_DIR, exist_ok=True)
os.makedirs(UPLOAD_CAPTURED_DIR, exist_ok=True)

# Mount static files and Jinja templates safely
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

valid_template_dirs = [d for d in [TEMPLATES_DIR, BASE_DIR] if os.path.exists(d)]
templates = Jinja2Templates(directory=valid_template_dirs)

def render_html(request: Request, template_name: str):
    try:
        return templates.TemplateResponse(request=request, name=template_name)
    except Exception:
        paths = [
            os.path.join(TEMPLATES_DIR, template_name),
            os.path.join(BASE_DIR, template_name)
        ]
        for p in paths:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    return HTMLResponse(content=f.read())
        return HTMLResponse(content=f"<h1>Template {template_name} Error</h1>")

@app.on_event("startup")
def startup_event():
    """Initialize DB and seed default sample data if empty."""
    database.init_db()
    print("[Startup] SQLite database initialized and ready.")

# --- WEB PAGE ROUTES ---

@app.get("/", response_class=HTMLResponse)
def page_home(request: Request):
    """System Landing Overview Page."""
    return render_html(request, "index.html")

@app.get("/enroll", response_class=HTMLResponse)
def page_enroll(request: Request):
    """Student Enrollment Module Page."""
    return render_html(request, "enroll.html")

@app.get("/kiosk", response_class=HTMLResponse)
def page_kiosk(request: Request):
    """Kiosk Barcode & Instant Camera Scan Page."""
    return render_html(request, "kiosk.html")

@app.get("/admin", response_class=HTMLResponse)
def page_admin(request: Request):
    """Faculty / Admin Attendance Dashboard."""
    return render_html(request, "admin.html")

@app.get("/student", response_class=HTMLResponse)
def page_student(request: Request):
    """Student Attendance Portal Page."""
    return render_html(request, "student.html")


# --- API ENDPOINTS ---

class ScanRequest(BaseModel):
    uid: str
    image_data: str # Base64 encoded image string

@app.post("/api/enroll")
async def api_enroll_student(
    name: str = Form(...),
    uid: str = Form(...),
    roll_no: Optional[str] = Form(None),
    branch: str = Form(...),
    photo: Optional[UploadFile] = File(None),
    captured_image_base64: Optional[str] = Form(None)
):
    """
    Enroll a new student baseline into system.
    Extracts baseline 128-d face vector and stores profile photo.
    """
    try:
        if not roll_no:
            roll_no = uid

        # Check if student already exists
        existing = database.get_student_by_uid(uid)
        if existing:
            return JSONResponse({"status": "error", "message": f"Student with UID '{uid}' is already registered."}, status_code=400)

        filename = f"{uid}_{int(datetime.now().timestamp())}.jpg"
        filepath = os.path.join(UPLOAD_ENROLLED_DIR, filename)
        db_photo_path = f"/static/uploads/enrolled/{filename}"

        if photo:
            content = await photo.read()
            with open(filepath, "wb") as f:
                f.write(content)
        elif captured_image_base64:
            if "," in captured_image_base64:
                captured_image_base64 = captured_image_base64.split(",")[1]
            image_bytes = base64.b64decode(captured_image_base64)
            with open(filepath, "wb") as f:
                f.write(image_bytes)
        else:
            return JSONResponse({"status": "error", "message": "Baseline student photo is required."}, status_code=400)

        # Extract baseline face vector
        encoding, face_count = ai_engine.extract_face_encoding(filepath)
        if face_count == 0:
            os.remove(filepath)
            return JSONResponse({"status": "error", "message": "No clear face detected in the provided baseline photo. Please provide a clear facial picture."}, status_code=400)

        # Save to database
        database.add_student(uid, name, roll_no, branch, db_photo_path, encoding)

        return JSONResponse({
            "status": "success",
            "message": f"Student '{name}' (UID: {uid}) successfully enrolled!",
            "photo_path": db_photo_path
        })
    except Exception as e:
        print(f"[API Enroll Error] {e}")
        return JSONResponse({"status": "error", "message": f"Enrollment failed: {str(e)}"}, status_code=500)

@app.post("/api/scan")
def api_kiosk_scan(data: ScanRequest, background_tasks: BackgroundTasks):
    """
    Step 1 (Instant Scan at Kiosk):
    - Validates Barcode UID.
    - Saves snapshot photo to disk.
    - Saves raw scan record with Status="PENDING" in SQLite DB.
    - Returns instant success message in < 1 second.
    - Queues Async Background AI Worker Task (Step 2).
    """
    start_time = datetime.now()
    uid = data.uid.strip()

    if not uid:
        return JSONResponse({"status": "error", "message": "Invalid Barcode / UID scanned."}, status_code=400)

    student = database.get_student_by_uid(uid)
    if not student:
        return JSONResponse({"status": "error", "message": f"Unrecognized UID '{uid}'. Student not enrolled."}, status_code=404)

    # Decode and save snapshot image
    try:
        image_str = data.image_data
        if "," in image_str:
            image_str = image_str.split(",")[1]
        image_bytes = base64.b64decode(image_str)

        filename = f"scan_{uid}_{int(start_time.timestamp())}.jpg"
        filepath = os.path.join(UPLOAD_CAPTURED_DIR, filename)
        db_img_path = f"/static/uploads/captured/{filename}"

        with open(filepath, "wb") as f:
            f.write(image_bytes)

        # Record scan in DB with Status = 'PENDING'
        scan_timestamp = start_time.strftime("%Y-%m-%d %H:%M:%S")
        date_str = start_time.strftime("%Y-%m-%d")

        attendance_id = database.create_attendance_record(
            student_uid=uid,
            scan_timestamp=scan_timestamp,
            date_str=date_str,
            captured_image_path=db_img_path,
            status="PENDING"
        )

        # Trigger Step 2: Queue Async Background AI Verification task
        background_tasks.add_task(
            ai_engine.run_async_verification, 
            attendance_id=attendance_id, 
            database_module=database
        )

        elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000.0

        return JSONResponse({
            "status": "success",
            "message": "✅ Scan Registered! AI Verification queued.",
            "student_name": student["name"],
            "uid": student["uid"],
            "attendance_id": attendance_id,
            "response_time_ms": round(elapsed_ms, 2)
        })

    except Exception as e:
        print(f"[API Scan Error] {e}")
        return JSONResponse({"status": "error", "message": f"Scan processing failed: {str(e)}"}, status_code=500)

class OCRScanRequest(BaseModel):
    image_data: str # Base64 ID card snapshot
    live_face_data: Optional[str] = None # Base64 real live human face snapshot
    manual_uid: Optional[str] = None # Manual fallback UID

class MarkAttendanceRequest(BaseModel):
    uid: str
    verified: bool
    distance: Optional[float] = 0.0
    captured_image_data: Optional[str] = None
    verification_note: Optional[str] = None

@app.post("/api/mark_attendance")
def api_mark_attendance(data: MarkAttendanceRequest):
    """
    Step 3 of Client-Side Architecture:
    Dispatches verified client-side attendance directly to SQLite DB.
    """
    try:
        start_time = datetime.now()
        date_str = start_time.strftime("%Y-%m-%d")
        scan_timestamp = start_time.strftime("%Y-%m-%d %H:%M:%S")

        student = database.get_student_by_uid(data.uid.strip())
        if not student:
            database.add_student(
                uid=data.uid.strip(),
                name=f"Student {data.uid.strip()}",
                roll_no=data.uid.strip(),
                branch="General",
                photo_path="",
                encoding=None
            )
            student = database.get_student_by_uid(data.uid.strip())


        captured_img_path = f"/static/uploads/captured/client_verify_{int(start_time.timestamp())}.jpg"
        if data.captured_image_data:
            img_str = data.captured_image_data
            if "," in img_str:
                img_str = img_str.split(",")[1]
            img_bytes = base64.b64decode(img_str)
            filename = f"client_verify_{int(start_time.timestamp())}.jpg"
            filepath = os.path.join(UPLOAD_CAPTURED_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(img_bytes)
            captured_img_path = f"/static/uploads/captured/{filename}"

        status_str = "PRESENT" if data.verified else "PROXY_ALERT"
        note_str = data.verification_note if data.verification_note else (
            f"VERIFIED · ATTENDANCE MARKED ({student['name']})" if data.verified else "PROXY ALERT — Face Mismatch with Student ID"
        )

        attendance_id = database.create_attendance_record(
            student_uid=data.uid.strip(),
            scan_timestamp=scan_timestamp,
            date_str=date_str,
            captured_image_path=captured_img_path,
            status=status_str
        )
        database.update_attendance_status(attendance_id, status_str, note_str)

        return JSONResponse({
            "status": "success" if data.verified else "failed",
            "verified": data.verified,
            "attendance_status": status_str,
            "message": f"✅ VERIFIED · ATTENDANCE MARKED ({student['name']})" if data.verified else "❌ NOT VERIFIED (Face Mismatch / Missing UID)",
            "student_name": student["name"],
            "uid": data.uid.strip(),
            "attendance_id": attendance_id,
            "response_time_ms": 15.0
        })

    except Exception as e:
        print(f"[API Mark Attendance Error] {e}")
        return JSONResponse({"status": "error", "message": f"Failed to mark attendance: {str(e)}"}, status_code=500)


class VerifyStudentRequest(BaseModel):
    uid: str
    live_face_data: Optional[str] = None
    selfie_image_base64: Optional[str] = None

@app.post("/api/verify_and_mark_attendance")
def api_verify_and_mark_attendance(data: VerifyStudentRequest):
    """
    Core Anti-Proxy Verification Endpoint:
    Looks up student by UID in SQLite DB, compares live selfie against the ENROLLED BASELINE PHOTO in DB.
    Ignores ID Card face photo.
    """
    try:
        uid = data.uid.strip()
        student = database.get_student_by_uid(uid)

        if not student:
            database.add_student(
                uid=uid,
                name=f"Student {uid}",
                roll_no=uid,
                branch="Computer Science",
                photo_path="",
                encoding=None
            )
            student = database.get_student_by_uid(uid)

        start_time = datetime.now()
        date_str = start_time.strftime("%Y-%m-%d")
        scan_timestamp = start_time.strftime("%Y-%m-%d %H:%M:%S")

        captured_img_path = ""
        face_b64 = data.live_face_data or data.selfie_image_base64
        if face_b64:
            img_str = face_b64
            if "," in img_str:
                img_str = img_str.split(",")[1]
            img_bytes = base64.b64decode(img_str)
            filename = f"live_verify_{int(start_time.timestamp())}.jpg"
            filepath = os.path.join(UPLOAD_CAPTURED_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(img_bytes)
            captured_img_path = f"/static/uploads/captured/{filename}"

        verified = False
        match_score = 0.0
        note = f"PROXY ALERT — Student {uid} not enrolled with a baseline photo!"

        # Compare live selfie against ENROLLED baseline photo in SQLite DB using Robust Composite Face Matcher
        if student and student.get("photo_path") and captured_img_path:
            enrolled_rel = student["photo_path"].lstrip("/").replace("/", os.sep)
            captured_rel = captured_img_path.lstrip("/").replace("/", os.sep)
            enrolled_full_path = os.path.join(BASE_DIR, enrolled_rel)
            captured_full_path = os.path.join(BASE_DIR, captured_rel)

            if os.path.exists(enrolled_full_path) and os.path.exists(captured_full_path):
                is_match, composite_score, good_matches = ai_engine.robust_composite_face_match(enrolled_full_path, captured_full_path)
                match_score = composite_score

                if is_match:
                    verified = True
                    note = f"VERIFIED · ATTENDANCE MARKED ({student['name']})"
                else:
                    verified = False
                    note = f"PROXY ALERT — Face mismatch with enrolled profile of {student['name']} (Sim: {match_score}%)"

        status_str = "PRESENT" if verified else "PROXY_ALERT"

        attendance_id = database.create_attendance_record(
            student_uid=uid,
            scan_timestamp=scan_timestamp,
            date_str=date_str,
            captured_image_path=captured_img_path,
            status=status_str
        )
        database.update_attendance_status(attendance_id, status_str, note)

        return JSONResponse({
            "status": "success" if verified else "proxy_alert",
            "verified": verified,
            "match_score": match_score,
            "attendance_status": status_str,
            "student_name": student["name"],
            "uid": uid,
            "message": note
        })
    except Exception as e:
        print(f"[Verify API Error] {e}")
        return JSONResponse({"status": "error", "message": f"Verification failed: {str(e)}"}, status_code=500)



@app.post("/api/extract_uid")
def api_extract_uid(data: OCRScanRequest):
    """
    Step 1 of Kiosk Flow: Extract Student UID from ID Card image via OCR and look up student in DB.
    """
    try:
        image_str = data.image_data
        if "," in image_str:
            image_str = image_str.split(",")[1]
        image_bytes = base64.b64decode(image_str)

        filename = f"card_scan_{int(datetime.now().timestamp())}.jpg"
        filepath = os.path.join(UPLOAD_CAPTURED_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(image_bytes)

        extracted_uid = None
        ocr_note = ""

        if data.manual_uid and data.manual_uid.strip():
            extracted_uid = data.manual_uid.strip()
            ocr_note = "Extracted via Manual Fallback Input"
        else:
            extracted_uid, ocr_note = ai_engine.extract_uid_from_id_card(filepath)

        if not extracted_uid:
            return JSONResponse({
                "status": "error",
                "message": "⚠ Could not detect Student UID from ID card. Please re-align card or enter UID in the fallback box.",
                "ocr_note": ocr_note
            }, status_code=400)

        student = database.get_student_by_uid(extracted_uid)
        if not student:
            return JSONResponse({
                "status": "error",
                "message": f"❌ Student UID '{extracted_uid}' not found in database registry.",
                "extracted_uid": extracted_uid
            }, status_code=404)

        return JSONResponse({
            "status": "success",
            "message": f"✅ ID Card Scanned! Found Student: {student['name']} (UID: {extracted_uid})",
            "uid": extracted_uid,
            "student_name": student["name"],
            "card_image_path": f"/static/uploads/captured/{filename}"
        })

    except Exception as e:
        print(f"[API Extract UID Error] {e}")
        return JSONResponse({"status": "error", "message": f"ID Card OCR failed: {str(e)}"}, status_code=500)

@app.post("/api/scan_ocr")
def api_kiosk_scan_ocr(data: OCRScanRequest):
    """
    Step 2 of Kiosk Flow (Unified or Two-Stage):
    - Uses ID Card image (image_data) to extract UID via OCR (or manual_uid).
    - Uses Live Face image (live_face_data or image_data) to perform real human face verification.
    - Matches live face vector against student's enrolled profile face in SQLite DB.
    """
    start_time = datetime.now()

    try:
        # Save ID Card Image
        card_img_str = data.image_data
        if "," in card_img_str:
            card_img_str = card_img_str.split(",")[1]
        card_bytes = base64.b64decode(card_img_str)
        card_filename = f"ocr_card_{int(start_time.timestamp())}.jpg"
        card_filepath = os.path.join(UPLOAD_CAPTURED_DIR, card_filename)
        with open(card_filepath, "wb") as f:
            f.write(card_bytes)

        # Save Live Human Face Image (use live_face_data if available, otherwise card_img_str)
        live_img_str = data.live_face_data if data.live_face_data else data.image_data
        if "," in live_img_str:
            live_img_str = live_img_str.split(",")[1]
        live_bytes = base64.b64decode(live_img_str)
        live_filename = f"live_face_{int(start_time.timestamp())}.jpg"
        live_filepath = os.path.join(UPLOAD_CAPTURED_DIR, live_filename)
        with open(live_filepath, "wb") as f:
            f.write(live_bytes)

        # Extract UID via OCR or Manual Fallback
        extracted_uid = None
        ocr_note = ""

        if data.manual_uid and data.manual_uid.strip():
            extracted_uid = data.manual_uid.strip()
            ocr_note = "Extracted via Manual Input"
        else:
            extracted_uid, ocr_note = ai_engine.extract_uid_from_id_card(card_filepath)

        if not extracted_uid:
            return JSONResponse({
                "status": "error",
                "message": "⚠ Could not detect Student UID from ID card. Type UID in the fallback box and click 'Scan & Verify'.",
                "ocr_note": ocr_note
            }, status_code=400)

        # Database Student Lookup
        student = database.get_student_by_uid(extracted_uid)
        if not student:
            return JSONResponse({
                "status": "error",
                "message": f"❌ Student UID '{extracted_uid}' not found in database.",
                "extracted_uid": extracted_uid
            }, status_code=404)

        # Immediate Face Verification using LIVE HUMAN FACE PHOTO
        date_str = start_time.strftime("%Y-%m-%d")
        verification = ai_engine.perform_single_frame_verification(
            image_path=live_filepath,
            student_uid=extracted_uid,
            date_str=date_str,
            database_module=database
        )

        elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000.0
        status_code_type = verification["status"]

        if status_code_type == "PRESENT":
            msg = f"✅ Attendance Marked: Match Success ({student['name']})"
            res_status = "success"
        elif status_code_type == "PROXY_ALERT":
            msg = f"⚠ PROXY ALERT: Duplicate physical face detected across UIDs on same date!"
            res_status = "warning"
        elif status_code_type == "FLAGGED_NO_FACE":
            msg = f"⚠ FLAGGED NO FACE: No human face detected in captured live camera photo."
            res_status = "warning"
        else:
            msg = f"❌ Face Mismatch: ABSENT (Distance: {verification['distance']:.2f})"
            res_status = "failed"

        return JSONResponse({
            "status": res_status,
            "verified": verification["verified"],
            "attendance_status": status_code_type,
            "message": msg,
            "student_name": student["name"],
            "uid": extracted_uid,
            "distance": verification["distance"],
            "attendance_id": verification["attendance_id"],
            "response_time_ms": round(elapsed_ms, 2)
        })

    except Exception as e:
        print(f"[API OCR Scan Error] {e}")
        return JSONResponse({"status": "error", "message": f"Kiosk processing failed: {str(e)}"}, status_code=500)




@app.get("/api/attendance")
def api_get_attendance(
    date: Optional[str] = Query(None),
    branch: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    uid: Optional[str] = Query(None)
):
    """Retrieve filtered attendance records for Faculty Admin Panel."""
    records = database.get_attendance_records(
        date_filter=date,
        branch_filter=branch,
        status_filter=status,
        uid_filter=uid
    )
    return {"status": "success", "count": len(records), "data": records}

@app.post("/api/admin/override")
def api_admin_override(data: dict):
    """Faculty Manual Override for Proxy Alerts / Flagged Scans."""
    attendance_id = data.get("attendance_id")
    action = data.get("action") # 'PRESENT' or 'ABSENT'

    if not attendance_id or action not in ("PRESENT", "ABSENT"):
        return JSONResponse({"status": "error", "message": "Invalid override parameters."}, status_code=400)

    record = database.get_attendance_by_id(attendance_id)
    if not record:
        return JSONResponse({"status": "error", "message": "Record not found."}, status_code=404)

    status = "MANUAL_OVERRIDE" if action == "PRESENT" else "ABSENT"
    note = f"Manually overridden to {action} by Faculty Admin."

    database.update_attendance_status(attendance_id, status, note)
    return {"status": "success", "message": f"Attendance record #{attendance_id} updated to {status}."}

@app.get("/api/student/{uid}")
def api_get_student_summary(uid: str):
    """Fetch attendance summary for Student Portal."""
    summary = database.get_student_attendance_summary(uid.strip())
    if not summary:
        return JSONResponse({"status": "error", "message": f"No student found with UID '{uid}'."}, status_code=404)
    return {"status": "success", "data": summary}

@app.get("/api/students")
def api_get_all_students():
    """Get list of all enrolled students."""
    students = database.get_all_students()
    return {"status": "success", "data": students}

class UpdateStudentRequest(BaseModel):
    name: str
    roll_no: str
    branch: str

@app.put("/api/students/{uid}")
def api_update_student(uid: str, data: UpdateStudentRequest):
    """Update student profile details in DB."""
    try:
        student = database.get_student_by_uid(uid.strip())
        if not student:
            return JSONResponse({"status": "error", "message": f"Student '{uid}' not found."}, status_code=404)
        
        database.update_student(uid.strip(), data.name.strip(), data.roll_no.strip(), data.branch.strip())
        return {"status": "success", "message": f"Student '{data.name}' profile updated successfully."}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.delete("/api/students/{uid}")
def api_delete_student(uid: str):
    """Delete student and all their attendance logs from DB."""
    try:
        student = database.get_student_by_uid(uid.strip())
        if not student:
            return JSONResponse({"status": "error", "message": f"Student '{uid}' not found."}, status_code=404)
        
        database.delete_student(uid.strip())
        return {"status": "success", "message": f"Student '{student['name']}' (UID: {uid}) successfully deleted."}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.get("/api/reports/excel")
def api_export_excel(branch: Optional[str] = None):
    """Download 7-day Attendance Grid as formatted Excel sheet."""
    filename = f"Attendance_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    output_path = os.path.join(STATIC_DIR, "uploads", filename)
    generate_weekly_excel_report(output_path, branch_filter=branch)
    return FileResponse(output_path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=filename)

@app.get("/api/reports/pdf")
def api_export_pdf(branch: Optional[str] = None):
    """Download 7-day Attendance Grid as printable PDF."""
    filename = f"Attendance_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    output_path = os.path.join(STATIC_DIR, "uploads", filename)
    generate_weekly_pdf_report(output_path, branch_filter=branch)
    return FileResponse(output_path, media_type="application/pdf", filename=filename)

@app.post("/api/admin/clear_attendance")
def api_clear_attendance():
    """
    Purge all stored attendance records and face vector logs from the SQLite database.
    """
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM face_logs")
        cursor.execute("DELETE FROM attendance")
        conn.commit()
        conn.close()

        # Delete captured image files
        for f in os.listdir(UPLOAD_CAPTURED_DIR):
            file_path = os.path.join(UPLOAD_CAPTURED_DIR, f)
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass

        return JSONResponse({
            "status": "success",
            "message": "All stored attendance logs and scan entries successfully cleared!"
        })
    except Exception as e:
        print(f"[API Clear Error] {e}")
        return JSONResponse({"status": "error", "message": f"Purge failed: {str(e)}"}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

