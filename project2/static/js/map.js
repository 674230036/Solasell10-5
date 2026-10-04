/**
 * map.js  –  SolarAI Ban Pong | GIS Map + 3-Step Analysis
 *
 * Panel flow:
 *   placeholder  →  (click valid location)
 *   input        →  (enter monthly bill + click วิเคราะห์)
 *   results      →  (show full analysis)
 */

'use strict';

// ─────────────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────────────
const BAN_PONG_CENTER = { lat: 13.8264, lng: 99.8780 };
const DEFAULT_ZOOM    = 13;

let map, currentMarker, currentAnalysisId;
let searchTimeout   = null;
let boundaryPolygon = null;   // [lng, lat] pairs for PIP check
let boundaryLayer   = null;   // Leaflet GeoJSON layer

// Pending location (set when user clicks map / searches)
let pendingLat     = null;
let pendingLng     = null;
let pendingAddress = null;

// User's monthly bill (stored for financial display recalc)
let currentMonthlyBill = 3500;

// ─────────────────────────────────────────────────────────────────────────────
// Panel State Machine
// ─────────────────────────────────────────────────────────────────────────────
function setPanelState(state) {
    const panel = document.getElementById('result-panel');
    if (!panel) return;
    panel.classList.remove('open', 'rp-state-input');
    if (state === 'input')   panel.classList.add('rp-state-input');
    if (state === 'results') panel.classList.add('open');
}

function backToInput() {
    if (pendingLat !== null) {
        showInputStep(pendingLat, pendingLng, pendingAddress);
    } else {
        setPanelState('placeholder');
    }
}
window.backToInput = backToInput;

// ─────────────────────────────────────────────────────────────────────────────
// Boundary Warning Dialog
// ─────────────────────────────────────────────────────────────────────────────
function showBoundaryWarning() {
    const existing = document.getElementById('boundary-warning');
    if (existing) existing.remove();

    const dlg = document.createElement('div');
    dlg.id = 'boundary-warning';
    dlg.innerHTML = `
        <div class="bw-overlay" onclick="closeBoundaryWarning()"></div>
        <div class="bw-dialog">
            <div class="bw-icon"><i class="bi bi-exclamation-triangle-fill"></i></div>
            <h3>นอกเขตพื้นที่โครงการ</h3>
            <p>ระบบรองรับเฉพาะพื้นที่<br>
               <strong>อำเภอบ้านโป่ง จังหวัดราชบุรี</strong><br>
               กรุณาเลือกตำแหน่งภายในพื้นที่โครงการ</p>
            <button class="btn btn-primary" onclick="closeBoundaryWarning()"
                    style="width:100%;justify-content:center;">
                <i class="bi bi-geo-alt-fill"></i> รับทราบ
            </button>
        </div>`;
    document.body.appendChild(dlg);
    setTimeout(closeBoundaryWarning, 6000);
}
window.closeBoundaryWarning = function () {
    const dlg = document.getElementById('boundary-warning');
    if (dlg) { dlg.style.opacity = '0'; setTimeout(() => dlg.remove(), 250); }
};

// ─────────────────────────────────────────────────────────────────────────────
// Point-in-Polygon (Ray Casting)
// ─────────────────────────────────────────────────────────────────────────────
function pointInPolygon(lat, lng, polygon) {
    let inside = false;
    const x = lng, y = lat;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
        const xi = polygon[i][0], yi = polygon[i][1];
        const xj = polygon[j][0], yj = polygon[j][1];
        const intersect = ((yi > y) !== (yj > y)) &&
            (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
        if (intersect) inside = !inside;
    }
    return inside;
}

function isInsideBanPong(lat, lng) {
    if (!boundaryPolygon) return true;   // not loaded yet → allow (fail open)
    return pointInPolygon(lat, lng, boundaryPolygon);
}

// ─────────────────────────────────────────────────────────────────────────────
// Load Boundary GeoJSON
// ─────────────────────────────────────────────────────────────────────────────
async function loadBoundary() {
    try {
        const res  = await fetch('/api/boundary');
        const data = await res.json();

        const geom = data.features[0].geometry;
        if (geom.type === 'Polygon') {
            boundaryPolygon = geom.coordinates[0];
        } else if (geom.type === 'MultiPolygon') {
            boundaryPolygon = geom.coordinates.reduce((a, b) =>
                b[0].length > a[0].length ? b : a)[0];
        }

        boundaryLayer = L.geoJSON(data, {
            style: {
                color:       '#10b981',
                weight:      2.5,
                opacity:     0.85,
                fillColor:   '#10b981',
                fillOpacity: 0.07,
                dashArray:   '7 5',
            },
        }).addTo(map);

        map.fitBounds(boundaryLayer.getBounds(), { padding: [50, 50] });

    } catch (e) {
        console.warn('[map] Boundary load failed:', e);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Map Init
// ─────────────────────────────────────────────────────────────────────────────
function initMap() {
    map = L.map('map', {
        center:      [BAN_PONG_CENTER.lat, BAN_PONG_CENTER.lng],
        zoom:        DEFAULT_ZOOM,
        zoomControl: false,
    });

    // Basemap layers (Free, no API key required)
    const osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
    });

    const satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
        maxZoom: 19,
    });

    // Default to OpenStreetMap
    osmLayer.addTo(map);

    // Layer switcher control (Street vs Satellite for solar roof viewing)
    L.control.layers({
        'แผนที่ถนน (OpenStreetMap)': osmLayer,
        'ภาพดาวเทียม (Esri Satellite)': satelliteLayer
    }, null, { position: 'topright' }).addTo(map);

    L.control.zoom({ position: 'bottomleft' }).addTo(map);
    L.control.scale({ imperial: false }).addTo(map);

    map.on('click', (e) => onMapClick(e.latlng.lat, e.latlng.lng));

    setupSearch();
    setupCurrentLocation();
    setupInputForm();
    loadBoundary();
}

// ─────────────────────────────────────────────────────────────────────────────
// Custom Marker Icon
// ─────────────────────────────────────────────────────────────────────────────
function makeIcon(color = '#10b981') {
    return L.divIcon({
        html: `<div style="
            width:36px;height:36px;
            background:${color};
            border:3px solid white;
            border-radius:50% 50% 50% 0;
            transform:rotate(-45deg);
            box-shadow:0 3px 10px rgba(0,0,0,0.28);
        "></div>`,
        iconSize:   [36, 36],
        iconAnchor: [18, 36],
        className:  '',
    });
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 1 → Step 2: Location Selected → Show Input Form
// ─────────────────────────────────────────────────────────────────────────────
async function onMapClick(lat, lng) {
    if (!isInsideBanPong(lat, lng)) {
        showBoundaryWarning();
        return;
    }

    // Place marker
    if (currentMarker) map.removeLayer(currentMarker);
    currentMarker = L.marker([lat, lng], { icon: makeIcon() }).addTo(map);
    map.panTo([lat, lng]);

    // Geocode
    let address = `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
    try { address = await reverseGeocode(lat, lng); } catch {}

    showInputStep(lat, lng, address);
}

function showInputStep(lat, lng, address) {
    pendingLat     = lat;
    pendingLng     = lng;
    pendingAddress = address;

    setHtml('rp-input-address', escHtml(address));
    setText('rp-input-coords', `${lat.toFixed(5)}°N, ${lng.toFixed(5)}°E`);

    // Reset bill input to default if empty
    const billInput = document.getElementById('monthly-bill');
    if (billInput && !billInput.value) billInput.value = 3500;

    setPanelState('input');
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 2 → Step 3: Run Analysis
// ─────────────────────────────────────────────────────────────────────────────
function setupInputForm() {
    const runBtn  = document.getElementById('run-analysis-btn');
    const backBtn = document.getElementById('back-to-map-btn');
    const bill    = document.getElementById('monthly-bill');

    runBtn?.addEventListener('click', () => runAnalysis());
    backBtn?.addEventListener('click', () => {
        setPanelState('placeholder');
        pendingLat = pendingLng = pendingAddress = null;
        if (currentMarker) { map.removeLayer(currentMarker); currentMarker = null; }
    });

    // Preset buttons in input form
    document.querySelectorAll('.bill-preset-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const val = parseInt(btn.dataset.bill);
            if (bill) bill.value = val;
            document.querySelectorAll('.bill-preset-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        });
    });

    // Sync input field changes with preset buttons
    bill?.addEventListener('input', () => {
        const val = parseInt(bill.value);
        document.querySelectorAll('.bill-preset-btn').forEach(b => {
            b.classList.toggle('active', parseInt(b.dataset.bill) === val);
        });
    });

    // Allow Enter key to submit
    bill?.addEventListener('keydown', (e) => { if (e.key === 'Enter') runAnalysis(); });
}

async function runAnalysis(overrideBill = null) {
    if (pendingLat === null) return;

    const billInput = document.getElementById('monthly-bill');
    if (overrideBill !== null) {
        currentMonthlyBill = Math.max(100, parseInt(overrideBill));
        if (billInput) billInput.value = currentMonthlyBill;
    } else {
        currentMonthlyBill = Math.max(100, parseInt(billInput?.value || 3000));
        if (billInput) billInput.value = currentMonthlyBill;
    }

    showLoading(true);

    try {
        const res = await fetch('/api/analyze', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({
                lat:          pendingLat,
                lng:          pendingLng,
                address:      pendingAddress,
                monthly_bill: currentMonthlyBill,
            }),
        });
        const data = await res.json();
        if (data.status !== 'ok') throw new Error(data.message || 'Analysis failed');

        currentAnalysisId = data.id;
        renderPanel(data, currentMonthlyBill);
        setPanelState('results');

    } catch (e) {
        Toast.show('เกิดข้อผิดพลาดในการวิเคราะห์: ' + e.message, 'error');
    } finally {
        showLoading(false);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Render Results Panel
// ─────────────────────────────────────────────────────────────────────────────
function renderPanel(d, monthlyBill = 3000) {

    // ── Header ────────────────────────────────────────────────────────────────
    setHtml('rp-address',
        `<i class="bi bi-geo-alt-fill text-green" style="margin-right:4px;"></i>${escHtml(d.address || '')}`);
    setText('rp-coords', `${d.lat.toFixed(5)}°N, ${d.lng.toFixed(5)}°E`);

    // ── Suitability & Confidence (From AI) ────────────────────────────────────
    setHtml('rp-stars', renderStars(d.suitability || 0));
    setText('rp-suit-label', d.suitability_label || '–');
    setText('rp-confidence', `AI Confidence: ${fmt.pct(d.confidence || 0)}`);
    const bar = document.getElementById('rp-conf-bar');
    if (bar) bar.style.width = `${Math.round(d.confidence || 0)}%`;

    // ═════════════════════════════════════════════════════════════════════════
    // FINANCIAL & RECOMMENDATION LOGIC
    // ═════════════════════════════════════════════════════════════════════════
    const rec = d.recommended;
    const bill = d.monthly_bill || monthlyBill;

    // ── Energy production display (from recommended system) ───────────────────
    setText('rp-daily',   fmt.num(rec.daily_kwh));
    setText('rp-monthly', fmt.int(rec.monthly_kwh));
    setText('rp-annual',  fmt.int(rec.annual_kwh));

    // ── Financial display ─────────────────────────────────────────────────────
    setText('rp-cur-bill',    fmt.thb(bill));
    setText('rp-after-bill',  fmt.thb(rec.remaining_bill));
    setText('rp-save-month',  fmt.thb(rec.monthly_save));
    setText('rp-save-annual', fmt.thb(rec.annual_save));
    setText('rp-roi',         fmt.pct(rec.roi));
    setText('rp-breakeven',   `${rec.breakeven} ปี`);

    // ── Recommendation Reason Banner ──────────────────────────────────────────
    const recReasonEl = document.getElementById('rp-rec-reason');
    if (recReasonEl) {
        recReasonEl.innerHTML = `
            <div style="display:flex;align-items:center;gap:6px;">
                <span class="badge badge-green" style="font-size:12px;padding:4px 8px;">
                    ⭐ แนะนำขนาด ${rec.kw} kW
                </span>
                <span style="font-size:11.5px;color:var(--text);font-weight:600;">
                    ${escHtml(d.recommendation_note || rec.note || '')}
                </span>
            </div>`;
    }

    // ── System cards display (all tiers) ──────────────────────────────────────
    const sysCont = document.getElementById('rp-systems');
    if (sysCont && d.systems) {
        sysCont.innerHTML = d.systems.map(s => `
            <div class="sys-card ${s.recommended ? 'rec' : ''}">
                <div class="sys-card-header">
                    <span class="sys-card-kw">${s.kw} kW</span>
                    ${s.recommended ? '<span class="badge badge-green sys-card-badge">⭐ เหมาะกับค่าไฟนี้ที่สุด</span>' : ''}
                </div>
                <div class="sys-card-note" style="font-size:11px;color:${s.recommended ? 'var(--primary-dark)' : 'var(--text-muted)'};margin-bottom:6px;font-weight:500;">
                    ${escHtml(s.note || '')}
                </div>
                <div class="sys-card-detail">
                    ผลิต <span>${fmt.int(s.monthly_kwh)} kWh/เดือน</span> ·
                    ประหยัด <span>${fmt.thb(s.monthly_save)}/เดือน</span> (<span>${fmt.thb(s.annual_save)}/ปี</span>)
                </div>
                <div class="sys-card-detail" style="margin-top:3px;">
                    ราคา <span>${fmt.thb(s.cost)}</span> ·
                    ROI <span>${s.roi}%</span> ·
                    คืนทุน <span>${s.breakeven} ปี</span>
                </div>
            </div>`).join('');
    }

    // ── Bind In-Panel Result Preset Buttons ────────────────────────────────────
    document.querySelectorAll('.result-preset-btn').forEach(btn => {
        const bVal = parseInt(btn.dataset.bill);
        btn.classList.toggle('active', bVal === Math.round(bill));
        btn.onclick = () => {
            runAnalysis(bVal);
        };
    });

    // ── Environmental ─────────────────────────────────────────────────────────
    setText('rp-co2',   `${fmt.int(d.co2_saved_kg || 0)} kg`);
    setText('trees', `${fmt.int(d.trees_equiv  || 0)} ต้น`);
    setText('rp-trees', `${fmt.int(d.trees_equiv  || 0)} ต้น`);

    // ── Full analysis link ────────────────────────────────────────────────────
    const link = document.getElementById('rp-full-link');
    if (link) link.href = `/analysis/${d.id}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Panel helpers
// ─────────────────────────────────────────────────────────────────────────────
function closePanel() {
    setPanelState('placeholder');
    pendingLat = pendingLng = pendingAddress = null;
    if (currentMarker) { map.removeLayer(currentMarker); currentMarker = null; }
}
window.closePanel = closePanel;

function showLoading(show) {
    document.getElementById('map-loading')?.classList.toggle('show', show);
}

// ─────────────────────────────────────────────────────────────────────────────
// Reverse Geocode (Nominatim)
// ─────────────────────────────────────────────────────────────────────────────
async function reverseGeocode(lat, lng) {
    const url  = `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}&format=json&accept-language=th`;
    const data = await (await fetch(url)).json();
    if (data.display_name) {
        return data.display_name.split(',').slice(0, 3).join(', ').trim();
    }
    return `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Search
// ─────────────────────────────────────────────────────────────────────────────
function setupSearch() {
    const input    = document.getElementById('search-input');
    const btn      = document.getElementById('search-btn');
    const dropdown = document.getElementById('search-results');
    if (!input) return;

    input.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        const q = input.value.trim();
        if (q.length < 2) { dropdown.style.display = 'none'; return; }
        searchTimeout = setTimeout(() => doSearch(q), 500);
    });

    btn?.addEventListener('click', () => {
        const q = input.value.trim();
        if (q) doSearch(q);
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            clearTimeout(searchTimeout);
            const q = input.value.trim();
            if (q) doSearch(q);
        }
    });

    document.addEventListener('click', (e) => {
        if (!input.closest('.search-box').contains(e.target)) {
            dropdown.style.display = 'none';
        }
    });
}

async function doSearch(query) {
    const dropdown = document.getElementById('search-results');
    const hasArea  = /บ้านโป่ง|ราชบุรี|Ban Pong|Ratchaburi/i.test(query);
    const fullQ    = hasArea ? query : `${query} บ้านโป่ง ราชบุรี ประเทศไทย`;

    dropdown.innerHTML = `<div class="search-result-item" style="color:var(--text-muted);justify-content:center;">
        <i class="bi bi-hourglass-split"></i> กำลังค้นหา...</div>`;
    dropdown.style.display = 'block';

    try {
        const url  = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(fullQ)}&format=json&limit=6&accept-language=th`;
        const data = await (await fetch(url)).json();

        if (!data.length) {
            dropdown.innerHTML = `<div class="search-result-item" style="color:var(--text-muted);">
                <i class="bi bi-search"></i> ไม่พบผลลัพธ์</div>`;
            return;
        }

        dropdown.innerHTML = data.map((r, i) => `
            <div class="search-result-item" id="sr-${i}"
                 data-lat="${r.lat}" data-lng="${r.lon}"
                 data-name="${escHtml(r.display_name.split(',').slice(0,3).join(', '))}">
                <i class="bi bi-geo-alt" style="color:var(--text-muted);flex-shrink:0;"></i>
                <span>${escHtml(r.display_name.split(',').slice(0,4).join(', '))}</span>
            </div>`).join('');

        dropdown.querySelectorAll('.search-result-item[data-lat]').forEach(item => {
            item.addEventListener('click', () => {
                const lat  = parseFloat(item.dataset.lat);
                const lng  = parseFloat(item.dataset.lng);
                const name = item.dataset.name;

                document.getElementById('search-input').value = name;
                dropdown.style.display = 'none';

                // Boundary check before placing
                if (!isInsideBanPong(lat, lng)) {
                    showBoundaryWarning();
                    return;
                }

                if (currentMarker) map.removeLayer(currentMarker);
                currentMarker = L.marker([lat, lng], { icon: makeIcon() }).addTo(map);
                map.setView([lat, lng], 15);
                showInputStep(lat, lng, name);
            });
        });

    } catch {
        dropdown.style.display = 'none';
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Current Location
// ─────────────────────────────────────────────────────────────────────────────
function setupCurrentLocation() {
    const btn = document.getElementById('location-btn');
    if (!btn) return;

    btn.addEventListener('click', () => {
        if (!navigator.geolocation) {
            Toast.show('Browser ไม่รองรับ Geolocation', 'error');
            return;
        }
        btn.classList.add('active');
        navigator.geolocation.getCurrentPosition(
            async (pos) => {
                btn.classList.remove('active');
                const lat = pos.coords.latitude;
                const lng = pos.coords.longitude;

                if (!isInsideBanPong(lat, lng)) {
                    showBoundaryWarning();
                    return;
                }

                map.setView([lat, lng], 15);
                if (currentMarker) map.removeLayer(currentMarker);
                currentMarker = L.marker([lat, lng], { icon: makeIcon() }).addTo(map);

                let address = `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
                try { address = await reverseGeocode(lat, lng); } catch {}
                showInputStep(lat, lng, address);
            },
            () => {
                btn.classList.remove('active');
                Toast.show('ไม่สามารถดึงตำแหน่งปัจจุบันได้', 'error');
            }
        );
    });
}

// ─────────────────────────────────────────────────────────────────────────────
// Utility Helpers
// ─────────────────────────────────────────────────────────────────────────────
function escHtml(str) {
    return String(str || '').replace(/[&<>"']/g, c =>
        ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}

function setText(id, val)  {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}

function setHtml(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
}

// ─────────────────────────────────────────────────────────────────────────────
// Boot
// ─────────────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', initMap);
