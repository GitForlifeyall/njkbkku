let brandsData = [];
let activeWs = null;
let currentUploadBrand = null;
let currentTerminalBrand = null;
let pendingScrcpyLaunch = null;
let pollTimer = null;

let currentLogCategory = "morphe"; // 'morphe', 'container', 'start', 'all', 'live'
let currentLogSearch = "";
let cachedLogs = {
    morphe: "",
    container: "",
    start: "",
    all: "",
    live: []
};

document.addEventListener("DOMContentLoaded", () => {
    initApp();
    setupEventListeners();
});

function initApp() {
    fetchBrands();
    pollTimer = setInterval(fetchBrands, 2500);
}

function setupEventListeners() {
    document.getElementById("btn-refresh-brands").addEventListener("click", () => {
        fetchBrands();
    });

    const modalAddBrand = document.getElementById("modal-add-brand");
    document.getElementById("btn-open-add-brand").addEventListener("click", () => {
        document.getElementById("input-brand-name").value = "";
        document.getElementById("input-brand-id").value = "";
        modalAddBrand.classList.add("active");
        document.getElementById("input-brand-name").focus();
    });

    document.getElementById("btn-close-add-brand").addEventListener("click", () => {
        modalAddBrand.classList.remove("active");
    });

    document.getElementById("btn-cancel-add-brand").addEventListener("click", () => {
        modalAddBrand.classList.remove("active");
    });

    document.getElementById("btn-submit-add-brand").addEventListener("click", submitAddBrand);

    const modalUpload = document.getElementById("modal-upload");
    document.getElementById("btn-close-upload").addEventListener("click", () => {
        modalUpload.classList.remove("active");
    });

    document.getElementById("btn-cancel-upload").addEventListener("click", () => {
        modalUpload.classList.remove("active");
    });

    document.getElementById("btn-submit-upload").addEventListener("click", submitUploadJob);

    const modalTerminal = document.getElementById("modal-terminal");
    document.getElementById("btn-close-terminal").addEventListener("click", () => {
        closeTerminal();
    });

    document.getElementById("btn-clear-terminal").addEventListener("click", () => {
        document.getElementById("terminal-output").innerHTML = "";
    });

    const btnTerminalScrcpy = document.getElementById("btn-terminal-scrcpy");
    if (btnTerminalScrcpy) {
        btnTerminalScrcpy.addEventListener("click", () => {
            if (currentTerminalBrand) {
                handleLogin(currentTerminalBrand.brand_id);
            }
        });
    }

    const btnTerminalRefresh = document.getElementById("btn-terminal-refresh-logs");
    if (btnTerminalRefresh) {
        btnTerminalRefresh.addEventListener("click", () => {
            if (currentTerminalBrand) {
                pullContainerLogsSnapshot(currentTerminalBrand.brand_id);
            }
        });
    }

    const btnTerminalStopUpload = document.getElementById("btn-terminal-stop-upload");
    if (btnTerminalStopUpload) {
        btnTerminalStopUpload.addEventListener("click", () => {
            if (currentTerminalBrand) {
                handleStopUpload(currentTerminalBrand.brand_id);
            }
        });
    }

    const btnTerminalPauseUpload = document.getElementById("btn-terminal-pause-upload");
    if (btnTerminalPauseUpload) {
        btnTerminalPauseUpload.addEventListener("click", () => {
            if (currentTerminalBrand) {
                handleTogglePauseUpload(currentTerminalBrand.brand_id);
            }
        });
    }

    // Log category tab clicks
    document.querySelectorAll(".filter-tab").forEach(tab => {
        tab.addEventListener("click", () => {
            document.querySelectorAll(".filter-tab").forEach(t => t.classList.remove("active"));
            tab.classList.add("active");
            currentLogCategory = tab.getAttribute("data-filter") || "morphe";
            renderCurrentLogs();
        });
    });

    // Real-time search filter input
    const searchInput = document.getElementById("terminal-search-input");
    const clearSearchBtn = document.getElementById("btn-clear-log-search");
    if (searchInput) {
        searchInput.addEventListener("input", (e) => {
            currentLogSearch = e.target.value.toLowerCase().trim();
            if (clearSearchBtn) clearSearchBtn.style.display = currentLogSearch ? "block" : "none";
            renderCurrentLogs();
        });
    }

    if (clearSearchBtn) {
        clearSearchBtn.addEventListener("click", () => {
            if (searchInput) searchInput.value = "";
            currentLogSearch = "";
            clearSearchBtn.style.display = "none";
            renderCurrentLogs();
        });
    }
}

async function fetchBrands() {
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 6000);
        const res = await fetch("/api/brands", { signal: controller.signal });
        clearTimeout(timeoutId);
        if (!res.ok) throw new Error("Failed to fetch brands");
        brandsData = await res.json();
        renderDashboard(brandsData);

        // Check if there is a pending scrcpy auto-launch waiting for boot
        if (pendingScrcpyLaunch) {
            const brand = brandsData.find(b => b.brand_id === pendingScrcpyLaunch);
            if (brand && (brand.state === "READY" || brand.state === "BUSY")) {
                const targetId = pendingScrcpyLaunch;
                pendingScrcpyLaunch = null;
                handleLogin(targetId);
                appendTerminalLine(`\n[+] Container '${brand.name}' is READY! Auto-launching Scrcpy live screen...\n`, "sys");
            }
        }
    } catch (err) {
        console.error("Error polling brands:", err);
        if (!brandsData || brandsData.length === 0) {
            const container = document.getElementById("brands-container");
            if (container && container.querySelector(".loading-skeleton")) {
                container.innerHTML = `
                    <div class="empty-state">
                        <p style="color: #ef4444;">Connecting to Redroid Manager server...</p>
                        <button class="btn btn-secondary btn-sm" onclick="fetchBrands()">Retry Connection</button>
                    </div>
                `;
            }
        }
    }
}

function renderDashboard(brands) {
    const container = document.getElementById("brands-container");
    const activeCount = brands.filter(b => b.state === "READY" || b.state === "BUSY" || b.state === "BOOTING").length;

    document.getElementById("active-instances-text").textContent = `${activeCount} / ${brands.length} Active`;
    document.getElementById("metric-total-brands").textContent = brands.length;
    document.getElementById("metric-active-containers").textContent = activeCount;

    if (brands.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <p>No brand instances created yet.</p>
                <button class="btn btn-primary" onclick="document.getElementById('btn-open-add-brand').click()">
                    + Add Your First Brand
                </button>
            </div>
        `;
        return;
    }

    container.innerHTML = brands.map(brand => {
        const state = brand.state || "STOPPED";
        const stateClass = `state-${state.toLowerCase()}`;
        const badgeClass = `badge-${state.toLowerCase()}`;

        const isRunning = state === "READY" || state === "BUSY" || state === "BOOTING";
        const isReady = state === "READY";
        const isBooting = state === "BOOTING";
        const isBusy = state === "BUSY";

        let startStopBtn = "";
        if (isRunning) {
            startStopBtn = `
                <button class="btn btn-danger btn-sm" onclick="event.stopPropagation(); handleStopBrand('${brand.brand_id}')" title="Stop Container">
                    ⏹ Stop
                </button>
            `;
        } else {
            startStopBtn = `
                <button class="btn btn-success btn-sm" onclick="event.stopPropagation(); handleStartBrand('${brand.brand_id}')" title="Start Container via redroid.ps1">
                    ▶ Start
                </button>
            `;
        }

        const scrcpyBtnDisabled = (!isReady && !isBusy) ? "disabled" : "";
        const uploadBtnDisabled = ""; // Always enable Upload button

        let statusDisplay = state;
        if (isBooting) statusDisplay = "Booting...";
        let uploadActionBtn = "";
        if (brand.is_uploading) {
            const pauseLabel = brand.is_upload_paused ? "▶ Resume" : "⏸ Pause";
            const pauseClass = brand.is_upload_paused ? "paused" : "";
            uploadActionBtn = `
                <button class="btn btn-warning-solid btn-sm ${pauseClass}" onclick="event.stopPropagation(); handleTogglePauseUpload('${brand.brand_id}')" title="${brand.is_upload_paused ? 'Resume Upload Script' : 'Pause Upload Script'}">
                    ${pauseLabel}
                </button>
                <button class="btn btn-danger-solid btn-sm pulse-upload-stop" onclick="event.stopPropagation(); handleStopUpload('${brand.brand_id}')" title="Immediately Terminate Upload Script">
                    🛑 Stop
                </button>
            `;
        } else {
            uploadActionBtn = `
                <button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); openUploadModal('${brand.brand_id}')" title="Upload Video / Short">
                    🚀 Upload
                </button>
            `;
        }

        // Keep terminal stop and pause upload buttons in sync if terminal is open for this brand
        if (currentTerminalBrand && currentTerminalBrand.brand_id === brand.brand_id) {
            const stopBtn = document.getElementById("btn-terminal-stop-upload");
            if (stopBtn) {
                stopBtn.style.display = brand.is_uploading ? "inline-flex" : "none";
            }
            const pauseBtn = document.getElementById("btn-terminal-pause-upload");
            if (pauseBtn) {
                pauseBtn.style.display = brand.is_uploading ? "inline-flex" : "none";
                if (brand.is_upload_paused) {
                    pauseBtn.innerHTML = "▶ Resume";
                    pauseBtn.classList.add("paused");
                    pauseBtn.title = "Resume Upload Script";
                } else {
                    pauseBtn.innerHTML = "⏸ Pause";
                    pauseBtn.classList.remove("paused");
                    pauseBtn.title = "Pause Upload Script";
                }
            }
        }

        return `
            <div class="brand-card ${stateClass}" id="card-${brand.brand_id}" onclick="handleBrandCardClick('${brand.brand_id}', event)" title="Click to view container logs & output">
                <div class="card-top">
                    <div class="brand-identity">
                        <h3>${escapeHtml(brand.name)}</h3>
                        <div class="brand-id-tag">${escapeHtml(brand.brand_id)}</div>
                        <div class="card-click-hint">⚡ Click to view container logs & output</div>
                    </div>
                    <span class="status-badge ${badgeClass}">
                        ${isBooting ? '⏳' : isReady ? '●' : isBusy ? '⚡' : '○'} ${statusDisplay}
                    </span>
                </div>

                <div class="card-details">
                    <div class="detail-item">
                        <span class="detail-label">ADB Port</span>
                        <span class="detail-value">127.0.0.1:${brand.host_port}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">Container</span>
                        <span class="detail-value">${brand.container_name}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">Memory</span>
                        <span class="detail-value">${brand.memory_usage || '0B'}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label">Storage Path</span>
                        <span class="detail-value" title="${brand.data_dir}">${brand.data_dir}</span>
                    </div>
                </div>

                <div class="card-actions" onclick="event.stopPropagation()">
                    ${startStopBtn}
                    <button class="btn btn-secondary btn-sm" ${scrcpyBtnDisabled} onclick="event.stopPropagation(); handleLogin('${brand.brand_id}')" title="Open Interactive Scrcpy Screen">
                        🖥️ Scrcpy
                    </button>
                    <button class="btn btn-secondary btn-sm" onclick="event.stopPropagation(); openBrandLogs('${brand.brand_id}')" title="View Container & Boot Logs">
                        📜 Logs
                    </button>
                    ${uploadActionBtn}
                    <button class="btn btn-secondary btn-icon-only btn-sm" onclick="event.stopPropagation(); handleDeleteBrand('${brand.brand_id}', '${escapeHtml(brand.name)}')" title="Delete Brand">
                        🗑️
                    </button>
                </div>
            </div>
        `;
    }).join("");
}

function handleBrandCardClick(brandId, event) {
    if (event.target.closest("button") || event.target.closest(".card-actions")) {
        return;
    }

    const brand = brandsData.find(b => b.brand_id === brandId);
    if (!brand) return;

    // Open live terminal & logs modal
    openTerminal(brand);
}

function openBrandLogs(brandId) {
    const brand = brandsData.find(b => b.brand_id === brandId);
    if (!brand) return;
    openTerminal(brand);
}

async function handleStartBrand(brandId) {
    updateCardState(brandId, "BOOTING");
    const brand = brandsData.find(b => b.brand_id === brandId);
    if (brand) {
        pendingScrcpyLaunch = brandId;
        openTerminal(brand);
        appendTerminalLine(`\n[*] Initiating boot sequence for ${brand.name} via redroid.ps1...\n`, "sys");
    }

    try {
        const res = await fetch(`/api/brands/${brandId}/start`, { method: "POST" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to start");
        fetchBrands();
    } catch (err) {
        appendTerminalLine(`\n[ERROR] Start error: ${err.message}\n`, "err");
        alert(`Error starting container: ${err.message}`);
        fetchBrands();
    }
}

async function handleStopBrand(brandId) {
    updateCardState(brandId, "STOPPED");
    try {
        const res = await fetch(`/api/brands/${brandId}/stop`, { method: "POST" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to stop");
        fetchBrands();
    } catch (err) {
        alert(`Error stopping container: ${err.message}`);
        fetchBrands();
    }
}

async function handleLogin(brandId) {
    try {
        const res = await fetch(`/api/brands/${brandId}/scrcpy`, { method: "POST" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to launch scrcpy");
        if (data.booting) {
            pendingScrcpyLaunch = brandId;
            const brand = brandsData.find(b => b.brand_id === brandId);
            if (brand) openTerminal(brand);
            appendTerminalLine(`\n[*] Container is booting. Scrcpy will open automatically once boot completes.\n`, "sys");
        }
        fetchBrands();
    } catch (err) {
        alert(`Error launching Scrcpy window: ${err.message}`);
    }
}

async function handleDeleteBrand(brandId, brandName) {
    if (!confirm(`Are you sure you want to delete brand profile '${brandName}' (${brandId})?\n\nThis will stop its container.`)) {
        return;
    }
    try {
        const res = await fetch(`/api/brands/${brandId}`, { method: "DELETE" });
        if (!res.ok) throw new Error("Failed to delete brand");
        fetchBrands();
    } catch (err) {
        alert(`Error deleting brand: ${err.message}`);
    }
}

async function submitAddBrand() {
    const nameInput = document.getElementById("input-brand-name");
    const idInput = document.getElementById("input-brand-id");
    const name = nameInput.value.trim();
    const brand_id = idInput.value.trim() || undefined;

    if (!name) {
        alert("Please enter a brand name.");
        return;
    }

    try {
        const res = await fetch("/api/brands", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, brand_id })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to create brand");

        document.getElementById("modal-add-brand").classList.remove("active");
        fetchBrands();
    } catch (err) {
        alert(`Error creating brand: ${err.message}`);
    }
}

function openUploadModal(brandId) {
    const brand = brandsData.find(b => b.brand_id === brandId);
    if (!brand) return;

    currentUploadBrand = brand;
    document.getElementById("upload-target-brand-info").innerHTML = `Target Brand: <strong>${escapeHtml(brand.name)}</strong> (Port ${brand.host_port})`;
    document.getElementById("input-upload-title").value = "";
    document.getElementById("input-upload-video").value = "";
    document.getElementById("input-upload-sound").value = "";
    document.getElementById("input-upload-timestamp").value = "";
    
    const fileChosenName = document.getElementById("upload-file-chosen-name");
    if (fileChosenName) fileChosenName.textContent = "No file chosen";
    const fileInput = document.getElementById("input-upload-file");
    if (fileInput) fileInput.value = "";

    document.getElementById("modal-upload").classList.add("active");
}

async function handleFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;

    const fileChosenName = document.getElementById("upload-file-chosen-name");
    if (fileChosenName) fileChosenName.textContent = `Uploading ${file.name}...`;

    const formData = new FormData();
    formData.append("file", file);

    try {
        const res = await fetch("/api/upload-media", {
            method: "POST",
            body: formData
        });
        const data = await res.json();
        if (!res.ok || !data.success) throw new Error(data.detail || "Upload failed");

        document.getElementById("input-upload-video").value = data.file_path;
        if (fileChosenName) fileChosenName.textContent = `✓ ${file.name}`;
    } catch (err) {
        alert(`Failed to stage file: ${err.message}`);
        if (fileChosenName) fileChosenName.textContent = "Upload failed. Try entering path manually.";
    }
}

async function submitUploadJob() {
    if (!currentUploadBrand) return;

    const brandId = currentUploadBrand.brand_id;
    const title = document.getElementById("input-upload-title").value.trim() || undefined;
    const video_path = document.getElementById("input-upload-video").value.trim() || undefined;
    const sound = document.getElementById("input-upload-sound").value.trim() || undefined;
    const timestamp = document.getElementById("input-upload-timestamp").value.trim() || undefined;

    document.getElementById("modal-upload").classList.remove("active");

    openTerminal(currentUploadBrand);

    const stopBtn = document.getElementById("btn-terminal-stop-upload");
    if (stopBtn) stopBtn.style.display = "inline-flex";

    try {
        const res = await fetch(`/api/brands/${brandId}/upload`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ video_path, title, sound, timestamp })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to start upload");
        appendTerminalLine(`\n[+] ${data.message}\n`, "sys");
        fetchBrands();
    } catch (err) {
        appendTerminalLine(`[ERROR] ${err.message}`, "err");
    }
}

function openTerminal(brand) {
    currentTerminalBrand = brand;
    const modal = document.getElementById("modal-terminal");
    document.getElementById("terminal-brand-title").textContent = `Live Output - ${brand.name} (${brand.container_name || brand.brand_id})`;
    modal.classList.add("active");

    const stopBtn = document.getElementById("btn-terminal-stop-upload");
    if (stopBtn) {
        stopBtn.style.display = brand.is_uploading ? "inline-flex" : "none";
        stopBtn.disabled = false;
    }

    cachedLogs.live = [];

    // Reset search input
    const searchInput = document.getElementById("terminal-search-input");
    if (searchInput) searchInput.value = "";
    currentLogSearch = "";
    const clearSearchBtn = document.getElementById("btn-clear-log-search");
    if (clearSearchBtn) clearSearchBtn.style.display = "none";

    renderCurrentLogs();

    if (activeWs) {
        activeWs.close();
    }

    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${location.host}/ws/logs/${brand.brand_id}`;
    activeWs = new WebSocket(wsUrl);

    activeWs.onopen = () => {
        const welcome = `[SYSTEM] Connected to live log broadcaster for ${brand.name} (${brand.brand_id}).\n`;
        cachedLogs.live.push(welcome);
        if (currentLogCategory === "live" || currentLogCategory === "all") {
            appendTerminalLine(welcome, "sys");
        }
    };

    activeWs.onmessage = (event) => {
        cachedLogs.live.push(event.data);
        if (currentLogCategory === "live" || currentLogCategory === "all") {
            const line = event.data;
            if (!currentLogSearch || line.toLowerCase().includes(currentLogSearch)) {
                appendTerminalLine(line);
            }
        }
    };

    activeWs.onerror = () => {
        const err = "[SYSTEM] WebSocket stream disconnected.\n";
        cachedLogs.live.push(err);
        if (currentLogCategory === "live" || currentLogCategory === "all") {
            appendTerminalLine(err, "err");
        }
    };

    activeWs.onclose = () => {
        const closed = "[SYSTEM] WebSocket stream closed.\n";
        cachedLogs.live.push(closed);
        if (currentLogCategory === "live" || currentLogCategory === "all") {
            appendTerminalLine(closed, "sys");
        }
    };

    // Pull container logs snapshot across all categories
    pullContainerLogsSnapshot(brand.brand_id);
}

async function pullContainerLogsSnapshot(brandId) {
    try {
        const res = await fetch(`/api/brands/${brandId}/container-logs`);
        if (!res.ok) return;
        const data = await res.json();

        cachedLogs.morphe = data.morphe_logs || "[No active Morphe logs captured or app is idle]";
        cachedLogs.container = data.container_logs || "[No container logs]";
        cachedLogs.start = data.start_logs || "[No start/boot logs recorded]";
        cachedLogs.all = data.all_logs || data.logs || "";

        renderCurrentLogs();
    } catch (e) {
        console.warn("Could not pull logs snapshot:", e);
    }
}

function renderCurrentLogs() {
    const term = document.getElementById("terminal-output");
    if (!term) return;

    let rawText = "";
    if (currentLogCategory === "morphe") {
        rawText = cachedLogs.morphe;
    } else if (currentLogCategory === "container") {
        rawText = cachedLogs.container;
    } else if (currentLogCategory === "start") {
        rawText = cachedLogs.start;
    } else if (currentLogCategory === "live") {
        rawText = cachedLogs.live.join("");
    } else { // "all"
        rawText = (cachedLogs.all || "") + (cachedLogs.live.length ? "\n\n=== [LIVE STREAM BROADCAST] ===\n" + cachedLogs.live.join("") : "");
    }

    term.innerHTML = "";

    if (!rawText.trim()) {
        const span = document.createElement("span");
        span.className = "term-line sys";
        span.textContent = `[No logs available for ${currentLogCategory.toUpperCase()}]`;
        term.appendChild(span);
        return;
    }

    const lines = rawText.split("\n");
    let matchCount = 0;
    const fragment = document.createDocumentFragment();

    for (const line of lines) {
        if (currentLogSearch && !line.toLowerCase().includes(currentLogSearch)) {
            continue;
        }
        matchCount++;
        const span = document.createElement("span");
        span.className = "term-line";
        if (line.includes("[ERROR]") || line.includes("FATAL") || line.includes("Exception") || line.includes("Error") || line.includes("🛑") || line.includes("fail")) {
            span.classList.add("err");
        } else if (line.includes("[SUCCESS]") || line.includes("READY") || line.includes("✓")) {
            span.classList.add("suc");
        } else if (line.includes("[SYSTEM]") || line.includes("===") || line.includes("[*]")) {
            span.classList.add("sys");
        }
        span.textContent = line + "\n";
        fragment.appendChild(span);
    }

    if (matchCount === 0 && currentLogSearch) {
        const noMatch = document.createElement("span");
        noMatch.className = "term-line sys";
        noMatch.textContent = `[No log lines matching filter: "${currentLogSearch}"]\n`;
        term.appendChild(noMatch);
    } else {
        term.appendChild(fragment);
    }

    if (document.getElementById("chk-auto-scroll").checked) {
        term.scrollTop = term.scrollHeight;
    }
}

function closeTerminal() {
    if (activeWs) {
        activeWs.close();
        activeWs = null;
    }
    currentTerminalBrand = null;
    const stopBtn = document.getElementById("btn-terminal-stop-upload");
    if (stopBtn) stopBtn.style.display = "none";
    const pauseBtn = document.getElementById("btn-terminal-pause-upload");
    if (pauseBtn) pauseBtn.style.display = "none";
    document.getElementById("modal-terminal").classList.remove("active");
}

async function handleStopUpload(brandId) {
    const brand = brandsData.find(b => b.brand_id === brandId) || currentTerminalBrand;
    const brandName = brand ? brand.name : brandId;

    appendTerminalLine(`\n[SYSTEM] 🛑 Stopping upload script immediately for '${brandName}'...\n`, "err");

    const stopBtn = document.getElementById("btn-terminal-stop-upload");
    if (stopBtn) {
        stopBtn.disabled = true;
        stopBtn.textContent = "⏳ Stopping...";
    }

    try {
        const res = await fetch(`/api/brands/${brandId}/stop-upload`, { method: "POST" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to stop upload");
        appendTerminalLine(`[+] ${data.message}\n`, "sys");
    } catch (err) {
        appendTerminalLine(`[ERROR] Failed to stop upload: ${err.message}\n`, "err");
        alert(`Failed to stop upload: ${err.message}`);
    } finally {
        if (stopBtn) {
            stopBtn.disabled = false;
            stopBtn.textContent = "🛑 Stop Upload";
            stopBtn.style.display = "none";
        }
        const pauseBtn = document.getElementById("btn-terminal-pause-upload");
        if (pauseBtn) pauseBtn.style.display = "none";
        fetchBrands();
    }
}

async function handleTogglePauseUpload(brandId) {
    const brand = brandsData.find(b => b.brand_id === brandId) || currentTerminalBrand;
    const brandName = brand ? brand.name : brandId;

    const pauseBtn = document.getElementById("btn-terminal-pause-upload");
    if (pauseBtn) {
        pauseBtn.disabled = true;
    }

    try {
        const res = await fetch(`/api/brands/${brandId}/pause-upload`, { method: "POST" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to toggle pause");

        const stateMsg = data.is_paused ? "PAUSED ⏸" : "RESUMED ▶";
        appendTerminalLine(`[SYSTEM] Upload ${stateMsg} for '${brandName}': ${data.message}\n`, "sys");
    } catch (err) {
        appendTerminalLine(`[ERROR] Failed to toggle upload pause: ${err.message}\n`, "err");
        alert(`Failed to pause/resume upload: ${err.message}`);
    } finally {
        if (pauseBtn) {
            pauseBtn.disabled = false;
        }
        await fetchBrands();
    }
}

function appendTerminalLine(text, customClass = "") {
    const term = document.getElementById("terminal-output");
    const span = document.createElement("span");
    if (customClass) span.className = `term-line ${customClass}`;
    span.textContent = text;
    term.appendChild(span);

    if (document.getElementById("chk-auto-scroll").checked) {
        term.scrollTop = term.scrollHeight;
    }
}

function updateCardState(brandId, state) {
    const card = document.getElementById(`card-${brandId}`);
    if (card) {
        card.className = `brand-card state-${state.toLowerCase()}`;
    }
}

function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
