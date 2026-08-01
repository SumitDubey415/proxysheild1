// Student Enrollment Controller
let enrollStream = null;

let enrollFacingMode = 'user';

async function initEnrollWebcam() {
    const video = document.getElementById('enrollWebcam');
    if (!video) return;

    if (enrollStream) {
        enrollStream.getTracks().forEach(track => track.stop());
    }

    try {
        enrollStream = await navigator.mediaDevices.getUserMedia({
            video: { width: { ideal: 640 }, height: { ideal: 640 }, facingMode: enrollFacingMode }
        });
        video.srcObject = enrollStream;
        await video.play();
    } catch (e) {
        console.log("Enroll camera init notice:", e);
    }
}

function flipEnrollCamera() {
    enrollFacingMode = enrollFacingMode === 'user' ? 'environment' : 'user';
    const video = document.getElementById('enrollWebcam');
    const preview = document.getElementById('enrollPhotoPreview');
    if (video) video.style.display = 'block';
    if (preview) preview.style.display = 'none';
    initEnrollWebcam();
}

function captureEnrollSnapshot() {
    const video = document.getElementById('enrollWebcam');
    const canvas = document.getElementById('enrollCanvas');
    const preview = document.getElementById('enrollPhotoPreview');
    const base64Input = document.getElementById('captured_image_base64');

    if (!video || video.readyState !== video.HAVE_ENOUGH_DATA) return;

    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 640;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    const b64 = canvas.toDataURL('image/jpeg', 0.90);
    if (base64Input) base64Input.value = b64;

    if (preview) {
        preview.src = b64;
        preview.style.display = 'block';
        video.style.display = 'none';
    }
}

function handleEnrollFileUpload(input) {
    if (input.files && input.files[0]) {
        const video = document.getElementById('enrollWebcam');
        const preview = document.getElementById('enrollPhotoPreview');
        const base64Input = document.getElementById('captured_image_base64');
        const reader = new FileReader();

        reader.onload = function(e) {
            if (base64Input) base64Input.value = e.target.result;
            if (preview) {
                preview.src = e.target.result;
                preview.style.display = 'block';
                if (video) video.style.display = 'none';
            }
        };
        reader.readAsDataURL(input.files[0]);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initEnrollWebcam();

    const form = document.getElementById('enrollForm');
    const alertBox = document.getElementById('enrollAlert');
    const submitBtn = document.getElementById('submitBtn');

    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (submitBtn) submitBtn.disabled = true;

            const formData = new FormData(form);

            try {
                const res = await fetch('/api/enroll', {
                    method: 'POST',
                    body: formData
                });
                const json = await res.json();

                if (res.ok && json.status === 'success') {
                    if (alertBox) {
                        alertBox.className = 'result-badge match';
                        alertBox.innerHTML = `✔ ${json.message}`;
                        alertBox.style.display = 'block';
                    }
                    form.reset();
                    const video = document.getElementById('enrollWebcam');
                    const preview = document.getElementById('enrollPhotoPreview');
                    if (video) video.style.display = 'block';
                    if (preview) preview.style.display = 'none';
                    fetchEnrolledStudents();
                } else {
                    let errText = json.message;
                    if (!errText && json.detail) {
                        errText = Array.isArray(json.detail) ? json.detail.map(d => d.msg).join(', ') : json.detail;
                    }
                    if (!errText) errText = "Enrollment failed. Please capture a clear face photo.";

                    if (alertBox) {
                        alertBox.className = 'result-badge fail';
                        alertBox.innerHTML = `⚠ Error: ${errText}`;
                        alertBox.style.display = 'block';
                    }
                }
            } catch (err) {
                console.error("Enrollment submission error:", err);
                if (alertBox) {
                    alertBox.className = 'result-badge fail';
                    alertBox.innerText = 'Connection error while saving student baseline.';
                    alertBox.style.display = 'block';
                }
            } finally {
                if (submitBtn) submitBtn.disabled = false;
            }
        });
    }

    fetchEnrolledStudents();

    const editForm = document.getElementById('editStudentForm');
    if (editForm) {
        editForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const uid = document.getElementById('editUid').value;
            const name = document.getElementById('editName').value;
            const rollNo = document.getElementById('editRollNo').value;
            const branch = document.getElementById('editBranch').value;

            try {
                const res = await fetch(`/api/students/${uid}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, roll_no: rollNo, branch })
                });
                const json = await res.json();
                if (json.status === 'success') {
                    closeEditModal();
                    fetchEnrolledStudents();
                } else {
                    alert(`⚠ Update failed: ${json.message}`);
                }
            } catch (e) {
                alert("Error updating student.");
            }
        });
    }
});

let enrolledStudentsCache = [];

function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

async function fetchEnrolledStudents() {
    const tbody = document.getElementById('enrolledStudentsBody');
    if (!tbody) return;

    try {
        const res = await fetch('/api/students');
        const json = await res.json();

        if (json.status === 'success' && json.data) {
            enrolledStudentsCache = json.data;
            if (json.data.length === 0) {
                tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--text-dim); padding:20px;">No enrolled students found in database.</td></tr>`;
                return;
            }

            tbody.innerHTML = json.data.map(st => `
                <tr>
                    <td>
                        <img src="${st.photo_path}" style="width:36px; height:36px; border-radius:50%; object-fit:cover; border:1px solid var(--line);" onerror="this.src='/static/uploads/enrolled/default.jpg'">
                    </td>
                    <td style="font-weight:700;">${escapeHtml(st.name)}</td>
                    <td><span class="tag cyan">${escapeHtml(st.uid)}</span></td>
                    <td>${escapeHtml(st.roll_no || st.uid)}</td>
                    <td>${escapeHtml(st.branch)}</td>
                    <td style="font-size:11px; color:var(--text-dim);">${st.created_at ? st.created_at.split('T')[0] : 'Enrolled'}</td>
                    <td style="text-align:right;">
                        <button onclick="openEditModal('${st.uid}')" class="btn secondary" style="width:auto; padding:4px 10px; font-size:11px; margin-right:4px; cursor:pointer;">✏️ Edit</button>
                        <button onclick="deleteStudent('${st.uid}')" class="btn red" style="width:auto; padding:4px 10px; font-size:11px; cursor:pointer;">🗑️ Delete</button>
                    </td>
                </tr>
            `).join('');
        }
    } catch (e) {
        console.error("Error fetching enrolled students:", e);
    }
}

function openEditModal(uid) {
    const st = enrolledStudentsCache.find(s => String(s.uid) === String(uid));
    if (!st) return;

    document.getElementById('editUid').value = st.uid;
    document.getElementById('editName').value = st.name;
    document.getElementById('editRollNo').value = st.roll_no || st.uid;
    document.getElementById('editBranch').value = st.branch;
    document.getElementById('editStudentModal').style.display = 'flex';
}

function closeEditModal() {
    document.getElementById('editStudentModal').style.display = 'none';
}

async function deleteStudent(uid) {
    const st = enrolledStudentsCache.find(s => String(s.uid) === String(uid));
    const name = st ? st.name : uid;

    if (!confirm(`Are you sure you want to delete student "${name}" (UID: ${uid})?\nThis will also remove their attendance records.`)) return;

    try {
        const res = await fetch(`/api/students/${uid}`, { method: 'DELETE' });
        const json = await res.json();
        if (json.status === 'success') {
            alert(`✔ Student "${name}" deleted successfully.`);
            fetchEnrolledStudents();
        } else {
            alert(`⚠ Delete failed: ${json.message}`);
        }
    } catch (e) {
        alert("Error deleting student.");
    }
}
