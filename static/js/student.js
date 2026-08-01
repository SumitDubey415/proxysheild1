// Student Portal Controller
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('studentSearchForm');
    if (form) {
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            const uid = document.getElementById('studentUidInput').value.trim();
            if (uid) fetchStudentSummary(uid);
        });
    }
});

async function fetchStudentSummary(uid) {
    const alertBox = document.getElementById('studentPortalAlert');
    const resultView = document.getElementById('studentSummaryResult');

    if (alertBox) alertBox.style.display = 'none';
    if (resultView) resultView.style.display = 'none';

    try {
        const res = await fetch(`/api/student/${encodeURIComponent(uid)}`);
        const json = await res.json();

        if (json.status === 'success') {
            renderStudentView(json.data);
            if (resultView) resultView.style.display = 'block';
        } else {
            if (alertBox) {
                alertBox.className = 'result-badge fail';
                alertBox.innerHTML = `⚠ ${json.message}`;
                alertBox.style.display = 'block';
            }
        }
    } catch (err) {
        console.error("Student portal fetch error:", err);
        if (alertBox) {
            alertBox.className = 'result-badge fail';
            alertBox.innerText = 'Error connecting to student database.';
            alertBox.style.display = 'block';
        }
    }
}

function renderStudentView(data) {
    const s = data.student;
    const stats = data.stats;

    // Student Details
    const nameEl = document.getElementById('studentName');
    if (nameEl) nameEl.innerText = s.name;

    const uidBadge = document.getElementById('studentUidBadge');
    if (uidBadge) uidBadge.innerText = `UID: ${s.uid}`;

    const branchBadge = document.getElementById('studentBranchBadge');
    if (branchBadge) branchBadge.innerText = s.branch;

    // Eligibility Banners
    const warnBanner = document.getElementById('eligibilityWarningBanner');
    const successBanner = document.getElementById('eligibilitySuccessBanner');
    const pctVal = document.getElementById('percentageValue');

    if (pctVal) pctVal.innerText = `${stats.percentage}%`;

    if (stats.is_eligible) {
        if (successBanner) successBanner.style.display = 'block';
        if (warnBanner) warnBanner.style.display = 'none';
        if (pctVal) pctVal.style.color = 'var(--cyan)';
    } else {
        if (warnBanner) warnBanner.style.display = 'block';
        if (successBanner) successBanner.style.display = 'none';
        if (pctVal) pctVal.style.color = 'var(--red)';
    }

    // Counters
    const countTotal = document.getElementById('countTotal');
    if (countTotal) countTotal.innerText = stats.total;

    const countPresent = document.getElementById('countPresent');
    if (countPresent) countPresent.innerText = stats.present;

    const countAbsent = document.getElementById('countAbsent');
    if (countAbsent) countAbsent.innerText = stats.absent;

    // Logs Table
    const tbody = document.getElementById('studentLogsTableBody');
    if (tbody) {
        tbody.innerHTML = '';
        if (data.recent_logs.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:16px; color:var(--text-dim);">No attendance logs found for this student.</td></tr>`;
        } else {
            data.recent_logs.forEach(log => {
                const tr = document.createElement('tr');
                let tagHtml = '';
                if (['PRESENT', 'MANUAL_OVERRIDE'].includes(log.status)) {
                    tagHtml = `<span class="tag cyan">✔ PRESENT</span>`;
                } else if (log.status === 'PROXY_ALERT') {
                    tagHtml = `<span class="tag amber">⚠ PROXY ALERT</span>`;
                } else {
                    tagHtml = `<span class="tag red">✘ ABSENT</span>`;
                }

                tr.innerHTML = `
                    <td>${log.date}</td>
                    <td>${log.scan_timestamp.split(' ')[1] || log.scan_timestamp}</td>
                    <td>${tagHtml}</td>
                    <td style="color:var(--text-dim);">${log.verification_note || '-'}</td>
                `;
                tbody.appendChild(tr);
            });
        }
    }
}
