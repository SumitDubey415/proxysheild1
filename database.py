import sqlite3
import os
import json
import shutil
from datetime import datetime

# Vercel Serverless File System Compatibility
if os.environ.get("VERCEL") or not os.access(os.path.dirname(__file__), os.W_OK):
    DB_PATH = "/tmp/attendance_system.db"
    local_db = os.path.join(os.path.dirname(__file__), "attendance_system.db")
    if os.path.exists(local_db) and not os.path.exists(DB_PATH):
        try:
            shutil.copyfile(local_db, DB_PATH)
        except Exception:
            pass
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "attendance_system.db")

def get_db_connection():
    """Establish connection to SQLite database with Row factory and safe fallback for Vercel serverless environments."""
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
    except Exception:
        pass
    return conn

def init_db():
    """Initialize database schema if tables do not exist."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Students Registry Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            roll_no TEXT NOT NULL,
            branch TEXT NOT NULL,
            photo_path TEXT NOT NULL,
            encoding_json TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # 2. Attendance Log Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_uid TEXT NOT NULL,
            scan_timestamp TEXT NOT NULL,
            date TEXT NOT NULL,
            captured_image_path TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            verification_note TEXT,
            processed_at TEXT,
            FOREIGN KEY (student_uid) REFERENCES students(uid)
        )
    """)

    # 3. Face Vector Logs Table (For async proxy checks & cross-referencing)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS face_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attendance_id INTEGER UNIQUE NOT NULL,
            student_uid TEXT NOT NULL,
            face_encoding_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (attendance_id) REFERENCES attendance(id)
        )
    """)

    conn.commit()
    conn.close()

# --- STUDENT HELPERS ---

def add_student(uid, name, roll_no, branch, photo_path, encoding=None):
    """Register a new student baseline in DB."""
    conn = get_db_connection()
    cursor = conn.cursor()
    created_at = datetime.now().isoformat()
    encoding_json = json.dumps(encoding) if encoding is not None else None

    cursor.execute("""
        INSERT INTO students (uid, name, roll_no, branch, photo_path, encoding_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (uid, name, roll_no, branch, photo_path, encoding_json, created_at))

    conn.commit()
    conn.close()
    return True

def get_student_by_uid(uid):
    """Fetch student profile by UID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students WHERE uid = ?", (uid,))
    row = cursor.fetchone()
    conn.close()
    if row:
        student = dict(row)
        if student.get("encoding_json"):
            student["encoding"] = json.loads(student["encoding_json"])
        else:
            student["encoding"] = None
        return student
    return None

def get_all_students():
    """Retrieve list of all registered students."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, uid, name, roll_no, branch, photo_path, created_at FROM students ORDER BY name ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_student(uid, name, roll_no, branch):
    """Update student profile details in DB."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE students 
        SET name = ?, roll_no = ?, branch = ?
        WHERE uid = ?
    """, (name, roll_no, branch, uid))
    conn.commit()
    conn.close()
    return True

def delete_student(uid):
    """Delete a student and all their associated attendance logs from DB."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM attendance WHERE student_uid = ?", (uid,))
    cursor.execute("DELETE FROM students WHERE uid = ?", (uid,))
    conn.commit()
    conn.close()
    return True

# --- ATTENDANCE HELPERS ---

def create_attendance_record(student_uid, scan_timestamp, date_str, captured_image_path, status="PENDING"):
    """Create a new raw scan record instantly at kiosk step."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO attendance (student_uid, scan_timestamp, date, captured_image_path, status, verification_note)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (student_uid, scan_timestamp, date_str, captured_image_path, status, "Queued for AI Verification"))
    attendance_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return attendance_id

def update_attendance_status(attendance_id, status, verification_note=""):
    """Update status after AI verification or manual admin override."""
    conn = get_db_connection()
    cursor = conn.cursor()
    processed_at = datetime.now().isoformat()
    cursor.execute("""
        UPDATE attendance
        SET status = ?, verification_note = ?, processed_at = ?
        WHERE id = ?
    """, (status, verification_note, processed_at, attendance_id))
    conn.commit()
    conn.close()

def add_face_log(attendance_id, student_uid, encoding):
    """Store extracted face vector for proxy cross-matching."""
    conn = get_db_connection()
    cursor = conn.cursor()
    encoding_json = json.dumps(encoding) if isinstance(encoding, list) else json.dumps(encoding.tolist())
    created_at = datetime.now().isoformat()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO face_logs (attendance_id, student_uid, face_encoding_json, created_at)
            VALUES (?, ?, ?, ?)
        """, (attendance_id, student_uid, encoding_json, created_at))
        conn.commit()
    except Exception as e:
        print(f"[DB Error] Failed to insert face log: {e}")
    finally:
        conn.close()

def get_face_logs_for_date(date_str, exclude_attendance_id=None):
    """Fetch all face vectors captured on a specific date for same-day proxy duplicate checks."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if exclude_attendance_id:
        cursor.execute("""
            SELECT fl.attendance_id, fl.student_uid, fl.face_encoding_json, a.date
            FROM face_logs fl
            JOIN attendance a ON fl.attendance_id = a.id
            WHERE a.date = ? AND fl.attendance_id != ?
        """, (date_str, exclude_attendance_id))
    else:
        cursor.execute("""
            SELECT fl.attendance_id, fl.student_uid, fl.face_encoding_json, a.date
            FROM face_logs fl
            JOIN attendance a ON fl.attendance_id = a.id
            WHERE a.date = ?
        """, (date_str,))
    
    rows = cursor.fetchall()
    conn.close()
    results = []
    for r in rows:
        results.append({
            "attendance_id": r["attendance_id"],
            "student_uid": r["student_uid"],
            "encoding": json.loads(r["face_encoding_json"]),
            "date": r["date"]
        })
    return results

def get_attendance_records(date_filter=None, branch_filter=None, status_filter=None, uid_filter=None):
    """Fetch filtered attendance records for admin panel."""
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT a.id, a.student_uid, a.scan_timestamp, a.date, a.captured_image_path, 
               a.status, a.verification_note, a.processed_at,
               s.name as student_name, s.roll_no, s.branch, s.photo_path as enrolled_photo_path
        FROM attendance a
        LEFT JOIN students s ON a.student_uid = s.uid
        WHERE 1=1
    """
    params = []

    if date_filter:
        query += " AND a.date = ?"
        params.append(date_filter)
    if branch_filter:
        query += " AND s.branch = ?"
        params.append(branch_filter)
    if status_filter:
        query += " AND a.status = ?"
        params.append(status_filter)
    if uid_filter:
        query += " AND (a.student_uid LIKE ? OR s.name LIKE ?)"
        params.append(f"%{uid_filter}%")
        params.append(f"%{uid_filter}%")

    query += " ORDER BY a.id DESC"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_attendance_by_id(attendance_id):
    """Fetch single attendance record by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.*, s.name as student_name, s.roll_no, s.branch, s.photo_path as enrolled_photo_path
        FROM attendance a
        LEFT JOIN students s ON a.student_uid = s.uid
        WHERE a.id = ?
    """, (attendance_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_student_attendance_summary(uid):
    """Calculate total attendance, present days, percentage & subject count for Student Portal."""
    student = get_student_by_uid(uid)
    if not student:
        return None

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            COUNT(*) as total_scans,
            SUM(CASE WHEN status IN ('PRESENT', 'MANUAL_OVERRIDE') THEN 1 ELSE 0 END) as present_count,
            SUM(CASE WHEN status = 'ABSENT' THEN 1 ELSE 0 END) as absent_count,
            SUM(CASE WHEN status = 'PROXY_ALERT' THEN 1 ELSE 0 END) as proxy_alert_count,
            SUM(CASE WHEN status = 'FLAGGED_NO_FACE' THEN 1 ELSE 0 END) as no_face_count
        FROM attendance
        WHERE student_uid = ?
    """, (uid,))
    stats = dict(cursor.fetchone())

    # Get recent attendance log
    cursor.execute("""
        SELECT id, scan_timestamp, date, status, verification_note
        FROM attendance
        WHERE student_uid = ?
        ORDER BY id DESC LIMIT 10
    """, (uid,))
    recent_logs = [dict(r) for r in cursor.fetchall()]

    conn.close()

    total = stats["total_scans"] or 0
    present = stats["present_count"] or 0
    percentage = round((present / total * 100), 1) if total > 0 else 100.0

    return {
        "student": {
            "uid": student["uid"],
            "name": student["name"],
            "roll_no": student["roll_no"],
            "branch": student["branch"],
            "photo_path": student["photo_path"]
        },
        "stats": {
            "total": total,
            "present": present,
            "absent": stats["absent_count"] or 0,
            "proxy_alerts": stats["proxy_alert_count"] or 0,
            "no_face": stats["no_face_count"] or 0,
            "percentage": percentage,
            "is_eligible": percentage >= 75.0
        },
        "recent_logs": recent_logs
    }
