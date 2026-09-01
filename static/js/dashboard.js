/**
 * AI Stock Intelligence Dashboard - Client-side javascript
 * Vietnamese UI language, rich interactions, offline-first simple markdown rendering.
 */

document.addEventListener("DOMContentLoaded", () => {
    // Check status on load
    checkOllamaStatus();
    // Load latest screening results on load
    loadScreeningData();
});

// Toast Notification helper
function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    
    let icon = "ℹ️";
    if (type === "success") icon = "✅";
    if (type === "danger") icon = "❌";

    toast.innerHTML = `
        <div style="display: flex; align-items: center; gap: 8px;">
            <span>${icon}</span>
            <span>${message}</span>
        </div>
        <button class="toast-close" onclick="this.parentElement.remove()">&times;</button>
    `;

    container.appendChild(toast);

    // Auto remove after 5 seconds
    setTimeout(() => {
        toast.style.animation = "toast-in 0.3s reverse forwards";
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

// Simple regex-based markdown parser
function renderMarkdown(text) {
    if (!text) return "<em>Không có dữ liệu nhận định từ AI.</em>";

    // Escape HTML to prevent XSS (but preserve basic line breaks/paragraphs)
    let html = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

    // Clean headers
    html = html.replace(/^###\s+(.*)/gm, "<h3>$1</h3>");
    html = html.replace(/^##\s+(.*)/gm, "<h2>$1</h2>");
    html = html.replace(/^#\s+(.*)/gm, "<h1>$1</h1>");

    // Bold text **text**
    html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");

    // Italic *text* or _text_
    html = html.replace(/\*(.*?)\*/g, "<em>$1</em>");
    html = html.replace(/_(.*?)_/g, "<em>$1</em>");

    // Bullet lists
    const lines = html.split("\n");
    let inList = false;
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (line.startsWith("- ") || line.startsWith("* ")) {
            const content = line.substring(2);
            if (!inList) {
                lines[i] = "<ul><li>" + content + "</li>";
                inList = true;
            } else {
                lines[i] = "<li>" + content + "</li>";
            }
        } else {
            if (inList) {
                lines[i] = "</ul>" + (line ? "<p>" + line + "</p>" : "");
                inList = false;
            } else {
                // If it is not a header and not empty, wrap in paragraph
                if (line && !line.startsWith("<h") && !line.startsWith("<ul") && !line.startsWith("<li") && !line.startsWith("</ul")) {
                    lines[i] = "<p>" + line + "</p>";
                }
            }
        }
    }
    if (inList) {
        lines.push("</ul>");
    }

    return lines.join("\n");
}

// Format numbers nicely in Vietnamese format (1.234.567,89)
function formatNumber(value, digits = 2, suffix = "") {
    if (value === null || value === undefined || value === "") return "N/A";
    const num = parseFloat(value);
    if (isNaN(num)) return value;
    
    // Format to VN locale style (dot for thousands, comma for decimals)
    const formatted = num.toLocaleString("vi-VN", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits
    });
    return formatted + suffix;
}

// Get Badge Classes
function getTrendBadge(trend) {
    if (!trend) return '<span class="text-muted">N/A</span>';
    const norm = trend.trim().toUpperCase();
    if (norm === "TĂNG" || norm === "UP" || norm === "BULLISH") {
        return '<span class="trend-badge trend-up">▲ TĂNG</span>';
    } else if (norm === "GIẢM" || norm === "DOWN" || norm === "BEARISH") {
        return '<span class="trend-badge trend-down">▼ GIẢM</span>';
    } else {
        return `<span class="trend-badge trend-sideway">■ SIDEWAY</span>`;
    }
}

function getGradeBadge(grade) {
    if (!grade) return '<span class="text-muted">N/A</span>';
    const char = grade.trim().toUpperCase();
    let cls = "grade-d";
    if (char === "A") cls = "grade-a";
    else if (char === "B") cls = "grade-b";
    else if (char === "C") cls = "grade-c";
    return `<span class="grade-badge ${cls}">${char}</span>`;
}

// Helper to disable/enable UI buttons
function setButtonsState(loading) {
    const buttons = [
        "btn-check-status",
        "btn-analyze-full",
        "btn-analyze-tech",
        "btn-analyze-fund",
        "btn-report",
        "btn-load-screening"
    ];
    buttons.forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.disabled = loading;
    });

    const inputs = ["symbolInput"];
    inputs.forEach(id => {
        const input = document.getElementById(id);
        if (input) input.disabled = loading;
    });
}

// 1. Check Ollama Status
async function checkOllamaStatus() {
    const dot = document.getElementById("ollama-dot");
    const text = document.getElementById("ollama-text");
    const recModel = document.getElementById("ollama-recommended");
    const urlSpan = document.getElementById("ollama-url");
    const listDiv = document.getElementById("ollama-models-list");
    const btn = document.getElementById("btn-check-status");

    if (btn) btn.disabled = true;
    text.textContent = "Đang kiểm tra...";
    dot.className = "pulse-dot";
    dot.style.backgroundColor = "#eab308"; // yellow loading

    try {
        const response = await fetch("/api/agent/status");
        const data = await response.json();

        urlSpan.textContent = data.base_url || "http://localhost:11434";
        recModel.textContent = data.recommended_model || "llama3.2";

        if (data.online) {
            dot.className = "pulse-dot status-online-dot";
            text.textContent = "Online";
            text.className = "status-text text-green";
            
            // Render models
            if (data.models && data.models.length > 0) {
                listDiv.innerHTML = data.models.map(m => `<span class="model-tag">${m}</span>`).join("");
            } else {
                listDiv.innerHTML = '<span class="text-muted">Không tìm thấy model nào</span>';
            }
            showToast("Kết nối Ollama AI Agent thành công!", "success");
        } else {
            dot.className = "pulse-dot status-offline-dot";
            text.textContent = "Offline";
            text.className = "status-text text-red";
            listDiv.innerHTML = `<span class="text-red">${data.error || "Connection refused"}</span>`;
            showToast("Không thể kết nối đến Ollama. Hãy chắc chắn Ollama đang chạy.", "danger");
        }
    } catch (err) {
        dot.className = "pulse-dot status-offline-dot";
        text.textContent = "Lỗi kết nối";
        text.className = "status-text text-red";
        listDiv.innerHTML = `<span class="text-red">${err.message || err}</span>`;
        showToast("Lỗi khi kiểm tra trạng thái Ollama API", "danger");
    } finally {
        if (btn) btn.disabled = false;
    }
}

// 2. Load Screening Data
async function loadScreeningData() {
    const tableBody = document.getElementById("screening-table-body");
    const metaDiv = document.getElementById("screening-meta");
    const fileInfo = document.getElementById("screening-file-info");
    const timeInfo = document.getElementById("screening-time-info");
    const btn = document.getElementById("btn-load-screening");

    if (btn) btn.disabled = true;
    tableBody.innerHTML = `
        <tr>
            <td colspan="12" class="text-center py-5">
                <div style="display:inline-block; border-top:2px solid var(--accent-cyan); border-radius:50%; width:24px; height:24px; animation:blinker 1s infinite;"></div>
                <span style="margin-left:8px;" class="text-muted">Đang tải bảng xếp hạng...</span>
            </td>
        </tr>
    `;

    try {
        const response = await fetch("/api/screening/latest");
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const payload = await response.json();

        if (payload.success && payload.data && payload.data.length > 0) {
            let html = "";
            payload.data.forEach(row => {
                // Parse signals
                let signalsHtml = "";
                if (row.active_signals) {
                    const signalsArray = row.active_signals.split(",");
                    signalsHtml = signalsArray.map(sig => `<span class="signal-tag">${sig.trim()}</span>`).join("");
                } else {
                    signalsHtml = '<span class="text-muted">Không có</span>';
                }

                html += `
                    <tr>
                        <td class="text-center font-bold text-cyan" style="font-family: 'JetBrains Mono', monospace;">${row.rank || "N/A"}</td>
                        <td class="symbol-col">${row.symbol || "N/A"}</td>
                        <td class="score-col text-cyan">${row.screening_score !== null ? row.screening_score : "N/A"}</td>
                        <td class="price-col text-white">${formatNumber(row.last_price, 2, "k")}</td>
                        <td>${getTrendBadge(row.trend)}</td>
                        <td class="ratio-val">${formatNumber(row.rsi, 1)}</td>
                        <td class="ratio-val">${formatNumber(row.pe, 2)}</td>
                        <td class="ratio-val">${formatNumber(row.pb, 2)}</td>
                        <td class="ratio-val">${formatNumber(row.roe, 1, "%")}</td>
                        <td class="text-center">${getGradeBadge(row.grade)}</td>
                        <td style="max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: normal;">
                            ${signalsHtml}
                        </td>
                        <td class="table-actions">
                            <button class="btn btn-primary btn-sm" onclick="analyzeSymbolInline('${row.symbol}')">Phân tích</button>
                            <button class="btn btn-danger btn-sm" onclick="createSymbolReportInline('${row.symbol}')">Báo cáo</button>
                        </td>
                    </tr>
                `;
            });
            tableBody.innerHTML = html;
            
            // Show meta
            metaDiv.classList.remove("hidden");
            fileInfo.textContent = `Tệp: ${payload.file_name || "N/A"}`;
            timeInfo.textContent = `Thời gian tải: ${new Date().toLocaleTimeString("vi-VN")}`;
            showToast(`Đã tải xếp hạng mới nhất (${payload.count} mã)`, "success");
        } else {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="12" class="text-center text-yellow py-5">
                        ⚠️ Không tìm thấy kết quả screening hợp lệ. Hãy chạy batch_collect.py để tạo kết quả.
                    </td>
                </tr>
            `;
            metaDiv.classList.add("hidden");
        }
    } catch (err) {
        tableBody.innerHTML = `
            <tr>
                <td colspan="12" class="text-center text-red py-5">
                    ❌ Lỗi khi tải dữ liệu: ${err.message || err}
                </td>
            </tr>
        `;
        metaDiv.classList.add("hidden");
        showToast("Lỗi khi kết nối đến API screening/latest", "danger");
    } finally {
        if (btn) btn.disabled = false;
    }
}

// Callbacks for inline actions in ranking table
function analyzeSymbolInline(symbol) {
    const input = document.getElementById("symbolInput");
    if (input) input.value = symbol;
    analyzeSymbol("full");
}

function createSymbolReportInline(symbol) {
    const input = document.getElementById("symbolInput");
    if (input) input.value = symbol;
    createSymbolReport();
}

function handleInputKeyUp(event) {
    if (event.key === "Enter") {
        analyzeSymbol("full");
    }
}

// 3. Analyze Stock Symbol
async function analyzeSymbol(type = "full") {
    const symbolInput = document.getElementById("symbolInput");
    const symbol = (symbolInput.value || "FPT").trim().toUpperCase();
    
    if (!symbol) {
        showToast("Hãy nhập mã cổ phiếu hợp lệ", "danger");
        return;
    }

    setButtonsState(true);
    
    // UI Loading states
    const initMsg = document.getElementById("analysis-initial-msg");
    const loadingBlock = document.getElementById("analysis-loading");
    const contentBlock = document.getElementById("tab-content-wrapper");
    
    initMsg.classList.add("hidden");
    loadingBlock.classList.remove("hidden");
    contentBlock.classList.add("hidden");
    
    // Hide old report button
    document.getElementById("report-link-container").classList.add("hidden");

    // Scroll to results section smoothly
    document.getElementById("analysis-results-section").scrollIntoView({ behavior: "smooth" });

    // Update title
    document.getElementById("current-analyzed-symbol").textContent = `${symbol} (Đang tải...)`;
    document.getElementById("analysis-meta-time").textContent = "";

    try {
        const response = await fetch(`/api/analysis/${encodeURIComponent(symbol)}?type=${type}`);
        
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.error || `HTTP error! Status: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Populate results
        renderAnalysisResults(symbol, type, data);
        
        showToast(`Đã hoàn tất phân tích ${type.toUpperCase()} cho mã ${symbol}!`, "success");
    } catch (err) {
        console.error(err);
        showToast(`Lỗi phân tích mã ${symbol}: ${err.message || err}`, "danger");
        
        // Return to error state display
        document.getElementById("current-analyzed-symbol").textContent = `${symbol} (Lỗi)`;
        initMsg.innerHTML = `<span class="text-red">❌ Lỗi: ${err.message || err}</span>`;
        initMsg.classList.remove("hidden");
        loadingBlock.classList.add("hidden");
        contentBlock.classList.add("hidden");
    } finally {
        setButtonsState(false);
    }
}

// Render analysis results nicely
function renderAnalysisResults(symbol, type, data) {
    const loadingBlock = document.getElementById("analysis-loading");
    const contentBlock = document.getElementById("tab-content-wrapper");
    const metaTime = document.getElementById("analysis-meta-time");
    
    // Extract nodes from nested formats securely
    const technical = data.technical_data || (data.technical && data.technical.technical_data) || {};
    const fundamental = data.fundamental_data || (data.fundamental && data.fundamental.fundamental_data) || {};
    const indicators = technical.indicators || {};
    const signals = technical.signals || {};
    const ratios = fundamental.ratios || [];
    const scoreObj = fundamental.score || data.score_data || {};
    
    // Set headers
    document.getElementById("current-analyzed-symbol").textContent = symbol;
    metaTime.textContent = `Tạo lúc: ${data.generated_at || new Date().toISOString()}`;

    // 1. Overview Tab
    document.getElementById("overview-symbol").textContent = symbol;
    
    const scoreVal = data.score !== undefined ? data.score : (scoreObj.score !== undefined ? scoreObj.score : (data.fundamental && data.fundamental.score !== undefined ? data.fundamental.score : "N/A"));
    const scoreSpan = document.getElementById("overview-score");
    scoreSpan.textContent = scoreVal !== "N/A" ? `${scoreVal}/100` : "N/A";
    
    const gradeVal = data.grade || scoreObj.grade || (data.fundamental && data.fundamental.grade) || "N/A";
    const gradeSpan = document.getElementById("overview-grade");
    gradeSpan.innerHTML = getGradeBadge(gradeVal);
    
    const trendVal = technical.trend || "N/A";
    const trendSpan = document.getElementById("overview-trend");
    trendSpan.innerHTML = getTrendBadge(trendVal);
    
    // AI commentary
    const aiBox = document.getElementById("overview-ai-commentary");
    const rawCommentary = data.comprehensive_analysis || data.llm_analysis || "";
    aiBox.innerHTML = renderMarkdown(rawCommentary);

    // 2. Technical Tab
    document.getElementById("tech-last-price").textContent = formatNumber(technical.last_price, 2, " nghìn đ");
    document.getElementById("tech-last-date").textContent = technical.last_date || "N/A";
    document.getElementById("tech-rsi").textContent = formatNumber(indicators.rsi, 2);
    document.getElementById("tech-macd").textContent = formatNumber(indicators.macd, 3);
    
    document.getElementById("tech-ema20").textContent = formatNumber(indicators.ema20, 2, " k");
    document.getElementById("tech-ema50").textContent = formatNumber(indicators.ema50, 2, " k");
    document.getElementById("tech-ema200").textContent = formatNumber(indicators.ema200, 2, " k");
    document.getElementById("tech-bb-upper").textContent = formatNumber(indicators.bb_upper, 2, " k");
    document.getElementById("tech-bb-lower").textContent = formatNumber(indicators.bb_lower, 2, " k");
    
    // Technical signals
    const signalsContainer = document.getElementById("tech-signals-tags");
    let signalsHtml = "";
    let activeSignalsCount = 0;
    
    if (signals && typeof signals === "object") {
        for (const [key, val] of Object.entries(signals)) {
            if (val && val.active) {
                const signalClass = key.includes("bearish") || key.includes("death") || key.includes("below") ? "signal-negative" : "signal-positive";
                signalsHtml += `<div class="signal-large-tag ${signalClass}" title="${val.description || ''}">
                    <strong>${key.replace(/_/g, " ").toUpperCase()}</strong>: ${formatNumber(val.value, 2)}
                </div>`;
                activeSignalsCount++;
            }
        }
    }
    
    if (activeSignalsCount === 0) {
        signalsContainer.innerHTML = '<span class="text-muted">Không có tín hiệu kích hoạt nào trong kỳ.</span>';
    } else {
        signalsContainer.innerHTML = signalsHtml;
    }

    // Technical LLM commentary
    const techAiBox = document.getElementById("tech-ai-box");
    const techAiContent = document.getElementById("tech-ai-commentary");
    if (data.technical && data.technical.llm_analysis && data.technical.llm_analysis !== "Đã được tổng hợp trong comprehensive_analysis để giảm thời gian xử lý.") {
        techAiBox.classList.remove("hidden");
        techAiContent.innerHTML = renderMarkdown(data.technical.llm_analysis);
    } else {
        techAiBox.classList.add("hidden");
    }

    // 3. Fundamental Tab
    const latestRatio = ratios[0] || {};
    document.getElementById("fund-pe").textContent = formatNumber(latestRatio.pe, 2);
    document.getElementById("fund-pb").textContent = formatNumber(latestRatio.pb, 2);
    document.getElementById("fund-roe").textContent = formatNumber(latestRatio.roe, 1, "%");
    document.getElementById("fund-roa").textContent = formatNumber(latestRatio.roa, 1, "%");
    
    document.getElementById("fund-eps").textContent = formatNumber(latestRatio.eps, 0, " đ");
    document.getElementById("fund-debt-equity").textContent = formatNumber(latestRatio.debt_equity, 2, " lần");
    document.getElementById("fund-score-val").textContent = scoreVal;
    document.getElementById("fund-grade-val").textContent = gradeVal;
    
    const fundSummary = document.getElementById("fund-score-summary");
    fundSummary.textContent = scoreObj.summary_vi || "Chưa có đánh giá cơ bản chi tiết từ hệ thống.";

    // Fundamental LLM commentary
    const fundAiBox = document.getElementById("fund-ai-box");
    const fundAiContent = document.getElementById("fund-ai-commentary");
    if (data.fundamental && data.fundamental.llm_analysis && data.fundamental.llm_analysis !== "Đã được tổng hợp trong comprehensive_analysis để giảm thời gian xử lý.") {
        fundAiBox.classList.remove("hidden");
        fundAiContent.innerHTML = renderMarkdown(data.fundamental.llm_analysis);
    } else {
        fundAiBox.classList.add("hidden");
    }

    // 4. Raw JSON Tab
    document.getElementById("raw-json-output").textContent = JSON.stringify(data, null, 2);

    // Switch view to appropriate tab
    if (type === "technical") {
        triggerTabSwitch("tab-technical");
    } else if (type === "fundamental") {
        triggerTabSwitch("tab-fundamental");
    } else {
        triggerTabSwitch("tab-overview");
    }

    loadingBlock.classList.add("hidden");
    contentBlock.classList.remove("hidden");
}

// Tab Switching logic
function switchTab(event, tabId) {
    const tabButtons = document.querySelectorAll(".tab-btn");
    tabButtons.forEach(btn => btn.classList.remove("active"));
    
    const tabContents = document.querySelectorAll(".tab-content");
    tabContents.forEach(content => content.classList.remove("active-content"));
    
    event.currentTarget.classList.add("active");
    const targetContent = document.getElementById(tabId);
    if (targetContent) targetContent.classList.add("active-content");
}

function triggerTabSwitch(tabId) {
    const tabButtons = document.querySelectorAll(".tab-btn");
    tabButtons.forEach(btn => {
        if (btn.getAttribute("onclick").includes(tabId)) {
            btn.classList.add("active");
        } else {
            btn.classList.remove("active");
        }
    });

    const tabContents = document.querySelectorAll(".tab-content");
    tabContents.forEach(content => {
        if (content.id === tabId) {
            content.classList.add("active-content");
        } else {
            content.classList.remove("active-content");
        }
    });
}

// 4. Create HTML Report
async function createSymbolReport() {
    const symbolInput = document.getElementById("symbolInput");
    const symbol = (symbolInput.value || "FPT").trim().toUpperCase();

    if (!symbol) {
        showToast("Hãy nhập mã cổ phiếu hợp lệ để tạo báo cáo", "danger");
        return;
    }

    setButtonsState(true);
    const linkContainer = document.getElementById("report-link-container");
    const openBtn = document.getElementById("btn-open-report");
    linkContainer.classList.add("hidden");

    showToast(`Đang sinh báo cáo HTML cho mã ${symbol}. Vui lòng chờ...`, "info");

    try {
        const response = await fetch(`/api/report/${encodeURIComponent(symbol)}?format=html`);
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.error || `HTTP error! Status: ${response.status}`);
        }

        const data = await response.json();

        if (data.success && data.file_url) {
            linkContainer.classList.remove("hidden");
            openBtn.href = data.file_url;
            
            showToast(`Đã xuất báo cáo thành công cho mã ${symbol}!`, "success");
            
            // Attempt to open in a new tab if allowed
            const newWindow = window.open(data.file_url, "_blank");
            if (!newWindow || newWindow.closed || typeof newWindow.closed === "undefined") {
                showToast("Cửa sổ bật lên bị chặn. Hãy bấm nút 'Mở báo cáo' bên dưới.", "info");
            }
        } else {
            throw new Error(data.error || "Không nhận được liên kết tải báo cáo");
        }
    } catch (err) {
        console.error(err);
        showToast(`Lỗi khi tạo báo cáo cho mã ${symbol}: ${err.message || err}`, "danger");
    } finally {
        setButtonsState(false);
    }
}
