const $ = (id) => document.getElementById(id);
let trendChart = null, dashChart = null;

const CAT_KO = {
  verb_agreement: "주어-동사 일치", tense: "시제 / 현재완료", article: "관사 (a/an/the)",
  preposition: "전치사", plural: "복수형", word_choice: "어휘 선택 / 콩글리시",
  word_order: "어순", formality: "격식 (register)", filler: "필러", pace: "말 속도", other: "기타",
};
const SEV_KO = { high: "높음", medium: "보통", low: "낮음" };
const escapeHtml = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

// ── navigation / router ───────────────────────────────────────────
function showView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
  document.querySelectorAll(".nav").forEach((n) => n.classList.toggle("active", n.dataset.view === name));
  if (window.innerWidth <= 820) document.body.classList.remove("drawer-open");
  if (name === "dashboard") loadDashboard();
  if (name === "progress") { loadTrend(); loadWeaknesses("weakness"); }
  if (name === "vocab") loadVocab();
  if (name === "practice") { recommendFocus(); loadPracticeHistory(); }
  if (name === "history") loadHistory();
  location.hash = name;
}
document.querySelectorAll("[data-view]").forEach((el) =>
  el.addEventListener("click", () => showView(el.dataset.view)));
$("hamburger").addEventListener("click", () => {
  document.body.classList.toggle("drawer-closed");
  document.body.classList.toggle("drawer-open");
});
$("goAnalyze").addEventListener("click", () => showView("analyze"));

// ── metric cards ──────────────────────────────────────────────────
function metricCard(value, label, klass) {
  return `<div class="metric ${klass || ""}"><div class="v">${value}</div><div class="k">${label}</div></div>`;
}
function renderMetrics(m, elId = "metrics") {
  const el = $(elId);
  if (!el) return;
  if (!m) {
    el.innerHTML = ["필러/100단어", "어휘 다양성 (TTR)", "평균 문장 길이", "분석 단어 수"]
      .map((l) => metricCard("—", l, "")).join("");
    return;
  }
  const f = m.filler_rate > 10 ? "bad" : m.filler_rate > 5 ? "warn" : "good";
  const t = m.type_token_ratio >= 0.6 ? "good" : m.type_token_ratio >= 0.45 ? "warn" : "bad";
  el.innerHTML = [
    metricCard(m.filler_rate, "필러/100단어", f),
    metricCard(m.type_token_ratio, "어휘 다양성 (TTR)", t),
    metricCard(m.avg_sentence_length, "평균 문장 길이", "good"),
    metricCard(m.total_words, "분석 단어 수", ""),
  ].join("");
}

// ── structured diagnosis ──────────────────────────────────────────
function renderDiagnosis(d, elId = "report") {
  const el = $(elId);
  if (!d || !d.summary) { el.innerHTML = `<p class="hint">분석 결과가 없습니다.</p>`; return; }
  const e = escapeHtml;
  let html = `<div class="dx-summary">${e(d.summary)}`;
  if (d.cefr_estimate?.level)
    html += ` <span class="dx-cefr" title="${e(d.cefr_estimate.reason || "")}">레벨 추정: ${e(d.cefr_estimate.level)}</span>`;
  html += `</div>`;
  if (d.priority) html += `<div class="dx-priority"><span class="dx-pin">우선순위</span> ${e(d.priority)}</div>`;
  (d.top_habits || []).forEach((h, i) => {
    const sev = h.severity || "low";
    html += `<div class="dx-habit sev-${sev}"><div class="dx-habit-head"><span class="dx-rank">${i + 1}</span>
      <span class="dx-title">${e(h.title)}</span><span class="dx-tags">
      <span class="dx-cat">${CAT_KO[h.category] || e(h.category || "")}</span>
      <span class="dx-sev sev-${sev}">심각도 ${SEV_KO[sev] || sev}</span></span></div>`;
    if (h.evidence) html += `<div class="dx-row"><b>근거</b> ${e(h.evidence)}</div>`;
    if (h.why) html += `<div class="dx-row"><b>원인</b> ${e(h.why)}</div>`;
    if (h.examples?.length)
      html += `<table class="dx-ex"><tr><th>원문</th><th>교정</th></tr>` +
        h.examples.map((x) => `<tr><td>${e(x.original)}</td><td>${e(x.correction)}</td></tr>`).join("") + `</table>`;
    if (h.practice_tip) html += `<div class="dx-tip"><b>연습 팁</b> ${e(h.practice_tip)}</div>`;
    html += `</div>`;
  });
  // conversation ability (comprehension / engagement / coherence)
  const c = d.conversation;
  if (c) {
    const RT = { good: "좋음", mixed: "보통", poor: "미흡" };
    const dims = [["comprehension", "이해·응답"], ["engagement", "참여도"], ["coherence", "응집성"]];
    html += `<div class="dx-block"><h3>대화 능력</h3>`;
    dims.forEach(([k, lbl]) => {
      const o = c[k]; if (!o) return;
      html += `<div class="dx-conv"><span class="dx-conv-dim">${lbl}</span>
        <span class="dx-conv-rate r-${o.rating}">${RT[o.rating] || o.rating}</span>
        <span class="dx-conv-note">${e(o.note || "")}</span></div>`;
      (o.examples || []).forEach((x) =>
        html += `<div class="dx-conv-ex">Q: ${e(x.question)} → A: ${e(x.response)} <i>(${e(x.issue || "")})</i></div>`);
    });
    html += `</div>`;
  }
  if (d.register?.advice)
    html += `<div class="dx-block"><h3>격식 (register)</h3><p><b>${e(d.register.level || "")}</b> — ${e(d.register.advice)}</p></div>`;
  if (d.vocabulary_upgrades?.length)
    html += `<div class="dx-block"><h3>어휘 업그레이드</h3>` + d.vocabulary_upgrades.map((v) =>
      `<div class="dx-vu"><span class="dx-over">${e(v.overused)}</span> → ${(v.suggestions || []).map(e).join(", ")}` +
      (v.example ? `<div class="dx-ex-line">"${e(v.example)}"</div>` : "") + `</div>`).join("") + `</div>`;
  if (d.strengths?.length)
    html += `<div class="dx-block dx-strength"><h3>강점</h3><ul>` + d.strengths.map((s) => `<li>${e(s)}</li>`).join("") + `</ul></div>`;
  el.innerHTML = html;
}

function renderSteps(steps) {
  $("stepCount").textContent = steps.length;
  $("steps").innerHTML = steps.map((s) => {
    const args = Object.entries(s.input).map(([k, v]) => `${k}=${v}`).join(", ");
    return `<div class="step"><span class="name">${s.tool}(${args})</span><pre>${escapeHtml(s.output).slice(0, 1200)}</pre></div>`;
  }).join("");
  $("stepsWrap").classList.remove("hidden");
}

// ── analyze ───────────────────────────────────────────────────────
function loadSamples() {
  fetch("/api/transcripts").then((r) => r.json()).then((files) => {
    const sel = $("sampleSelect");
    files.forEach((f) => { const o = document.createElement("option"); o.value = f; o.textContent = f; sel.appendChild(o); });
  });
}
$("sampleSelect").addEventListener("change", async (e) => {
  const name = e.target.value;
  if (!name) return;
  const data = await fetch(`/api/transcript/${name}`).then((r) => r.json());
  $("transcript").value = data.text || "";
  const m = name.match(/(\d{4}-\d{2}-\d{2})/);
  if (m) $("date").value = m[1];
});

$("analyzeBtn").addEventListener("click", async () => {
  const text = $("transcript").value.trim();
  if (!text) { $("status").textContent = "전사본을 붙여넣거나 샘플을 먼저 불러오세요."; return; }
  const btn = $("analyzeBtn");
  btn.disabled = true;
  $("status").innerHTML = `<span class="spinner"></span>에이전트가 분석 중 — 도구 실행 및 진단 작성…`;
  $("reportWrap").classList.add("hidden");
  $("stepsWrap").classList.add("hidden");
  const payload = { speaker: $("speaker").value.trim() || "Me", date: $("date").value, text };
  if ($("sampleSelect").value) payload.filename = $("sampleSelect").value;
  try {
    const res = await fetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await res.json();
    if (!res.ok) { $("status").textContent = data.error || "오류가 발생했습니다."; return; }
    $("status").textContent = `${data.filename} 분석 완료 · 화자 "${data.speaker}"` + (data.saved ? " · 추세 저장됨" : "");
    renderMetrics(data.metrics, "metrics");
    renderDiagnosis(data.diagnosis, "report");
    $("reportWrap").classList.remove("hidden");
    renderSteps(data.steps || []);
    loadHistory();
  } catch (err) {
    $("status").textContent = "요청 실패: " + err.message;
  } finally { btn.disabled = false; }
});

// ── trend / weakness ──────────────────────────────────────────────
function lineConfig(labels, data, label) {
  return {
    type: "line",
    data: { labels, datasets: [{ label, data, borderColor: "#5b8cff",
      backgroundColor: "rgba(91,140,255,.15)", fill: true, tension: 0.25, pointRadius: 5, pointBackgroundColor: "#38d39f" }] },
    options: { plugins: { legend: { labels: { color: "#9aa7b8" } } },
      scales: { x: { ticks: { color: "#9aa7b8" }, grid: { color: "#2a3342" } },
                y: { ticks: { color: "#9aa7b8" }, grid: { color: "#2a3342" }, beginAtZero: true } } },
  };
}
async function loadTrend() {
  const metric = $("metricSelect").value;
  const rows = await fetch("/api/sessions").then((r) => r.json());
  if (!rows.length) { $("trendEmpty").classList.remove("hidden"); if (trendChart) { trendChart.destroy(); trendChart = null; } return; }
  $("trendEmpty").classList.add("hidden");
  const cfg = lineConfig(rows.map((r) => r.date), rows.map((r) => r[metric]), metric);
  if (trendChart) { trendChart.data = cfg.data; trendChart.update(); } else trendChart = new Chart($("trendChart"), cfg);
}
$("metricSelect").addEventListener("change", loadTrend);
$("refreshTrend").addEventListener("click", loadTrend);

async function loadWeaknesses(elId) {
  const data = await fetch("/api/weaknesses").then((r) => r.json());
  const el = $(elId);
  if (!data.categories || !data.categories.length) { el.innerHTML = `<span class="hint">아직 기록된 오류가 없습니다.</span>`; return; }
  const max = Math.max(...data.categories.map((c) => c.total));
  el.innerHTML = `<p class="hint">${data.sessions}개 세션 누적 · 최신 ${data.latest}</p>` +
    data.categories.map((c) => {
      const earlier = (c.total - c.latest) / Math.max(data.sessions - 1, 1);
      const arrow = data.sessions > 1 ? (c.latest < earlier ? `<span class="down">▼ 개선</span>` : c.latest > earlier ? `<span class="up">▲ 증가</span>` : "—") : "";
      return `<div class="wrow"><span class="cat">${CAT_KO[c.category] || c.category}</span>
        <span class="bar"><span style="width:${(c.total / max) * 100}%"></span></span>
        <span class="num">${c.total}회 ${arrow}</span></div>`;
    }).join("");
}

// ── vocab ─────────────────────────────────────────────────────────
async function loadVocab() {
  const rows = await fetch("/api/vocab").then((r) => r.json());
  const el = $("vocab");
  if (!rows.length) { el.innerHTML = `<span class="hint">단어장이 비어 있습니다.</span>`; return; }
  const groups = {};
  rows.forEach((v) => { (groups[v.theme || "기타"] ||= []).push(v); });
  el.innerHTML = Object.entries(groups).map(([theme, items]) =>
    `<div class="vgroup"><div class="vtheme">${escapeHtml(theme)}</div>` +
    items.map((v) => `<div class="vitem"><span class="w">${escapeHtml(v.word)}</span>
      <span class="n">${escapeHtml(v.note || "")}</span>
      <span class="badge ${v.status}" data-word="${escapeHtml(v.word)}" data-status="${v.status}">${v.status === "known" ? "외움 ✓" : "학습중"}</span></div>`).join("") +
    `</div>`).join("");
  el.querySelectorAll(".badge").forEach((b) => b.addEventListener("click", async () => {
    const next = b.dataset.status === "known" ? "learning" : "known";
    await fetch("/api/vocab/mark", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ word: b.dataset.word, status: next }) });
    loadVocab();
  }));
}

// ── practice ──────────────────────────────────────────────────────
$("genPractice").addEventListener("click", async () => {
  const btn = $("genPractice");
  btn.disabled = true;
  $("practiceArea").innerHTML = `<p class="hint"><span class="spinner"></span>연습문제 생성 중…</p>`;
  try {
    const data = await fetch("/api/practice", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ focus: $("focusSelect").value }) }).then((r) => r.json());
    if (data.error) { $("practiceArea").innerHTML = `<p class="hint">${data.error}</p>`; return; }
    const qs = data.questions.map((q, i) => `<div class="pq"><span class="qtext">${i + 1}. ${escapeHtml(q)}</span><input data-i="${i}" placeholder="정답" /></div>`).join("");
    $("practiceArea").innerHTML = `<p class="hint">연습 #${data.practice_id} · 주제: ${data.focus}</p>${qs}<button id="gradeBtn">채점하기</button><div id="practiceResult"></div>`;
    $("practiceArea").dataset.pid = data.practice_id;
    $("gradeBtn").addEventListener("click", gradePractice);
  } catch (e) { $("practiceArea").innerHTML = `<p class="hint">생성 실패: ${e.message}</p>`; }
  finally { btn.disabled = false; }
});
async function gradePractice() {
  const pid = Number($("practiceArea").dataset.pid);
  const responses = [...$("practiceArea").querySelectorAll("input")].map((i) => i.value);
  const data = await fetch("/api/practice/grade", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ practice_id: pid, responses }) }).then((r) => r.json());
  let el = $("practiceResult");
  if (!el) { el = document.createElement("div"); el.id = "practiceResult"; $("practiceArea").appendChild(el); }
  el.className = "practice-result";
  el.textContent = data.result || data.error || "오류";
  loadPracticeHistory();
}

// manual vocab add
$("vAdd").addEventListener("click", async () => {
  const word = $("vWord").value.trim();
  if (!word) return;
  await fetch("/api/vocab", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ word, theme: $("vTheme").value.trim(), note: $("vNote").value.trim() }) });
  $("vWord").value = $("vTheme").value = $("vNote").value = "";
  loadVocab();
});

// recommend the top recurring weakness as the practice focus
async function recommendFocus() {
  const data = await fetch("/api/weaknesses").then((r) => r.json());
  const top = data.categories?.[0]?.category;
  const sel = $("focusSelect");
  if (top && [...sel.options].some((o) => o.value === top)) {
    sel.value = top;
    $("focusReco").textContent = `추천: 반복 실수 1위는 "${CAT_KO[top] || top}" 입니다. 이걸로 연습해 보세요.`;
  } else { $("focusReco").textContent = ""; }
}

async function loadPracticeHistory() {
  const rows = await fetch("/api/practice/history").then((r) => r.json());
  const el = $("practiceHistory");
  if (!rows.length) { el.innerHTML = `아직 채점한 연습이 없습니다.`; return; }
  el.innerHTML = `<table class="dx-ex"><tr><th>연습</th><th>주제</th><th>점수</th></tr>` +
    rows.map((p) => `<tr><td>#${p.practice_id}</td><td>${CAT_KO[p.focus] || escapeHtml(p.focus)}</td><td>${p.score}/${p.total}</td></tr>`).join("") + `</table>`;
}

// ── history ───────────────────────────────────────────────────────
let _analyses = {};
async function loadHistory() {
  const rows = await fetch("/api/analyses").then((r) => r.json());
  _analyses = Object.fromEntries(rows.map((a) => [a.id, a]));
  // dropdown in analyze view
  const sel = $("historySelect");
  if (sel) sel.innerHTML = `<option value="">지난 분석 ▾</option>` +
    rows.map((a) => `<option value="${a.id}">${a.created || "(날짜없음)"} · ${escapeHtml(a.filename)}</option>`).join("");
  // list in history view
  const list = $("histList");
  if (list) {
    if (!rows.length) { list.innerHTML = `<span class="hint">기록이 없습니다.</span>`; }
    else list.innerHTML = rows.map((a) =>
      `<div class="hitem" data-id="${a.id}"><div class="hfile">${escapeHtml(a.filename)}</div>
        <div class="hmeta">${a.created || "(날짜없음)"} · 화자 ${escapeHtml(a.speaker)}</div></div>`).join("");
    list.querySelectorAll(".hitem").forEach((it) => it.addEventListener("click", () => {
      list.querySelectorAll(".hitem").forEach((x) => x.classList.remove("active"));
      it.classList.add("active");
      const a = _analyses[it.dataset.id];
      renderMetrics(a.metrics, "histMetrics");
      renderDiagnosis(a.diagnosis, "histReport");
    }));
  }
}
$("historySelect")?.addEventListener("change", (e) => {
  const a = _analyses[e.target.value];
  if (!a) return;
  $("status").textContent = `저장된 분석 · ${a.created || ""} · ${a.filename}`;
  renderMetrics(a.metrics, "metrics");
  renderDiagnosis(a.diagnosis, "report");
  $("reportWrap").classList.remove("hidden");
});

// ── dashboard ─────────────────────────────────────────────────────
async function loadDashboard() {
  const [sessions, vocab, analyses] = await Promise.all([
    fetch("/api/sessions").then((r) => r.json()),
    fetch("/api/vocab").then((r) => r.json()),
    fetch("/api/analyses").then((r) => r.json()),
  ]);
  const last = sessions[sessions.length - 1];
  $("dashStats").innerHTML = [
    metricCard(sessions.length, "기록된 세션", ""),
    metricCard(last ? last.filler_rate : "—", "최근 필러/100단어", last && last.filler_rate > 10 ? "bad" : "good"),
    metricCard(last ? last.type_token_ratio : "—", "최근 어휘 다양성", "good"),
    metricCard(vocab.length, "단어장 단어 수", ""),
  ].join("");
  // mini filler chart
  if (sessions.length) {
    $("dashChartEmpty").classList.add("hidden");
    const cfg = lineConfig(sessions.map((r) => r.date), sessions.map((r) => r.filler_rate), "filler_rate");
    if (dashChart) { dashChart.data = cfg.data; dashChart.update(); } else dashChart = new Chart($("dashChart"), cfg);
  } else { $("dashChartEmpty").classList.remove("hidden"); }
  loadWeaknesses("dashWeak");
  // recent analysis
  const recent = analyses[0];
  $("dashRecent").innerHTML = recent
    ? `<div class="hfile">${escapeHtml(recent.filename)}</div>
       <p class="hint">${recent.created || "(날짜없음)"} · 화자 ${escapeHtml(recent.speaker)}</p>
       <p>${escapeHtml((recent.diagnosis?.summary || "").slice(0, 160))}…</p>
       <a class="link" data-view="history" id="dashRecentLink">자세히 보기 →</a>`
    : `<span class="hint">아직 분석 기록이 없습니다. "분석하기"에서 시작하세요.</span>`;
  $("dashRecentLink")?.addEventListener("click", () => showView("history"));
}

// ── init ──────────────────────────────────────────────────────────
renderMetrics(null, "metrics");
loadSamples();
const start = (location.hash || "#dashboard").slice(1);
showView(["dashboard", "analyze", "progress", "vocab", "practice", "history"].includes(start) ? start : "dashboard");
