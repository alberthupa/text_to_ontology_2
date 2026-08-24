"""Render one report dictionary as a self-contained educational HTML page.

The page has two jobs and keeps them visibly apart: it explains how each view
is derived, and it shows what this particular graph currently contains. It is
one file with no external assets, so it can be opened straight from disk or
mailed to someone.

Only `view_report.build_report` output is read here. Nothing touches the graph.
"""

import html
import json

from .view_report import build_report


PAGE_STYLE = """
:root {
  --bg: #0e1420; --panel: #161f31; --panel-2: #1c2740; --border: #2a3854;
  --text: #e7edf7; --muted: #93a2bf; --accent: #5aa9ff; --accent-2: #7ee0c0;
  --warn: #ffc46b; --rose: #ff7aa2; --violet: #b39cff;
  --mono: "SFMono-Regular", ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; line-height: 1.55; color: var(--text);
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background: radial-gradient(1200px 600px at 80% -10%, #1b2a4a 0%, var(--bg) 55%);
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 24px 20px 90px; }

header.hero { padding: 22px 0 16px; border-bottom: 1px solid var(--border); }
.kicker { font-family: var(--mono); font-size: 12px; letter-spacing: .16em;
  text-transform: uppercase; color: var(--accent); margin: 0 0 8px; }
h1 { margin: 0; font-size: 36px; line-height: 1.15; letter-spacing: -.02em; }
.subtitle { color: var(--muted); margin: 10px 0 0; max-width: 820px; }
.pill-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.pill { font-family: var(--mono); font-size: 12px; border: 1px solid var(--border);
  background: var(--panel); padding: 4px 10px; border-radius: 999px; color: var(--muted); }
.pill b { color: var(--text); font-weight: 600; }

nav.toc { position: sticky; top: 0; z-index: 20; margin: 0 -20px 8px;
  padding: 10px 20px; background: rgba(14,20,32,.92); backdrop-filter: blur(6px);
  border-bottom: 1px solid var(--border); display: flex; flex-wrap: wrap; gap: 6px; }
nav.toc a { font-family: var(--mono); font-size: 12px; color: var(--muted);
  border: 1px solid transparent; padding: 3px 9px; border-radius: 8px; }
nav.toc a:hover { color: var(--text); border-color: var(--border);
  background: var(--panel); text-decoration: none; }

section { margin: 46px 0; scroll-margin-top: 64px; }
h2 { font-size: 23px; display: flex; align-items: center; gap: 10px;
  border-bottom: 1px solid var(--border); padding-bottom: 10px; }
h2 .num { font-family: var(--mono); font-size: 13px; color: var(--bg);
  background: var(--accent); border-radius: 7px; padding: 2px 8px; font-weight: 700; }
h3 { font-size: 17px; margin: 26px 0 8px; }
h4 { font-size: 14px; margin: 18px 0 6px; color: var(--muted);
  font-family: var(--mono); text-transform: uppercase; letter-spacing: .08em; }
p { max-width: 900px; }
p.lead { color: var(--muted); max-width: 920px; }

.card { background: var(--panel); border: 1px solid var(--border);
  border-radius: 12px; padding: 16px 18px; }
.grid { display: grid; gap: 14px; align-items: start; }
.grid.two { grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
.grid.three { grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }
.grid.five { grid-template-columns: repeat(auto-fit, minmax(188px, 1fr)); }

.note { background: linear-gradient(180deg, var(--panel-2), var(--panel));
  border: 1px solid var(--border); border-left: 4px solid var(--accent-2);
  border-radius: 12px; padding: 14px 18px; margin: 16px 0; }
.note.warn { border-left-color: var(--warn); }
.note.rose { border-left-color: var(--rose); }
.note b { color: var(--accent-2); }
.note.warn b { color: var(--warn); }
.note.rose b { color: var(--rose); }

.stat { background: var(--panel); border: 1px solid var(--border);
  border-radius: 12px; padding: 14px 16px; }
.stat .n { font-size: 28px; font-weight: 700; font-family: var(--mono); }
.stat .k { font-family: var(--mono); font-size: 12px; color: var(--muted);
  text-transform: uppercase; letter-spacing: .08em; }
.stat .d { color: var(--muted); font-size: 13px; margin-top: 6px; }
.stat.schema .n { color: var(--accent); }
.stat.instance .n { color: var(--accent-2); }
.stat.support .n { color: var(--warn); }
.stat.skeleton .n { color: var(--violet); }
.stat.patterns .n { color: var(--rose); }

.bar { display: flex; height: 26px; border-radius: 8px; overflow: hidden;
  border: 1px solid var(--border); margin: 12px 0 6px; }
.bar span { display: flex; align-items: center; justify-content: center;
  font-family: var(--mono); font-size: 11px; color: #0b1220; font-weight: 700; }
.bar .schema { background: var(--accent); }
.bar .instance { background: var(--accent-2); }
.bar .support { background: var(--warn); }
.legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 13px; color: var(--muted); }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 3px;
  margin-right: 6px; }

.diagram { background: var(--panel); border: 1px solid var(--border);
  border-radius: 14px; padding: 18px; overflow-x: auto; }
.diagram svg { display: block; min-width: 860px; }

code, .mono { font-family: var(--mono); font-size: 12.5px; }
code { background: #111827; border: 1px solid var(--border); border-radius: 5px;
  padding: 1px 6px; color: #d6e2f5; }
pre { background: #111827; border: 1px solid var(--border); border-radius: 10px;
  padding: 12px 14px; overflow-x: auto; font-family: var(--mono); font-size: 12.5px;
  color: #d6e2f5; }

table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--border);
  vertical-align: top; }
th { color: var(--muted); font-family: var(--mono); font-size: 11.5px;
  text-transform: uppercase; letter-spacing: .06em; position: sticky; top: 0;
  background: var(--panel); z-index: 5; }
th.sortable { cursor: pointer; user-select: none; }
th.sortable:hover { color: var(--text); }
tbody tr:hover { background: var(--panel-2); }
.scroll { max-height: 620px; overflow: auto; border: 1px solid var(--border);
  border-radius: 12px; background: var(--panel); }

.controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  background: var(--panel-2); border: 1px solid var(--border); border-radius: 12px;
  padding: 12px 14px; margin: 14px 0; }
.controls label { font-size: 12.5px; color: var(--muted); display: flex;
  align-items: center; gap: 7px; }
input[type=search], input[type=text], select {
  background: #0f1725; color: var(--text); border: 1px solid var(--border);
  border-radius: 8px; padding: 6px 10px; font-size: 13px; font-family: inherit; }
input[type=search] { min-width: 240px; }
input[type=range] { accent-color: var(--accent); }
button { background: var(--panel); color: var(--text); border: 1px solid var(--border);
  border-radius: 8px; padding: 6px 12px; font-size: 12.5px; cursor: pointer;
  font-family: inherit; }
button:hover { border-color: var(--accent); }
button.on { background: var(--accent); color: #0b1220; border-color: var(--accent);
  font-weight: 600; }
button.on.instance { background: var(--accent-2); border-color: var(--accent-2); }
button.on.support { background: var(--warn); border-color: var(--warn); }
.count { font-family: var(--mono); font-size: 12px; color: var(--muted);
  margin-left: auto; }

.tag { font-family: var(--mono); font-size: 11px; border-radius: 6px;
  padding: 1px 7px; border: 1px solid var(--border); color: var(--muted);
  display: inline-block; white-space: nowrap; }
.tag.schema { color: var(--accent); border-color: #24507f; }
.tag.instance { color: var(--accent-2); border-color: #1f5e51; }
.tag.support { color: var(--warn); border-color: #6b5223; }
.tag.literal { color: var(--accent-2); border-color: #1f5e51; }
.tag.uri { color: var(--accent); border-color: #24507f; }
.tag.blank { color: var(--violet); border-color: #453a75; }
.tag.accept { color: var(--accent-2); border-color: #1f5e51; }
.tag.duplicate { color: var(--muted); }
.tag.review, .tag.partial_review { color: var(--warn); border-color: #6b5223; }
.muted { color: var(--muted); }
.small { font-size: 12.5px; }

.covbar { display: inline-block; width: 64px; height: 7px; border-radius: 4px;
  background: #22304a; vertical-align: middle; margin-right: 7px; overflow: hidden; }
.covbar i { display: block; height: 100%; background: var(--rose); }

.entity { background: var(--panel); border: 1px solid var(--border);
  border-radius: 12px; padding: 12px 14px; }
.entity h5 { margin: 0 0 4px; font-size: 15px; }
.entity .uri { font-family: var(--mono); font-size: 11.5px; color: var(--muted); }
.entity ul { margin: 6px 0 0; padding-left: 18px; font-size: 13px; }
.entity li { margin: 2px 0; }
.entity .p { color: var(--accent); font-family: var(--mono); font-size: 12px; }

details { border: 1px solid var(--border); border-radius: 10px; padding: 10px 14px;
  background: var(--panel); margin: 10px 0; }
details summary { cursor: pointer; font-weight: 600; }
details[open] summary { margin-bottom: 8px; }

ol.ladder { counter-reset: rule; list-style: none; padding-left: 0; max-width: 920px; }
ol.ladder li { counter-increment: rule; position: relative; padding: 10px 12px 10px 46px;
  border: 1px solid var(--border); border-radius: 10px; margin: 8px 0;
  background: var(--panel); font-size: 14px; }
ol.ladder li::before { content: counter(rule); position: absolute; left: 12px; top: 10px;
  font-family: var(--mono); font-size: 12px; font-weight: 700; color: #0b1220;
  background: var(--muted); border-radius: 6px; padding: 1px 7px; }

dl.glossary { display: grid; grid-template-columns: minmax(140px, 210px) 1fr;
  gap: 8px 18px; font-size: 14px; max-width: 980px; }
dl.glossary dt { font-family: var(--mono); color: var(--accent); font-size: 13px; }
dl.glossary dd { margin: 0; color: var(--text); }
footer { margin-top: 60px; padding-top: 18px; border-top: 1px solid var(--border);
  color: var(--muted); font-size: 13px; }
@media (max-width: 640px) {
  dl.glossary { grid-template-columns: 1fr; }
  .count { margin-left: 0; }
}
"""


PAGE_SCRIPT = r"""
const $ = (id) => document.getElementById(id);
const esc = (text) => String(text).replace(/[&<>"]/g,
  (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const clip = (text, limit) => text.length > limit ? text.slice(0, limit) + '…' : text;

/* ---------- 2. triple browser ---------- */
const TRIPLE_PAGE = 300;
let tripleViews = new Set(['schema', 'instance', 'support']);
let tripleShown = TRIPLE_PAGE;

function tripleMatches() {
  const needle = $('t-search').value.trim().toLowerCase();
  return DATA.triples.filter((row) => {
    if (!tripleViews.has(row[0])) return false;
    if (!needle) return true;
    return (row[1] + ' ' + row[3] + ' ' + row[4]).toLowerCase().includes(needle);
  });
}

function renderTriples() {
  const rows = tripleMatches();
  const slice = rows.slice(0, tripleShown);
  $('t-body').innerHTML = slice.map((row) => `<tr>
      <td><span class="tag ${row[0]}">${row[0]}</span></td>
      <td class="mono">${esc(row[1])}</td>
      <td class="mono">${esc(row[3])}</td>
      <td class="mono">${esc(clip(row[4], 160))}</td>
      <td><span class="tag ${row[5]}">${esc(row[6])}</span></td>
    </tr>`).join('');
  $('t-count').textContent = `${rows.length} of ${DATA.triples.length} triples shown`;
  $('t-more').style.display = rows.length > slice.length ? 'inline-block' : 'none';
  $('t-more').textContent = `show ${Math.min(TRIPLE_PAGE, rows.length - slice.length)} more`;
}

function toggleView(button, view) {
  if (tripleViews.has(view)) { tripleViews.delete(view); button.classList.remove('on'); }
  else { tripleViews.add(view); button.classList.add('on'); }
  tripleShown = TRIPLE_PAGE;
  renderTriples();
}

/* ---------- 3. skeleton ---------- */
function renderSkeleton() {
  const needle = $('s-search').value.trim().toLowerCase();
  const kind = $('s-kind').value;
  const hit = (text) => !needle || text.toLowerCase().includes(needle);

  const showClasses = kind === 'all' || kind === 'classes';
  const classes = showClasses ? DATA.skeleton.classes.filter((item) =>
    hit(item.label + ' ' + item.short + ' ' + item.comment)) : [];
  $('s-classes').innerHTML = classes.map((item) => `<div class="entity">
      <h5>${esc(item.label)} <span class="tag schema">class</span></h5>
      <div class="uri">${esc(item.short)}</div>
      ${item.comment ? `<p class="small muted">${esc(item.comment)}</p>` : ''}
      ${item.parents.length ? `<div class="small">subclass of ${item.parents.map(
        (p) => `<code>${esc(p.short)}</code>`).join(' ')}</div>` :
        '<div class="small muted">no stated parent — a root class</div>'}
      ${item.restrictions.length ? `<ul>${item.restrictions.map(
        (r) => `<li>restricted by <span class="mono">${esc(r)}</span></li>`).join('')}</ul>` : ''}
    </div>`).join('') || '<p class="muted">No class matches.</p>';
  $('s-classes').style.display = showClasses ? 'grid' : 'none';

  const visible = kind === 'classes' ? [] : DATA.skeleton.properties.filter(
    (item) => (kind === 'all' || kind === 'properties' || item.kind === kind) &&
      hit(item.label + ' ' + item.short + ' ' + item.comment));
  $('s-props').innerHTML = visible.map((item) => `<tr>
      <td>${esc(item.label)}<div class="uri mono muted">${esc(item.short)}</div></td>
      <td><span class="tag ${item.kind === 'object' ? 'uri' : 'literal'}">${item.kind}</span></td>
      <td>${item.domain.map((d) => `<code>${esc(d.short)}</code>`).join(' ') ||
        '<span class="muted">not stated</span>'}</td>
      <td>${item.range.map((r) => `<code>${esc(r.short)}</code>`).join(' ') ||
        '<span class="muted">not stated</span>'}</td>
      <td class="small muted">${esc(item.comment)}</td>
    </tr>`).join('');
  $('s-props-wrap').style.display = kind === 'classes' ? 'none' : 'block';
  const shown = [];
  if (showClasses) shown.push(`${classes.length} classes`);
  if (kind !== 'classes') shown.push(`${visible.length} properties`);
  $('s-count').textContent = shown.join(', ') + ' shown';
}

/* ---------- 4. patterns ---------- */
let patternSort = { key: 'occurrences', desc: true };

function patternMatches() {
  const needle = $('p-search').value.trim().toLowerCase();
  const kind = $('p-kind').value;
  const minCoverage = Number($('p-coverage').value) / 100;
  const minOccurrences = Number($('p-occurrences').value);
  return DATA.patterns.filter((row) => {
    if (kind === 'relations' && row.target_kind === 'datatype') return false;
    if (kind === 'literals' && row.target_kind !== 'datatype') return false;
    if ((row.coverage || 0) < minCoverage) return false;
    if (row.occurrences < minOccurrences) return false;
    if (!needle) return true;
    return (row.subject + ' ' + row.predicate + ' ' + row.target)
      .toLowerCase().includes(needle);
  });
}

function renderPatterns() {
  const rows = patternMatches().sort((a, b) => {
    const key = patternSort.key;
    const left = a[key] === null ? -1 : a[key];
    const right = b[key] === null ? -1 : b[key];
    const order = typeof left === 'string' ? left.localeCompare(right) : left - right;
    return patternSort.desc ? -order : order;
  });
  $('p-body').innerHTML = rows.map((row) => {
    const coverage = row.coverage === null ? '<span class="muted">—</span>' :
      `<span class="covbar"><i style="width:${Math.round(row.coverage * 100)}%"></i></span>${
        Math.round(row.coverage * 100)}%`;
    return `<tr>
      <td>${esc(row.subject)}</td>
      <td class="mono" style="color:var(--accent)">${esc(row.predicate)}</td>
      <td>${esc(row.target)} <span class="tag ${
        row.target_kind === 'datatype' ? 'literal' : 'uri'}">${
        row.target_kind === 'datatype' ? 'literal' : row.target_kind}</span></td>
      <td class="mono">${row.occurrences}</td>
      <td class="mono">${row.subjects}</td>
      <td class="mono">${row.population === null ? '—' : row.population}</td>
      <td class="mono">${coverage}</td>
      <td class="mono">${row.min} / ${row.median} / ${row.max}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="8" class="muted">No pattern passes these filters.</td></tr>';
  $('p-count').textContent = `${rows.length} of ${DATA.patterns.length} patterns shown`;
  $('p-coverage-value').textContent = $('p-coverage').value + '%';
  $('p-occurrences-value').textContent = $('p-occurrences').value;
}

function sortPatterns(key) {
  patternSort = { key, desc: patternSort.key === key ? !patternSort.desc : true };
  renderPatterns();
}

/* ---------- 5. instances ---------- */
function renderInstances() {
  const needle = $('i-search').value.trim().toLowerCase();
  const wanted = $('i-class').value;
  const rows = DATA.instances.filter((card) => {
    if (wanted !== 'all' && !card.classes.some((c) => c.short === wanted)) return false;
    if (!needle) return true;
    const text = card.label + ' ' + card.short + ' ' + card.aliases.join(' ') + ' ' +
      card.comment + ' ' + card.relations.map((r) => r.predicate + r.value).join(' ') +
      ' ' + card.facts.map((f) => f.predicate + f.value).join(' ');
    return text.toLowerCase().includes(needle);
  });
  $('i-list').innerHTML = rows.map((card) => `<div class="entity">
      <h5>${esc(card.label)}</h5>
      <div class="uri">${esc(card.short)}</div>
      <div style="margin:6px 0">${card.classes.map(
        (c) => `<span class="tag instance">${esc(c.short)}</span>`).join(' ')}
        ${card.other_types.concat(card.metatypes).map(
          (m) => `<span class="tag">${esc(m)}</span>`).join(' ')}</div>
      ${card.comment ? `<p class="small muted">${esc(card.comment)}</p>` : ''}
      ${card.aliases.length ? `<div class="small muted">also called: ${
        card.aliases.map(esc).join(', ')}</div>` : ''}
      ${card.relations.length ? `<ul>${card.relations.map((r) =>
        `<li><span class="p">${esc(r.predicate)}</span> → ${esc(r.value)}</li>`).join('')}</ul>` : ''}
      ${card.facts.length ? `<ul>${card.facts.map((f) =>
        `<li><span class="p">${esc(f.predicate)}</span> “${esc(clip(f.value, 140))}”</li>`
        ).join('')}</ul>` : ''}
    </div>`).join('') || '<p class="muted">No entity matches.</p>';
  $('i-count').textContent = `${rows.length} of ${DATA.instances.length} entities shown`;
}

/* ---------- 6. provenance ---------- */
function renderCandidates() {
  const needle = $('c-search').value.trim().toLowerCase();
  const decision = $('c-decision').value;
  const section = $('c-section').value;
  const rows = DATA.support.candidates.filter((row) => {
    if (decision !== 'all' && row.decision !== decision) return false;
    if (section !== 'all' && row.section !== section) return false;
    if (!needle) return true;
    return (row.candidate + ' ' + row.resolved + ' ' + row.statement)
      .toLowerCase().includes(needle);
  });
  $('c-body').innerHTML = rows.map((row) => `<tr>
      <td><span class="tag">${esc(row.section)} ${row.index}</span></td>
      <td><span class="tag ${esc(row.decision)}">${esc(row.decision)}</span></td>
      <td class="mono">${row.confidence === null ? '—' : row.confidence.toFixed(2)}</td>
      <td class="small">${esc(row.statement || row.resolved || '—')}</td>
      <td class="mono small">${esc(clip(row.candidate, 190))}</td>
      <td class="small muted">${esc(row.reasons.join(', ') || '—')}</td>
    </tr>`).join('') || '<tr><td colspan="6" class="muted">No record matches.</td></tr>';
  $('c-count').textContent =
    `${rows.length} of ${DATA.support.candidates.length} records shown`;
}

function renderAll() {
  renderTriples(); renderSkeleton(); renderPatterns();
  renderInstances(); renderCandidates();
}
document.addEventListener('DOMContentLoaded', renderAll);
"""


def escape(text):
    """Text safe to place inside the page."""
    return html.escape(str(text))


def pipeline_diagram(counts, total):
    """The derivation, drawn once with this graph's own numbers."""
    return f"""
<svg viewBox="0 0 880 400" role="img" aria-label="How the views are derived">
  <defs>
    <marker id="arrow" markerWidth="9" markerHeight="9" refX="7" refY="3"
            orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#93a2bf"/></marker>
  </defs>
  <g font-family="ui-monospace, monospace" font-size="12" fill="none"
     stroke="#93a2bf" stroke-width="1.4">
    <path d="M440,66 L440,104"/>
    <path d="M150,104 L730,104"/>
    <path d="M150,104 L150,132" marker-end="url(#arrow)"/>
    <path d="M440,104 L440,132" marker-end="url(#arrow)"/>
    <path d="M730,104 L730,132" marker-end="url(#arrow)"/>
    <path d="M110,196 L110,286" marker-end="url(#arrow)"/>
    <path d="M230,196 L230,270 L370,270 L370,286" marker-end="url(#arrow)"/>
    <path d="M440,196 L440,270 L430,270 L430,286" marker-end="url(#arrow)"/>
  </g>
  <g font-family="ui-monospace, monospace" font-size="12" stroke="none">
    <rect x="300" y="14" width="280" height="52" rx="10" fill="#1c2740"
          stroke="#2a3854"/>
    <text x="440" y="36" fill="#e7edf7" font-size="13" text-anchor="middle"
          font-weight="700">the graph file</text>
    <text x="440" y="55" fill="#93a2bf" text-anchor="middle">{total} triples, read only</text>
    <text x="452" y="92" fill="#5aa9ff">partition_graph()</text>

    <rect x="40" y="134" width="220" height="60" rx="10" fill="#161f31" stroke="#24507f"/>
    <text x="150" y="156" fill="#5aa9ff" text-anchor="middle" font-weight="700">schema</text>
    <text x="150" y="175" fill="#93a2bf" text-anchor="middle">{counts['schema']} triples</text>

    <rect x="330" y="134" width="220" height="60" rx="10" fill="#161f31" stroke="#1f5e51"/>
    <text x="440" y="156" fill="#7ee0c0" text-anchor="middle" font-weight="700">instance</text>
    <text x="440" y="175" fill="#93a2bf" text-anchor="middle">{counts['instance']} triples</text>

    <rect x="620" y="134" width="220" height="60" rx="10" fill="#161f31" stroke="#6b5223"/>
    <text x="730" y="156" fill="#ffc46b" text-anchor="middle" font-weight="700">support</text>
    <text x="730" y="175" fill="#93a2bf" text-anchor="middle">{counts['support']} triples</text>

    <text x="30" y="232" fill="#b39cff">create_graph_skeleton()</text>
    <text x="480" y="258" fill="#ff7aa2">observed_relationships()</text>

    <rect x="40" y="288" width="220" height="60" rx="10" fill="#161f31" stroke="#453a75"/>
    <text x="150" y="310" fill="#b39cff" text-anchor="middle" font-weight="700">skeleton</text>
    <text x="150" y="329" fill="#93a2bf" text-anchor="middle">{counts['skeleton']} triples</text>

    <rect x="290" y="288" width="220" height="60" rx="10" fill="#161f31" stroke="#7a2a45"/>
    <text x="400" y="310" fill="#ff7aa2" text-anchor="middle" font-weight="700">patterns</text>
    <text x="400" y="329" fill="#93a2bf" text-anchor="middle">{counts['patterns']} observations</text>

    <text x="590" y="304" fill="#93a2bf">support is kept out of prompts,</text>
    <text x="590" y="322" fill="#93a2bf">out of the skeleton, and out of</text>
    <text x="590" y="340" fill="#93a2bf">every usage statistic.</text>

    <text x="40" y="382" fill="#93a2bf">declared structure</text>
    <text x="290" y="382" fill="#93a2bf">observed evidence</text>
    <text x="590" y="382" fill="#93a2bf">provenance and metadata</text>
  </g>
</svg>"""


def head_section(report):
    """Title, the five headline numbers, and the navigation."""
    graph = report["graph"]
    counts = graph["counts"]
    stats = [
        ("schema", counts["schema"], "declarations and rules"),
        ("instance", counts["instance"], "named things and their statements"),
        ("support", counts["support"], "headers, shapes, provenance"),
        ("skeleton", counts["skeleton"], "the declared structural core"),
        ("patterns", counts["patterns"], "observed usage records"),
    ]
    cards = "".join(
        f'<div class="stat {name}"><div class="k">{name}</div>'
        f'<div class="n">{value}</div><div class="d">{note}</div></div>'
        for name, value, note in stats)
    links = "".join(
        f'<a href="#{anchor}">{title}</a>' for anchor, title in (
            ("read", "0 · How to read this"),
            ("pipeline", "1 · Derivation"),
            ("partitions", "2 · Partitions"),
            ("skeleton", "3 · Skeleton"),
            ("patterns", "4 · Patterns"),
            ("instances", "5 · Instances"),
            ("support", "6 · Provenance"),
            ("controls", "7 · Controls"),
            ("glossary", "8 · Glossary"),
        ))
    return f"""
<nav class="toc">{links}</nav>
<header class="hero">
  <p class="kicker">read-only views of one turtle graph</p>
  <h1>{escape(graph['path'])}</h1>
  <p class="subtitle">Every number on this page was computed by reading the graph
  file and nothing was written back. The page explains how each view is derived
  before it shows you what is in it.</p>
  <div class="pill-row">
    <span class="pill"><b>{graph['triples']}</b> triples in the file</span>
    <span class="pill"><b>{len(report['instances'])}</b> named individuals</span>
    <span class="pill"><b>{len(report['skeleton']['classes'])}</b> declared classes</span>
    <span class="pill"><b>{len(report['skeleton']['properties'])}</b> declared properties</span>
    <span class="pill">generated <b>{graph['generated']}</b></span>
  </div>
</header>
<section id="read">
  <h2><span class="num">0</span> How to read this page</h2>
  <p class="lead">The whole knowledge base is one Turtle file. Everything else —
  the partitions, the skeleton, the patterns — is derived from it in memory,
  every time you look. Nothing here is stored, cached, or written back, so what
  you see is always the current state of that one file.</p>
  <div class="grid five">{cards}</div>
  <h3>A triple is one statement</h3>
  <p>RDF has exactly one kind of sentence: <b>subject → predicate → object</b>.
  “Taiwan” “pursues” “porcupine strategy” is one triple. So is “Taiwan”
  “prefLabel” “Taiwan”. A graph is nothing but a pile of such statements, and
  every count on this page is a count of statements.</p>
  <pre>entity:taiwan   relation:pursues   entity:porcupine-strategy   ← subject, predicate, object (a link)
entity:taiwan   skos:prefLabel     "Taiwan"                    ← subject, predicate, object (a value)</pre>
  <p>An object is either another <b>resource</b> (identified by a URI, so the
  statement is a link) or a <b>literal</b> (a plain value such as a string or a
  date, so the statement is a fact). A third form, the <b>blank node</b>, is an
  anonymous helper resource used to express something that needs several parts
  at once, such as an OWL restriction.</p>
  <div class="note"><b>Prefixes.</b> URIs are long, so they are abbreviated:
  <code>entity:taiwan</code> stands for
  <code>http://example.org/text-ontology/entity/taiwan</code>. The prefix is
  only a display shortcut; the full URI is the real identifier.</div>
</section>"""


def prefix_section(report):
    """The bound prefixes this graph actually uses."""
    rows = "".join(
        f"<tr><td class='mono' style='color:var(--accent)'>{escape(prefix)}:</td>"
        f"<td class='mono muted'>{escape(namespace)}</td></tr>"
        for prefix, namespace in report["graph"]["prefixes"])
    return f"""
<details>
  <summary>The prefixes used on this page</summary>
  <table><thead><tr><th>prefix</th><th>stands for</th></tr></thead>
  <tbody>{rows}</tbody></table>
  <p class="small muted">The <code>onto:</code>, <code>class:</code>,
  <code>entity:</code>, <code>relation:</code> and <code>fact:</code>
  namespaces belong to this project and are defined in
  <code>graph_management.py</code>. The rest are the W3C standards this graph
  is written in.</p>
</details>"""


def pipeline_section(report):
    """The derivation itself: what runs, in what order, and what it may not do."""
    graph = report["graph"]
    counts = graph["counts"]
    lossless = (
        f"{counts['schema']} + {counts['instance']} + {counts['support']} = "
        f"{graph['partitioned']}, and the file holds {graph['triples']}")
    verdict = ("matches exactly, so nothing was dropped or duplicated"
               if graph["partitioned"] == graph["triples"]
               else "does not match — that would be a bug worth reporting")
    return f"""
<section id="pipeline">
  <h2><span class="num">1</span> How the views are derived</h2>
  <p class="lead">Three small read-only modules do all the work. Each one is
  handed a graph and returns a new graph or a list of records; none of them can
  modify what they were given.</p>
  <div class="diagram">{pipeline_diagram(counts, graph['triples'])}</div>
  <div class="grid" style="margin-top:16px;
       grid-template-columns:repeat(auto-fit, minmax(420px, 1fr))">
    <div class="card"><h4>graph_partition.py</h4>
      <p class="small">Reads every statement once and files it under
      <b>schema</b>, <b>instance</b>, or <b>support</b>. A statement it cannot
      classify with confidence goes to support rather than being guessed into
      one of the other two.</p></div>
    <div class="card"><h4>graph_skeleton.py</h4>
      <p class="small">Copies the explicitly declared structure out of the
      schema view: class and property declarations, subclass/domain/range
      axioms, complete supported restrictions, and the labels that name them.
      It never invents a parent, a domain, or a range.</p></div>
    <div class="card"><h4>graph_patterns.py</h4>
      <p class="small">Counts how the instance data actually uses its
      properties, reading class membership from the schema view. The result is
      evidence about the current data, never a rule about future data.</p></div>
    <div class="card"><h4>ontology_views.py</h4>
      <p class="small">Runs those three and hands back all five views as one
      group, so a caller cannot accidentally mix a schema built one way with
      patterns built another.</p></div>
  </div>
  <div class="note"><b>Lossless and non-overlapping.</b> Every triple lands in
  exactly one partition: {lossless} — that {verdict}.</div>
  <div class="note rose"><b>The distinction the whole project turns on.</b>
  <i>Declared</i> structure is what the graph says about itself: this is a
  class, this property has this domain. <i>Observed</i> patterns are what the
  data happens to do right now: 2 of 19 locations carry this property. The
  first is a rule and can be relied on. The second is a measurement and changes
  the moment a new source is added. This page keeps them in separate sections
  and never turns one into the other.</div>
  <h3>Why this exists at all</h3>
  <p>When a new text file is ingested, the model cannot be shown the whole
  graph — it would not fit in the prompt and most of it would be irrelevant.
  These views are how a small, relevant slice is chosen: the skeleton supplies
  the declared vocabulary, the patterns show how that vocabulary is really
  used, the instance view supplies the entities the text might be talking
  about, and the support view is deliberately excluded from all of it.</p>
</section>"""


def partitions_section(report):
    """Partition rules, the classification ladder, and the triple browser."""
    counts = report["graph"]["counts"]
    total = max(report["graph"]["partitioned"], 1)
    bar = "".join(
        f'<span class="{name}" style="width:{counts[name] / total:.4%}">'
        f'{counts[name]}</span>' for name in ("schema", "instance", "support"))
    return f"""
<section id="partitions">
  <h2><span class="num">2</span> Partitions — three ways of looking at the same graph</h2>
  <p class="lead">The partition does not change a single statement. It only
  answers, for each one, the question “what job is this doing?”</p>
  <div class="bar">{bar}</div>
  <div class="legend">
    <span><i style="background:var(--accent)"></i><b>schema</b> — explicit class
      and property definitions, and the rules relating them</span>
    <span><i style="background:var(--accent-2)"></i><b>instance</b> — named
      things, their types, their relations, their facts, their names</span>
    <span><i style="background:var(--warn)"></i><b>support</b> — ontology
      header, SHACL shapes, merge provenance, and anything not safely
      classifiable</span>
  </div>
  <h3>The decision ladder</h3>
  <p>Each statement is tested against these rules in order, from the most
  certain to the least. The first rule that matches decides, and the ladder
  ends in a deliberate fallback rather than a guess.</p>
  <ol class="ladder">
    <li>Does the statement touch <b>supporting material</b> — the ontology
      header, a SHACL shape, an extraction event, a merge candidate, or a blank
      node owned by one of them? → <span class="tag support">support</span></li>
    <li>Does it touch a <b>blank node belonging to no recognized structure</b>?
      → <span class="tag support">support</span>. Half of an expression
      misleads more than none of it, so such statements are kept whole in
      support.</li>
    <li>Is it an <b>rdf:type</b> statement? If the type is a schema type
      (<code>owl:Class</code>, <code>owl:ObjectProperty</code>, …) or
      <code>owl:Restriction</code> → <span class="tag schema">schema</span>.
      Otherwise it is <span class="tag instance">instance</span> when the
      subject is a recognized individual, and
      <span class="tag support">support</span> when it is not.</li>
    <li>Is the subject a <b>recognized OWL restriction</b>?
      → <span class="tag schema">schema</span></li>
    <li>Is the predicate a <b>schema axiom</b> (<code>rdfs:subClassOf</code>,
      <code>rdfs:domain</code>, <code>rdfs:range</code>,
      <code>owl:equivalentClass</code>, …)? →
      <span class="tag schema">schema</span> if the subject really is a schema
      resource, otherwise <span class="tag support">support</span>.</li>
    <li>Is the predicate a <b>naming statement</b> (<code>rdfs:label</code>,
      <code>skos:prefLabel</code>, …)? Then it follows whatever it describes:
      the subject's schema role wins, then its instance role, else
      <span class="tag support">support</span>.</li>
    <li>Anything else → <span class="tag instance">instance</span> if the
      subject is a recognized individual, else
      <span class="tag support">support</span>.</li>
  </ol>
  <div class="note warn"><b>“Recognized individual” is a strict test.</b> A
  resource counts as one only if it is typed with <code>owl:NamedIndividual</code>,
  <code>skos:Concept</code>, or a class the schema view actually declares. A
  resource that is only mentioned, never typed, produces support statements —
  which is exactly the signal that something is under-declared.</div>
  <h3>Browse every statement</h3>
  <p class="small muted">The controls below only change what is displayed. They
  cannot move a statement from one partition to another — that is decided by the
  ladder above, before the page exists.</p>
  <div class="controls">
    <button class="on" onclick="toggleView(this, 'schema')">schema</button>
    <button class="on instance" onclick="toggleView(this, 'instance')">instance</button>
    <button class="on support" onclick="toggleView(this, 'support')">support</button>
    <label>search
      <input type="search" id="t-search" placeholder="taiwan, subClassOf, …"
             oninput="tripleShown = 300; renderTriples()"></label>
    <span class="count" id="t-count"></span>
  </div>
  <div class="scroll">
    <table>
      <thead><tr><th>view</th><th>subject</th><th>predicate</th>
        <th>object</th><th>object is</th></tr></thead>
      <tbody id="t-body"></tbody>
    </table>
  </div>
  <p><button id="t-more" onclick="tripleShown += 300; renderTriples()">show more</button></p>
</section>"""


def skeleton_section(report):
    """What the skeleton keeps, what it refuses, and the current contents."""
    skeleton = report["skeleton"]
    kept = skeleton["triples"]
    schema_total = max(skeleton["schema_triples"], 1)
    share = kept / schema_total
    dropped = skeleton["schema_triples"] - kept
    dropped_note = (
        "Every statement in the schema view qualified this time, so the "
        "skeleton and the schema view are the same size."
        if dropped == 0 else
        f"{dropped} schema statements did not qualify and were left behind — "
        "usually unsupported or incomplete restrictions.")
    restrictions = skeleton["restrictions"]
    restriction_note = (
        "This graph currently declares no OWL restrictions, so that part of the "
        "skeleton is empty. It is not an error: restrictions are optional, and "
        "an extraction pipeline rarely writes them."
        if restrictions == 0 else
        f"This graph carries {restrictions} complete restrictions; each is shown "
        "inline under the class it constrains.")
    return f"""
<section id="skeleton">
  <h2><span class="num">3</span> Skeleton — the small, explicitly declared structure</h2>
  <p class="lead">The skeleton is the part of the schema you could hand to
  someone as “the model”: the classes, the properties, and the axioms that
  relate them. It kept <b>{kept} of {skeleton['schema_triples']}</b> schema
  statements ({share:.0%}). {dropped_note}</p>
  <div class="grid two">
    <div class="card"><h4>What is copied</h4>
      <ul class="small">
        <li><code>owl:Class</code> and <code>rdfs:Class</code> declarations</li>
        <li><code>owl:ObjectProperty</code> and <code>owl:DatatypeProperty</code>
          declarations</li>
        <li><code>rdfs:subClassOf</code>, <code>rdfs:domain</code>,
          <code>rdfs:range</code> between two named resources</li>
        <li>complete, supported OWL restrictions</li>
        <li>the labels, comments, and definitions of everything kept</li>
      </ul></div>
    <div class="card"><h4>What is refused</h4>
      <ul class="small">
        <li>anything <b>inferred</b> — a property never gains a domain it was
          not given</li>
        <li>axioms pointing at blank nodes that are not supported restrictions</li>
        <li>a restriction missing a part, carrying an extra one, or using a form
          outside <code>someValuesFrom</code>, <code>allValuesFrom</code>,
          <code>hasValue</code>, <code>cardinality</code>,
          <code>minCardinality</code>, <code>maxCardinality</code></li>
        <li>a resource that is only mentioned as a range and never declared</li>
      </ul></div>
  </div>
  <div class="note warn"><b>Whole or nothing.</b> A restriction is copied only
  when it is exactly a type, one <code>owl:onProperty</code>, and one supported
  constraint, all pointing at named resources. Half a restriction would read as
  a weaker rule than it is, so it is dropped instead. {restriction_note}</div>
  <div class="controls">
    <label>search
      <input type="search" id="s-search" placeholder="location, pursues, …"
             oninput="renderSkeleton()"></label>
    <label>show
      <select id="s-kind" onchange="renderSkeleton()">
        <option value="all">classes and properties</option>
        <option value="classes">classes only</option>
        <option value="properties">properties only</option>
        <option value="object">object properties only</option>
        <option value="datatype">datatype properties only</option>
      </select></label>
    <span class="count" id="s-count"></span>
  </div>
  <h4>Declared classes</h4>
  <div class="grid two" id="s-classes"></div>
  <div id="s-props-wrap">
    <h4>Declared properties</h4>
    <p class="small muted">An <b>object property</b> links two resources; a
    <b>datatype property</b> attaches a literal value. “not stated” below means
    exactly that — the graph never says it, and the skeleton refuses to invent
    it.</p>
    <div class="scroll">
      <table><thead><tr><th>property</th><th>kind</th><th>domain</th>
        <th>range</th><th>description</th></tr></thead>
        <tbody id="s-props"></tbody></table>
    </div>
  </div>
</section>"""


def worked_example(patterns):
    """One real pattern, narrated number by number."""
    usable = [row for row in patterns if row["coverage"] is not None]
    if not usable:
        return ""
    row = max(usable, key=lambda item: (item["occurrences"], item["subjects"]))
    coverage = f"{row['coverage']:.0%}"
    population = row["population"]
    target = ("a literal value" if row["target_kind"] == "datatype"
              else f"a <b>{escape(row['target'])}</b>")
    return f"""
  <div class="note"><b>Worked example, from this graph.</b>
  <span class="mono">{escape(row['subject'])} —{escape(row['predicate'])}→
  {escape(row['target'])}</span><br>
  Read it as: the graph currently holds <b>{population}</b> individuals of class
  <b>{escape(row['subject'])}</b>. Of those, <b>{row['subjects']}</b> state
  <b>{escape(row['predicate'])}</b> at least once — that is the coverage of
  <b>{coverage}</b>. Between them they make <b>{row['occurrences']}</b> such
  statements, each pointing at {target}. Among the subjects that participate at
  all, the fewest values one of them has is <b>{row['min']}</b>, the middle is
  <b>{row['median']:g}</b>, and the most is <b>{row['max']}</b>. The
  {population - row['subjects']} individuals with no value at all are counted in
  the coverage, and deliberately left out of those three numbers.</div>"""


def patterns_section(report):
    """Pattern semantics, the honest caveats, and the filterable table."""
    patterns = report["patterns"]
    literal_count = sum(1 for row in patterns if row["target_kind"] == "datatype")
    return f"""
<section id="patterns">
  <h2><span class="num">4</span> Patterns — what the data actually does</h2>
  <p class="lead">A pattern is one sentence of the form
  <b>subject class → property → value type</b>, together with the evidence for
  it. There are {len(patterns)} of them right now: {len(patterns) - literal_count}
  ending in another entity and {literal_count} ending in a literal value.</p>
  <div class="grid two">
    <div class="card"><h4>How a pattern is formed</h4>
      <p class="small">Every statement in the instance view is grouped by the
      class of its subject, the property used, and the type of its value. The
      subject is reported under its <b>most specific stated class</b>: if
      something is both a <code>class:location</code> and an
      <code>onto:Entity</code>, and the schema says the first is a subclass of
      the second, only <code>class:location</code> is used. Two unrelated
      classes both count. Types that only say “this exists”
      (<code>owl:NamedIndividual</code>, <code>skos:Concept</code>,
      <code>owl:Thing</code>) are ignored.</p></div>
    <div class="card"><h4>What is left out on purpose</h4>
      <p class="small">Structural and naming predicates — anything from RDF,
      RDFS, OWL, SHACL, or SKOS — never form a pattern, because they describe
      the modeling rather than the subject matter. The project's own
      <code>onto:kind</code> is excluded too, since it merely repeats the type
      as text. Nothing else is filtered: rare patterns are kept, because
      rarity is not the same as noise.</p></div>
  </div>
  <h3>What each number means</h3>
  <table style="max-width:920px">
    <thead><tr><th>column</th><th>meaning</th></tr></thead>
    <tbody>
      <tr><td class="mono">occurrences</td><td>How many matching values exist in
        total. One subject with three values contributes three.</td></tr>
      <tr><td class="mono">subjects</td><td>How many distinct individuals have at
        least one matching value.</td></tr>
      <tr><td class="mono">population</td><td>How many individuals of that class
        exist in the graph right now, whether or not they use the property.</td></tr>
      <tr><td class="mono">coverage</td><td><code>subjects ÷ population</code>.
        Low coverage means the property is occasional, not that the data is
        wrong.</td></tr>
      <tr><td class="mono">min / median / max</td><td>Values per
        <i>participating</i> subject. Individuals with no value affect coverage
        instead, so these three never get diluted by absence.</td></tr>
    </tbody>
  </table>
  {worked_example(patterns)}
  <div class="note rose"><b>These are observations, not rules.</b> A pattern
  saying “{len(patterns)} shapes exist” does not mean anything is required or
  forbidden. If 100% of locations carry a property today, the next source may
  add one that does not — and nothing was violated. Turning an observation into
  a rule is a human decision, made by writing an axiom into the schema; this
  viewer will never do it for you.</div>
  <h3>Explore the observations</h3>
  <p class="small muted">These filters change only what the table shows. The
  underlying records are always computed in full — no threshold is applied
  before you see them.</p>
  <div class="controls">
    <label>search
      <input type="search" id="p-search" placeholder="location, affects, …"
             oninput="renderPatterns()"></label>
    <label>show
      <select id="p-kind" onchange="renderPatterns()">
        <option value="all">all patterns</option>
        <option value="relations">links to entities only</option>
        <option value="literals">literal values only</option>
      </select></label>
    <label>min coverage
      <input type="range" id="p-coverage" min="0" max="100" value="0" step="5"
             oninput="renderPatterns()">
      <span class="mono" id="p-coverage-value">0%</span></label>
    <label>min occurrences
      <input type="range" id="p-occurrences" min="1" max="20" value="1"
             oninput="renderPatterns()">
      <span class="mono" id="p-occurrences-value">1</span></label>
    <span class="count" id="p-count"></span>
  </div>
  <div class="scroll">
    <table>
      <thead><tr>
        <th class="sortable" onclick="sortPatterns('subject')">subject class</th>
        <th class="sortable" onclick="sortPatterns('predicate')">property</th>
        <th class="sortable" onclick="sortPatterns('target')">value</th>
        <th class="sortable" onclick="sortPatterns('occurrences')">occur.</th>
        <th class="sortable" onclick="sortPatterns('subjects')">subjects</th>
        <th class="sortable" onclick="sortPatterns('population')">pop.</th>
        <th class="sortable" onclick="sortPatterns('coverage')">coverage</th>
        <th>min / med / max</th>
      </tr></thead>
      <tbody id="p-body"></tbody>
    </table>
  </div>
  <p class="small muted">Click any column heading to sort by it; click again to
  reverse.</p>
</section>"""


def instances_section(report):
    """The instance view, as browsable entity cards."""
    cards = report["instances"]
    classes = sorted({item["short"] for card in cards for item in card["classes"]})
    options = "".join(f'<option value="{escape(name)}">{escape(name)}</option>'
                      for name in classes)
    relations = sum(len(card["relations"]) for card in cards)
    facts = sum(len(card["facts"]) for card in cards)
    return f"""
<section id="instances">
  <h2><span class="num">5</span> Instances — the things the texts talked about</h2>
  <p class="lead">The instance view holds {len(cards)} named individuals, making
  {relations} links to each other and {facts} literal statements. Each one was
  created or matched by the merge policy when a source text was read.</p>
  <div class="grid two">
    <div class="card"><h4>How an individual is recognized</h4>
      <p class="small">A resource enters this view when it is typed as an
      <code>owl:NamedIndividual</code>, a <code>skos:Concept</code>, or an
      instance of a class the schema declares. Its own name, its relations, and
      its literal facts then follow it here. Everything else a text produced but
      that could not be tied to a declared class ends up in support instead.</p></div>
    <div class="card"><h4>Why an entity has several types</h4>
      <p class="small">A typical entity carries four: <code>owl:NamedIndividual</code>
      and <code>skos:Concept</code> say it exists and is a concept,
      <code>onto:Entity</code> is the project's root class, and
      <code>class:something</code> is the specific class the model chose. Only
      the specific one is used for patterns; the rest are shown here in grey.</p></div>
  </div>
  <div class="note"><b>Identity is decided before anything is written.</b> An
  exact identifier, or a unique exact name or alias match of the same kind,
  resolves to the existing entity. An ambiguous match or a very close spelling
  is held for review rather than merged. Only a confident, unambiguous record
  creates a new entity — which is why aliases below are worth reading: each one
  is a name that will resolve to this entity next time.</div>
  <div class="controls">
    <label>search
      <input type="search" id="i-search" placeholder="name, alias, relation, fact…"
             oninput="renderInstances()"></label>
    <label>class
      <select id="i-class" onchange="renderInstances()">
        <option value="all">every class</option>{options}
      </select></label>
    <span class="count" id="i-count"></span>
  </div>
  <div class="grid two" id="i-list"></div>
</section>"""


def support_section(report):
    """The support view: header, shapes, extraction events, merge candidates."""
    support = report["support"]
    events = support["events"]
    decisions = sorted({row["decision"] for row in support["candidates"]})
    sections = sorted({row["section"] for row in support["candidates"]})
    event_rows = "".join(
        f"<tr><td class='mono'>{escape(event['id'])}</td>"
        f"<td>{escape(event['sourcePath'])}</td>"
        f"<td class='mono small'>{escape(event['sourceSha256'][:16])}…</td>"
        f"<td class='mono small'>{escape(event['modelName'])}</td>"
        f"<td class='mono'>{escape(event['mergePolicyVersion'])}</td></tr>"
        for event in events)
    shape_rows = "".join(
        f"<tr><td>{escape(shape['label'])}</td>"
        f"<td class='mono'>{escape(', '.join(shape['targets']))}</td>"
        f"<td class='mono small'>{escape('; '.join(shape['rules']))}</td></tr>"
        for shape in support["shapes"])
    header_rows = "".join(
        f"<tr><td class='mono'>{escape(subject)}</td>"
        f"<td class='mono'>{escape(predicate)}</td>"
        f"<td class='mono'>{escape(target)}</td></tr>"
        for subject, predicate, target in support["header"])
    decision_options = "".join(f'<option value="{escape(name)}">{escape(name)}</option>'
                               for name in decisions)
    section_options = "".join(f'<option value="{escape(name)}">{escape(name)}</option>'
                              for name in sections)
    return f"""
<section id="support">
  <h2><span class="num">6</span> Support — provenance, shapes, and the audit trail</h2>
  <p class="lead">The third partition is the part nobody usually looks at, and
  it is the reason the other two can be trusted. It records where every
  statement came from, what the model originally said, and what the merge
  policy decided to do about it.</p>
  <div class="note warn"><b>Support is quarantined on purpose.</b> These
  records never appear as entities, never enter a prompt, and never appear in
  any usage statistic. Otherwise the system would start extracting knowledge
  from its own bookkeeping.</div>
  <h3>Extraction events — one per source file that was merged</h3>
  <table><thead><tr><th>event</th><th>source</th><th>content digest</th>
    <th>model</th><th>policy</th></tr></thead>
    <tbody>{event_rows or '<tr><td colspan="5" class="muted">none</td></tr>'}</tbody></table>
  <p class="small muted">The digest is of the source text, so re-reading a
  changed file is visibly a different event. The policy version records which
  merge rules were in force when the decisions below were made.</p>
  <h3>Merge candidates — every record the model proposed</h3>
  <p>Each candidate keeps the model's normalized output, its self-reported
  confidence, and the decision made about it. The gate is fixed: a new
  assertion below <b>0.80</b> confidence is not merged, it is retained as a
  review record. An exact duplicate of something already in the graph is kept
  as corroboration rather than re-added. A conflict with an existing
  statement goes to review; nothing is overwritten automatically.</p>
  <div class="controls">
    <label>decision
      <select id="c-decision" onchange="renderCandidates()">
        <option value="all">every decision</option>{decision_options}
      </select></label>
    <label>section
      <select id="c-section" onchange="renderCandidates()">
        <option value="all">every section</option>{section_options}
      </select></label>
    <label>search
      <input type="search" id="c-search" placeholder="entity name, predicate…"
             oninput="renderCandidates()"></label>
    <span class="count" id="c-count"></span>
  </div>
  <div class="scroll">
    <table><thead><tr><th>record</th><th>decision</th><th>conf.</th>
      <th>became</th><th>the model's normalized output</th><th>reasons</th>
    </tr></thead><tbody id="c-body"></tbody></table>
  </div>
  <h3>SHACL shapes — validation rules carried in the graph</h3>
  <table><thead><tr><th>shape</th><th>applies to</th><th>requires</th></tr></thead>
    <tbody>{shape_rows or '<tr><td colspan="3" class="muted">none</td></tr>'}</tbody></table>
  <p class="small muted">SHACL describes what valid data must look like. It is
  support material rather than schema because it constrains data instead of
  defining vocabulary — and because a shape is not something an LLM should be
  invited to imitate.</p>
  <h3>The ontology header</h3>
  <table><thead><tr><th>subject</th><th>predicate</th><th>object</th></tr></thead>
    <tbody>{header_rows or '<tr><td colspan="3" class="muted">none</td></tr>'}</tbody></table>
</section>"""


def controls_section():
    """What can be changed here, and what can only be changed in the code."""
    knobs = (
        ("graph_partition.py", "SCHEMA_TYPES, SCHEMA_AXIOMS, ANNOTATIONS",
         "which declarations and predicates count as schema"),
        ("graph_partition.py", "SUPPORT_TYPES, AUDIT_TYPES",
         "what is treated as metadata rather than knowledge"),
        ("graph_skeleton.py", "SKELETON_TYPES, NAMED_AXIOMS",
         "which declarations and axioms reach the skeleton"),
        ("graph_skeleton.py", "SUPPORTED_CONSTRAINTS",
         "which OWL restriction forms are allowed through"),
        ("graph_patterns.py", "METATYPES, STRUCTURAL, EXCLUDED",
         "which types and predicates are ignored when counting usage"),
        ("prompt_budget.py", "PROMPT_BUDGET['context_tokens']",
         "how much ontology context one prompt may carry"),
        ("merge_policy.py", "min_new_confidence (0.80)",
         "the confidence a new assertion needs to be merged rather than reviewed"),
        ("entity_lookup.py", "CLOSE_SPELLING_THRESHOLD (0.96)",
         "how close a spelling must be before it is held for review"),
        ("graph_management.py", "BASE",
         "the namespace all generated URIs are minted under"),
    )
    rows = "".join(
        f"<tr><td class='mono'>{escape(module)}</td>"
        f"<td class='mono' style='color:var(--accent)'>{escape(name)}</td>"
        f"<td>{escape(effect)}</td></tr>" for module, name, effect in knobs)
    return f"""
<section id="controls">
  <h2><span class="num">7</span> Controls — what you can change, and where</h2>
  <div class="note"><b>Two very different kinds of control.</b> The widgets on
  this page are <i>display</i> controls: they hide and sort rows that were
  already computed. They cannot change a single derived number. What a view
  contains is decided in the code, before this page is generated — so a filter
  can never make the graph look different from what it is.</div>
  <h3>Display controls on this page</h3>
  <table style="max-width:940px">
    <thead><tr><th>where</th><th>control</th><th>does</th></tr></thead>
    <tbody>
      <tr><td>Partitions</td><td>view buttons, search</td>
        <td>hides partitions or rows; the classification is unchanged</td></tr>
      <tr><td>Skeleton</td><td>search, kind selector</td>
        <td>narrows to classes, properties, or one property kind</td></tr>
      <tr><td>Patterns</td><td>search, kind, min coverage, min occurrences,
        column sort</td><td>hides weaker observations from the table; every
        observation is still computed and counted</td></tr>
      <tr><td>Instances</td><td>search, class selector</td>
        <td>narrows the entity cards</td></tr>
      <tr><td>Provenance</td><td>decision, section, search</td>
        <td>narrows the audit records</td></tr>
    </tbody>
  </table>
  <h3>Command-line controls</h3>
  <pre>python view_ontology.py                     # union of ontology.trig
python view_ontology.py ontology.trig -g GRAPH_IRI # one named graph
python view_ontology.py other.ttl           # a legacy Turtle graph
python view_ontology.py -html               # write ontology_views.html
python view_ontology.py other.ttl -html out.html   # a different graph, a chosen file</pre>
  <p>There are no filter options on the command line, and that is deliberate: a
  view that could be silently narrowed would be a view you could not trust.</p>
  <h3>Derivation controls — in the code</h3>
  <p>These are the real knobs. Changing one changes what the views contain for
  everybody, so each is a decision to make once and record, not a setting to
  flip per run.</p>
  <table style="max-width:980px">
    <thead><tr><th>module</th><th>constant</th><th>controls</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"""


def glossary_section(report):
    """Every term the page uses, defined once."""
    terms = (
        ("triple", "One statement: subject, predicate, object. The only kind of "
                   "sentence RDF has."),
        ("URI / IRI", "The global identifier of a resource. Two graphs that use "
                      "the same URI are talking about the same thing."),
        ("literal", "A plain value — a string, a number, a date — that sits in "
                    "the object position and identifies nothing."),
        ("blank node", "An anonymous resource used to hold a multi-part "
                       "expression, such as an OWL restriction. It has no URI "
                       "and cannot be referred to from outside."),
        ("prefix", "A display shortcut for a namespace: <code>entity:taiwan</code> "
                   "for the full URI."),
        ("class", "A kind of thing, declared with <code>owl:Class</code>. "
                  "Individuals are members of it."),
        ("individual", "A specific thing, as opposed to a kind of thing. Also "
                       "called an instance."),
        ("object property", "A property whose value is another resource: it "
                            "makes a link."),
        ("datatype property", "A property whose value is a literal: it records "
                              "a fact."),
        ("domain", "The class a property's <i>subject</i> is expected to belong "
                   "to. A declaration, not a check."),
        ("range", "The class or datatype a property's <i>value</i> is expected "
                  "to belong to."),
        ("rdfs:subClassOf", "States that every member of one class is also a "
                            "member of another."),
        ("OWL restriction", "An anonymous class defined by a condition on a "
                            "property, such as “has at least one member”."),
        ("SHACL shape", "A validation rule: what data must look like to be "
                        "considered valid. Distinct from a class definition."),
        ("SKOS", "A small vocabulary for concepts and their labels. This project "
                 "uses <code>skos:prefLabel</code> for the main name and "
                 "<code>skos:altLabel</code> for aliases."),
        ("axiom", "A statement the ontology asserts as true by definition, such "
                  "as a subclass link."),
        ("assertion", "A statement about a particular individual, as opposed to "
                      "an axiom about classes."),
        ("provenance", "The record of where a statement came from: which source "
                       "file, which model, which decision."),
        ("coverage", "Of the individuals in a class, the share that use a given "
                     "property at least once."),
        ("cardinality", "How many values a property has for one subject."),
    )
    rows = "".join(f"<dt>{escape(term) if '<' not in term else term}</dt>"
                   f"<dd>{definition}</dd>" for term, definition in terms)
    counts = report["graph"]["counts"]
    return f"""
<section id="glossary">
  <h2><span class="num">8</span> Glossary</h2>
  <dl class="glossary">{rows}</dl>
</section>
<footer>
  <p>Generated by <code>view_ontology.py -html</code> from
  <code>{escape(report['graph']['path'])}</code> on
  {escape(report['graph']['generated'])}:
  {report['graph']['triples']} triples → {counts['schema']} schema,
  {counts['instance']} instance, {counts['support']} support;
  {counts['skeleton']} skeleton statements and {counts['patterns']}
  observed patterns. The graph file was not modified.</p>
  <p>The same report without the explanations is printed by
  <code>python view_ontology.py</code>.</p>
</footer>"""


def render_page(report):
    """The complete standalone HTML document."""
    data = json.dumps(report, ensure_ascii=False).replace("</", "<\\/")
    body = "".join([
        head_section(report),
        prefix_section(report),
        pipeline_section(report),
        partitions_section(report),
        skeleton_section(report),
        patterns_section(report),
        instances_section(report),
        support_section(report),
        controls_section(),
        glossary_section(report),
    ])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(report['graph']['path'])} — ontology views</title>
<style>{PAGE_STYLE}</style>
</head>
<body>
<div class="wrap">{body}</div>
<script>const DATA = {data};</script>
<script>{PAGE_SCRIPT}</script>
</body>
</html>
"""


def write_report(path, graph, views, destination):
    """Build the report for one graph and write the page to `destination`."""
    destination.write_text(render_page(build_report(path, graph, views)),
                           encoding="utf-8")
    return destination
