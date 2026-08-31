// ==================== EWS Banjir — Main JS ====================
// Dipakai oleh index.html (publik) dan operator.html

// --- Jam Digital ---
function updateClock() {
    const now = new Date();
    const timeString = now.toLocaleTimeString('id-ID', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
    const el = document.getElementById('clock');
    if (el) el.textContent = timeString + ' WIB';
}
setInterval(updateClock, 1000);
updateClock();

// --- Chart.js Setup ---
Chart.defaults.color = '#64748b';
Chart.defaults.font.family = "'JetBrains Mono', 'Consolas', monospace";

const chartEl = document.getElementById('waterChart');
let waterChart = null;

if (chartEl) {
    const ctx = chartEl.getContext('2d');
    waterChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Ketinggian Air (%)',
                data: [],
                borderColor: '#0d9488',
                backgroundColor: 'rgba(13, 148, 136, 0.08)',
                borderWidth: 2,
                pointRadius: 0,
                fill: true,
                tension: 0.3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(0, 0, 0, 0.06)' },
                    ticks: { maxTicksLimit: 8, font: { size: 10 } }
                },
                y: {
                    grid: { color: 'rgba(0, 0, 0, 0.06)' },
                    min: 0,
                    max: 100,
                    ticks: {
                        font: { size: 10 },
                        callback: function(value) { return value + '%'; }
                    }
                }
            },
            animation: { duration: 0 }
        }
    });
}

const MAX_CHART_POINTS = 60;

// --- Polling Status API ---
let lastStatus = '';

async function fetchStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();

        // Update status text
        const statusEl = document.getElementById('status-text');
        if (statusEl) {
            statusEl.textContent = data.status;
            statusEl.className = 'status-value ' + data.status.toLowerCase();
        }

        // Update water level (persentase)
        const waterEl = document.getElementById('water-level-text');
        if (waterEl) {
            waterEl.textContent = data.water_pct !== null ? `${data.water_pct}%` : '—';
        }

        // Update timestamp
        const tsEl = document.getElementById('last-update');
        if (tsEl && data.timestamp) {
            const d = new Date(data.timestamp * 1000);
            tsEl.textContent = 'Terakhir: ' + d.toLocaleTimeString('id-ID', { hour12: false });
        }

        // Update connection dot
        const dot = document.getElementById('connection-dot');
        const badge = document.getElementById('camera-badge');
        if (data.camera_connected) {
            if (dot) { dot.className = 'status-dot'; }
            if (badge) { badge.className = 'camera-badge online'; badge.textContent = '● Online'; }
        } else {
            if (dot) { dot.className = 'status-dot offline'; }
            if (badge) { badge.className = 'camera-badge offline'; badge.textContent = '● Offline'; }
        }

        // Update chart (hanya di menit kelipatan 5: 08:50, 08:55, 09:00, ...)
        if (waterChart && data.water_pct !== null && data.water_pct !== undefined) {
            const now = new Date();
            const mins = now.getMinutes();

            // Hanya tambah data di menit kelipatan 5
            if (mins % 5 === 0) {
                const label = now.getHours().toString().padStart(2, '0') + ':' +
                              mins.toString().padStart(2, '0');

                const lastLabel = waterChart.data.labels[waterChart.data.labels.length - 1];
                if (label !== lastLabel) {
                    waterChart.data.labels.push(label);
                    waterChart.data.datasets[0].data.push(data.water_pct);

                    if (waterChart.data.labels.length > MAX_CHART_POINTS) {
                        waterChart.data.labels.shift();
                        waterChart.data.datasets[0].data.shift();
                    }
                    waterChart.update();
                }
            }
        }

        lastStatus = data.status;
    } catch (e) {
        // Server mungkin belum siap
        const dot = document.getElementById('connection-dot');
        if (dot) dot.className = 'status-dot offline';
    }
}

// Polling status setiap 5 detik (bukan 1 detik agar tidak lag)
setInterval(fetchStatus, 5000);
fetchStatus();

// --- Load Historical Data for Chart ---
async function loadHistory() {
    try {
        const res = await fetch('/api/history?hours=1');
        const data = await res.json();

        if (waterChart && data.length > 0) {
            // Ambil max 60 titik terakhir
            const recent = data.slice(-MAX_CHART_POINTS);
            waterChart.data.labels = recent.map(d => {
                const t = new Date(d.timestamp * 1000);
                return t.getHours().toString().padStart(2, '0') + ':' +
                       t.getMinutes().toString().padStart(2, '0');
            });
            waterChart.data.datasets[0].data = recent.map(d => d.water_pct);
            waterChart.update();
        }
    } catch (e) {
        console.log('Gagal memuat riwayat:', e);
    }
}

// Load history saat halaman dibuka, lalu refresh setiap 5 menit
loadHistory();
setInterval(loadHistory, 300000);
