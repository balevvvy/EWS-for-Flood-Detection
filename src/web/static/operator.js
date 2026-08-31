async function resetPTZ() {
    const btn = document.getElementById('btn-reset-camera');
    const feedback = document.getElementById('ptz-feedback');

    btn.disabled = true;
    btn.textContent = 'Mengembalikan kamera...';
    if (feedback) feedback.textContent = 'Proses berjalan, harap tunggu ~15 detik...';

    try {
        const res = await fetch('/api/ptz/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();

        if (data.ok) {
            if (feedback) feedback.textContent = data.message;
            btn.textContent = 'Berhasil';
            setTimeout(() => { btn.textContent = 'Kembalikan Kamera ke Papan Duga'; }, 3000);
        } else if (data.error) {
            if (feedback) feedback.textContent = data.error;
            btn.textContent = 'Kembalikan Kamera ke Papan Duga';
        }
    } catch (e) {
        if (feedback) feedback.textContent = 'Gagal menghubungi server';
        btn.textContent = 'Kembalikan Kamera ke Papan Duga';
    }

    btn.disabled = false;
    setTimeout(() => { if (feedback) feedback.textContent = ''; }, 5000);
}

// --- Kontrol Sensitivitas & Blur ---
function updateSensitivity(val) {
    document.getElementById('sensitivity-val').textContent = val;
    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sensitivity: parseInt(val) })
    });
}

function updateBlur(val) {
    document.getElementById('blur-val').textContent = val;
    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ blur_size: parseInt(val) })
    });
}

// Load current settings dari server
async function loadSettings() {
    try {
        const res = await fetch('/api/settings');
        const data = await res.json();
        if (data.sensitivity !== undefined) {
            document.getElementById('sensitivity-slider').value = data.sensitivity;
            document.getElementById('sensitivity-val').textContent = data.sensitivity;
        }
        if (data.blur_size !== undefined) {
            document.getElementById('blur-slider').value = data.blur_size;
            document.getElementById('blur-val').textContent = data.blur_size;
        }
    } catch (e) { }
}
loadSettings();

// --- Alert Log ---
async function loadAlerts() {
    try {
        const res = await fetch('/api/alerts?hours=24');
        const data = await res.json();

        const tbody = document.getElementById('alert-log-body');
        if (!tbody) return;

        if (data.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="3" style="text-align: center; padding: 20px; color: var(--text-muted);">
                        Belum ada alert dalam 24 jam terakhir.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = data.map(alert => {
            const t = new Date(alert.timestamp * 1000);
            const timeStr = t.toLocaleString('id-ID', {
                hour12: false,
                day: '2-digit',
                month: 'short',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
            const statusClass = alert.status.toLowerCase();
            return `
                <tr>
                    <td class="mono">${timeStr}</td>
                    <td><span class="status-badge ${statusClass}">${alert.status}</span></td>
                    <td>${alert.pesan || '-'}</td>
                </tr>
            `;
        }).join('');
    } catch (e) {
        console.log('Gagal memuat alert:', e);
    }
}

loadAlerts();
setInterval(loadAlerts, 600000); // Refresh setiap 10 menit

// --- Export CSV ---
async function exportCSV() {
    try {
        const res = await fetch('/api/history?hours=24');
        const data = await res.json();

        if (data.length === 0) {
            alert('Tidak ada data untuk diexport.');
            return;
        }

        let csv = 'Timestamp,Water_Y,Status\n';
        data.forEach(row => {
            const t = new Date(row.timestamp * 1000);
            const timeStr = t.toISOString();
            csv += `${timeStr},${row.water_y ?? ''},${row.status}\n`;
        });

        const blob = new Blob([csv], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `ews_data_${new Date().toISOString().slice(0, 10)}.csv`;
        a.click();
        URL.revokeObjectURL(url);
    } catch (e) {
        alert('Gagal export: ' + e.message);
    }
}
