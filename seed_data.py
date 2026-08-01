import os
import json
from datetime import datetime, timedelta
import database
import ai_engine

def seed_sample_data():
    """Populate initial database with sample students and scan records for testing."""
    database.init_db()

    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM students")
    count = cursor.fetchone()[0]
    conn.close()

    if count > 0:
        print("[Seed] Database already populated with students.")
        return

    print("[Seed] Adding sample enrolled students & baseline profiles...")

    students = [
        {"uid": "725101", "name": "SUMIT DUBEY", "roll_no": "BCA1/101", "branch": "Computer Science"},
        {"uid": "STU1001", "name": "Alexander Vance", "roll_no": "21CS001", "branch": "Computer Science"},
        {"uid": "STU1002", "name": "Sophia Martinez", "roll_no": "21CS014", "branch": "Computer Science"},
        {"uid": "STU1003", "name": "Marcus Chen", "roll_no": "21IT022", "branch": "Information Tech"},
        {"uid": "STU1004", "name": "Elena Rostova", "roll_no": "21EC009", "branch": "Electronics"}
    ]

    for s in students:
        # Create a placeholder photo
        placeholder_photo = f"/static/uploads/enrolled/{s['uid']}_profile.jpg"
        database.add_student(s["uid"], s["name"], s["roll_no"], s["branch"], placeholder_photo)

    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Add sample attendance records
    att1 = database.create_attendance_record("STU1001", f"{today} 09:15:22", today, "/static/uploads/captured/scan_stu1001.jpg", "PRESENT")
    database.update_attendance_status(att1, "PRESENT", "Verified Match (Distance: 0.24)")

    att2 = database.create_attendance_record("STU1002", f"{today} 09:18:40", today, "/static/uploads/captured/scan_stu1002.jpg", "PROXY_ALERT")
    database.update_attendance_status(att2, "PROXY_ALERT", "PROXY ALERT! Same physical face detected under STU1002 and STU1003.")

    att3 = database.create_attendance_record("STU1003", f"{today} 09:18:42", today, "/static/uploads/captured/scan_stu1003.jpg", "PROXY_ALERT")
    database.update_attendance_status(att3, "PROXY_ALERT", "PROXY ALERT! Same physical face detected under STU1003 and STU1002.")

    att4 = database.create_attendance_record("STU1004", f"{today} 09:22:05", today, today, "FLAGGED_NO_FACE")
    database.update_attendance_status(att4, "FLAGGED_NO_FACE", "ALERT: No human face detected in captured frame.")

    print("[Seed] Sample students and proxy alert logs populated successfully.")

if __name__ == "__main__":
    seed_sample_data()
