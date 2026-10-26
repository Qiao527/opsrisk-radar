// OpsRisk Radar dashboard. Feed text is untrusted: it is only ever inserted
// with textContent, and links are limited to https URLs.
"use strict";

const SEV_RANK = { CRITICAL: 3, HIGH: 2, MEDIUM: 1, LOW: 0 };
const state = { meta: null, latest: [], current: [], labels: {} };

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null) continue;
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function safeUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}

async function getJSON(path) {
  const resp = await fetch(path, { cache: "no-cache" });
  if (!resp.ok) throw new Error(`${path}: HTTP ${resp.status}`);
  return resp.json();
}

function fmtTime(iso) {
  if (!iso) return "unknown";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function fmtDate(iso) {
  return iso ? iso.slice(0, 10) : "n/a";
}

function sevBadge(sev) {
  return el("span", { class: `sev sev-${sev}` }, sev === "CRITICAL" ? "Critical" : sev.charAt(0) + sev.slice(1).toLowerCase());
}

function catLabel(c) {
  return state.labels[c] || c;
}

// ---------------------------------------------------------------- banner

function showBanner(meta, status) {
  const banner = document.getElementById("banner");
  const msgs = [];
  let warn = false;
  if (meta.data_label !== "live") {
    warn = true;
    msgs.push(`This page shows ${meta.data_label} data, not live monitoring output.`);
  }
  const genAgeH = (Date.now() - new Date(meta.generated_at).getTime()) / 3.6e6;
  if (meta.stale || genAgeH > meta.stale_after_hours) {
    warn = true;
    const age = status && status.hours_since_success != null
      ? `${Math.round(Math.max(status.hours_since_success, genAgeH))} hours`
      : "an unknown time";
    msgs.push(`Data is stale: the last successful pipeline run was ${age} ago. Treat these events as historical.`);
  }
  if (!warn) {
    msgs.push("Automated, unreviewed scoring of public headlines. Verify with the original article before acting.");
  }
  banner.textContent = msgs.join(" ");
  banner.className = warn ? "banner" : "banner info";
  banner.hidden = false;
}

// -------------------------------------------------------------- briefing

function renderBriefing(articles, meta) {
  const counts = { HIGH: 0, MEDIUM: 0, LOW: 0 };
  for (const a of articles) counts[a.severity === "CRITICAL" ? "HIGH" : a.severity]++;
  const kpis = document.getElementById("kpis");
  kpis.replaceChildren(
    el("div", { class: "kpi" }, el("b", {}, counts.HIGH), el("span", {}, "High or critical")),
    el("div", { class: "kpi" }, el("b", {}, counts.MEDIUM), el("span", {}, "Medium")),
    el("div", { class: "kpi" }, el("b", {}, counts.LOW), el("span", {}, "Low")),
    el("div", { class: "kpi" }, el("b", {}, articles.length), el("span", {}, "Distinct stories, 7 days")),
  );
  document.getElementById("briefing-meta").textContent =
    `Stories first seen in the 7 days to ${fmtTime(meta.generated_at)}. Scorer: ${meta.scorer || "n/a"}.`;
  const top = articles.filter((a) => SEV_RANK[a.severity] >= 2).slice(0, 5);
  const list = document.getElementById("brief-list");
  list.replaceChildren(...top.map((a) => {
    const href = safeUrl(a.url);
    return el("li", {},
      sevBadge(a.severity), " ",
      href ? el("a", { href, rel: "noopener noreferrer", target: "_blank" }, a.title) : a.title,
      el("div", { class: "why" }, `${a.source} · ${a.reason}`),
    );
  }));
  document.getElementById("brief-empty").hidden = top.length > 0;
}

// ---------------------------------------------------------------- events

function eventItem(a) {
  const href = safeUrl(a.url);
  const meta = [a.source, `published ${fmtDate(a.published)}`, `first seen ${fmtDate(a.first_seen)}`];
  if (a.also_reported_by.length) meta.push(`also: ${a.also_reported_by.join(", ")}`);
  const evidence = a.evidence.length
    ? el("dd", {}, ...a.evidence.flatMap((q, i) => [i ? " · " : "", el("span", { class: "quote" }, q)]))
    : el("dd", {}, "none");
  return el("li", { class: "event" },
    el("div", { class: "event-head" },
      sevBadge(a.severity),
      el("div", {},
        href ? el("a", { class: "event-title", href, rel: "noopener noreferrer", target: "_blank" }, a.title)
             : el("span", { class: "event-title" }, a.title),
        el("div", { class: "event-meta" }, meta.join(" · ")),
      ),
    ),
    el("details", {},
      el("summary", {}, `Why ${a.score.toFixed(2)}?`),
      el("dl", {},
        el("dt", {}, "Reason"), el("dd", {}, a.reason || "n/a"),
        el("dt", {}, "Categories"), el("dd", {}, a.categories.map(catLabel).join(", ") || "none"),
        el("dt", {}, "Status"), el("dd", {}, a.status || "n/a"),
        el("dt", {}, "Evidence"), evidence,
        el("dt", {}, "Method"), el("dd", {}, a.method),
        a.flags.length ? el("dt", {}, "Checks") : null,
        a.flags.length ? el("dd", {}, a.flags.join("; ")) : null,
        el("dt", {}, "Summary"), el("dd", {}, a.summary || "none"),
      ),
    ),
  );
}

function fillSelect(id, values, labelFn = (v) => v) {
  const sel = document.getElementById(id);
  const keep = sel.value;
  sel.replaceChildren(sel.options[0], ...values.map((v) => el("option", { value: v }, labelFn(v))));
  if (values.includes(keep)) sel.value = keep;
}

function refreshFilterOptions() {
  const cats = [...new Set(state.current.flatMap((a) => a.categories))].sort();
  const srcs = [...new Set(state.current.map((a) => a.source))].sort();
  fillSelect("f-cat", cats, catLabel);
  fillSelect("f-src", srcs);
}

function applyFilters() {
  const q = document.getElementById("f-q").value.trim().toLowerCase();
  const sev = document.getElementById("f-sev").value;
  const cat = document.getElementById("f-cat").value;
  const src = document.getElementById("f-src").value;
  const shown = state.current.filter((a) => {
    if (q && !`${a.title} ${a.summary} ${a.source}`.toLowerCase().includes(q)) return false;
    if (sev === "HIGH" && SEV_RANK[a.severity] < 2) return false;
    if (sev === "MEDIUM" && SEV_RANK[a.severity] < 1) return false;
    if (sev === "LOW" && a.severity !== "LOW") return false;
    if (cat && !a.categories.includes(cat)) return false;
    if (src && a.source !== src) return false;
    return true;
  });
  document.getElementById("count").textContent = `${shown.length} of ${state.current.length} stories`;
  document.getElementById("event-list").replaceChildren(...shown.map(eventItem));
}

async function selectDay(day) {
  if (!day) {
    state.current = state.latest;
  } else {
    try {
      state.current = (await getJSON(`data/history/${day}.json`)).articles;
    } catch (err) {
      state.current = [];
      document.getElementById("count").textContent = `Could not load ${day}: ${err.message}`;
      return;
    }
  }
  refreshFilterOptions();
  applyFilters();
}

// --------------------------------------------------------------- history

function renderHistory(index) {
  const tbody = document.querySelector("#day-table tbody");
  tbody.replaceChildren(...index.days.map((d) => el("tr", {},
    el("td", {}, d.date),
    el("td", { class: "num" }, d.count),
    el("td", { class: "num" }, d.severity.CRITICAL + d.severity.HIGH),
    el("td", { class: "num" }, d.severity.MEDIUM),
    el("td", { class: "num" }, d.severity.LOW),
  )));
  fillSelect("f-day", index.days.map((d) => d.date), (v) => `Day ${v}`);
  const weekSel = document.getElementById("f-week");
  weekSel.replaceChildren(...index.weeks.map((w) => el("option", { value: w.week }, `${w.week} (${w.start} – ${w.end})`)));
  weekSel.onchange = () => renderWeek(weekSel.value);
  if (index.weeks.length) renderWeek(index.weeks[0].week);
  else document.getElementById("week-view").textContent = "No weekly data yet.";
}

async function renderWeek(week) {
  const view = document.getElementById("week-view");
  try {
    const w = await getJSON(`data/weekly/${week}.json`);
    view.replaceChildren(
      el("p", {}, `${w.total} stories from ${w.source_count} sources: ${w.severity.high} high+, ${w.severity.medium} medium, ${w.severity.low} low.`),
      el("h4", {}, "Highest-scored"),
      el("ol", {}, ...w.top.map((a) => el("li", {}, sevBadge(a.severity), " ", a.title))),
      el("h4", {}, "Headline themes"),
      w.themes.length
        ? el("ul", {}, ...w.themes.map((t) => el("li", {}, `${t.name}: ${t.count} (${t.pct}%)`)))
        : el("p", { class: "muted" }, "No themed headlines."),
    );
  } catch (err) {
    view.textContent = `Could not load week ${week}: ${err.message}`;
  }
}

// ---------------------------------------------------------------- status

function renderStatus(status) {
  const last = status.last_run;
  const ok = status.last_successful_run;
  const summary = document.getElementById("status-summary");
  if (!last) {
    summary.textContent = "No pipeline runs recorded.";
    return;
  }
  const failed = status.feeds.filter((f) => f.status !== "ok").length;
  summary.replaceChildren(
    `Latest run #${last.id} started ${fmtTime(last.started_at)}: `,
    el("strong", { class: last.status === "failed" ? "bad" : "ok" }, last.status),
    `. ${status.feeds.length - failed}/${status.feeds.length} feeds succeeded. `,
    ok ? `Last successful run finished ${fmtTime(ok.finished_at)}.` : "No successful run yet.",
  );
  document.querySelector("#feed-table tbody").replaceChildren(...status.feeds.map((f) => el("tr", {},
    el("td", {}, f.source_name),
    el("td", { class: f.status === "ok" ? "" : "bad" }, f.status === "ok" ? "ok" : `${f.status} ${f.error || ""}`),
    el("td", { class: "num" }, f.entries),
    el("td", { class: "num" }, f.attempts),
    el("td", { class: "num" }, `${(f.duration_ms / 1000).toFixed(1)} s`),
  )));
  document.querySelector("#run-table tbody").replaceChildren(...status.runs.map((r) => el("tr", {},
    el("td", {}, `#${r.id}`),
    el("td", {}, (r.started_at || "").replace("T", " ")),
    el("td", { class: r.status === "failed" ? "bad" : "" }, r.status),
    el("td", { class: "num" }, r.stats.new ?? "-"),
    el("td", {}, r.scorer || "-"),
    el("td", {}, (r.git_sha || "").slice(0, 7)),
  )));
}

// ------------------------------------------------------------------ main

async function main() {
  try {
    const [latest, status, index] = await Promise.all([
      getJSON("data/latest.json"), getJSON("data/status.json"), getJSON("data/history/index.json"),
    ]);
    state.meta = latest.meta;
    state.labels = latest.meta.category_labels || {};
    state.latest = latest.articles;
    showBanner(latest.meta, status);
    renderBriefing(latest.articles, latest.meta);
    renderHistory(index);
    renderStatus(status);
    await selectDay("");
    document.getElementById("footer-meta").textContent =
      `Generated ${fmtTime(latest.meta.generated_at)} by OpsRisk Radar v${latest.meta.version}.`;
  } catch (err) {
    const banner = document.getElementById("banner");
    banner.textContent = `Dashboard data could not be loaded (${err.message}). The pipeline may not have published yet.`;
    banner.className = "banner";
    banner.hidden = false;
    return;
  }
  for (const id of ["f-q", "f-sev", "f-cat", "f-src"]) {
    document.getElementById(id).addEventListener("input", applyFilters);
  }
  document.getElementById("f-day").addEventListener("change", (e) => selectDay(e.target.value));
}

main();
