let bridge = null;

/**
 * Returns a display label for a printer's canal/area column.
 * For specific Bogota areas (TechOps, CPL, TMK, etc.) shows the area.
 * For generic areas ("Oficina Interna", "Oficina Comercial") or null, shows the canal.
 */
function displayCanal(canal, area) {
    const generic = ["Oficina Interna", "Oficina Comercial", "", null, undefined];
    if (area && !generic.includes(area)) return area;
    return canal || "-";
}
let monthChart = null;
let docChart = null;
let latestDashboardData = null;
let isLoggedIn = false;
let isAdminValidated = false;

function callBridge(method, ...args) {
    return new Promise((resolve, reject) => {
        if (!bridge || typeof bridge[method] !== "function") {
            reject(new Error(`Bridge method not available: ${method}`));
            return;
        }

        let settled = false;
        const timer = setTimeout(() => {
            if (settled) return;
            settled = true;
            reject(new Error(`Timeout esperando respuesta de: ${method}`));
        }, 30000);

        try {
            bridge[method](...args, (result) => {
                if (settled) return;
                settled = true;
                clearTimeout(timer);
                resolve(result);
            });
        } catch (error) {
            if (!settled) { settled = true; clearTimeout(timer); reject(error); }
        }
    });
}

function parseResponse(raw) {
    if (raw && typeof raw === "object") {
        return raw;
    }
    try {
        return JSON.parse(raw);
    } catch {
        return {};
    }
}

// Parses "YYYY-MM-DD" or "YYYY-MM-DDTHH:mm:ss" without timezone shift (new Date() treats
// date-only strings as UTC midnight which shifts one day back in UTC-5 Colombia time).
function fmtDate(raw) {
    if (!raw) return "-";
    const s = String(raw).split("T")[0];   // "2026-04-29"
    const [y, m, d] = s.split("-");
    return `${parseInt(d)}/${parseInt(m)}/${y}`;  // "29/4/2026"
}

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// ====== Custom select helpers (replaces native <select> to prevent layout shift in QWebEngineView) ======
function _attachCustomSelItem(wrapper, item) {
    const btn = wrapper.querySelector(".custom-sel-btn");
    const menu = wrapper.querySelector(".custom-sel-menu");
    item.addEventListener("click", (e) => {
        e.stopPropagation();
        wrapper.querySelectorAll(".custom-sel-item").forEach(i => i.classList.remove("selected"));
        item.classList.add("selected");
        btn.dataset.value = item.dataset.value;
        btn.textContent = item.textContent;
        menu.classList.remove("open");
        wrapper.dispatchEvent(new Event("change", { bubbles: true }));
    });
}

function initCustomSels() {
    document.querySelectorAll(".custom-sel").forEach(wrapper => {
        const btn = wrapper.querySelector(".custom-sel-btn");
        const menu = wrapper.querySelector(".custom-sel-menu");
        if (!btn || !menu) return;
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            document.querySelectorAll(".custom-sel-menu").forEach(m => { if (m !== menu) m.classList.remove("open"); });
            menu.classList.toggle("open");
        });
        // Wire up any static items already in the menu (e.g. ip-reg-canal)
        menu.querySelectorAll(".custom-sel-item").forEach(item => _attachCustomSelItem(wrapper, item));
    });
    document.addEventListener("click", () => {
        document.querySelectorAll(".custom-sel-menu").forEach(m => m.classList.remove("open"));
    });
}

function populateCustomSel(id, entries, placeholder) {
    const wrapper = document.getElementById(id);
    if (!wrapper || !wrapper.classList.contains("custom-sel")) return;
    placeholder = placeholder || wrapper.dataset.placeholder || "-- Seleccionar --";
    const btn = wrapper.querySelector(".custom-sel-btn");
    const menu = wrapper.querySelector(".custom-sel-menu");
    btn.dataset.value = "";
    btn.textContent = placeholder;
    menu.innerHTML = "";
    const ph = document.createElement("button");
    ph.type = "button"; ph.className = "custom-sel-item"; ph.dataset.value = ""; ph.textContent = placeholder;
    menu.appendChild(ph);
    entries.forEach(({ value, label }) => {
        const item = document.createElement("button");
        item.type = "button"; item.className = "custom-sel-item"; item.dataset.value = value; item.textContent = label;
        menu.appendChild(item);
    });
    menu.querySelectorAll(".custom-sel-item").forEach(item => _attachCustomSelItem(wrapper, item));
}

function getCustomSelValue(id) {
    const wrapper = document.getElementById(id);
    if (!wrapper || !wrapper.classList.contains("custom-sel")) return "";
    return wrapper.querySelector(".custom-sel-btn")?.dataset.value ?? "";
}

function setCustomSelValue(id, value) {
    const wrapper = document.getElementById(id);
    if (!wrapper || !wrapper.classList.contains("custom-sel")) return;
    const btn = wrapper.querySelector(".custom-sel-btn");
    let found = false;
    wrapper.querySelectorAll(".custom-sel-item").forEach(item => {
        item.classList.remove("selected");
        if (item.dataset.value === value) { item.classList.add("selected"); btn.dataset.value = value; btn.textContent = item.textContent; found = true; }
    });
    if (!found) { btn.dataset.value = ""; btn.textContent = wrapper.dataset.placeholder || "-- Seleccionar --"; }
}
// ====== End custom select helpers ======

function renderMetrics(data) {
    document.getElementById("total-prints").textContent = Number(data.total_impresiones ?? 0).toLocaleString("es-CO");
    document.getElementById("top-user").textContent = data.top_usuario
        ? `${data.top_usuario.usuario} (${Number(data.top_usuario.paginas||0).toLocaleString("es-CO")})`
        : "-";
    document.getElementById("top-office").textContent = data.top_oficina
        ? `${data.top_oficina.oficina} (${Number(data.top_oficina.paginas||0).toLocaleString("es-CO")})`
        : "-";

    const reduction = data.oficina_reduccion;
    document.getElementById("office-reduction").textContent = reduction?.oficina
        ? `${reduction.oficina} (-${Number(reduction.reduccion||0).toLocaleString("es-CO")})`
        : "Sin datos";

    // Nuevas tarjetas de contadores
    const cntMaq = document.getElementById("stat-cnt-maquina");
    const cntProv = document.getElementById("stat-cnt-proveedor");
    const cntMaqPer = document.getElementById("stat-cnt-maquina-periodo");
    if (cntMaq) {
        cntMaq.textContent = data.contador_maquina_total != null
            ? Number(data.contador_maquina_total).toLocaleString("es-CO")
            : "-";
    }
    if (cntMaqPer) {
        cntMaqPer.textContent = data.periodo_excel ? `Periodo: ${data.periodo_excel}` : "";
    }
    if (cntProv) {
        cntProv.textContent = data.contador_proveedor_total != null
            ? Number(data.contador_proveedor_total).toLocaleString("es-CO")
            : "-";
    }
}

function renderRanking(data) {
    const tbody = document.querySelector("#ranking-table tbody");
    if (!tbody) return;
    tbody.innerHTML = "";
    (data.ranking_oficinas || []).forEach((row) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${row.oficina}</td><td>${row.ciudad}</td><td>${Number(row.paginas||0).toLocaleString("es-CO")}</td>`;
        tbody.appendChild(tr);
    });
}

function renderPrinterStatus(data) {
    const serialFilterInput = document.getElementById("serial-filter");
    const filterText = (serialFilterInput?.value || "").trim().toLowerCase();
    const rows = (data.estado_impresoras || []).filter((row) => {
        if (!filterText) return true;
        return String(row.numero_serie || "").toLowerCase().includes(filterText);
    });

    ["#printer-status-table tbody", "#printer-status-table-report tbody"].forEach((selector) => {
        const tbody = document.querySelector(selector);
        if (!tbody) return;
        tbody.innerHTML = "";

        rows.forEach((row) => {
            const tr = document.createElement("tr");
            tr.innerHTML = `<td>${row.numero_serie}</td><td>${row.impresora}</td><td>${row.oficina}</td><td>${row.paginas || 0}</td>`;
            tbody.appendChild(tr);
        });
    });
}

function applyGlobalSerialFilter() {
    const filterText = (document.getElementById("serial-filter")?.value || "").trim().toLowerCase();
    const tables = [
        "#counter-compare-table tbody",
        "#counter-excel-table tbody",
        "#ip-list-table tbody",
    ];

    tables.forEach((selector) => {
        const tbody = document.querySelector(selector);
        if (!tbody) return;
        [...tbody.querySelectorAll("tr")].forEach((tr) => {
            if (!filterText) {
                tr.style.display = "";
                return;
            }
            const rowText = tr.textContent.toLowerCase();
            tr.style.display = rowText.includes(filterText) ? "" : "none";
        });
    });
}

function renderSerialFilterInfo(data) {
    const info = document.getElementById("serial-filter-info");
    if (!info) return;

    const filterText = (document.getElementById("serial-filter")?.value || "").trim().toLowerCase();
    if (!filterText) {
        info.innerHTML = "Escribe una serie para ver informacion relevante.";
        return;
    }

    const estadoRows = data.estado_impresoras || [];
    const matches = estadoRows.filter((row) => String(row.numero_serie || "").toLowerCase().includes(filterText));
    const counterRows = (data.contadores_excel || []).filter((row) => String(row.numero_serie || "").toLowerCase().includes(filterText));
    const compareRows = (data.contadores_comparados || []).filter((row) => String(row.numero_serie || "").toLowerCase().includes(filterText));

    if (!matches.length && !counterRows.length && !compareRows.length) {
        info.innerHTML = `No se encontraron series que coincidan con \"${escapeHtml(filterText)}\".`;
        return;
    }

    const parts = [];
    matches.slice(0, 3).forEach((row) => {
        const serie = escapeHtml(row.numero_serie || "-");
        const impresora = escapeHtml(row.impresora || "-");
        const oficina = escapeHtml(row.oficina || "-");
        const paginas = Number(row.paginas || 0).toLocaleString("es-CO");
        parts.push(`<div><strong>${serie}</strong> | ${impresora} | ${oficina} | ${paginas} pags</div>`);
    });

    if (counterRows.length) {
        const lastCounter = counterRows[0];
        parts.push(`<div>Ultimo contador Excel: ${Number(lastCounter.contador_actual || 0).toLocaleString("es-CO")} (${escapeHtml(lastCounter.fecha || "-")})</div>`);
    }

    if (compareRows.length) {
        const lastCmp = compareRows[0];
        parts.push(`<div>Comparador: prov. ${Number(lastCmp.contador_proveedor || 0).toLocaleString("es-CO")} vs maq. ${Number(lastCmp.contador_maquina || 0).toLocaleString("es-CO")} | error ${Number(lastCmp.porcentaje_error || 0)}%</div>`);
    }

    if (matches.length > 3) {
        parts.push(`<div>+${matches.length - 3} coincidencias mas</div>`);
    }

    info.innerHTML = parts.join("");
}

function renderMaintenance(data) {
    const list = document.getElementById("maintenance-list");
    list.innerHTML = "";
    const rows = data.mantenimiento || [];
    if (!rows.length) {
        const item = document.createElement("li");
        item.className = "list-group-item";
        item.textContent = "No hay alertas de mantenimiento.";
        list.appendChild(item);
        return;
    }

    rows.forEach((row) => {
        const item = document.createElement("li");
        item.className = "list-group-item";
        const prioridad = row.prioridad || "BAJA";
        const prioridadColor = prioridad === "ALTA"
            ? "#e83c6c"
            : (prioridad === "MEDIA" ? "#f59e0b" : "#00a86b");
        const contadorVida = Number(row.contador_vida || 0).toLocaleString("es-CO");
        const hito = Number(row.hito_mantenimiento || 0).toLocaleString("es-CO");
        const restante = Number(row.restante_hito || 0).toLocaleString("es-CO");
        const tonerRestante = Number(row.toner_restante_estimado || 0).toLocaleString("es-CO");
        const alertaToner = row.alerta_toner ? " | Alerta toner cercano" : "";

        item.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;">
                <div>
                    <strong>${row.impresora || "-"}</strong> (${row.numero_serie || "-"}) - ${row.oficina || "-"}
                    <div style="font-size:0.82rem;opacity:0.9;">
                        Modelo ${row.modelo || "M3655idn"} | Contador vida: ${contadorVida} (${row.fuente_contador || "N/A"})
                    </div>
                </div>
                <span style="padding:4px 10px;border-radius:999px;background:${prioridadColor};color:#fff;font-size:0.76rem;font-weight:700;">
                    ${row.estado || "CONTROL"} / ${prioridad}
                </span>
            </div>
            <div style="font-size:0.83rem;margin-top:6px;">
                Hito: ${hito} paginas | Restante: ${restante} | Tipo: ${row.tipo_mantenimiento || "Preventivo"}
            </div>
            <div style="font-size:0.83rem;margin-top:4px;">
                ${row.recomendacion || "Sin recomendacion"}
            </div>
            <div style="font-size:0.8rem;margin-top:4px;opacity:0.88;">
                Toner estimado restante: ${tonerRestante} pags${alertaToner}
            </div>
        `;
        list.appendChild(item);
    });
}

async function cargarMantenimientos(regenerar = false) {
    const list = document.getElementById("maintenance-list");
    const statusEl = document.getElementById("maint-status");
    if (!list) return;

    if (statusEl) statusEl.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Calculando mantenimientos...';
    list.innerHTML = "";

    try {
        if (regenerar) {
            await callBridge("sincronizarMantenimientos", true);
        }

    // Cargar todas las impresoras y los mantenimientos en paralelo
    const [imprRes, maintRes] = await Promise.all([
        callBridge("listarImpresorasIP"),
        callBridge("obtenerMantenimientosVigentes"),
    ]);

    const imprResult   = parseResponse(imprRes);
    const maintResult  = parseResponse(maintRes);

    const todasImpresoras = imprResult.impresoras || [];
    const mantenimientos  = maintResult.mantenimientos || [];

    // Índice: numero_serie → mantenimiento
    const maintMap = {};
    mantenimientos.forEach(m => {
        const key = (m.numero_serie || "").toUpperCase().trim();
        if (!maintMap[key]) maintMap[key] = [];
        maintMap[key].push(m);
    });

    if (statusEl) {
        const conMaint = todasImpresoras.filter(p => maintMap[(p.numero_serie||"").toUpperCase().trim()]).length;
        statusEl.textContent = `${todasImpresoras.length} impresora(s) — ${conMaint} con plan calculado.`;
    }

    if (!todasImpresoras.length) {
        list.innerHTML = '<li class="list-group-item text-muted">Sin impresoras. Ve a Admin → Cargar impresoras base.</li>';
        return;
    }

    todasImpresoras.forEach((p) => {
        const serie = (p.numero_serie || "").toUpperCase().trim();
        const filas = maintMap[serie] || [];
        const toner = p.toner_black_pct;

        const item = document.createElement("li");
        item.className = "list-group-item";

        // Alerta de toner si disponible
        let tonerBadge = "";
        if (toner != null) {
            const tonerNum = Number(toner);
            const tonerColor = tonerNum <= 10 ? "#e83c6c" : tonerNum <= 20 ? "#f59e0b" : "#00a86b";
            tonerBadge = `<span style="padding:2px 8px;border-radius:999px;background:${tonerColor};color:#fff;font-size:0.72rem;font-weight:700;margin-left:6px;">
                Toner ${tonerNum}%</span>`;
        }

        // Alerta 500K
        const contador = p.ultima_lectura != null ? Number(p.ultima_lectura) : null;
        const alert500k = contador != null && contador >= 500000
            ? `<span style="padding:2px 8px;border-radius:999px;background:#7c3aed;color:#fff;font-size:0.72rem;font-weight:700;margin-left:6px;">⚠ +500K</span>`
            : "";

        if (!filas.length) {
            // Sin plan calculado aún
            const contText = contador != null
                ? `<strong>${contador.toLocaleString("es-CO")}</strong> pgs`
                : '<span style="opacity:0.5">Sin correo importado</span>';
            item.innerHTML = `
                <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;">
                    <div>
                        <strong>${escapeHtml(p.nombre || "-")}</strong>
                        <span style="font-size:0.82rem;opacity:0.7;"> (${escapeHtml(p.numero_serie || "-")})</span>
                        &mdash; ${escapeHtml(p.oficina || "-")}
                        ${displayCanal(p.canal, p.area) !== "-" ? `<span style="font-size:0.75rem;opacity:0.8;margin-left:4px;">[${escapeHtml(displayCanal(p.canal, p.area))}]</span>` : ""}
                        ${tonerBadge}${alert500k}
                        <div style="font-size:0.82rem;margin-top:2px;opacity:0.75;">Contador: ${contText}</div>
                    </div>
                    <span style="padding:4px 10px;border-radius:999px;background:#6b7280;color:#fff;font-size:0.75rem;font-weight:600;">SIN PLAN</span>
                </div>`;
        } else {
            filas.forEach((row) => {
                const estado = (row.estado || "CONTROL").toUpperCase();
                const estadoColor = estado === "VENCIDO" ? "#e83c6c"
                    : estado === "PROXIMO" ? "#f59e0b"
                    : estado === "PROGRAMAR" ? "#3b82f6"
                    : "#00a86b";
                const paginas = Number(row.paginas_acumuladas || 0).toLocaleString("es-CO");
                const fecha = fmtDate(row.fecha_recomendacion);
                const desc = row.descripcion || "";
                const hitoMatch = desc.match(/Hito:\s*([\d,]+)/);
                const restanteMatch = desc.match(/Restante:\s*([\d,]+)/);
                const hitoTxt = hitoMatch ? Number(hitoMatch[1].replace(/,/g,"")).toLocaleString("es-CO") : "-";
                const restanteTxt = restanteMatch ? Number(restanteMatch[1].replace(/,/g,"")).toLocaleString("es-CO") : "-";

                item.innerHTML += `
                    <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;">
                        <div>
                            <strong>${escapeHtml(row.impresora || p.nombre || "-")}</strong>
                            <span style="font-size:0.82rem;opacity:0.8;"> (${escapeHtml(p.numero_serie || "-")})</span>
                            &mdash; ${escapeHtml(p.oficina || row.oficina || "-")}
                            ${displayCanal(p.canal, p.area) !== "-" ? `<span style="font-size:0.75rem;opacity:0.8;margin-left:4px;">[${escapeHtml(displayCanal(p.canal, p.area))}]</span>` : ""}
                            ${tonerBadge}${alert500k}
                            <div style="font-size:0.82rem;opacity:0.85;">Contador: <strong>${paginas}</strong> pgs</div>
                        </div>
                        <span style="padding:4px 12px;border-radius:999px;background:${estadoColor};color:#fff;font-size:0.76rem;font-weight:700;white-space:nowrap;">${estado}</span>
                    </div>
                    <div style="font-size:0.83rem;margin-top:6px;">
                        <strong>Tipo:</strong> ${escapeHtml(row.tipo || "-")} &bull;
                        Próx. hito: ${hitoTxt} pgs &bull; Restante: ${restanteTxt} pgs
                    </div>
                    <div style="font-size:0.78rem;margin-top:3px;opacity:0.6;">Calculado: ${fecha}</div>`;
            });
        }

        list.appendChild(item);
    });

    // Alerta global de toner bajo
    verificarAlertas(todasImpresoras);
    } catch (err) {
        if (statusEl) statusEl.textContent = "Error cargando mantenimientos.";
        list.innerHTML = '<li class="list-group-item text-warning">No se pudieron cargar los mantenimientos. Intenta con el botón Actualizar Mantenimientos.</li>';
    }
}

function renderToner(data) {
    const tbody = document.querySelector("#toner-table tbody");
    if (!tbody) return;
    tbody.innerHTML = "";
    ((data.toner && data.toner.mensual) || []).forEach((row) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${row.periodo}</td><td>${Number(row.paginas||0).toLocaleString("es-CO")}</td><td>${row.toner_estimado}</td><td>${Number(row.paginas_restantes_cambio||0).toLocaleString("es-CO")}</td>`;
        tbody.appendChild(tr);
    });
}

function renderCounterComparison(data) {
    const compareBody = document.querySelector("#counter-compare-table tbody");
    if (compareBody) {
        compareBody.innerHTML = "";
        (data.contadores_comparados || []).forEach((row) => {
            const statusClass = row.estado === "OK"
                ? "badge-counter-ok"
                : row.estado === "Revision"
                    ? "badge-counter-review"
                    : "badge-counter-alert";

            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${row.fecha || "-"}</td>
                <td>${row.numero_serie || "-"}</td>
                <td>${row.oficina || "-"}</td>
                <td>${Number(row.contador_proveedor ?? 0).toLocaleString("es-CO")}</td>
                <td>${Number(row.contador_maquina ?? 0).toLocaleString("es-CO")}</td>
                <td>${(row.diferencia > 0 ? "+" : "") + Number(row.diferencia ?? 0).toLocaleString("es-CO")}</td>
                <td>${row.porcentaje_error ?? 0}%</td>
                <td><span class="badge ${statusClass}">${row.estado || "-"}</span></td>
            `;
            compareBody.appendChild(tr);
        });
    }

    const excelBody = document.querySelector("#counter-excel-table tbody");
    if (excelBody) {
        excelBody.innerHTML = "";
        (data.contadores_excel || []).forEach((row) => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${row.fecha || "-"}</td>
                <td>${row.numero_serie || "-"}</td>
                <td>${row.oficina || "-"}</td>
                <td>${Number(row.contador_actual ?? 0).toLocaleString("es-CO")}</td>
            `;
            excelBody.appendChild(tr);
        });
    }
}

function renderCharts(data) {
    if (typeof Chart === "undefined") {
        drawFallbackCharts(data);
        return;
    }

    const monthData = data.mes_vs_mes || [];
    const monthLabels = monthData.map((x) => {
        const d = new Date(`${x.periodo}-01T00:00:00`);
        return Number.isNaN(d.getTime())
            ? x.periodo
            : d.toLocaleDateString("es-CO", { month: "short", year: "numeric" });
    });
    const monthValues = monthData.map((x) => Number(x.paginas || 0));
    const monthRolling = monthData.map((x) => Number(x.media_movil_3m || 0));
    const monthlySummary = data.mensual_resumen || {};
    const avgMonthly = Number(monthlySummary.promedio_mensual || 0).toLocaleString("es-CO", {
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
    });

    const _monthCanvas = document.getElementById("monthChart");
    if (!_monthCanvas) return;
    const _monthSection = _monthCanvas.closest(".view-section");
    if (_monthSection && _monthSection.style.display === "none") return;
    if (monthChart) {
        monthChart.destroy();
    }
    monthChart = new Chart(_monthCanvas, {
        type: "bar",
        data: {
            labels: monthLabels,
            datasets: [
                {
                    type: "bar",
                    label: "Paginas por mes",
                    data: monthValues,
                    backgroundColor: "rgba(0, 85, 164, 0.55)",
                    borderColor: "#0055A4",
                    borderWidth: 1,
                    borderRadius: 6,
                    maxBarThickness: 34,
                },
                {
                    type: "line",
                    label: "Promedio movil 3 meses",
                    data: monthRolling,
                    borderColor: "#E83C6C",
                    backgroundColor: "rgba(232, 60, 108, 0.2)",
                    fill: false,
                    tension: 0.25,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                title: {
                    display: true,
                    text: `Consumo mensual | Promedio: ${avgMonthly} pags`,
                    color: "#d9e7ff",
                    padding: { bottom: 8 },
                },
                legend: { position: "top", labels: { color: "#d9e7ff" } },
                tooltip: {
                    mode: "index",
                    intersect: false,
                    callbacks: {
                        afterBody: (items) => {
                            if (!items.length) return "";
                            const idx = items[0].dataIndex;
                            const row = monthData[idx] || {};
                            const delta = Number(row.delta_paginas || 0);
                            const pct = Number(row.delta_pct || 0);
                            const deltaFmt = `${delta > 0 ? "+" : ""}${delta.toLocaleString("es-CO")}`;
                            const pctFmt = `${pct > 0 ? "+" : ""}${pct}%`;
                            return `Variacion vs mes previo: ${deltaFmt} pags (${pctFmt})`;
                        },
                    },
                },
            },
            scales: {
                x: {
                    ticks: { color: "#d9e7ff" },
                    title: { display: true, text: "Periodo", color: "#d9e7ff" },
                },
                y: {
                    beginAtZero: true,
                    ticks: {
                        color: "#d9e7ff",
                        callback: (v) => Number(v).toLocaleString("es-CO"),
                    },
                    title: { display: true, text: "Paginas impresas", color: "#d9e7ff" },
                },
            },
        },
    });

    const docLabels = (data.documentos || []).map((x) => x.tipo_documento);
    const docValues = (data.documentos || []).map((x) => x.paginas);

    const _docCanvas = document.getElementById("docChart");
    if (!_docCanvas) return;
    if (docChart) {
        docChart.destroy();
    }
    docChart = new Chart(_docCanvas, {
        type: "bar",
        data: {
            labels: docLabels,
            datasets: [{
                label: "Paginas",
                data: docValues,
                backgroundColor: ["#1A2B4A", "#0055A4", "#E83C6C", "#00A86B", "#6b7280"],
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: "top", labels: { color: "#d9e7ff" } },
            },
            scales: {
                x: {
                    ticks: { color: "#d9e7ff" },
                    title: { display: true, text: "Tipo de documento", color: "#d9e7ff" },
                },
                y: {
                    beginAtZero: true,
                    ticks: {
                        color: "#d9e7ff",
                        callback: (v) => Number(v).toLocaleString("es-CO"),
                    },
                    title: { display: true, text: "Paginas", color: "#d9e7ff" },
                },
            },
        },
    });
}

function drawFallbackCharts(data) {
    drawSimpleLine("monthChart", (data.mes_vs_mes || []).map((x) => Number(x.paginas || 0)));
    drawSimpleBars("docChart", (data.documentos || []).map((x) => Number(x.paginas || 0)));
}

function drawSimpleLine(canvasId, values) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    const max = Math.max(...values, 1);
    const stepX = values.length > 1 ? w / (values.length - 1) : w;

    ctx.strokeStyle = "#f59e0b";
    ctx.lineWidth = 2;
    ctx.beginPath();
    values.forEach((v, i) => {
        const x = i * stepX;
        const y = h - ((v / max) * (h - 10)) - 5;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();
}

function drawSimpleBars(canvasId, values) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    const max = Math.max(...values, 1);
    const barW = values.length ? Math.max(6, Math.floor(w / values.length) - 4) : 10;

    values.forEach((v, i) => {
        const x = i * (barW + 4);
        const barH = (v / max) * (h - 10);
        const y = h - barH - 5;
        ctx.fillStyle = "#38bdf8";
        ctx.fillRect(x, y, barW, barH);
    });
}

function updateStatus(message) {
    document.getElementById("load-status").textContent = message;
}

function requireLoginGuard() {
    if (!isLoggedIn) {
        throw new Error("Debes iniciar sesion para usar el aplicativo");
    }
}

function hideLoginOverlay() {
    document.getElementById("login-overlay")?.classList.add("hidden");
}

function _renderContadoresDashboard(printers) {
    const tbody  = document.getElementById("dashboard-counters-body");
    const status = document.getElementById("dashboard-counters-status");
    if (!tbody) return;

    if (!printers.length) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-muted text-center">Sin impresoras registradas. Ve a Contadores → Sincronizar base.</td></tr>`;
        if (status) status.textContent = "";
        return;
    }

    const conDatos = printers.filter(p => p.ultima_lectura != null).length;
    if (status) status.textContent = `${printers.length} impresora(s) — ${conDatos} con contador de correo`;

    tbody.innerHTML = printers.map(p => {
        const contador = p.ultima_lectura != null
            ? `<strong>${Number(p.ultima_lectura).toLocaleString("es-CO")}</strong>`
            : '<span class="text-muted small">Sin correo</span>';
        const fecha = p.ultima_fecha
            ? `<small>${escapeHtml(p.ultima_fecha)}</small>`
            : '<small class="text-muted">-</small>';
        const canalLabel = displayCanal(p.canal, p.area);
        const canal = canalLabel && canalLabel !== "-"
            ? `<span class="badge bg-secondary">${escapeHtml(canalLabel)}</span>`
            : "";
        return `<tr>
            <td>${escapeHtml(p.nombre || "-")} ${canal}</td>
            <td><small class="text-muted">${escapeHtml(p.numero_serie || "-")}</small></td>
            <td>${escapeHtml(p.oficina || "-")}</td>
            <td class="text-end">${contador}</td>
            <td>${fecha}</td>
        </tr>`;
    }).join("");
}

function getCiudadEmail(ciudad, canal) {
    const c = (ciudad || "").toUpperCase().trim()
        .replace(/[ÁÀÂÄ]/g, "A").replace(/[ÉÈÊË]/g, "E")
        .replace(/[ÍÌÎÏ]/g, "I").replace(/[ÓÒÔÖ]/g, "O")
        .replace(/[ÚÙÛÜ]/g, "U").replace(/Ñ/g, "N");
    const isExt = (canal || "").toUpperCase() === "EXTERNO";
    const map = {
        "BARRANQUILLA": "barranquilla",
        "BOGOTA": "bogota",
        "BOGOTA D.C": "bogota",
        "BOGOTA DC": "bogota",
        "CALI": "cali",
        "MEDELLIN": "medellin",
        "CARTAGENA": "cartagena",
        "BUCARAMANGA": "bucaramanga",
        "SOACHA": "soacha",
        "SANTA MARTA": "santamarta",
        "PEREIRA": "pereira",
        "CUCUTA": "cucuta",
    };
    const base = map[c] || c.toLowerCase().replace(/\s+/g, "");
    if (!base) return null;
    return isExt ? `${base}ext@avista.co` : `${base}@avista.co`;
}

function abrirModalToner(printer) {
    const modal = document.getElementById("toner-email-modal");
    if (!modal) return;

    const serie = printer.numero_serie || "-";
    const oficina = printer.oficina || printer.nombre || "-";
    const ciudad = printer.ciudad || "";
    const canal = printer.canal || "INTERNO";
    const toner = printer.toner_black_pct != null ? Number(printer.toner_black_pct) : "?";
    const nivelTexto = toner <= 10 ? "CRÍTICO" : "BAJO";
    const _ccCiudad = getCiudadEmail(ciudad, canal);
    const _ccFijos = ["fidel.salas@avista.co", "julian.blanco@avista.co", "cristhian.bermudez@avista.co"];
    const ccEmail = [_ccCiudad, ..._ccFijos].filter(Boolean).join(",");

    const hoy = new Date();
    const fechaStr = `${hoy.getDate()}/${hoy.getMonth()+1}/${hoy.getFullYear()}`;

    const asunto = `[AVISTA] Alerta de Tóner ${nivelTexto} — Impresora ${serie} — ${oficina}`;
    const cuerpo =
`Estimado equipo de soporte DATECSA,

Por medio del presente correo, les informamos que la impresora registrada en nuestra plataforma presenta un nivel de tóner en estado ${nivelTexto}, lo cual requiere atención prioritaria.

DATOS DE LA IMPRESORA:
  • Número de serie: ${serie}
  • Ubicación / Oficina: ${oficina}${ciudad ? "\n  • Ciudad: " + ciudad : ""}
  • Canal: ${canal}
  • Nivel de tóner actual: ${toner}%
  • Fecha de alerta: ${fechaStr}

Solicitamos amablemente gestionar el reemplazo o recarga del cartucho de tóner a la mayor brevedad posible, con el fin de garantizar la continuidad operativa del equipo.

Quedamos atentos a su confirmación y a la programación de la visita técnica correspondiente.

Atentamente,
Equipo AVISTA Colombia S.A.S.`;

    document.getElementById("toner-email-to").value = "stbogota@datecsa.com";
    document.getElementById("toner-email-cc").value = ccEmail;
    document.getElementById("toner-email-subject").value = asunto;
    document.getElementById("toner-email-body").value = cuerpo;
    document.getElementById("toner-email-subtitle").textContent =
        `Tóner al ${toner}% — Serie: ${serie} | ${oficina}${ciudad ? " · " + ciudad : ""}`;

    modal.style.display = "flex";
}

function cerrarModalToner() {
    const modal = document.getElementById("toner-email-modal");
    if (modal) modal.style.display = "none";
}

function abrirCorreoToner() {
    const to = document.getElementById("toner-email-to").value;
    const cc = document.getElementById("toner-email-cc").value;
    const subject = encodeURIComponent(document.getElementById("toner-email-subject").value);
    const body = encodeURIComponent(document.getElementById("toner-email-body").value);
    const ccParam = cc ? `&cc=${encodeURIComponent(cc)}` : "";
    const url = `mailto:${to}?subject=${subject}${ccParam}&body=${body}`;
    if (bridge && typeof bridge.abrirMailto === "function") {
        bridge.abrirMailto(url, () => {});
    } else {
        window.location.href = url;
    }
    cerrarModalToner();
}

function verificarAlertas(impresoras) {
    const alertBanner = document.getElementById("alert-banner");
    if (!alertBanner) return;
    const items = [];
    impresoras.forEach((p) => {
        const nombre = escapeHtml(p.oficina || p.nombre || p.numero_serie || "-");
        const toner = p.toner_black_pct != null ? Number(p.toner_black_pct) : null;
        const contador = p.ultima_lectura != null ? Number(p.ultima_lectura) : null;
        if (toner != null && toner <= 10) {
            items.push({ html: `⚠ <strong>Tóner CRÍTICO (${toner}%)</strong> — ${nombre} (${escapeHtml(p.numero_serie || "")})`, printer: p });
        } else if (toner != null && toner <= 20) {
            items.push({ html: `🟡 <strong>Tóner bajo (${toner}%)</strong> — ${nombre} (${escapeHtml(p.numero_serie || "")})`, printer: p });
        }
        if (contador != null && contador >= 500000) {
            items.push({ html: `🔔 <strong>500.000+ impresiones</strong> — ${nombre} (${escapeHtml(p.numero_serie || "")}) · Verificar con proveedor`, printer: null });
        }
    });
    if (items.length) {
        alertBanner.innerHTML = items.map((it, i) => {
            const btn = it.printer
                ? `<button class="btn-alerta-toner" onclick='abrirModalToner(${JSON.stringify(it.printer)})'>✉ Notificar proveedor</button>`
                : "";
            return `<div class="alert-item"><span class="alert-txt">${it.html}</span>${btn}</div>`;
        }).join("");
        alertBanner.style.display = "block";
    } else {
        alertBanner.style.display = "none";
    }
}

async function cargarDashboard() {
    if (!bridge) return;

    // Counters load first — instant JOIN from cache table, never blocks on stats
    try {
        const impRes = parseResponse(await callBridge("listarImpresorasIP"));
        const printers = impRes.impresoras || [];
        _renderContadoresDashboard(printers);
        verificarAlertas(printers);
    } catch (_) {
        const tbody = document.getElementById("dashboard-counters-body");
        if (tbody) tbody.innerHTML = `<tr><td colspan="5" class="text-warning text-center">Sin datos de correo aún — importa correos desde Contadores.</td></tr>`;
    }

    // Stats (KPIs, charts) load after — can fail without breaking the counters table
    try {
        const data = parseResponse(await callBridge("generarEstadisticas"));
        if (!data || data.ok === false) {
            updateStatus(data?.mensaje || "Sin datos Excel cargados");
            return;
        }
        latestDashboardData = data;
        renderMetrics(data);
        renderRanking(data);
        renderPrinterStatus(data);
        renderMaintenance(data);
        renderToner(data);
        renderCounterComparison(data);
        renderCharts(data);
        applyGlobalSerialFilter();
        renderSerialFilterInfo(data);
        updateStatus("Actualizado");
    } catch (err) {
        updateStatus("Error cargando estadísticas: " + (err.message || err));
    }
}

function setupSectionNavigation() {
    const links = document.querySelectorAll(".side-link[data-section]");
    const sections = document.querySelectorAll(".view-section");

    links.forEach((link) => {
        link.addEventListener("click", (event) => {
            event.preventDefault();
            const target = link.getAttribute("data-section");

            showSection(target);
        });
    });

    function showSection(target) {
        if (!target) return;

        links.forEach((item) => item.classList.remove("active"));
        const active = [...links].find((item) => item.getAttribute("data-section") === target);
        active?.classList.add("active");

        sections.forEach((section) => {
            const visible = section.getAttribute("data-section") === target;
            section.style.display = visible ? "block" : "none";
        });

        // Cargar datos al navegar a mantenimiento
        if (target === "mantenimiento") {
            cargarMantenimientos(false);
        }
        // Poblar selector de impresoras en reportes y estadísticas
        if (target === "reportes") {
            poblarSelectorReportes();
        }
        if (target === "estadisticas") {
            poblarSelectorEstadisticas();
            cargarChartsContadores();
            // Re-renderizar charts de estadísticas si ya hay datos cacheados
            if (latestDashboardData) {
                setTimeout(() => renderCharts(latestDashboardData), 80);
            }
        }
        if (target === "contadores") {
            cargarListaIP();
            cargarPeriodosComparativos();
            // Auto-cargar comparativos del mes actual al entrar a Contadores
            setTimeout(async () => {
                const periodoActual = new Date().toISOString().slice(0, 7); // YYYY-MM
                const r = parseResponse(await callBridge("listarComparativosPeriodo", periodoActual));
                const wrap = document.getElementById("comparativos-wrap");
                const tbody = document.getElementById("comparativos-body");
                const statusEl = document.getElementById("comparativos-status");
                if (r.ok && r.comparativos && r.comparativos.length > 0) {
                    if (statusEl) statusEl.textContent = `Comparativos ${periodoActual}: ${r.comparativos.length} impresoras`;
                    tbody.innerHTML = r.comparativos.map(row => {
                        const sinCorreo = (row.fuente || "").includes("sin_correo");
                        const dif = Number(row.diferencia);
                        const pct = Number(row.porcentaje_error);
                        const difColor = sinCorreo ? "" : (Math.abs(dif) > 500 ? "text-danger fw-bold" : (Math.abs(dif) > 100 ? "text-warning" : "text-success"));
                        const difTxt = sinCorreo ? '<span class="text-muted">Sin lectura</span>' : `${dif > 0 ? "+" : ""}${dif.toLocaleString("es-CO")}`;
                        const maqTxt = sinCorreo ? '<span class="text-muted fst-italic">Sin correo</span>' : Number(row.contador_maquina||0).toLocaleString("es-CO");
                        const pctTxt = sinCorreo ? '<span class="text-muted">—</span>' : `${pct}%`;
                        return `<tr${sinCorreo ? ' class="table-light text-muted"' : ''}>
                            <td class="small">${escapeHtml(row.numero_serie || "-")}</td>
                            <td class="small">${escapeHtml(row.oficina || "-")}</td>
                            <td class="text-end">${Number(row.contador_proveedor||0).toLocaleString("es-CO")}</td>
                            <td class="text-end">${maqTxt}</td>
                            <td class="text-end ${difColor}">${difTxt}</td>
                            <td class="text-end">${pctTxt}</td>
                            <td class="small">${escapeHtml(row.fuente || "-")}</td>
                            <td class="small text-muted">${escapeHtml((row.guardado_en || "").toString().slice(0,10))}</td>
                        </tr>`;
                    }).join("");
                    if (wrap) wrap.style.display = "block";
                } else if (statusEl) {
                    statusEl.textContent = `Sin comparativos guardados para ${periodoActual}. Importa Excel y correo del mismo período.`;
                }
            }, 200);
        }
    }

    return showSection;
}

// ===== GRAFICAS DE CONTADORES =====
let _chartGeneral  = null;
let _chartOficina  = null;
let _impresorasCache = [];   // shared between general and oficina charts

function _chartColors(impresoras) {
    return impresoras.map(p => {
        if (p.ultima_lectura == null) return "rgba(107,114,128,0.5)";
        const t = p.toner_black_pct != null ? Number(p.toner_black_pct) : 100;
        if (t <= 10) return "rgba(232,60,108,0.85)";
        if (t <= 20) return "rgba(245,158,11,0.85)";
        return p.canal === "EXTERNO" ? "rgba(245,158,11,0.75)" : "rgba(59,130,246,0.85)";
    });
}

function _makeBarOptions(lista) {
    return {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
            tooltip: {
                callbacks: {
                    title: (items) => {
                        const p = lista[items[0].dataIndex];
                        return `${p.nombre || p.numero_serie} — ${p.oficina || ""}`;
                    },
                    label: (item) => {
                        return ` Contador: ${Number(item.raw).toLocaleString("es-CO")}`;
                    },
                    afterLabel: (item) => {
                        const p = lista[item.dataIndex];
                        const lines = [`Serie: ${p.numero_serie || "-"}`, `Canal: ${p.canal || "-"}`];
                        if (p.toner_black_pct != null) lines.push(`Toner: ${p.toner_black_pct}%`);
                        if (p.ultima_fecha) lines.push(`Lectura: ${p.ultima_fecha}`);
                        return lines;
                    }
                }
            }
        },
        scales: {
            y: {
                beginAtZero: true,
                ticks: { callback: v => v.toLocaleString("es-CO"), font: { size: 11 } },
                grid: { color: "rgba(148,163,184,0.12)" }
            },
            x: {
                ticks: { font: { size: 10 }, maxRotation: 40, minRotation: 20 },
                grid: { display: false }
            }
        }
    };
}

function renderChartContadoresGeneral(impresoras) {
    const wrap = document.getElementById("chart-general-wrap");
    const canvas = document.getElementById("chart-contadores-general");
    const statusEl = document.getElementById("chart-general-status");
    if (!canvas || !wrap) return;
    // No renderizar si la SECCIÓN PADRE está oculta (no el wrap interno)
    const section = canvas.closest(".view-section");
    if (section && section.style.display === "none") return;

    const lista = impresoras.filter(p => p.ultima_lectura != null);
    if (!lista.length) {
        if (statusEl) statusEl.textContent = "Sin datos de contador. Importe correos desde Contadores.";
        wrap.style.minHeight = "0";
        return;
    }

    const horizontal = lista.length > 8;
    // Horizontal bars: ~34px per row; vertical: fixed 280px
    const height = horizontal ? Math.max(280, lista.length * 34) : 280;
    wrap.style.height = height + "px";

    const labels = lista.map(p => `${p.nombre || p.numero_serie}`);
    const values = lista.map(p => Number(p.ultima_lectura));
    const colors = _chartColors(lista);
    if (_chartGeneral) { _chartGeneral.destroy(); _chartGeneral = null; }
    _chartGeneral = new Chart(canvas, {
        type: "bar",
        data: {
            labels,
            datasets: [{ label: "Contador", data: values, backgroundColor: colors, borderRadius: 4 }]
        },
        options: {
            indexAxis: horizontal ? "y" : "x",
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        title: (items) => {
                            const p = lista[items[0].dataIndex];
                            return `${p.nombre || p.numero_serie} — ${p.oficina || ""}`;
                        },
                        label: (item) => ` Contador: ${Number(item.raw).toLocaleString("es-CO")}`,
                        afterLabel: (item) => {
                            const p = lista[item.dataIndex];
                            const lines = [`Serie: ${p.numero_serie || "-"}`, `Canal: ${p.canal || "-"}`];
                            if (p.toner_black_pct != null) lines.push(`Toner: ${p.toner_black_pct}%`);
                            if (p.ultima_fecha) lines.push(`Lectura: ${p.ultima_fecha}`);
                            return lines;
                        }
                    }
                }
            },
            scales: horizontal ? {
                x: { beginAtZero: true, ticks: { callback: v => v.toLocaleString("es-CO"), font: { size: 11 } }, grid: { color: "rgba(148,163,184,0.12)" } },
                y: { ticks: { font: { size: 10 } }, grid: { display: false } }
            } : {
                y: { beginAtZero: true, ticks: { callback: v => v.toLocaleString("es-CO"), font: { size: 11 } }, grid: { color: "rgba(148,163,184,0.12)" } },
                x: { ticks: { font: { size: 10 }, maxRotation: 40 }, grid: { display: false } }
            }
        }
    });
    if (statusEl) statusEl.textContent = `${lista.length} impresoras con datos. Rojo = toner bajo.`;
}

function renderChartContadoresOficina(impresoras, oficina) {
    const wrap = document.getElementById("chart-oficina-wrap");
    const canvas = document.getElementById("chart-contadores-oficina");
    const statusEl = document.getElementById("chart-oficina-status");
    if (!canvas || !wrap) return;
    // Mostrar el wrap ANTES de verificar visibilidad de la sección
    wrap.style.display = "block";
    const section = canvas.closest(".view-section");
    if (section && section.style.display === "none") return;

    const lista = impresoras.filter(p => (p.oficina || "").toLowerCase() === (oficina || "").toLowerCase());
    if (!lista.length) {
        if (statusEl) statusEl.textContent = `Sin impresoras registradas para "${oficina}".`;
        wrap.style.display = "none";
        return;
    }

    const height = Math.max(220, lista.length * 40);
    wrap.style.height = height + "px";
    wrap.style.display = "block";

    const labels = lista.map(p => `${p.nombre || p.numero_serie}`);
    const values = lista.map(p => p.ultima_lectura != null ? Number(p.ultima_lectura) : 0);
    const colors = _chartColors(lista);

    if (_chartOficina) { _chartOficina.destroy(); _chartOficina = null; }
    _chartOficina = new Chart(canvas, {
        type: "bar",
        data: {
            labels,
            datasets: [{ label: `Contadores — ${oficina}`, data: values, backgroundColor: colors, borderRadius: 4 }]
        },
        options: _makeBarOptions(lista)
    });

    const conDatos = lista.filter(p => p.ultima_lectura != null).length;
    if (statusEl) statusEl.textContent = `${lista.length} impresora(s) en ${oficina}${conDatos < lista.length ? ` — ${lista.length - conDatos} sin contador importado` : ""}.`;
}

async function cargarChartsContadores() {
    try {
        const result = parseResponse(await callBridge("listarImpresorasIP"));
        _impresorasCache = result.impresoras || [];
        renderChartContadoresGeneral(_impresorasCache);

        const oficinas = [...new Set(_impresorasCache.map(p => p.oficina || "").filter(Boolean))].sort();
        populateCustomSel("chart-oficina-select", oficinas.map(o => ({ value: o, label: o })), "-- Seleccionar oficina --");
        verificarAlertas(_impresorasCache);
    } catch (err) {
        const statusEl = document.getElementById("chart-general-status");
        if (statusEl) statusEl.textContent = "Error cargando datos de contadores.";
    }
}

async function poblarSelectorReportes() {
    const result = parseResponse(await callBridge("listarImpresorasIP"));
    const impresoras = result.impresoras || [];
    const entries = impresoras.filter(p => p.numero_serie).map(p => {
        const cLabel = displayCanal(p.canal, p.area);
        const canal = cLabel && cLabel !== "-" ? ` [${cLabel}]` : "";
        return { value: p.numero_serie, label: `${p.nombre || p.numero_serie}${canal} — ${p.oficina || ""} (${p.numero_serie})` };
    });
    populateCustomSel("report-serial-select", entries, "-- Seleccionar impresora --");
}

async function poblarSelectorEstadisticas() {
    let impresoras = _impresorasCache.length ? _impresorasCache : [];
    if (!impresoras.length) {
        const result = parseResponse(await callBridge("listarImpresorasIP"));
        impresoras = result.impresoras || [];
    }
    const entries = impresoras.filter(p => p.numero_serie).map(p => {
        const label = displayCanal(p.canal, p.area);
        return { value: p.numero_serie, label: `${p.nombre || p.numero_serie} [${label}] — ${p.oficina || ""} (${p.numero_serie})` };
    });
    populateCustomSel("stat-printer-select", entries, "-- Seleccionar impresora --");
}

let _chartPrinterContador = null;
let _chartPrinterToner    = null;

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("btn-chart-oficina")?.addEventListener("click", () => {
        const oficina = getCustomSelValue("chart-oficina-select");
        if (!oficina) {
            const s = document.getElementById("chart-oficina-status");
            if (s) s.textContent = "Selecciona una oficina primero.";
            return;
        }
        renderChartContadoresOficina(_impresorasCache, oficina);
    });

    document.getElementById("btn-stat-printer")?.addEventListener("click", async () => {
        const serial     = getCustomSelValue("stat-printer-select");
        const statusEl   = document.getElementById("stat-printer-status");
        const chartsWrap = document.getElementById("stat-printer-charts");
        if (!serial) {
            if (statusEl) statusEl.textContent = "Selecciona una impresora primero.";
            return;
        }
        if (statusEl) statusEl.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Cargando historial...';
        if (chartsWrap) chartsWrap.style.display = "none";

        const result = parseResponse(await callBridge("obtenerHistoricoImpresora", serial));
        if (!result.ok) {
            if (statusEl) statusEl.textContent = result.mensaje || "Error al cargar historial.";
            return;
        }
        const hist = result.historial || [];
        if (!hist.length) {
            if (statusEl) statusEl.textContent = "Sin datos de historial para esta impresora.";
            return;
        }
        const info  = result.info || {};
        const label = displayCanal(info.canal, info.area);
        if (statusEl) statusEl.textContent = `${info.nombre || serial} [${label}] — ${info.oficina || ""} | ${hist.length} lecturas`;

        const labels    = hist.map(r => r.fecha || r.periodo || "-");
        const contVals  = hist.map(r => r.contador_efectivo ?? null);
        const tonerVals = hist.map(r => r.toner_black_pct ?? null);

        if (_chartPrinterContador) { _chartPrinterContador.destroy(); _chartPrinterContador = null; }
        if (_chartPrinterToner)    { _chartPrinterToner.destroy();    _chartPrinterToner    = null; }

        const canvasCnt = document.getElementById("chart-printer-contador");
        if (canvasCnt) {
            _chartPrinterContador = new Chart(canvasCnt, {
                type: "line",
                data: {
                    labels,
                    datasets: [{
                        label: "Contador Máquina",
                        data: contVals,
                        borderColor: "rgba(59,130,246,1)",
                        backgroundColor: "rgba(59,130,246,0.12)",
                        fill: true,
                        tension: 0.35,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        spanGaps: true,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: { callbacks: { label: i => ` ${Number(i.raw).toLocaleString("es-CO")} pgs` } }
                    },
                    scales: {
                        x: { ticks: { maxRotation: 45, font: { size: 10 } }, grid: { color: "rgba(148,163,184,0.1)" } },
                        y: { beginAtZero: false, ticks: { callback: v => v.toLocaleString("es-CO") }, grid: { color: "rgba(148,163,184,0.1)" } }
                    }
                }
            });
        }

        const canvasToner = document.getElementById("chart-printer-toner");
        if (canvasToner) {
            _chartPrinterToner = new Chart(canvasToner, {
                type: "bar",
                data: {
                    labels,
                    datasets: [{
                        label: "Tóner %",
                        data: tonerVals,
                        backgroundColor: tonerVals.map(v =>
                            v == null ? "rgba(107,114,128,0.35)" :
                            v <= 10   ? "rgba(239,68,68,0.85)"   :
                            v <= 20   ? "rgba(245,158,11,0.85)"  :
                                        "rgba(34,197,94,0.80)"
                        ),
                        borderRadius: 4,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: { callbacks: { label: i => ` ${i.raw ?? "-"}%` } }
                    },
                    scales: {
                        x: { ticks: { maxRotation: 45, font: { size: 10 } }, grid: { display: false } },
                        y: { min: 0, max: 100, ticks: { callback: v => v + "%" }, grid: { color: "rgba(148,163,184,0.1)" } }
                    }
                }
            });
        }

        const tbody = document.getElementById("printer-hist-body");
        if (tbody) {
            tbody.innerHTML = [...hist].reverse().map(r => {
                const t = r.toner_black_pct;
                const badge = t != null
                    ? `<span class="badge ${t <= 10 ? "bg-danger" : t <= 20 ? "bg-warning text-dark" : "bg-success"}">${t}%</span>`
                    : '<span class="text-muted">-</span>';
                return `<tr>
                    <td>${escapeHtml(r.fecha || r.periodo || "-")}</td>
                    <td class="text-end fw-bold">${r.contador_efectivo != null ? Number(r.contador_efectivo).toLocaleString("es-CO") : "-"}</td>
                    <td class="text-end">${r.printed_total != null ? Number(r.printed_total).toLocaleString("es-CO") : "-"}</td>
                    <td class="text-center">${badge}</td>
                </tr>`;
            }).join("");
        }

        if (chartsWrap) chartsWrap.style.display = "block";
    });
});

function mostrarOverlay(msg) {
    const el = document.getElementById("loading-overlay");
    const msgEl = document.getElementById("loading-msg");
    if (!el) return;
    if (msgEl) msgEl.textContent = msg || "Procesando...";
    el.style.display = "flex";
}

function ocultarOverlay() {
    const el = document.getElementById("loading-overlay");
    if (el) el.style.display = "none";
}

// ===== GESTION DE IMPRESORAS (por correo, identificadas por serial) =====

async function cargarListaIP() {
    const result = parseResponse(await callBridge("listarImpresorasIP"));
    const listBody = document.getElementById("ip-list-body");
    listBody.innerHTML = "";

    const impresoras = result.impresoras || [];
    if (impresoras.length === 0) {
        listBody.innerHTML = '<tr><td colspan="9" class="text-center text-muted">Sin impresoras registradas. Usa "Sincronizar base".</td></tr>';
        return;
    }

    // Si todas tienen canal nulo, sincronizar base automáticamente
    const todasSinCanal = impresoras.every(p => !p.canal);
    if (todasSinCanal) {
        const syncStatus = document.getElementById("base-sync-status");
        if (syncStatus) { syncStatus.textContent = "Sincronizando datos base..."; syncStatus.style.display = "block"; }
        await callBridge("cargarImpresorasBase");
        if (syncStatus) { syncStatus.textContent = "Base sincronizada. Canales actualizados."; }
        const r2 = parseResponse(await callBridge("listarImpresorasIP"));
        impresoras.length = 0;
        (r2.impresoras || []).forEach(p => impresoras.push(p));
    }

    impresoras.forEach((p) => {
        const serie = p.numero_serie || "";
        const canalBadge = p.canal
            ? `<span class="badge bg-secondary">${escapeHtml(p.canal)}</span>`
            : '<span class="text-muted">-</span>';
        const contadorCell = p.ultima_lectura != null
            ? `<strong>${Number(p.ultima_lectura).toLocaleString("es-CO")}</strong>`
            : '<span class="text-muted small">Sin datos</span>';
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${escapeHtml(p.nombre || "-")}</td>
            <td>${escapeHtml(p.oficina || "-")}</td>
            <td>${canalBadge}</td>
            <td class="text-monospace small">${escapeHtml(serie)}</td>
            <td>${contadorCell}</td>
            <td class="small text-muted">${escapeHtml(p.ultima_fecha || "-")}</td>
            <td>
                <button class="btn btn-outline-secondary btn-sm me-1 btn-ip-history"
                    data-serial="${escapeHtml(serie)}"
                    data-nombre="${escapeHtml(p.nombre || serie)}">Historial</button>
                <button class="btn btn-outline-danger btn-sm btn-ip-delete"
                    data-serial="${escapeHtml(serie)}"
                    data-nombre="${escapeHtml(p.nombre || serie)}">Eliminar</button>
            </td>
        `;
        listBody.appendChild(tr);
    });

    listBody.querySelectorAll(".btn-ip-history").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const rowSerie = btn.getAttribute("data-serial");
            const rowNombre = btn.getAttribute("data-nombre");
            document.getElementById("ip-history-title").textContent = `${rowNombre} (${rowSerie})`;
            const r = parseResponse(await callBridge("historialLecturasIP", rowSerie));
            const hbody = document.getElementById("ip-history-body");
            hbody.innerHTML = "";
            const rows = r.historial || [];
            if (rows.length === 0) {
                hbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Sin lecturas de correo para esta impresora.</td></tr>';
            } else {
                rows.forEach((row) => {
                    const tr = document.createElement("tr");
                    tr.innerHTML = `
                        <td>${row.fecha || "-"}</td>
                        <td>${row.contador_efectivo != null ? Number(row.contador_efectivo).toLocaleString("es-CO") : "-"}</td>
                        <td>${row.printed_total != null ? Number(row.printed_total).toLocaleString("es-CO") : "-"}</td>
                        <td>${row.scanned_total != null ? Number(row.scanned_total).toLocaleString("es-CO") : "-"}</td>
                        <td>${row.toner_black_pct != null ? row.toner_black_pct + "%" : "-"}</td>
                        <td class="small text-muted">${escapeHtml(row.asunto || "-")}</td>
                    `;
                    hbody.appendChild(tr);
                });
            }
            document.getElementById("ip-history-panel").style.display = "block";
        });
    });

    listBody.querySelectorAll(".btn-ip-delete").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const rowSerie = btn.getAttribute("data-serial");
            const rowNombre = btn.getAttribute("data-nombre");
            if (!confirm(`¿Eliminar ${rowNombre} (${rowSerie}) del listado?`)) return;
            const r = parseResponse(await callBridge("eliminarImpresoraIP", rowSerie));
            document.getElementById("ip-list-status").textContent = r.mensaje || "Eliminado";
            cargarListaIP();
        });
    });

    applyGlobalSerialFilter();
}

async function cargarPeriodosComparativos() {
    const r = parseResponse(await callBridge("listarPeriodosComparativos"));
    populateCustomSel("comparativos-periodo-sel", (r.periodos || []).map(p => ({ value: p, label: p })), "-- Periodo --");
}

function bindEvents() {
    initCustomSels();

    // When a printer is selected from the custom dropdown, copy its serial to the manual input
    document.getElementById("report-serial-select")?.addEventListener("change", () => {
        const manual = document.getElementById("report-serial");
        if (manual) manual.value = getCustomSelValue("report-serial-select");
    });

    const showSection = setupSectionNavigation();

    function isValidPeriod(value) {
        return /^\d{4}-\d{2}$/.test((value || "").trim());
    }

    function defaultPeriodFromDashboard() {
        const periods = (latestDashboardData?.mes_vs_mes || []).map((row) => String(row.periodo || "")).filter(Boolean);
        if (!periods.length) return "";
        return periods[periods.length - 1];
    }

    function getGeneralReportPeriod() {
        const periodInput = document.getElementById("report-general-period");
        const typed = periodInput?.value.trim() || "";
        if (typed) return typed;
        const fallback = defaultPeriodFromDashboard();
        if (periodInput && fallback) periodInput.value = fallback;
        return fallback;
    }

    const LOGO_ORIGINAL = "assets/avista%20logo.png";
    const LOGO_DARK     = "assets/avista-logo-dark.png";

    function syncThemeButtonLabel() {
        const btn = document.getElementById("btn-theme-toggle");
        if (!btn) return;
        const isLight = document.body.classList.contains("light-theme");
        btn.textContent = isLight ? "☽ Modo oscuro" : "☀ Modo claro";
    }

    function syncLogos() {
        const isLight = document.body.classList.contains("light-theme");
        const brandLogo = document.querySelector(".brand-logo");
        if (brandLogo) {
            brandLogo.src = isLight ? LOGO_ORIGINAL : LOGO_DARK;
        }
    }

    document.getElementById("btn-theme-toggle")?.addEventListener("click", () => {
        document.body.classList.toggle("light-theme");
        syncThemeButtonLabel();
        syncLogos();
    });

    syncThemeButtonLabel();
    syncLogos();

    document.getElementById("btn-load").addEventListener("click", async () => {
        const path = await callBridge("openExcelDialog");
        if (!path) return;
        mostrarOverlay("Cargando datos del archivo Excel...");
        const result = parseResponse(await callBridge("cargarExcel", path));
        ocultarOverlay();
        if (result.ok === false) {
            updateStatus(result.mensaje || "Error en carga");
            return;
        }

        const insertados = result.insertados ?? 0;
        const duplicados = result.duplicados ?? 0;
        const baseMsg = result.mensaje || "Carga completada";
        updateStatus(`${baseMsg} | Insertados: ${insertados} | Duplicados: ${duplicados}`);
        await cargarDashboard();

        // Auto-comparativo: Excel vs correo para el mes actual
        if (insertados > 0) {
            const cmp = parseResponse(await callBridge("autoCompararMesActual"));
            if (cmp.ok && cmp.comparados > 0) {
                updateStatus(
                    `${baseMsg} | Insertados: ${insertados} | ` +
                    `Auto-comparativo ${cmp.periodo}: ${cmp.comparados} impresoras comparadas, ` +
                    `${cmp.sin_correo} sin correo registrado`
                );
            }
        }
    });

    document.getElementById("serial-filter")?.addEventListener("input", () => {
        if (latestDashboardData) {
            renderPrinterStatus(latestDashboardData);
            renderSerialFilterInfo(latestDashboardData);
        }
        applyGlobalSerialFilter();
    });

    document.getElementById("btn-refresh").addEventListener("click", cargarDashboard);

    document.getElementById("btn-clean").addEventListener("click", async () => {
        const result = parseResponse(await callBridge("limpiarRegistros"));
        updateStatus(result.mensaje || "Registros limpiados");
        await cargarDashboard();
    });

    document.getElementById("btn-compare").addEventListener("click", async () => {
        const serie = document.getElementById("serial-input").value.trim();
        const periodo = document.getElementById("compare-period")?.value.trim();
        const proveedor = Number(document.getElementById("provider-counter").value);
        const maquinaTxt = document.getElementById("machine-counter").value.trim();
        const resultEl = document.getElementById("counter-result");
        const wrapEl = document.getElementById("counter-verdict-wrap");

        if (!serie || !Number.isFinite(proveedor) || proveedor < 0) {
            resultEl.textContent = "Ingresa serie y contador de proveedor validos.";
            wrapEl.style.display = "none";
            return;
        }

        let result = {};
        let maquina = Number(maquinaTxt || 0);

        if (periodo) {
            result = parseResponse(await callBridge("compararContadoresMensual", serie, periodo, proveedor));
            maquina = Number(result.contador_maquina ?? 0);
        } else {
            if (!maquinaTxt || !Number.isFinite(maquina) || maquina < 0) {
                resultEl.textContent = "Ingresa contador de maquina o usa el campo Periodo (YYYY-MM).";
                wrapEl.style.display = "none";
                return;
            }
            result = parseResponse(await callBridge("compararContadores", serie, proveedor, maquina));
        }

        if (result.ok === false) {
            resultEl.textContent = result.mensaje || "Error en comparacion";
            wrapEl.style.display = "none";
            return;
        }

        const diff = result.diferencia ?? (proveedor - maquina);
        const pct = parseFloat(result.porcentaje_error ?? 0);
        const isOk = Math.abs(pct) <= 5;

        // Serie label
        document.getElementById("counter-verdict-serie").textContent =
            periodo ? `Serie: ${serie} | Periodo: ${periodo}` : (serie ? `Serie: ${serie}` : "Sin número de serie");

        // Verdict badge
        const badgeEl = document.getElementById("counter-verdict-badge");
        badgeEl.innerHTML = isOk
            ? `<span class="verdict-badge-ok">✓ COINCIDE</span>`
            : `<span class="verdict-badge-alert">✗ NO COINCIDE</span>`;

        // Stats
        document.getElementById("c-prov").textContent = Number(proveedor).toLocaleString("es-CO");
        document.getElementById("c-maq").textContent = Number(maquina).toLocaleString("es-CO");
        document.getElementById("c-diff").textContent =
            (diff > 0 ? "+" : "") + Number(diff).toLocaleString("es-CO");
        document.getElementById("c-pct").textContent = `${pct}%`;

        // Color the diff box
        const diffBox = document.getElementById("c-diff-box");
        diffBox.classList.toggle("ok", isOk);

        wrapEl.style.display = "block";
        if (periodo) {
            const vol = Number(result.volumen_mes || 0).toLocaleString("es-CO");
            const reg = Number(result.registros_mes || 0).toLocaleString("es-CO");
            const fuente = result.fuente_maquina || "Lectura mensual";
            resultEl.textContent = `Maquina (${periodo}): ${maquina.toLocaleString("es-CO")} | Volumen mes: ${vol} | Registros: ${reg} | Fuente: ${fuente}`;
        } else {
            resultEl.textContent = "";
        }
    });

    function renderReportComparativo(result) {
        const wrap = document.getElementById("report-detail-wrap");
        const resultEl = document.getElementById("report-result");
        if (!wrap) return;
        if (result.ok === false || !result.comparativo) {
            wrap.style.display = "none";
            resultEl.textContent = result.mensaje || "Error generando reporte";
            return;
        }

        const rows = result.comparativo || [];

        // Sin datos en ninguna fuente → mensaje claro
        if (rows.length === 0) {
            wrap.style.display = "none";
            resultEl.innerHTML = `<span style="color:#f59e0b">⚠ Sin registros para los períodos seleccionados.<br>
                Verifica que hayas importado datos (Excel o correo IMAP) para esos meses.</span>`;
            return;
        }

        // Indicador de fuente de datos
        const fuente = result.fuente || "excel";
        const fuenteBadge = fuente === "correo"
            ? `<span style="background:#0055A4;color:#fff;padding:2px 8px;border-radius:999px;font-size:0.75rem;margin-left:8px;">📧 Datos desde Correo</span>`
            : `<span style="background:#00A86B;color:#fff;padding:2px 8px;border-radius:999px;font-size:0.75rem;margin-left:8px;">📊 Datos desde Excel</span>`;

        const delta = result.delta || {};
        const fmt = (v) => v != null ? Number(v).toLocaleString("es-CO") : "—";
        const sign = (v) => v == null ? "—" : (v > 0 ? `+${fmt(v)}` : fmt(v));

        // Period rows
        const rowsHtml = rows.map(r => `
            <tr>
                <td><strong>${r.periodo || "—"}</strong></td>
                <td>${r.oficina || "—"}</td>
                <td>${r.ciudad || "—"}</td>
                <td>${r.impresora || "—"}</td>
                <td class="text-end"><strong>${fmt(r.volumen)}</strong></td>
                <td class="text-end">${fmt(r.paginas_mono)}</td>
                <td class="text-end">${fmt(r.paginas_color)}</td>
                <td class="text-end">${fmt(r.ultimo_contador)}</td>
                <td class="text-end">${fmt(r.dias_activos)}</td>
                <td class="text-end">${fmt(r.total_trabajos)}</td>
            </tr>`).join("");

        // Delta section
        let deltaHtml = "";
        if (delta && delta.volumen_a != null) {
            const variacion = delta.variacion ?? 0;
            const isRed = variacion > 0;
            const tendClass = isRed ? "text-danger" : "text-success";
            const tendIcon = variacion > 0 ? "↑" : (variacion < 0 ? "↓" : "=");
            const verdict = variacion < 0
                ? "↓ REDUCCIÓN DE VOLUMEN — Tendencia favorable"
                : (variacion > 0 ? "↑ AUMENTO DE VOLUMEN — Revisar uso" : "= SIN VARIACIÓN");
            const verdictBg = variacion <= 0 ? "bg-success" : "bg-danger";

            deltaHtml = `
            <div class="mt-3">
              <h6 class="fw-bold mb-2" style="color:var(--azul-profundo)">Análisis Comparativo entre Períodos</h6>
              <div class="table-responsive mb-2">
                <table class="table table-sm table-bordered align-middle mb-0" id="report-delta-table">
                  <thead style="background:#1A2B4A;color:#fff">
                    <tr>
                      <th>Indicador</th>
                      <th class="text-end">${result.periodo_a}</th>
                      <th class="text-end">${result.periodo_b}</th>
                      <th class="text-end">Variación</th>
                      <th class="text-end">% Cambio</th>
                      <th class="text-center">Tendencia</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Total Páginas</td>
                      <td class="text-end">${fmt(delta.volumen_a)}</td>
                      <td class="text-end">${fmt(delta.volumen_b)}</td>
                      <td class="text-end fw-bold ${tendClass}">${sign(delta.variacion)}</td>
                      <td class="text-end fw-bold ${tendClass}">${sign(delta.porcentaje_cambio)}%</td>
                      <td class="text-center fw-bold ${tendClass}">${tendIcon} ${delta.tendencia}</td>
                    </tr>
                    <tr>
                      <td>Contador Impresora</td>
                      <td class="text-end">${fmt(delta.contador_a)}</td>
                      <td class="text-end">${fmt(delta.contador_b)}</td>
                      <td class="text-end fw-bold">${sign(delta.variacion_contador)}</td>
                      <td class="text-end">—</td>
                      <td class="text-center">—</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="p-2 rounded text-white text-center fw-bold ${verdictBg}">${verdict}</div>
            </div>`;
        }

        document.getElementById("report-detail-inner").innerHTML = `
            <div class="mb-2">${fuenteBadge}</div>
            <div class="table-responsive">
              <table class="table table-sm table-hover align-middle mb-0" id="report-comp-table">
                <thead style="background:#1A2B4A;color:#fff">
                  <tr>
                    <th>Periodo</th><th>Oficina</th><th>Ciudad</th><th>Impresora</th>
                    <th class="text-end">Total Pags</th><th class="text-end">Mono</th>
                    <th class="text-end">Color</th><th class="text-end">Contador</th>
                    <th class="text-end">Días Activos</th><th class="text-end">Trabajos</th>
                  </tr>
                </thead>
                <tbody>${rowsHtml}</tbody>
              </table>
            </div>
            ${deltaHtml}`;

        wrap.style.display = "block";
        resultEl.textContent = "";
    }

    document.getElementById("btn-report").addEventListener("click", async () => {
        const serie = document.getElementById("report-serial").value.trim();
        const a = document.getElementById("period-a").value.trim();
        const b = document.getElementById("period-b").value.trim();
        const resultEl = document.getElementById("report-result");

        if (!serie) {
            resultEl.textContent = "Ingresa un numero de serie para el comparativo.";
            return;
        }
        if (!isValidPeriod(a) || !isValidPeriod(b)) {
            resultEl.textContent = "Los periodos deben tener formato YYYY-MM.";
            return;
        }

        resultEl.textContent = "Generando comparativo...";
        const result = parseResponse(await callBridge("generarReporteMensual", serie, a, b));
        renderReportComparativo(result);
    });

    document.getElementById("btn-export-xlsx").addEventListener("click", async () => {
        const serie = document.getElementById("report-serial").value.trim();
        const a = document.getElementById("period-a").value.trim();
        const b = document.getElementById("period-b").value.trim();
        if (!serie || !isValidPeriod(a) || !isValidPeriod(b)) {
            document.getElementById("report-result").textContent = "Completa serie y periodos validos (YYYY-MM).";
            return;
        }
        const result = parseResponse(await callBridge("exportarReporteExcel", serie, a, b));
        document.getElementById("report-result").textContent = result.ok === false
            ? (result.mensaje || "Error exportando Excel")
            : `Excel exportado: ${result.archivo}`;
    });

    document.getElementById("btn-export-pdf").addEventListener("click", async () => {
        const serie = document.getElementById("report-serial").value.trim();
        const a = document.getElementById("period-a").value.trim();
        const b = document.getElementById("period-b").value.trim();
        if (!serie || !isValidPeriod(a) || !isValidPeriod(b)) {
            document.getElementById("report-result").textContent = "Completa serie y periodos validos (YYYY-MM).";
            return;
        }
        const result = parseResponse(await callBridge("exportarReportePDF", serie, a, b));
        document.getElementById("report-result").textContent = result.ok === false
            ? (result.mensaje || "Error exportando PDF")
            : `PDF exportado: ${result.archivo}`;
    });

    function renderGeneralReport(result) {
        const wrap = document.getElementById("report-general-wrap");
        const resultEl = document.getElementById("report-general-result");
        const detailBody = document.getElementById("report-general-detail-body");

        if (!wrap || !resultEl || !detailBody) return;

        if (result.ok === false) {
            wrap.style.display = "none";
            resultEl.textContent = result.mensaje || "No fue posible generar reporte general.";
            return;
        }

        const detail = result.detalle_impresoras || [];
        const fmt = (v) => v != null ? Number(v).toLocaleString("es-CO") : "-";

        // Sort: oficina → canal → nombre
        const sorted = [...detail].sort((a, b) => {
            const o = (a.oficina || "").localeCompare(b.oficina || "");
            if (o !== 0) return o;
            return (a.canal || "").localeCompare(b.canal || "");
        });

        // Render individual rows
        detailBody.innerHTML = sorted.map((row) => {
            const toner = row.toner_pct != null
                ? `<span class="badge ${row.toner_pct <= 10 ? 'bg-danger' : row.toner_pct <= 20 ? 'bg-warning text-dark' : 'bg-success'}">${row.toner_pct}%</span>`
                : '<span class="text-muted">-</span>';
            const label = displayCanal(row.canal, row.area);
            const canalRaw = (row.canal || "").toUpperCase();
            const badgeColor = canalRaw === "INTERNO" ? "bg-primary" :
                               canalRaw === "EXTERNO" ? "bg-warning text-dark" : "bg-secondary";
            return `<tr>
                <td>${escapeHtml(row.oficina || "-")}</td>
                <td>${escapeHtml(row.impresora || "-")}</td>
                <td class="text-monospace small">${escapeHtml(row.numero_serie || "-")}</td>
                <td><span class="badge ${badgeColor}">${escapeHtml(label)}</span></td>
                <td class="text-end fw-bold">${row.contador_maquina != null ? fmt(row.contador_maquina) : '<span class="text-muted">Sin datos</span>'}</td>
                <td>${toner}</td>
                <td class="small text-muted">${escapeHtml(row.ultima_lectura || "-")}</td>
            </tr>`;
        }).join("");

        const t = result.totales || {};
        resultEl.textContent = `Periodo ${result.periodo || "TODOS"} | Impresoras: ${fmt(t.impresoras_total)} | Con datos correo: ${fmt(t.impresoras_con_datos)}`;

        wrap.style.display = "block";
    }

    document.getElementById("btn-report-general")?.addEventListener("click", async () => {
        const period = getGeneralReportPeriod();
        if (period && !isValidPeriod(period)) {
            document.getElementById("report-general-result").textContent = "El periodo debe ser YYYY-MM.";
            return;
        }
        document.getElementById("report-general-result").textContent = "Generando reporte general...";
        const result = parseResponse(await callBridge("generarReporteGeneral", period));
        renderGeneralReport(result);
    });

    document.getElementById("btn-export-general-xlsx")?.addEventListener("click", async () => {
        const period = getGeneralReportPeriod();
        if (period && !isValidPeriod(period)) {
            document.getElementById("report-general-result").textContent = "El periodo debe ser YYYY-MM.";
            return;
        }
        const result = parseResponse(await callBridge("exportarReporteGeneralExcel", period));
        document.getElementById("report-general-result").textContent = result.ok === false
            ? (result.mensaje || "Error exportando reporte general Excel")
            : `Reporte general Excel exportado: ${result.archivo}`;
    });

    document.getElementById("btn-export-general-pdf")?.addEventListener("click", async () => {
        const period = getGeneralReportPeriod();
        if (period && !isValidPeriod(period)) {
            document.getElementById("report-general-result").textContent = "El periodo debe ser YYYY-MM.";
            return;
        }
        const result = parseResponse(await callBridge("exportarReporteGeneralPDF", period));
        document.getElementById("report-general-result").textContent = result.ok === false
            ? (result.mensaje || "Error exportando reporte general PDF")
            : `Reporte general PDF exportado: ${result.archivo}`;
    });

    document.getElementById("btn-create-report")?.addEventListener("click", async () => {
        showSection("reportes");
        const period = getGeneralReportPeriod();
        if (period && !isValidPeriod(period)) {
            document.getElementById("report-general-result").textContent = "El periodo debe ser YYYY-MM.";
            return;
        }
        document.getElementById("report-general-result").textContent = "Preparando reporte general...";
        const result = parseResponse(await callBridge("generarReporteGeneral", period));
        renderGeneralReport(result);
    });

    document.getElementById("btn-export-data")?.addEventListener("click", async () => {
        showSection("reportes");
        const period = getGeneralReportPeriod();
        const resultEl = document.getElementById("report-general-result");
        if (period && !isValidPeriod(period)) {
            resultEl.textContent = "El periodo debe ser YYYY-MM.";
            return;
        }
        resultEl.textContent = "Generando y exportando datos generales...";
        const preview = parseResponse(await callBridge("generarReporteGeneral", period));
        renderGeneralReport(preview);
        const result = parseResponse(await callBridge("exportarReporteGeneralExcel", period));
        resultEl.textContent = result.ok === false
            ? (result.mensaje || "Error exportando datos")
            : `Datos exportados: ${result.archivo}`;
    });

    document.getElementById("btn-reg-ip").addEventListener("click", async () => {
        requireLoginGuard();
        const nombre   = document.getElementById("ip-reg-nombre").value.trim();
        const oficina  = document.getElementById("ip-reg-oficina").value.trim();
        const ip       = document.getElementById("ip-reg-ip").value.trim();
        const serie    = document.getElementById("ip-reg-serie").value.trim();
        const modelo   = document.getElementById("ip-reg-modelo").value.trim() || "ECOSYS M3655idn";
        const canal    = getCustomSelValue("ip-reg-canal");
        const regStatus = document.getElementById("ip-reg-status");

        if (!nombre || !serie) {
            regStatus.textContent = "Nombre y número de serie son obligatorios.";
            return;
        }
        const result = parseResponse(await callBridge("registrarImpresoraIP", nombre, oficina, ip, serie, modelo, canal));
        regStatus.textContent = result.mensaje || (result.ok ? "Guardado" : "Error");
        if (result.ok) {
            document.getElementById("ip-reg-nombre").value  = "";
            document.getElementById("ip-reg-oficina").value = "";
            document.getElementById("ip-reg-ip").value      = "";
            document.getElementById("ip-reg-serie").value   = "";
            setCustomSelValue("ip-reg-canal", "");
            cargarListaIP();
        }
    });

    // Sincronizar impresoras base manualmente
    document.getElementById("btn-sincronizar-base")?.addEventListener("click", async () => {
        const syncStatus = document.getElementById("base-sync-status");
        const btn = document.getElementById("btn-sincronizar-base");
        btn.disabled = true;
        if (syncStatus) { syncStatus.textContent = "Sincronizando..."; syncStatus.style.display = "block"; }
        const r = parseResponse(await callBridge("cargarImpresorasBase"));
        btn.disabled = false;
        if (syncStatus) {
            syncStatus.textContent = r.ok
                ? `✅ ${r.mensaje}`
                : `❌ ${r.mensaje || "Error al sincronizar"}`;
        }
        await cargarListaIP();
        await cargarChartsContadores();
    });

    // Ver comparativos guardados
    document.getElementById("btn-ver-comparativos")?.addEventListener("click", async () => {
        const periodo = getCustomSelValue("comparativos-periodo-sel");
        const statusEl = document.getElementById("comparativos-status");
        const wrap = document.getElementById("comparativos-wrap");
        const tbody = document.getElementById("comparativos-body");
        if (!periodo) { if (statusEl) statusEl.textContent = "Selecciona un periodo."; return; }
        if (statusEl) statusEl.textContent = "Cargando...";
        const r = parseResponse(await callBridge("listarComparativosPeriodo", periodo));
        if (!r.ok) { if (statusEl) statusEl.textContent = r.mensaje || "Error"; return; }
        const rows = r.comparativos || [];
        if (rows.length === 0) {
            if (statusEl) statusEl.textContent = "Sin comparativos guardados para ese periodo.";
            wrap.style.display = "none";
            return;
        }
        if (statusEl) statusEl.textContent = `${rows.length} comparativos para ${periodo}`;
        tbody.innerHTML = rows.map(row => {
            const sinCorreo = (row.fuente || "").includes("sin_correo");
            const dif = Number(row.diferencia);
            const pct = Number(row.porcentaje_error);
            const color = sinCorreo ? "" : (Math.abs(pct) > 5 ? "text-danger" : Math.abs(pct) > 2 ? "text-warning" : "text-success");
            const difTxt = sinCorreo ? '<span class="text-muted">Sin lectura</span>' : `${dif > 0 ? "+" : ""}${dif.toLocaleString("es-CO")}`;
            const pctTxt = sinCorreo ? '<span class="text-muted">—</span>' : `${pct.toFixed(2)}%`;
            const maqTxt = sinCorreo ? '<span class="text-muted fst-italic">Sin correo</span>' : Number(row.contador_maquina).toLocaleString("es-CO");
            const rowStyle = sinCorreo ? ' class="table-light text-muted"' : '';
            return `<tr${rowStyle}>
                <td class="text-monospace small">${escapeHtml(row.numero_serie)}</td>
                <td>${escapeHtml(row.oficina || "-")}</td>
                <td class="text-end">${Number(row.contador_proveedor).toLocaleString("es-CO")}</td>
                <td class="text-end">${maqTxt}</td>
                <td class="text-end ${sinCorreo ? "" : (dif > 0 ? "text-warning" : dif < 0 ? "text-danger" : "")}">${difTxt}</td>
                <td class="text-end ${color}">${pctTxt}</td>
                <td><span class="badge ${sinCorreo ? "bg-light text-secondary border" : "bg-secondary"}">${escapeHtml(row.fuente || "manual")}</span></td>
                <td class="small text-muted">${escapeHtml((row.guardado_en || "").toString().slice(0,10))}</td>
            </tr>`;
        }).join("");
        wrap.style.display = "block";
    });

    // Función compartida: importa correos (si hay clave) y recarga tabla
    // Uses background-thread signal so the UI never freezes ("No responde").
    async function importarYRefrescar() {
        const statusEl  = document.getElementById("cnt-mail-status");
        const allStatus = document.getElementById("ip-list-status");
        const user      = (document.getElementById("cnt-mail-user")?.value || "").trim();
        const pass      = document.getElementById("cnt-mail-pass")?.value || "";
        const host      = (document.getElementById("cnt-mail-host")?.value || "").trim();
        const folder    = (document.getElementById("cnt-mail-folder")?.value || "datecsa").trim();
        const max       = Number(document.getElementById("cnt-mail-max")?.value || 200);
        const onlyUnseen = document.getElementById("cnt-mail-only-unseen")?.checked || false;
        const btn       = document.getElementById("btn-cnt-mail-import");

        if (!pass) {
            if (statusEl) statusEl.innerHTML = "&#x26A0; Ingresa la contraseña del correo para actualizar.";
            allStatus.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Recargando desde BD...';
            await cargarListaIP();
            await cargarChartsContadores();
            allStatus.textContent = "Tabla recargada desde base de datos.";
            return;
        }
        if (!user || !host) {
            if (statusEl) statusEl.innerHTML = "&#x26A0; Correo y host son requeridos.";
            return;
        }

        if (btn) btn.disabled = true;
        mostrarOverlay(`Conectando a ${host} — importando correos de "${folder}"...`);
        if (statusEl) statusEl.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Importando en segundo plano...';
        allStatus.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Importando correos...';

        // Ask the bridge to start the import in a background thread
        const startResult = parseResponse(await callBridge(
            "importarLecturasCorreo", user, pass, host, folder, "", "", onlyUnseen, max
        ));

        if (startResult.ok === false) {
            ocultarOverlay();
            if (btn) btn.disabled = false;
            if (statusEl) statusEl.innerHTML = "&#x274C; " + escapeHtml(startResult.mensaje || "Error al iniciar importación");
            allStatus.textContent = "Error al importar correos.";
            return;
        }

        if (!startResult.en_proceso) {
            // Sync fallback (shouldn't happen with new bridge, but just in case)
            ocultarOverlay();
            if (btn) btn.disabled = false;
            const msg = startResult.mensaje || "Importación finalizada";
            if (statusEl) statusEl.innerHTML = "&#x2705; " + escapeHtml(msg);
            await cargarListaIP();
            await cargarChartsContadores();
            allStatus.textContent = "Contadores actualizados desde correo.";
            return;
        }

        // Wait for the signal fired by the background worker (max 3 min)
        const result = await new Promise((resolve) => {
            let settled = false;
            const timer = setTimeout(() => {
                if (settled) return;
                settled = true;
                try { bridge.importacionLista.disconnect(onDone); } catch (_) {}
                resolve({ ok: false, mensaje: "Tiempo de espera agotado — revisa tu conexión IMAP." });
            }, 180000);
            function onDone(resultJson) {
                if (settled) return;
                settled = true;
                clearTimeout(timer);
                bridge.importacionLista.disconnect(onDone);
                resolve(parseResponse(resultJson));
            }
            bridge.importacionLista.connect(onDone);
        });

        ocultarOverlay();
        if (btn) btn.disabled = false;

        if (result.ok === false) {
            if (statusEl) statusEl.innerHTML = "&#x274C; " + escapeHtml(result.mensaje || "Error al importar");
            allStatus.textContent = "Error al importar correos.";
            return;
        }

        const msg = result.mensaje || "Importación finalizada";
        if (statusEl) statusEl.innerHTML = "&#x2705; " + escapeHtml(msg);
        allStatus.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Recargando tabla...';
        await cargarListaIP();
        await cargarChartsContadores();
        allStatus.textContent = "Contadores actualizados desde correo.";
    }

    document.getElementById("btn-cnt-mail-import")?.addEventListener("click", async () => {
        requireLoginGuard();
        await importarYRefrescar();
    });

    document.getElementById("btn-query-all-ip").addEventListener("click", async () => {
        requireLoginGuard();
        await importarYRefrescar();
    });

    document.getElementById("btn-close-history").addEventListener("click", () => {
        document.getElementById("ip-history-panel").style.display = "none";
    });

    document.getElementById("btn-cargar-base-impresoras")?.addEventListener("click", async () => {
        requireLoginGuard();
        const statusEl = document.getElementById("base-impresoras-status");
        const btn = document.getElementById("btn-cargar-base-impresoras");
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Cargando...';
        statusEl.textContent = "Cargando 32 impresoras base...";
        const result = parseResponse(await callBridge("cargarImpresorasBase"));
        btn.disabled = false;
        btn.textContent = "Cargar / Actualizar impresoras base";
        if (result.ok) {
            statusEl.innerHTML = `✅ ${result.mensaje}`;
            await cargarListaIP();
        } else {
            statusEl.textContent = `❌ ${result.mensaje || "Error"}`;
        }
    });

    async function prefillCredenciales() {
        try {
            const cfg = parseResponse(await callBridge("obtenerConfigCorreo"));
            if (!cfg.ok) return;
            const setVal = (id, val) => {
                const el = document.getElementById(id);
                if (el && val) el.value = val;
            };
            setVal("cnt-mail-user",   cfg.email_user);
            setVal("cnt-mail-pass",   cfg.email_password);
            setVal("cnt-mail-host",   cfg.imap_host);
            setVal("cnt-mail-folder", cfg.imap_folder);
            setVal("mail-user",       cfg.email_user);
            setVal("mail-pass",       cfg.email_password);
            setVal("mail-host",       cfg.imap_host);
            setVal("mail-folder",     cfg.imap_folder);
            // Pre-fill edit form too
            setVal("imap-new-user",   cfg.email_user);
            setVal("imap-new-host",   cfg.imap_host);
            setVal("imap-new-folder", cfg.imap_folder);
        } catch (_) {}
    }

    document.getElementById("btn-toggle-imap-creds")?.addEventListener("click", () => {
        const form = document.getElementById("imap-cred-form");
        if (!form) return;
        const isHidden = form.style.display === "none";
        form.style.display = isHidden ? "flex" : "none";
        form.style.flexWrap = "wrap";
        document.getElementById("btn-toggle-imap-creds").textContent = isHidden
            ? "✖ Cerrar"
            : "✏ Cambiar credenciales";
    });

    document.getElementById("btn-save-imap-creds")?.addEventListener("click", async () => {
        const statusEl = document.getElementById("imap-cred-status");
        const emailUser   = document.getElementById("imap-new-user")?.value.trim() || "";
        const emailPass   = document.getElementById("imap-new-pass")?.value || "";
        const imapHost    = document.getElementById("imap-new-host")?.value.trim() || "";
        const imapFolder  = document.getElementById("imap-new-folder")?.value.trim() || "";
        const adminPass   = document.getElementById("imap-admin-pass")?.value || "";
        if (!adminPass) {
            statusEl.textContent = "Ingresa la clave admin para confirmar.";
            return;
        }
        statusEl.textContent = "Guardando...";
        const res = parseResponse(await callBridge("actualizarCredencialesImap", emailUser, emailPass, imapHost, imapFolder, adminPass));
        statusEl.textContent = res.mensaje || (res.ok ? "Guardado" : "Error");
        if (res.ok) {
            await prefillCredenciales();
            document.getElementById("imap-cred-form").style.display = "none";
            document.getElementById("btn-toggle-imap-creds").textContent = "✏ Cambiar credenciales";
        }
    });

    document.getElementById("btn-admin-auth")?.addEventListener("click", async () => {
        requireLoginGuard();
        const pass = document.getElementById("admin-pass").value;
        const res = parseResponse(await callBridge("validarAdmin", pass));
        isAdminValidated = !!res.ok;
        document.getElementById("admin-auth-status").textContent = isAdminValidated
            ? "Acceso admin concedido"
            : (res.mensaje || "Clave admin invalida");
        document.getElementById("admin-panel").style.display = isAdminValidated ? "block" : "none";
        if (isAdminValidated) {
            await cargarLecturasCorreo(100);
        }
    });

    document.getElementById("btn-save-credentials")?.addEventListener("click", async () => {
        if (!isAdminValidated) {
            document.getElementById("admin-save-status").textContent = "Primero valida la clave admin.";
            return;
        }
        const user = document.getElementById("new-login-user").value.trim();
        const userPass = document.getElementById("new-login-pass").value;
        const adminPass = document.getElementById("new-admin-pass").value;
        const res = parseResponse(await callBridge("actualizarCredenciales", user, userPass, adminPass));
        document.getElementById("admin-save-status").textContent = res.mensaje || (res.ok ? "Guardado" : "Error");
    });

    async function cargarLecturasCorreo(limit = 120) {
        const tbody = document.getElementById("mail-readings-body");
        const statusEl = document.getElementById("mail-import-status");
        if (!tbody) return;

        const result = parseResponse(await callBridge("listarLecturasCorreo", Number(limit)));
        tbody.innerHTML = "";

        if (result.ok === false) {
            statusEl.textContent = result.mensaje || "Error consultando lecturas por correo";
            return;
        }

        const rows = result.lecturas || [];
        if (!rows.length) {
            statusEl.textContent = "No hay lecturas de correo registradas.";
            return;
        }

        rows.forEach((row) => {
            const tr = document.createElement("tr");
            const toner = row.toner_black_pct != null ? `${row.toner_black_pct}%` : "-";
            tr.innerHTML = `
                <td>${escapeHtml(row.importado_en || "-")}</td>
                <td>${escapeHtml(row.meter_date || "-")}</td>
                <td>${escapeHtml(row.serial_number || "-")}</td>
                <td>${escapeHtml(row.model_name || "-")}</td>
                <td>${escapeHtml(row.office_hint || "-")}</td>
                <td>${row.contador_efectivo != null ? Number(row.contador_efectivo).toLocaleString("es-CO") : "-"}</td>
                <td>${escapeHtml(toner)}</td>
                <td>${escapeHtml(row.asunto || "-")}</td>
            `;
            tbody.appendChild(tr);
        });

        statusEl.textContent = `Lecturas cargadas: ${rows.length}`;
    }

    document.getElementById("btn-mail-refresh")?.addEventListener("click", async () => {
        if (!isAdminValidated) {
            document.getElementById("mail-import-status").textContent = "Primero valida la clave admin.";
            return;
        }
        await cargarLecturasCorreo(150);
    });

    document.getElementById("btn-mail-local-browse")?.addEventListener("click", async () => {
        const path = await callBridge("openFolderDialog");
        if (path) {
            document.getElementById("mail-local-folder").value = path;
        }
    });

    document.getElementById("btn-mail-local-import")?.addEventListener("click", async () => {
        if (!isAdminValidated) {
            document.getElementById("mail-import-status").textContent = "Primero valida la clave admin.";
            return;
        }

        const statusEl = document.getElementById("mail-import-status");
        const folder = document.getElementById("mail-local-folder").value.trim();
        const pattern = document.getElementById("mail-local-pattern").value.trim() || "*.txt,*.htm,*.html";

        if (!folder) {
            statusEl.textContent = "Selecciona la carpeta local de correos.";
            return;
        }

        statusEl.textContent = "Importando archivos de correo locales...";
        const result = parseResponse(await callBridge("procesarCorreosLocales", folder, "", pattern));

        if (result.ok === false) {
            statusEl.textContent = result.mensaje || "No se pudo importar archivos locales";
            return;
        }

        const baseMsg = result.mensaje || "Importacion finalizada";
        statusEl.textContent = baseMsg;
        await cargarLecturasCorreo(150);
    });

    document.getElementById("btn-mail-diagnose")?.addEventListener("click", async () => {
        const statusEl = document.getElementById("mail-import-status");
        const resultsEl = document.getElementById("mail-diagnose-results");
        const folder = document.getElementById("mail-local-folder").value.trim();
        const pattern = document.getElementById("mail-local-pattern").value.trim() || "*.txt,*.htm,*.html";

        if (!folder) {
            statusEl.textContent = "Selecciona la carpeta local primero.";
            return;
        }

        statusEl.textContent = "Diagnosticando archivos...";
        resultsEl.style.display = "none";
        
        const result = parseResponse(await callBridge("diagnosticarArchivosCorreos", folder, pattern));

        if (result.ok === false) {
            statusEl.textContent = result.mensaje || "Error en diagnóstico";
            return;
        }

        let html = `<strong>Total de archivos:</strong> ${result.total}<br>`;
        
        if (result.archivos && result.archivos.length > 0) {
            html += "<br><strong>Archivos encontrados:</strong><br>";
            html += "<table class='table table-sm table-dark mb-0'><thead><tr><th>Archivo</th><th>Serial</th><th>Modelo</th><th>Contador</th><th>Toner%</th><th>Error</th></tr></thead><tbody>";
            
            result.archivos.forEach(arch => {
                if (arch.error) {
                    html += `<tr><td>${arch.archivo}</td><td colspan='5' class='text-danger'>${arch.error}</td></tr>`;
                } else {
                    html += `<tr>
                        <td>${arch.archivo}</td>
                        <td>${arch.serial_number || '-'}</td>
                        <td>${arch.model_name || '-'}</td>
                        <td>${arch.contador_efectivo || '-'}</td>
                        <td>${arch.toner_black_pct || '-'}</td>
                        <td>-</td>
                    </tr>`;
                }
            });
            html += "</tbody></table>";
        }

        resultsEl.innerHTML = html;
        resultsEl.style.display = "block";
        statusEl.textContent = result.mensaje || "Diagnóstico completado";
    });

    document.getElementById("btn-mail-show-serials")?.addEventListener("click", async () => {
        const statusEl = document.getElementById("mail-import-status");
        const resultsEl = document.getElementById("mail-diagnose-results");

        statusEl.textContent = "Listando seriales en BD...";
        resultsEl.style.display = "none";
        
        const result = parseResponse(await callBridge("listarSerialessEnBD", 50));

        if (result.ok === false) {
            statusEl.textContent = result.mensaje || "Error listando seriales";
            return;
        }

        let html = `<strong>Total de seriales en BD:</strong> ${result.total}<br><br>`;
        
        if (result.seriales && result.seriales.length > 0) {
            html += "<strong>Seriales con lecturas:</strong><br>";
            html += "<table class='table table-sm table-dark mb-0'><thead><tr><th>Serial</th><th>Cantidad</th><th>Última lectura</th></tr></thead><tbody>";
            
            result.seriales.forEach(row => {
                html += `<tr>
                    <td><strong>${row.serial_number}</strong></td>
                    <td>${row.cantidad}</td>
                    <td>${row.ultima_lectura || '-'}</td>
                </tr>`;
            });
            html += "</tbody></table>";
        } else {
            html += "<p class='text-warning'>No hay seriales con lecturas en la BD.</p>";
        }

        resultsEl.innerHTML = html;
        resultsEl.style.display = "block";
        statusEl.textContent = result.mensaje || "Listado completado";
    });

    document.getElementById("btn-mail-import")?.addEventListener("click", async () => {
        const statusEl = document.getElementById("mail-import-status");
        const user = document.getElementById("mail-user").value.trim();
        const pass = document.getElementById("mail-pass").value;
        const host = document.getElementById("mail-host").value.trim();
        const folder = document.getElementById("mail-folder").value.trim();
        const senderFilter = document.getElementById("mail-sender-filter").value.trim();
        const subjectFilter = document.getElementById("mail-subject-filter").value.trim();
        const onlyUnseen = document.getElementById("mail-only-unseen").checked;
        const maxMessages = Number(document.getElementById("mail-max").value || 50);

        if (!user || !pass) {
            statusEl.innerHTML = "&#x26A0; Usuario y contraseña del correo son obligatorios.";
            return;
        }
        if (!host) {
            statusEl.innerHTML = "&#x26A0; Host IMAP requerido (ej. imap.gmail.com u outlook.office365.com).";
            return;
        }

        const btnImport = document.getElementById("btn-mail-import");
        btnImport.disabled = true;
        statusEl.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Conectando a ' + escapeHtml(host) + ' carpeta "' + escapeHtml(folder || "datecsa") + '"...';

        const result = parseResponse(await callBridge(
            "importarLecturasCorreo",
            user,
            pass,
            host,
            folder,
            senderFilter,
            subjectFilter,
            onlyUnseen,
            maxMessages,
        ));
        btnImport.disabled = false;

        if (result.ok === false) {
            statusEl.innerHTML = "&#x274C; " + escapeHtml(result.mensaje || "No se pudo importar correos");
            return;
        }

        const baseMsg = result.mensaje || "Importacion finalizada";
        const muestras = result.muestras || [];
        let muestrasHtml = "";
        if (muestras.length > 0) {
            muestrasHtml = "<br><small>Muestras: " + muestras.map(x =>
                `<strong>${escapeHtml(x.serial||"-")}</strong>: ${x.contador ? Number(x.contador).toLocaleString("es-CO") : "-"} pgs`
            ).join(" &bull; ") + "</small>";
        }
        statusEl.innerHTML = "&#x2705; " + escapeHtml(baseMsg) + muestrasHtml;
        await cargarDashboard();
        await cargarLecturasCorreo(150);
    });

    document.getElementById("btn-actualizar-todo")?.addEventListener("click", async () => {
        const btn    = document.getElementById("btn-actualizar-todo");
        const status = document.getElementById("load-status");
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Actualizando...';
        if (status) status.textContent = "Actualizando...";
        try {
            // Primero recargar desde lo que ya hay en BD (rápido, no bloquea)
            await callBridge("sincronizarMantenimientos", true);
            await cargarDashboard();
            await cargarListaIP();
        } finally {
            btn.disabled = false;
            btn.innerHTML = "&#x21BA; Actualizar Todo";
            if (status) status.textContent = "Actualizado";
        }
        // Importar correos en segundo plano si hay credenciales configuradas
        const pass = document.getElementById("cnt-mail-pass")?.value || "";
        const user = document.getElementById("cnt-mail-user")?.value || "";
        if (pass && user) {
            importarYRefrescar().catch(() => {});
        }
    });

    document.getElementById("btn-crear-bd")?.addEventListener("click", async () => {
        const host     = document.getElementById("bd-host").value.trim() || "127.0.0.1";
        const port     = parseInt(document.getElementById("bd-port").value) || 3306;
        const user     = document.getElementById("bd-user").value.trim() || "root";
        const password = document.getElementById("bd-password").value;
        const dbName   = document.getElementById("bd-name").value.trim() || "print_analytics";
        const statusEl = document.getElementById("bd-create-status");
        const resultEl = document.getElementById("bd-tablas-resultado");
        const listaEl  = document.getElementById("bd-tablas-lista");
        const btn      = document.getElementById("btn-crear-bd");

        btn.disabled = true;
        statusEl.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Conectando a MySQL...';
        resultEl.style.display = "none";

        const cfg = JSON.stringify({ host, port, user, password, db_name: dbName });
        const result = parseResponse(await callBridge("crearNuevaBaseDatos", cfg));
        btn.disabled = false;

        if (result.ok === false) {
            statusEl.innerHTML = "&#x274C; " + escapeHtml(result.mensaje || "Error creando base de datos");
            return;
        }

        statusEl.innerHTML = "&#x2705; " + escapeHtml(result.mensaje || "Base de datos creada exitosamente");

        const tablas = result.tablas || [];
        if (tablas.length > 0) {
            listaEl.innerHTML = tablas.map(t =>
                `<li class="list-group-item py-1 small">&#x1F4CB; ${escapeHtml(t)}</li>`
            ).join("");
            resultEl.style.display = "block";
        }
    });

    document.getElementById("btn-sync-mantenimientos")?.addEventListener("click", async () => {
        const btn = document.getElementById("btn-sync-mantenimientos");
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Calculando...';
        await cargarMantenimientos(true);
        btn.disabled = false;
        btn.innerHTML = "&#x21BA; Actualizar Mantenimientos";
    });

    document.getElementById("btn-login")?.addEventListener("click", async () => {
        const user = document.getElementById("login-user").value.trim();
        const pass = document.getElementById("login-pass").value;
        const status = document.getElementById("login-status");
        status.textContent = "Validando...";
        const result = parseResponse(await callBridge("iniciarSesion", user, pass));
        if (result.ok) {
            isLoggedIn = true;
            hideLoginOverlay();
            await prefillCredenciales();
            // Seed counter cache first so dashboard shows real data
            await callBridge("refrescarUltimoEstado").catch(() => {});
            await cargarDashboard();
            await cargarListaIP();
            status.textContent = "";
        } else {
            status.textContent = result.mensaje || "Credenciales invalidas";
        }
    });
}

new QWebChannel(qt.webChannelTransport, (channel) => {
    bridge = channel.objects.bridge;
    bindEvents();
    initHistorial();
    initActualizaciones();
});

// ══════════════════════════════════════════════════════════════════════════════
// HISTORIAL MENSUAL
// ══════════════════════════════════════════════════════════════════════════════

let _chartHistPaginas = null;
let _chartTendPaginas = null;
let _chartTendError   = null;

function initHistorial() {
    document.getElementById("btn-crear-backup")?.addEventListener("click", async () => {
        const status = document.getElementById("backup-status");
        status.textContent = "Creando backup...";
        const r = parseResponse(await callBridge("backupDatosMes", ""));
        if (r.ok) {
            status.innerHTML = `✅ Backup creado para <strong>${r.periodo}</strong>: ${r.comparativos} comparativos, ${r.historial} lecturas.`;
            await cargarListaBackups();
        } else {
            status.textContent = `❌ ${r.mensaje}`;
        }
    });

    document.getElementById("btn-refresh-backups")?.addEventListener("click", cargarListaBackups);

    document.getElementById("btn-sync-red")?.addEventListener("click", async () => {
        const syncStatus = document.getElementById("backup-sync-status");
        if (syncStatus) syncStatus.textContent = "⏳ Sincronizando...";
        const r = parseResponse(await callBridge("sincronizarBackupARed", ""));
        if (syncStatus) syncStatus.innerHTML = r.ok
            ? `<span class="text-success">✅ ${r.mensaje}</span>`
            : `<span class="text-danger">❌ ${r.mensaje}</span>`;
    });

    document.getElementById("btn-cerrar-backup")?.addEventListener("click", () => {
        document.getElementById("backup-detalle-panel").style.display = "none";
    });
    document.getElementById("btn-cargar-tendencia")?.addEventListener("click", cargarTendenciaGlobal);

    // Cargar al entrar a la sección
    document.querySelectorAll("[data-section='historial']").forEach(el => {
        el.addEventListener("click", () => {
            cargarListaBackups();
        });
    });
}

async function cargarListaBackups() {
    const lista = document.getElementById("backup-lista");
    const status = document.getElementById("backup-status");
    if (!lista) return;
    lista.innerHTML = '<div class="text-muted small">Cargando...</div>';
    const r = parseResponse(await callBridge("listarBackups"));
    if (!r.ok || !r.backups || r.backups.length === 0) {
        lista.innerHTML = '<div class="text-muted small p-3">No hay backups disponibles. Haz clic en "Crear Backup Ahora" para generar el primero.</div>';
        return;
    }
    lista.innerHTML = r.backups.map(b => `
        <button class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
                onclick="verDetalleBackup('${b.periodo}')">
            <div>
                <strong>📅 ${b.periodo}</strong>
                <div class="small text-muted">
                    ${b.comparativos ?? 0} comparativos · ${b.historial ?? 0} lecturas
                    ${b.generado_en ? ' · ' + b.generado_en.substring(0, 16).replace('T', ' ') : ''}
                </div>
            </div>
            <span class="badge bg-primary rounded-pill">Ver</span>
        </button>
    `).join("");
    status.textContent = `${r.backups.length} backup(s) disponibles.`;
}

async function verDetalleBackup(periodo) {
    const panel = document.getElementById("backup-detalle-panel");
    const titulo = document.getElementById("backup-detalle-titulo");
    panel.style.display = "block";
    titulo.textContent = `Período: ${periodo}`;
    panel.scrollIntoView({ behavior: "smooth" });

    const r = parseResponse(await callBridge("cargarDatosBackup", periodo));
    if (!r.ok) {
        document.getElementById("backup-comp-body").innerHTML = `<tr><td colspan="6" class="text-danger">${r.mensaje}</td></tr>`;
        return;
    }

    // Tabla comparativos
    const compBody = document.getElementById("backup-comp-body");
    const comps = r.comparativos || [];
    compBody.innerHTML = comps.length === 0
        ? '<tr><td colspan="6" class="text-muted text-center">Sin comparativos para este período</td></tr>'
        : comps.map(c => {
            const dif = Number(c.diferencia);
            const pct = Number(c.porcentaje_error).toFixed(2);
            const color = dif < 0 ? "#15803D" : dif > 0 ? "#B91C1C" : "#64748B";
            return `<tr>
                <td><code>${c.numero_serie}</code></td>
                <td>${c.oficina || "—"}</td>
                <td>${Number(c.contador_proveedor).toLocaleString()}</td>
                <td>${Number(c.contador_maquina).toLocaleString()}</td>
                <td style="color:${color};font-weight:bold;">${dif > 0 ? "+" : ""}${dif.toLocaleString()}</td>
                <td style="color:${color};">${pct}%</td>
            </tr>`;
          }).join("");

    // Tabla historial lecturas
    const histBody = document.getElementById("backup-hist-body");
    const hist = r.historial_lecturas || [];
    histBody.innerHTML = hist.length === 0
        ? '<tr><td colspan="5" class="text-muted text-center">Sin lecturas para este período</td></tr>'
        : hist.map(h => `<tr>
            <td><code>${h.serial_number}</code></td>
            <td>${h.oficina || "—"}</td>
            <td>${h.contador_efectivo != null ? Number(h.contador_efectivo).toLocaleString() : "—"}</td>
            <td>${h.toner_black_pct != null ? h.toner_black_pct + "%" : "—"}</td>
            <td>${h.meter_date ? h.meter_date.toString().substring(0, 10) : "—"}</td>
          </tr>`).join("");

    // Gráfica de páginas del backup
    const canvasHP = document.getElementById("chart-historial-paginas");
    if (canvasHP && hist.length > 0) {
        const bySerial = {};
        hist.forEach(h => {
            if (!h.serial_number) return;
            if (!bySerial[h.serial_number]) bySerial[h.serial_number] = 0;
            bySerial[h.serial_number] = Math.max(bySerial[h.serial_number], Number(h.contador_efectivo || 0));
        });
        const labels = Object.keys(bySerial).slice(0, 15);
        const datos = labels.map(s => bySerial[s]);
        if (_chartHistPaginas) _chartHistPaginas.destroy();
        _chartHistPaginas = new Chart(canvasHP, {
            type: "bar",
            data: {
                labels,
                datasets: [{ label: "Contador máquina", data: datos,
                             backgroundColor: "#1A2B4A", borderRadius: 4 }]
            },
            options: { responsive: true, plugins: { legend: { display: false } },
                       scales: { y: { beginAtZero: true } } }
        });
    }
}

async function cargarTendenciaGlobal() {
    const r = parseResponse(await callBridge("obtenerEstadisticasMensuales"));
    if (!r.ok) return;

    // Gráfica páginas por mes (correo)
    const canvasPag = document.getElementById("chart-tendencia-paginas");
    if (canvasPag && r.por_mes_correo && r.por_mes_correo.length > 0) {
        const meses = r.por_mes_correo.map(m => m.mes);
        const paginas = r.por_mes_correo.map(m => Number(m.total_paginas || 0));
        if (_chartTendPaginas) _chartTendPaginas.destroy();
        _chartTendPaginas = new Chart(canvasPag, {
            type: "line",
            data: {
                labels: meses,
                datasets: [{
                    label: "Páginas totales (correo)",
                    data: paginas,
                    borderColor: "#1A2B4A",
                    backgroundColor: "rgba(26,43,74,0.12)",
                    tension: 0.3,
                    fill: true,
                    pointRadius: 4,
                }]
            },
            options: { responsive: true, plugins: { legend: { position: "top" } },
                       scales: { y: { beginAtZero: true } } }
        });
    }

    // Gráfica % error comparativo por mes
    const canvasErr = document.getElementById("chart-tendencia-error");
    if (canvasErr && r.por_mes_comparativo && r.por_mes_comparativo.length > 0) {
        const meses = r.por_mes_comparativo.map(m => m.mes);
        const errores = r.por_mes_comparativo.map(m => Number(m.error_promedio || 0).toFixed(2));
        if (_chartTendError) _chartTendError.destroy();
        _chartTendError = new Chart(canvasErr, {
            type: "bar",
            data: {
                labels: meses,
                datasets: [{
                    label: "% Error promedio comparativo",
                    data: errores,
                    backgroundColor: errores.map(e => e > 10 ? "#E83C6C" : "#1A2B4A"),
                    borderRadius: 4,
                }]
            },
            options: { responsive: true, plugins: { legend: { position: "top" } },
                       scales: { y: { beginAtZero: true, suggestedMax: 20 } } }
        });
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// ACTUALIZACIONES
// ══════════════════════════════════════════════════════════════════════════════

async function cargarConfiguracionUpdate() {
    const input = document.getElementById("update-folder-input");
    if (!input) return;
    const r = parseResponse(await callBridge("obtenerUpdateFolder"));
    if (r.ok && r.carpeta) input.value = r.carpeta;
}

function initActualizaciones() {
    // Cargar carpeta guardada al iniciar
    cargarConfiguracionUpdate();

    // Guardar ruta de carpeta
    document.getElementById("btn-guardar-update-folder")?.addEventListener("click", async () => {
        const input = document.getElementById("update-folder-input");
        const status = document.getElementById("update-folder-status");
        const carpeta = input?.value?.trim();
        if (!carpeta) { status.innerHTML = '<span class="text-danger">Ingresa una ruta válida.</span>'; return; }
        const r = parseResponse(await callBridge("configurarUpdateFolder", carpeta));
        status.innerHTML = r.ok
            ? `<span class="text-success">✅ ${r.mensaje}</span>`
            : `<span class="text-danger">❌ ${r.mensaje}</span>`;
    });

    // Botón principal Buscar actualizaciones
    document.getElementById("btn-check-update")?.addEventListener("click", verificarActualizacion);

    // Botón instalar (en la tarjeta de actualización)
    document.getElementById("btn-instalar-update")?.addEventListener("click", ejecutarInstalacion);
}

async function verificarActualizacion() {
    const btnIcon  = document.getElementById("btn-check-update-icon");
    const spinner  = document.getElementById("update-check-spinner");
    const result   = document.getElementById("update-check-result");
    const card     = document.getElementById("update-install-card");
    const cardNueva = document.getElementById("update-version-nueva-card");

    if (btnIcon)  btnIcon.textContent = "⏳";
    if (spinner)  spinner.style.display = "block";
    if (result)   result.innerHTML = "";
    if (card)     card.style.display = "none";
    if (cardNueva) cardNueva.style.display = "none";

    const r = parseResponse(await callBridge("checkActualizacion"));

    if (btnIcon)  btnIcon.textContent = "🔍";
    if (spinner)  spinner.style.display = "none";

    if (!r.ok && !r.hay_actualizacion) {
        result.innerHTML = `<span class="text-muted">ℹ️ ${r.mensaje || "Sin información"}</span>`;
        return;
    }

    if (r.hay_actualizacion) {
        // Tarjeta verde "nueva versión"
        const cardLabel = document.getElementById("update-version-nueva-label");
        const fechaLabel = document.getElementById("update-fecha-label");
        const notasList  = document.getElementById("update-notas-list");
        if (cardLabel)  cardLabel.textContent = `v${r.version_nueva}`;
        if (fechaLabel) fechaLabel.textContent = `Publicada el ${r.fecha}`;
        if (notasList)  notasList.innerHTML = (r.notas || []).map(n => `<li>${n}</li>`).join("") || "<li>Sin notas de versión</li>";
        if (cardNueva)  cardNueva.style.display = "block";
        if (card)       card.style.display = "block";
        result.innerHTML = "";
        // También activar el banner flotante
        window.notificarActualizacion(r);
    } else {
        result.innerHTML = `<span class="text-success">✅ Ya tienes la versión más reciente (v${r.version_actual})</span>`;
    }
}

async function ejecutarInstalacion() {
    const btn  = document.getElementById("btn-instalar-update");
    const prog = document.getElementById("install-progress");
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Copiando archivos...'; }
    if (prog) prog.innerHTML = '<span class="text-muted">⏳ Descargando desde la red y preparando instalación en <code>C:\\AVISTA_Updates\\</code>...</span>';

    const ir = parseResponse(await callBridge("instalarActualizacion"));
    if (ir.ok) {
        if (prog) prog.innerHTML = `<span class="text-success">✅ ${ir.mensaje}<br>La ventana se cerrará en unos segundos y el aplicativo se reiniciará automáticamente.</span>`;
        if (btn)  btn.style.display = "none";
    } else {
        if (prog) prog.innerHTML = `<span class="text-danger">❌ ${ir.mensaje}</span>`;
        if (btn)  { btn.disabled = false; btn.innerHTML = "⚡ Instalar y reiniciar ahora"; }
    }
}

// Función global llamada desde Python cuando detecta actualización
window.notificarActualizacion = function(info) {
    const bar = document.getElementById("update-notification-bar");
    const text = document.getElementById("update-notif-text");
    if (!bar || !text) return;
    text.textContent = `🆕 Nueva versión disponible: v${info.version_nueva} — ${(info.notas || []).join(" · ")}`;
    bar.style.display = "flex";

    // Botón rápido de instalar desde el banner
    const btnInstalar = document.getElementById("btn-notif-instalar");
    if (btnInstalar && !btnInstalar._wired) {
        btnInstalar._wired = true;
        btnInstalar.addEventListener("click", async () => {
            btnInstalar.disabled = true;
            btnInstalar.textContent = "⏳ Instalando...";
            const ir = parseResponse(await callBridge("instalarActualizacion"));
            if (ir.ok) {
                text.textContent = `✅ ${ir.mensaje}`;
                btnInstalar.style.display = "none";
            } else {
                btnInstalar.disabled = false;
                btnInstalar.textContent = "⬇️ Instalar";
                text.textContent = `❌ ${ir.mensaje}`;
            }
        });
    }
};
