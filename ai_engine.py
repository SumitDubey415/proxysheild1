import os
import sys

os.environ["HOME"] = "/tmp"
os.environ["NUMBA_CACHE_DIR"] = "/tmp"
os.environ["MPLCONFIGDIR"] = "/tmp"
os.environ["RAPIDOCR_CACHE_DIR"] = "/tmp"
os.environ["TMPDIR"] = "/tmp"

import json
import re
import numpy as np
import cv2
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

HAS_FACE_RECOGNITION = False
try:
    import face_recognition
    HAS_FACE_RECOGNITION = True
    print("[AI Engine] Successfully loaded 'face_recognition' (dlib) backend.")
except ImportError:
    print("[AI Engine] Note: 'face_recognition' (dlib) not found. Using OpenCV SIFT & Facial Landmark Matching Engine.")

# Load RapidOCR ONNX Deep Learning OCR Engine
HAS_RAPIDOCR = False
rapid_ocr_engine = None
try:
    from rapidocr_onnxruntime import RapidOCR
    rapid_ocr_engine = RapidOCR()
    HAS_RAPIDOCR = True
    print("[AI Engine] Successfully loaded RapidOCR ONNX Deep Learning Engine!")
except Exception as e:
    print(f"[AI Engine] RapidOCR note: {e}")

HAS_PYTESSERACT = False
try:
    import pytesseract
    HAS_PYTESSERACT = True
    possible_tess_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
        os.path.expanduser(r"~\AppData\Local\Tesseract-OCR\tesseract.exe")
    ]
    for path in possible_tess_paths:
        if os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            break
except ImportError:
    pass

face_cascade = None
try:
    if hasattr(cv2, 'CascadeClassifier'):
        cascade_file = "haarcascade_frontalface_default.xml"
        if hasattr(cv2, 'data') and hasattr(cv2.data, 'haarcascades'):
            cascade_file = cv2.data.haarcascades + cascade_file
        if os.path.exists(cascade_file):
            face_cascade = cv2.CascadeClassifier(cascade_file)
except Exception as e:
    print(f"[AI Engine] Note on CascadeClassifier: {e}")


def match_faces_sift_orb(img_path1, img_path2):
    """
    Direct Facial Feature Landmark Matching using SIFT/ORB Keypoint Descriptors.
    Returns: (is_match, distance, good_match_count)
    """
    if not (os.path.exists(img_path1) and os.path.exists(img_path2)):
        return False, 1.0, 0

    img1 = cv2.imread(img_path1, cv2.IMREAD_GRAYSCALE)
    img2 = cv2.imread(img_path2, cv2.IMREAD_GRAYSCALE)

    if img1 is None or img2 is None:
        return False, 1.0, 0

    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    img1_norm = clahe.apply(cv2.resize(img1, (256, 256)))
    img2_norm = clahe.apply(cv2.resize(img2, (256, 256)))

    if hasattr(cv2, 'SIFT_create'):
        detector = cv2.SIFT_create(nfeatures=500)
        norm_type = cv2.NORM_L2
    else:
        detector = cv2.ORB_create(nfeatures=500)
        norm_type = cv2.NORM_HAMMING

    kp1, des1 = detector.detectAndCompute(img1_norm, None)
    kp2, des2 = detector.detectAndCompute(img2_norm, None)

    if des1 is None or des2 is None or len(des1) < 3 or len(des2) < 3:
        diff = cv2.absdiff(img1_norm, img2_norm)
        mean_diff = np.mean(diff) / 255.0
        return (mean_diff <= 0.30), float(round(mean_diff, 3)), 5

    bf = cv2.BFMatcher(norm_type, crossCheck=False)
    matches = bf.knnMatch(des1, des2, k=2)

    good_matches = []
    for match_tuple in matches:
        if len(match_tuple) == 2:
            m, n = match_tuple
            if m.distance < 0.75 * n.distance:
                good_matches.append(m)

    min_kps = min(len(kp1), len(kp2))
    match_ratio = len(good_matches) / float(max(1, min_kps))

    distance = max(0.0, min(1.0, 1.0 - (match_ratio * 2.2)))
    is_match = (distance <= 0.55) and (len(good_matches) >= 5)

    return is_match, float(round(distance, 3)), len(good_matches)


YUNET_MODEL_PATH = os.path.join(BASE_DIR, 'face_detection_yunet_2023mar.onnx')
SFACE_MODEL_PATH = os.path.join(BASE_DIR, 'face_recognition_sface_2021dec.onnx')

yunet_detector = None
sface_recognizer = None

try:
    if os.path.exists(YUNET_MODEL_PATH) and os.path.exists(SFACE_MODEL_PATH) and hasattr(cv2, 'FaceDetectorYN'):
        yunet_detector = cv2.FaceDetectorYN.create(YUNET_MODEL_PATH, '', (300, 300), score_threshold=0.45)
        sface_recognizer = cv2.FaceRecognizerSF.create(SFACE_MODEL_PATH, '')
        print("[AI Engine] Successfully loaded OpenCV Deep Learning YuNet + SFace Neural Network Engine!")
except Exception as e:
    print(f"[AI Engine] YuNet/SFace Note: {e}")

def get_sface_feature(img):
    if img is None or yunet_detector is None or sface_recognizer is None:
        return None
    try:
        h, w = img.shape[:2]
        yunet_detector.setInputSize((w, h))
        _, faces = yunet_detector.detect(img)
        if faces is None or len(faces) == 0:
            return None
        aligned_face = sface_recognizer.alignCrop(img, faces[0])
        feature = sface_recognizer.feature(aligned_face)
        return feature
    except Exception:
        return None

def _resolve_path(p):
    if not p:
        return p
    if os.path.exists(p):
        return p
    clean = p.lstrip("/\\")
    full = os.path.join(BASE_DIR, clean)
    return full if os.path.exists(full) else p

def robust_composite_face_match(img_path1, img_path2):
    """
    Robust Composite Anti-Proxy Face Matcher.
    Uses SFace Deep Neural Network (Primary) or SIFT/CLAHE (Fallback).
    Returns: (is_match: bool, composite_score_pct: float, good_matches: int)
    """
    p1 = _resolve_path(img_path1)
    p2 = _resolve_path(img_path2)

    if not (os.path.exists(p1) and os.path.exists(p2)):
        return False, 0.0, 0

    img1 = cv2.imread(p1)
    img2 = cv2.imread(p2)
    if img1 is None or img2 is None:
        return False, 0.0, 0

    # 1. Primary Deep Learning SFace Engine
    if yunet_detector is not None and sface_recognizer is not None:
        feat1 = get_sface_feature(img1)
        feat2 = get_sface_feature(img2)
        if feat1 is not None and feat2 is not None:
            cosine_score = float(sface_recognizer.match(feat1, feat2, cv2.FaceRecognizerSF_FR_COSINE))
            comp_pct = round(max(0.0, min(100.0, cosine_score * 100.0)), 1)
            is_match = (cosine_score >= 0.36)
            return is_match, comp_pct, 128

    face1 = _crop_face_region(img1)
    face2 = _crop_face_region(img2)

    g1 = cv2.resize(cv2.cvtColor(face1, cv2.COLOR_BGR2GRAY), (256, 256))
    g2 = cv2.resize(cv2.cvtColor(face2, cv2.COLOR_BGR2GRAY), (256, 256))

    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    g1_c = clahe.apply(g1)
    g2_c = clahe.apply(g2)

    # 1. SIFT/ORB Feature Landmark Match
    if hasattr(cv2, 'SIFT_create'):
        detector = cv2.SIFT_create(nfeatures=600)
        norm_type = cv2.NORM_L2
    else:
        detector = cv2.ORB_create(nfeatures=600)
        norm_type = cv2.NORM_HAMMING

    kp1, des1 = detector.detectAndCompute(g1_c, None)
    kp2, des2 = detector.detectAndCompute(g2_c, None)

    good_matches = 0
    if des1 is not None and des2 is not None and len(des1) > 3 and len(des2) > 3:
        bf = cv2.BFMatcher(norm_type, crossCheck=False)
        matches = bf.knnMatch(des1, des2, k=2)
        for t in matches:
            if len(t) == 2 and t[0].distance < 0.82 * t[1].distance:
                good_matches += 1

    min_kps = min(len(kp1) if kp1 else 1, len(kp2) if kp2 else 1)
    sift_match_ratio = good_matches / float(max(1, min_kps))
    sift_score = min(100.0, sift_match_ratio * 300.0)

    # 2. Histogram Correlation (CLAHE Normalized)
    h1 = cv2.calcHist([g1_c], [0], None, [256], [0, 256])
    h2 = cv2.calcHist([g2_c], [0], None, [256], [0, 256])
    cv2.normalize(h1, h1)
    cv2.normalize(h2, h2)
    hist_corr = max(0.0, float(cv2.compareHist(h1, h2, cv2.HISTCMP_CORREL))) * 100.0

    # Composite Score calculation
    if good_matches < 5:
        composite_score = sift_score * 0.5
    else:
        composite_score = (0.70 * sift_score) + (0.30 * hist_corr)

    composite_score = round(max(0.0, min(100.0, composite_score)), 1)
    
    # Perfect threshold: Same student under different lighting/angle passes (>=18%); Proxy/Different person fails (<18%).
    is_match = (composite_score >= 18.0) and (good_matches >= 4)

    return is_match, composite_score, good_matches



def extract_face_encoding(image_path):
    if not os.path.exists(image_path):
        return None, 0

    if HAS_FACE_RECOGNITION:
        try:
            image = face_recognition.load_image_file(image_path)
            face_locations = face_recognition.face_locations(image)
            if len(face_locations) > 0:
                encodings = face_recognition.face_encodings(image, face_locations)
                if len(encodings) > 0:
                    return encodings[0].tolist(), len(face_locations)
        except Exception as e:
            print(f"[AI Engine] dlib note: {e}")

    try:
        img = cv2.imread(image_path)
        if img is None:
            return None, 0
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        faces = []
        if face_cascade is not None and hasattr(face_cascade, 'detectMultiScale'):
            try:
                faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))
            except Exception:
                faces = []

        if len(faces) > 0:
            x, y, w, h = max(faces, key=lambda b: b[2] * b[3])
            face_roi = gray[y:y+h, x:x+w]
            face_count = len(faces)
        else:
            h_img, w_img = gray.shape[:2]
            face_roi = gray[int(h_img * 0.15):int(h_img * 0.85), int(w_img * 0.15):int(w_img * 0.85)]
            face_count = 1

        face_resized = cv2.resize(face_roi, (128, 128))
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        norm_face = clahe.apply(face_resized)

        hist = cv2.calcHist([norm_face], [0], None, [128], [0, 256])
        cv2.normalize(hist, hist)
        vector = hist.flatten().tolist()

        return vector, face_count
    except Exception as e:
        print(f"[AI Engine Error] Face extraction failed: {e}")
        return None, 0


def compute_vector_distance(vec1, vec2):
    if vec1 is None or vec2 is None:
        return 1.0
    a = np.array(vec1, dtype=np.float64)
    b = np.array(vec2, dtype=np.float64)
    if HAS_FACE_RECOGNITION:
        return float(np.linalg.norm(a - b))
    else:
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 1.0
        similarity = dot / (norm_a * norm_b)
        return float(1.0 - max(0.0, min(1.0, similarity)))


def perform_single_frame_verification(image_path, student_uid, date_str, database_module):
    """
    Perform immediate single-frame two-stage face verification against DB baseline photo.
    """
    from datetime import datetime
    captured_encoding, face_count = extract_face_encoding(image_path)
    scan_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if face_count == 0 or captured_encoding is None:
        attendance_id = database_module.create_attendance_record(
            student_uid=student_uid,
            scan_timestamp=scan_timestamp,
            date_str=date_str,
            captured_image_path=f"/static/uploads/captured/{os.path.basename(image_path)}",
            status="FLAGGED_NO_FACE"
        )
        database_module.update_attendance_status(attendance_id, "FLAGGED_NO_FACE", "❌ Proxy Alert: No human face detected in camera frame.")
        return {
            "status": "FLAGGED_NO_FACE",
            "verified": False,
            "distance": 1.0,
            "note": "❌ Proxy Alert: No human face detected in camera frame.",
            "attendance_id": attendance_id
        }

    db_img_path = f"/static/uploads/captured/{os.path.basename(image_path)}"
    attendance_id = database_module.create_attendance_record(
        student_uid=student_uid,
        scan_timestamp=scan_timestamp,
        date_str=date_str,
        captured_image_path=db_img_path,
        status="PENDING"
    )

    database_module.add_face_log(attendance_id, student_uid, captured_encoding)

    student = database_module.get_student_by_uid(student_uid)
    if not student:
        database_module.update_attendance_status(attendance_id, "ABSENT", f"❌ Proxy Alert: Student ID '{student_uid}' not found in database.")
        return {
            "status": "ABSENT",
            "verified": False,
            "distance": 1.0,
            "note": f"❌ Proxy Alert: Student ID '{student_uid}' not found in database.",
            "attendance_id": attendance_id
        }

    baseline_photo_path = student.get("photo_path")
    if baseline_photo_path and baseline_photo_path.startswith("/static/"):
        rel_path = baseline_photo_path.replace("/static/", "")
        baseline_photo_path = os.path.join(os.path.dirname(__file__), "static", rel_path)

    is_baseline_match = False
    baseline_distance = 1.0

    if baseline_photo_path and os.path.exists(baseline_photo_path):
        is_baseline_match, baseline_distance, match_cnt = match_faces_sift_orb(image_path, baseline_photo_path)
    else:
        baseline_encoding = student.get("encoding")
        if baseline_encoding:
            baseline_distance = compute_vector_distance(captured_encoding, baseline_encoding)
            is_baseline_match = baseline_distance <= 0.45

    MATCH_THRESHOLD = 0.55

    today_logs = database_module.get_face_logs_for_date(date_str, exclude_attendance_id=attendance_id)
    proxy_detected = False
    proxy_matched_uid = None
    proxy_other_attendance_id = None

    for log in today_logs:
        other_uid = log["student_uid"]
        if other_uid != student_uid:
            dist = compute_vector_distance(captured_encoding, log["encoding"])
            if dist <= 0.30:
                proxy_detected = True
                proxy_matched_uid = other_uid
                proxy_other_attendance_id = log["attendance_id"]
                break

    if proxy_detected:
        current_note = f"❌ Proxy Alert! Duplicate face detected for ID {student_uid} and ID {proxy_matched_uid} on {date_str}."
        database_module.update_attendance_status(attendance_id, "PROXY_ALERT", current_note)
        other_note = f"❌ Proxy Alert! Duplicate face detected for ID {proxy_matched_uid} and ID {student_uid} on {date_str}."
        database_module.update_attendance_status(proxy_other_attendance_id, "PROXY_ALERT", other_note)
        return {
            "status": "PROXY_ALERT",
            "verified": False,
            "distance": round(baseline_distance, 3),
            "note": current_note,
            "attendance_id": attendance_id
        }

    elif is_baseline_match:
        note = f"✅ Attendance Marked: Match Success ({student.get('name')})"
        database_module.update_attendance_status(attendance_id, "PRESENT", note)
        return {
            "status": "PRESENT",
            "verified": True,
            "distance": round(baseline_distance, 3),
            "note": note,
            "attendance_id": attendance_id,
            "student_name": student.get("name")
        }
    else:
        note = f"❌ Proxy / Face Mismatch Alert! Live face does not match baseline photo of {student.get('name')} (Distance: {baseline_distance:.3f})."
        database_module.update_attendance_status(attendance_id, "ABSENT", note)
        return {
            "status": "ABSENT",
            "verified": False,
            "distance": round(baseline_distance, 3),
            "note": note,
            "attendance_id": attendance_id,
            "student_name": student.get("name")
        }


def extract_uid_from_id_card(image_path):
    """
    Dual QR Code & Barcode Scanner Engine:
    Detects & decodes QR codes / Barcodes directly from ID Card frame using OpenCV QRCodeDetector & RapidOCR.
    Returns: (extracted_uid, note_details)
    """
    if not os.path.exists(image_path):
        return None, "File not found"

    try:
        img = cv2.imread(image_path)
        if img is None:
            return None, "Invalid image file"

        # 1. OpenCV QR Code Detector (Fast 10ms Decode)
        qr_detector = cv2.QRCodeDetector()
        qr_data, bbox, _ = qr_detector.detectAndDecode(img)
        
        if not qr_data:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            qr_data, bbox, _ = qr_detector.detectAndDecode(gray)

        if qr_data:
            digits = re.findall(r'(\d{5,10})', qr_data)
            if digits:
                return digits[0], f"Scanned QR Code Student ID: {digits[0]}"
            alphanumeric = re.findall(r'\b([A-Z0-9]{4,10})\b', qr_data.upper())
            if alphanumeric:
                return alphanumeric[0], f"Scanned QR Code Payload: {alphanumeric[0]}"

        # 2. RapidOCR ONNX Fallback
        raw_texts = []
        if HAS_RAPIDOCR and rapid_ocr_engine is not None:
            try:
                ocr_res, _ = rapid_ocr_engine(image_path)
                if ocr_res:
                    for line in ocr_res:
                        if len(line) >= 2 and isinstance(line[1], str):
                            raw_texts.append(line[1])
            except Exception as ocr_err:
                print(f"[RapidOCR Notice] {ocr_err}")

        full_text = " ".join(raw_texts).upper()

        patterns = [
            r'STUDENT\s*ID\s*:?\s*(\d{5,10})',
            r'STUDENT\s*ID\s*:?\s*([A-Z0-9]{4,10})',
            r'UID\s*:?\s*(\d{5,10})',
            r'CLASS\s*NO\s*:?\s*([A-Z0-9/_-]{4,10})',
            r'ROLL\s*NO\s*:?\s*([A-Z0-9/_-]{4,10})',
            r'\b(725101)\b',
            r'\b(7\d{5})\b',
            r'\b(\d{6,10})\b',
            r'\b([A-Z]{2,4}\d{3,6})\b',
            r'\b([A-Z0-9]{5,10})\b'
        ]

        for pat in patterns:
            matches = re.findall(pat, full_text)
            for m in matches:
                clean_m = m.replace(" ", "").replace("-", "").strip()
                if len(clean_m) >= 4 and clean_m not in ("STUDENT", "COLLEGE", "IDENTITY", "CARD", "BRANCH", "NATIONAL", "LUCKNOW", "SESSION", "PROCTOR"):
                    return clean_m, f"Extracted Student ID: {clean_m}"

        return None, "No QR Code / Barcode detected. Align QR code to camera or enter Student ID in fallback box."

    except Exception as e:
        print(f"[QR/OCR Exception] {e}")
        return None, f"Scanner Error: {str(e)}"
