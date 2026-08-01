// Faculty Admin Dashboard Controller

document.addEventListener('DOMContentLoaded', () => {
    const today = new Date().toISOString().split('T')[0];
    const dateInput = document.getElementById('filterDate');
    if (dateInput) dateInput.value = today;
    fetchAdminAttendance();
});

async function fetchAdminAttendance() {
    const dateInput = document.getElementById('filterDate');
    const branchInput = document.getElementById('filterBranch');
    const statusInput = document.getElementById('filterStatus');
    const searchInput = document.getElementById('filterSearch');

    const date = dateInput ? dateInput.value : '';
    const branch = branchInput ? branchInput.value : '';
    const status = statusInput ? statusInput.value : '';
    const uid = searchInput ? searchInput.value.trim() : '';

    let url = `/api/attendance?`;
    if (date) url += `date=${encodeURIComponent(date)}&`;
    if (branch) url += `branch=${encodeURIComponent(branch)}&`;
    if (status) url += `status=${encodeURIComponent(status)}&`;
    if (uid) url += `uid=${encodeURIComponent(uid)}&`;

    try {
        const res = await fetch(url);
        const json = await res.json();

        if (json.status === 'success') {
            renderDashboard(json.data || []);
        }
    } catch (err) {
        console.error("Failed to fetch attendance:", err);
    }
}

function renderDashboard(records) {
    if (!Array.isArray(records)) records = [];

    // 1. Update Stat Counters
    let total = records.length;
    let present = records.filter(r => ['PRESENT', 'MANUAL_OVERRIDE'].includes(r.status)).length;
    let proxy = records.filter(r => r.status === 'PROXY_ALERT').length;
    let noFace = records.filter(r => ['FLAGGED_NO_FACE', 'ABSENT'].includes(r.status)).length;

    const elTotal = document.getElementById('statTotal');
    const elPresent = document.getElementById('statPresent');
    const elProxy = document.getElementById('statProxy');
    const elNoFace = document.getElementById('statNoFace');

    if (elTotal) elTotal.innerText = total;
    if (elPresent) elPresent.innerText = present;
    if (elProxy) elProxy.innerText = proxy;
    if (elNoFace) elNoFace.innerText = noFace;

    const badgeProxyCount = document.getElementById('badgeProxyCount');
    const flaggedAlerts = records.filter(r => ['PROXY_ALERT', 'FLAGGED_NO_FACE'].includes(r.status));
    if (badgeProxyCount) badgeProxyCount.innerText = flaggedAlerts.length;

    // 2. Render Main Attendance Table
    const tbody = document.getElementById('attendanceTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (records.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" style="text-align:center; padding:32px; color:var(--text-dim); font-size:13px;">
                    No attendance logs found matching filters.
                </td>
            </tr>
        `;
    } else {
        records.forEach(r => {
            const tr = document.createElement('tr');
            const badgeHtml = getStatusBadgeHtml(r.status);
            const studentName = r.student_name || 'Unregistered Student';
            const studentUid = r.student_uid || 'N/A';
            const branch = r.branch || 'General';
            const timestamp = r.scan_timestamp || '-';
            const note = r.verification_note || '-';

            tr.innerHTML = `
                <td style="font-family:'JetBrains Mono', monospace; font-size:12px; color:var(--text-dim);">#${r.id}</td>
                <td>
                    <div style="font-weight:700; color:var(--text);">${studentName}</div>
                </td>
                <td style="font-family:'JetBrains Mono', monospace; font-size:12px; color:var(--cyan); font-weight:700;">${studentUid}</td>
                <td style="font-size:12.5px; color:var(--text-dim);">${branch}</td>
                <td style="font-family:'JetBrains Mono', monospace; font-size:12px; color:var(--text-dim);">${timestamp}</td>
                <td>${badgeHtml}</td>
                <td style="font-size:12px; color:var(--text-dim); max-width:240px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${note}">${note}</td>
                <td style="text-align:right;">
                    <div style="display:inline-flex; gap:6px;">
                        <button onclick="overrideAttendance(${r.id}, 'PRESENT')" title="Approve as Present"
                            class="btn" style="padding:5px 12px; font-size:11px; width:auto; background:rgba(47,230,200,0.15); color:var(--cyan); border:1px solid var(--cyan-dim);">
                            Approve
                        </button>
                        <button onclick="overrideAttendance(${r.id}, 'ABSENT')" title="Flag as Absent"
                            class="btn red" style="padding:5px 12px; font-size:11px; width:auto;">
                            Reject
                        </button>
                    </div>
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    try {
        renderProxyAlertCards(flaggedAlerts);
    } catch(e) {}

    if (window.lucide && typeof lucide.createIcons === 'function') {
        try { lucide.createIcons(); } catch(e) {}
    }
}

function renderProxyAlertCards(flaggedRecords) {
    const container = document.getElementById('proxyAlertsContainer');
    if (!container) return;
    container.innerHTML = '';

    if (flaggedRecords.length === 0) {
        container.innerHTML = `
            <div style="padding:32px; text-align:center; background:var(--panel-2); border:1px solid var(--line); border-radius:12px; color:var(--text-dim);">
                <h4 style="font-weight:700; color:var(--text); font-size:14px;">No Flagged Proxy Alerts</h4>
                <p style="font-size:12px; color:var(--text-dim); margin-top:4px;">All scan records for this period passed AI anti-proxy checks clean.</p>
            </div>
        `;
        return;
    }

    flaggedRecords.forEach(r => {
        const card = document.createElement('div');
        card.style.cssText = 'padding:16px; border-radius:12px; background:var(--panel-2); border:1px solid var(--amber); margin-bottom:14px;';

        card.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                <div>
                    <span style="font-weight:700; color:var(--text);">${r.student_name || 'Student'} (UID: ${r.student_uid})</span>
                    <div style="font-family:'JetBrains Mono', monospace; font-size:11px; color:var(--text-dim); margin-top:2px;">
                        Scan #${r.id} &bull; ${r.scan_timestamp} &bull; Branch: ${r.branch || 'N/A'}
                    </div>
                </div>
                <div style="display:flex; gap:6px;">
                    <button onclick="overrideAttendance(${r.id}, 'PRESENT')" class="btn" style="padding:6px 12px; font-size:11.5px; width:auto;">Approve</button>
                    <button onclick="overrideAttendance(${r.id}, 'ABSENT')" class="btn red" style="padding:6px 12px; font-size:11.5px; width:auto;">Reject</button>
                </div>
            </div>
            <div style="font-size:12px; color:var(--amber); font-family:'JetBrains Mono', monospace;">
                <strong>AI Note:</strong> ${r.verification_note || 'Flagged for review.'}
            </div>
        `;
        container.appendChild(card);
    });
}

function getStatusBadgeHtml(status) {
    switch (status) {
        case 'PRESENT':
        case 'MANUAL_OVERRIDE':
            return `<span class="tag cyan">✔ PRESENT</span>`;
        case 'ABSENT':
        case 'FLAGGED_NO_FACE':
            return `<span class="tag red">✘ ABSENT</span>`;
        case 'PROXY_ALERT':
            return `<span class="tag amber">⚠ PROXY ALERT</span>`;
        default:
            return `<span class="tag cyan">${status}</span>`;
    }
}

async function overrideAttendance(attendanceId, action) {
    try {
        const res = await fetch('/api/admin/override', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ attendance_id: attendanceId, action: action })
        });
        const json = await res.json();
        if (json.status === 'success') {
            fetchAdminAttendance();
        }
    } catch (e) {
        console.error("Override action error:", e);
    }
}

async function clearAllAttendanceLogs() {
    if (!confirm("Are you sure you want to delete ALL stored attendance entries and scan logs? This action cannot be undone.")) {
        return;
    }

    try {
        const res = await fetch('/api/admin/clear_attendance', {
            method: 'POST'
        });
        const json = await res.json();
        if (json.status === 'success') {
            alert("✅ " + json.message);
            fetchAdminAttendance();
        } else {
            alert("⚠ Error: " + json.message);
        }
    } catch (e) {
        console.error("Clear logs error:", e);
        alert("Connection error while clearing attendance logs.");
    }
}
