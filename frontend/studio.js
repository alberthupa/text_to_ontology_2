"use strict";
/* ===================== studio frontend =====================
   Loaded only when triple-lens.html is served by text_to_ontology.studio;
   opened from disk the page is the plain viewer.

   What it adds to the page:

     * a studio row in the top bar: the dataset status, one button per action
       (Starter ontology, Add sources, Prompts, Edit the graph, Clear view,
       Reset everything, Log), and the progress bar under it;
     * one dialog per action, opened from those buttons;
     * the right-hand column, which is the conversation with the graph and
       nothing else.

   It talks to the backend only through named operations
   (POST api/op/<name>, GET api/op/<name>?args) and changes the picture only
   through the lens view API (window.__lens.applyView), so no domain logic
   lives here: switching a capability on in the backend never needs more than
   the button that calls it. */
(function () {
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = (n) => Number(n).toLocaleString('en-US');
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  /* ---------- the transport: named operations only ---------- */
  async function call(name, args, method) {
    method = method || (args === undefined ? 'GET' : 'POST');
    let url = 'api/op/' + name;
    const options = { method };
    if (method === 'GET') {
      const query = new URLSearchParams();
      for (const key of Object.keys(args || {})) {
        if (args[key] !== undefined && args[key] !== null) query.set(key, args[key]);
      }
      url += query.toString() ? '?' + query.toString() : '';
    } else {
      options.headers = { 'Content-Type': 'application/json' };
      options.body = JSON.stringify(args || {});
    }
    const response = await fetch(url, options);
    const text = await response.text();
    try { return JSON.parse(text); }
    catch (error) { throw new Error('the studio server answered ' + response.status + ' with a non-JSON body'); }
  }

  const op = {
    status: () => call('status'),
    dataset: () => call('dataset'),
    progress: (job) => call('progress', { job }),
    reset: () => call('reset', {}),
    starter: (text) => call('starter.create', { text }),
    starterImport: (name, text) => call('starter.import', { name, text }),
    ingest: (files) => call('ingest', { files }),
    operations: () => call('operations.list'),
    prompts: () => call('prompts.list'),
    promptSave: (name, text) => call('prompts.save', { name, text }),
    promptReset: (name) => call('prompts.reset', { name }),
    promptPreview: (name) => call('prompts.preview', { name }),
    chat: (message, budget) => call('chat.ask', { message, budget }),
    chatState: () => call('chat.state'),
    chatReset: () => call('chat.reset', {}),
    editCurrent: () => call('edit.current'),
    editPreview: (text, allow) => call('edit.preview',
      { text, allow_new_vocabulary: !!allow }),
    editApply: (patchId) => call('edit.apply', { patch_id: patchId }),
  };

  /* ---------- markup: the studio row in the top bar ---------- */
  const MARK = '<svg viewBox="0 0 22 22" aria-hidden="true"><path d="M5 6 L17 5 M5 6 L11 17 M17 5 L11 17" stroke="currentColor" stroke-width="1.6" fill="none" opacity=".55"/><circle cx="5" cy="6" r="3.2" fill="var(--accent)"/><rect x="14" y="2" width="6" height="6" rx="1.4" fill="currentColor"/><circle cx="11" cy="17" r="2.6" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>';

  const BAR = `
    <span class="sdataset" id="stStatus">Looking for the studio server…</span>
    <span class="sep"></span>
    <button class="btn" id="stOpenStarter" title="Create the starter ontology from a description, or import an RDF file">Starter ontology…</button>
    <button class="btn" id="stOpenSources" title="Ingest text files into the data graph">Add sources…</button>
    <button class="btn" id="stOpenPrompts" title="Edit the prompts sent to the model">Prompts…</button>
    <button class="btn" id="stOpenEdit" title="Edit the data graph as Turtle, with a preview">Edit the graph…</button>
    <span class="sep"></span>
    <button class="btn" id="stClear" title="Unload the dataset from the graph view; nothing is deleted">Clear view</button>
    <button class="btn danger" id="stReset" title="Delete the dataset file and every source in the inbox">Reset everything</button>
    <button class="snote" id="stNote" type="button" title="Open the run log"></button>
    <button class="btn quiet" id="stOpenLog" title="Everything the studio did and said">Log</button>`;

  const PROGRESS = `
    <div class="sptop"><span id="stPLabel">Working…</span><b id="stPPct"></b></div>
    <div class="sptrack"><div class="spfill" id="stPFill"></div></div>
    <div class="spdetail" id="stPDetail"></div>`;

  /* ---------- markup: one dialog per action ---------- */
  const STARTER = `
    <p class="smuted">Describe the world in a few sentences. The model proposes the classes and relationships, and ingestion may then only use them.</p>
    <textarea id="stText" spellcheck="false" placeholder="Example: We are a coffee roaster. We track roasters, farms, coffee lots, retailers, and the shipments between them. A lot is grown at one farm, has a roast level and a price, and is sold by retailers."></textarea>
    <p class="smuted swarn" id="stWarn"></p>
    <div class="sactions"><button class="btn primary" id="stCreate" type="button">Create starter ontology</button></div>
    <div class="sor">or import an ontology you already have</div>
    <div id="stImportDrop" class="sdrop">
      <b>Drop an RDF / Turtle / TriG file here</b>
      <span>its classes and relations become the starter vocabulary, its individuals become data, and its IRIs are kept</span>
      <button class="btn" id="stImportPick" type="button">Choose a file…</button>
    </div>
    <input type="file" id="stImportFiles" accept=".ttl,.turtle,.trig,.nt,.nq,.n3,.rdf,.owl,.jsonld,.json" hidden>
    <div class="svocab" id="stVocab"></div>`;

  const SOURCES = `
    <p class="smuted">Each file is ingested through the data-only pipeline: it can add individuals and statements, never a class or a relationship. Those stay as the starter defines them.</p>
    <div id="stDrop" class="sdrop">
      <b>Drop text files or folders here</b>
      <span>folders are searched recursively; their structure is not retained</span>
      <span>an RDF or Turtle file is an ontology, not a source: import it under Starter ontology</span>
      <button class="btn primary" id="stPick" type="button">Choose files…</button>
    </div>
    <input type="file" id="stFiles" multiple accept=".txt,.md,.rst,.csv,.json,.jsonl,.yaml,.yml,.xml,.html,.log" hidden>
    <p class="smuted" id="stReady"></p>`;

  const PROMPTS = `
    <p class="smuted">The prompt sent for every source window. Placeholders stay in the text; anything else is yours to change. Saved edits live in <code>prompts.local.json</code> next to the dataset.</p>
    <div class="srow">
      <select id="stPromptName" aria-label="Which prompt to edit"></select>
      <button class="btn" id="stPromptPreview" type="button">Preview</button>
    </div>
    <textarea id="stPromptText" spellcheck="false" class="scode"></textarea>
    <p class="smuted" id="stPromptNote"></p>
    <div class="sactions">
      <button class="btn primary" id="stPromptSave" type="button">Save prompt</button>
      <button class="btn" id="stPromptReset" type="button">Back to default</button>
    </div>
    <pre class="slog" id="stPromptPreviewBox" hidden></pre>`;

  const EDIT = `
    <p class="smuted">The data graph as Turtle. Additions are ordinary statements; a line starting with <code>- </code> removes one. Nothing changes until you preview it and then apply exactly what you saw.</p>
    <div class="sactions">
      <button class="btn" id="stEditLoad" type="button">Reload the graph</button>
      <button class="btn primary" id="stEditPreview" type="button">Preview changes</button>
      <button class="btn" id="stEditApply" type="button" disabled>Apply changes</button>
      <label class="scheck"><input type="checkbox" id="stEditAllow"> allow new classes and relations</label>
    </div>
    <textarea id="stEditText" class="scode" spellcheck="false" placeholder="Loading the graph…"></textarea>
    <p class="smuted" id="stEditNote"></p>
    <pre class="slog" id="stEditDiff" hidden></pre>`;

  const LOG = `<pre class="slog" id="stLog">Nothing yet.</pre>`;

  /* ---------- markup: the conversation column ---------- */
  const CHAT = `
    <div class="shead">
      <span class="stitle">Chat with the graph</span>
      <button class="btn quiet" id="stChatReset" title="Forget this conversation and start a new one">New conversation</button>
      <button class="btn quiet" id="stCollapse" title="Hide or show the conversation" aria-label="Hide or show the conversation">&#8677;</button>
    </div>
    <div id="stChatLog" class="schat" aria-live="polite"></div>
    <div class="scompose">
      <div class="sback" id="stChatBack" hidden>
        <span>The canvas shows the subgraph of one answer.</span>
        <button class="lnk" id="stChatEverything" type="button">Show the full graph again</button>
      </div>
      <div class="sinput">
        <textarea id="stChatText" rows="1" spellcheck="false" placeholder="Ask about the graph…" aria-label="Your question"></textarea>
        <button class="btn primary ssend" id="stChatSend" type="button" title="Send (Enter)" aria-label="Send">&#10148;</button>
      </div>
      <div class="sopts">
        <select id="stChatBudget" title="How much of the subgraph the model may see">
          <option value="2500">compact subgraph</option>
          <option value="6000" selected>normal subgraph</option>
          <option value="12000">wide subgraph</option>
        </select>
        <label class="scheck"><input type="checkbox" id="stChatAuto" checked> show the subgraph after each answer</label>
      </div>
    </div>`;

  /* ---------- mount everything, hidden until the server answers ---------- */
  const top = $('#top');
  const bar = document.createElement('div');
  bar.className = 'row';
  bar.id = 'studiobar';
  bar.hidden = true;
  bar.innerHTML = BAR;
  const progressEl = document.createElement('div');
  progressEl.id = 'stProgress';
  progressEl.hidden = true;
  progressEl.setAttribute('role', 'status');
  progressEl.setAttribute('aria-live', 'polite');
  progressEl.innerHTML = PROGRESS;
  const filterbar = $('#filterbar');
  if (top) {
    top.insertBefore(bar, filterbar);
    top.insertBefore(progressEl, filterbar);
  } else {
    document.body.prepend(progressEl);
    document.body.prepend(bar);
  }

  function dialog(id, title, body, wide) {
    const el = document.createElement('dialog');
    el.id = id;
    el.className = 'sdlg' + (wide ? ' wide' : '');
    el.innerHTML = `<div class="sdhead"><h2>${esc(title)}</h2>`
      + `<button class="btn quiet sdclose" type="button" aria-label="Close">✕</button></div>`
      + `<div class="sdbody">${body}</div>`;
    el.querySelector('.sdclose').onclick = () => el.close();
    document.body.appendChild(el);
    return el;
  }
  const starterDlg = dialog('stStarterDlg', 'Starter ontology', STARTER);
  const sourcesDlg = dialog('stSourcesDlg', 'Add sources', SOURCES);
  const promptsDlg = dialog('stPromptsDlg', 'Prompts', PROMPTS, true);
  const editDlg = dialog('stEditDlg', 'Edit the graph', EDIT, true);
  const logDlg = dialog('stLogDlg', 'Run log', LOG, true);

  const workspace = $('#workspace') || document.body;
  const panel = document.createElement('aside');
  panel.id = 'studio';
  panel.hidden = true;
  panel.setAttribute('aria-label', 'Chat with the graph');
  panel.innerHTML = CHAT;
  workspace.appendChild(panel);

  const statusEl = $('#stStatus'), noteEl = $('#stNote'), logEl = $('#stLog');
  const vocabEl = $('#stVocab'), warnEl = $('#stWarn'), readyEl = $('#stReady');
  const dropEl = $('#stDrop'), importDrop = $('#stImportDrop'), importFiles = $('#stImportFiles');
  const chatLog = $('#stChatLog'), chatText = $('#stChatText'), chatSend = $('#stChatSend');
  const chatBack = $('#stChatBack'), chatEverything = $('#stChatEverything');
  const chatAuto = $('#stChatAuto'), chatBudget = $('#stChatBudget');
  const editText = $('#stEditText'), editNote = $('#stEditNote');
  const editDiff = $('#stEditDiff'), editAllow = $('#stEditAllow'), editApply = $('#stEditApply');
  const pLabel = $('#stPLabel'), pPct = $('#stPPct'), pFill = $('#stPFill'), pDetail = $('#stPDetail');
  const promptName = $('#stPromptName'), promptText = $('#stPromptText');
  const promptNote = $('#stPromptNote'), promptPreview = $('#stPromptPreviewBox');
  let busy = false, lastStatus = null, prompts = [];
  let turns = [], scopes = {}, proposals = {};
  let editPatch = null;

  /* ---------- the log: one line in the bar, everything in the dialog ---------- */
  function say(text) {
    logEl.textContent = text;
    const line = String(text).split('\n').find((part) => part.trim()) || '';
    noteEl.textContent = line;
    noteEl.title = 'Open the run log\n\n' + text;
  }

  /* ---------- progress ---------- */
  function showProgress(state) {
    if (!state || !state.running) { progressEl.hidden = true; return; }
    progressEl.hidden = false;
    progressEl.classList.add('running');
    pLabel.textContent = state.label || 'Working…';
    pPct.textContent = (state.percent == null ? '' : state.percent + '%');
    pFill.style.width = (state.percent == null ? 100 : state.percent) + '%';
    pDetail.textContent = state.detail || '';
  }
  function hideProgress() {
    progressEl.hidden = true;
    progressEl.classList.remove('running');
  }
  function setBusy(on, message) {
    busy = on;
    ['#stCreate', '#stImportPick', '#stPick', '#stReset', '#stClear',
     '#stPromptSave', '#stPromptReset', '#stEditLoad', '#stEditPreview',
     '#stChatSend', '#stChatReset'].forEach((s) => {
      const button = $(s); if (button) button.disabled = on;
    });
    if (on) editApply.disabled = true; else editApply.disabled = !editPatch;
    dropEl.classList.toggle('busy', on);
    importDrop.classList.toggle('busy', on);
    if (on && message) say(message);
    if (!on) hideProgress();
  }
  /* A quiet job (the chat) reports into the transcript instead of the bar. */
  async function follow(jobId, message, quiet) {
    let state = { running: true, label: message, percent: 0, detail: '' };
    if (!quiet) showProgress(state);
    while (state.running) {
      await sleep(400);
      state = await op.progress(jobId);
      if (quiet) thinking(state); else showProgress(state);
    }
    hideProgress();
    return state.result || { ok: false, error: 'the job ended without an answer' };
  }
  async function run(action, message, onResult, options) {
    options = options || {};
    if (busy) { say('Please wait: the studio is still busy with the previous step.'); return; }
    setBusy(true, message);
    let result;
    try {
      const started = await action();
      result = started && started.job_id
        ? await follow(started.job_id, message, options.quiet) : started;
      if (result.log) say(result.log);
      if (!result.ok) say((result.log || '') + '\nError: ' + (result.error || 'unknown error'));
      if (result.prompts) renderPrompts(result.prompts);
      if (result.status) renderStatus(result.status);
      if (result.ok && (result.status || result.sources || result.proposal
                        || result.summary)) {
        await loadDataset();
      }
    } catch (error) {
      hideProgress();
      result = { ok: false, error: error.message };
      say('Error: ' + error.message);
    } finally {
      setBusy(false);
    }
    if (onResult) onResult(result);
  }

  async function refreshPrompts() {
    const answer = await op.prompts();
    if (answer && answer.prompts) renderPrompts(answer.prompts);
  }

  /* ---------- the dataset status and the picture ---------- */
  function fileName(path) { return String(path || '').split(/[\\/]/).pop() || String(path || ''); }
  function renderStatus(status) {
    if (!status) return;
    lastStatus = status;
    const classes = status.classes || [], relations = status.relations || [], facts = status.facts || [];
    const sources = status.sources && status.sources.length
      ? ` · ${status.sources.length} source file${status.sources.length > 1 ? 's' : ''}` : '';
    statusEl.title = status.graph;
    statusEl.innerHTML = `<b>${esc(fileName(status.graph))}</b> · ${fmt(status.triples)} triples${sources}`;
    if (status.ready) {
      vocabEl.innerHTML = `<div class="tagline">Classes: <code>${esc(classes.join(', '))}</code></div>`
        + `<div class="tagline">Relations: <code>${esc(relations.join(', ') || 'none')}</code></div>`
        + `<div class="tagline">Facts: <code>${esc(facts.join(', ') || 'none')}</code></div>`;
      readyEl.textContent = 'Ready. Dropped files may only use the vocabulary the starter declares.';
      warnEl.textContent = status.triples > 0
        ? `A starter replaces the whole dataset, so this deletes the ${fmt(status.triples)} triples it holds now. Press Reset everything first if you want a clean start.`
        : '';
    } else {
      vocabEl.innerHTML = '<div class="tagline">No starter ontology yet. Ingestion has no classes or relationships to use until there is one.</div>';
      readyEl.textContent = 'No starter ontology yet: create one first, under Starter ontology in the top bar.';
      warnEl.textContent = status.triples > 0
        ? `This dataset has ${fmt(status.triples)} triples but no starter vocabulary. Reset everything before creating one.`
        : '';
    }
    if (!turns.length) renderChat(turns);   // the welcome depends on readiness
  }
  async function loadDataset() {
    const data = await op.dataset();
    const lens = window.__lens;
    if (!lens) return;
    const name = data.name || 'dataset.trig';   // the backend names the file
    const files = data.trig && data.trig.trim()
      ? [{ name, trig: data.trig }] : [];
    lens.applyView({ replace: true, files, resetFilters: true });
    chatBack.hidden = true;
  }
  function clearView(message) {
    const lens = window.__lens;
    if (lens) lens.applyView({ replace: true, files: [] });
    if (message) say(message);
  }

  /* ---------- top bar: open a dialog, clear, reset, log ---------- */
  $('#stOpenStarter').onclick = () => { starterDlg.showModal(); $('#stText').focus(); };
  $('#stOpenSources').onclick = () => sourcesDlg.showModal();
  $('#stOpenPrompts').onclick = () => { promptsDlg.showModal(); refreshPrompts(); };
  $('#stOpenEdit').onclick = () => {
    editDlg.showModal();
    if (!editText.value.trim()) loadEditor();
  };
  $('#stOpenLog').onclick = noteEl.onclick = () => {
    logDlg.showModal();
    logEl.scrollTop = logEl.scrollHeight;
  };
  $('#stClear').onclick = () => clearView('View cleared. The dataset is untouched — press Reset everything to delete it.');
  $('#stReset').onclick = () => {
    if (!confirm('Delete the dataset and every ingested source? This cannot be undone.')) return;
    run(() => op.reset(), 'Deleting the dataset and the inbox…', reloadChat);
  };

  /* ---------- the starter dialog ---------- */
  $('#stCreate').onclick = () => {
    const text = $('#stText').value.trim();
    if (!text) { warnEl.textContent = 'Write a few sentences first.'; return; }
    const held = lastStatus ? lastStatus.triples : 0;
    if (held > 0 && !confirm(`A starter replaces the whole dataset and deletes its ${fmt(held)} triples.\n\nContinue?`)) {
      say('Cancelled. Nothing was changed.');
      return;
    }
    starterDlg.close();
    run(() => op.starter(text), 'Asking the model for a starter ontology. This can take a minute…');
  };

  /* A dropped file is RDF when its suffix says so; the backend also sniffs
     the content, so a mislabelled file still lands in the right place. */
  const RDF_SUFFIX = /\.(ttl|turtle|trig|nt|nq|n3|rdf|owl|jsonld|json)$/i;
  const SOURCE_SUFFIX = /\.(txt|md|rst|csv|json|jsonl|yaml|yml|xml|html|log)$/i;
  function looksRdf(name) { return RDF_SUFFIX.test(name || ''); }
  function looksSourceRdf(name) {
    return looksRdf(name) && !/\.json$/i.test(name || '');
  }

  async function importStarter(file) {
    const text = await file.text();
    starterDlg.close();
    return run(() => op.starterImport(file.name, text),
      `Importing ${file.name}. No model is asked: the file is parsed and checked…`);
  }
  $('#stImportPick').onclick = () => importFiles.click();
  importFiles.onchange = () => {
    const file = importFiles.files[0];
    importFiles.value = '';
    if (file) importStarter(file);
  };

  /* A drop zone stops the events so the page's own "add to graph" drop
     handler never sees a file meant for the studio. */
  function filesFromEntry(entry, insideDirectory) {
    if (entry.isFile) {
      if (insideDirectory && !SOURCE_SUFFIX.test(entry.name || '')) {
        return Promise.resolve([]);
      }
      return new Promise((resolve) => entry.file(
        (file) => resolve([file]), () => resolve([])));
    }
    if (!entry.isDirectory) return Promise.resolve([]);

    const reader = entry.createReader();
    return new Promise((resolve) => {
      const entries = [];
      function readBatch() {
        reader.readEntries(async (batch) => {
          if (batch.length) {
            entries.push(...batch);
            readBatch();
            return;
          }
          entries.sort((left, right) =>
            (left.fullPath || left.name).localeCompare(right.fullPath || right.name));
          const nested = await Promise.all(entries.map((child) =>
            filesFromEntry(child, true)));
          resolve(nested.flat());
        }, () => resolve([]));
      }
      readBatch();
    });
  }

  async function filesFromDrop(dataTransfer) {
    const items = [...(dataTransfer ? dataTransfer.items || [] : [])];
    const entries = items.map((item) => item.webkitGetAsEntry
      ? item.webkitGetAsEntry() : null).filter(Boolean);
    if (!entries.length) return [...(dataTransfer ? dataTransfer.files : [])];
    entries.sort((left, right) =>
      (left.fullPath || left.name).localeCompare(right.fullPath || right.name));
    const nested = await Promise.all(entries.map((entry) =>
      filesFromEntry(entry, false)));
    return nested.flat();
  }

  function dropZone(zone, onFiles, recursive) {
    ['dragenter', 'dragover'].forEach((type) => zone.addEventListener(type, (event) => {
      if (!event.dataTransfer || [...event.dataTransfer.types].indexOf('Files') < 0) return;
      event.preventDefault(); event.stopPropagation(); zone.classList.add('over');
    }));
    ['dragleave', 'dragend'].forEach((type) => zone.addEventListener(type, (event) => {
      event.stopPropagation(); zone.classList.remove('over');
    }));
    zone.addEventListener('drop', async (event) => {
      event.preventDefault(); event.stopPropagation();
      zone.classList.remove('over');
      const files = recursive
        ? await filesFromDrop(event.dataTransfer)
        : [...(event.dataTransfer ? event.dataTransfer.files : [])];
      if (files.length || recursive) onFiles(files);
    });
  }
  dropZone(importDrop, (files) => {
    const file = files[0];
    if (looksRdf(file.name)) importStarter(file);
    else file.text().then((text) => {
      $('#stText').value = text;
      warnEl.textContent = `${file.name} is not RDF, so its text was put in the box above: read it, then press Create starter ontology.`;
    });
  });

  /* ---------- the sources dialog ---------- */
  $('#stPick').onclick = () => $('#stFiles').click();
  $('#stFiles').onchange = () => {
    const files = [...$('#stFiles').files];
    $('#stFiles').value = '';
    ingest(files);
  };
  async function ingest(fileList) {
    if (!fileList.length) {
      readyEl.textContent = 'No supported source files were found in that folder.';
      return;
    }
    const rdf = fileList.filter((file) => looksSourceRdf(file.name));
    if (rdf.length) {
      readyEl.textContent = `${rdf.map((f) => f.name).join(', ')} is RDF, not source text. `
        + 'Import it under Starter ontology instead.';
      return;
    }
    const files = [];
    for (const file of fileList) files.push({ name: file.name, text: await file.text() });
    if (!files.length) return;
    sourcesDlg.close();
    return run(() => op.ingest(files),
      `Ingesting ${files.length} file${files.length > 1 ? 's' : ''}. This can take a minute per file…`);
  }
  dropZone(dropEl, ingest, true);

  /* ---------- the prompts dialog ---------- */
  function renderPrompts(list) {
    prompts = list || [];
    const keep = promptName.value;
    promptName.innerHTML = prompts.map((item) =>
      `<option value="${esc(item.name)}">${esc(item.name)}${item.default ? '' : ' (edited)'}</option>`).join('');
    promptName.value = prompts.some((item) => item.name === keep)
      ? keep : (prompts.length ? prompts[0].name : '');
    showPrompt();
  }
  function currentPrompt() {
    return prompts.find((item) => item.name === promptName.value) || null;
  }
  function showPrompt() {
    const item = currentPrompt();
    if (!item) { promptText.value = ''; promptNote.textContent = ''; return; }
    promptText.value = item.text;
    const notes = [];
    notes.push(item.default ? 'using the tested default' : 'edited version in use');
    if (item.required.length) notes.push('must keep ' + item.required.map((f) => '$' + f).join(', '));
    if (item.fields.length) notes.push('may use ' + item.fields.map((f) => '$' + f).join(', '));
    if (item.error) notes.push('PROBLEM: ' + item.error);
    (item.advice || []).forEach((line) => notes.push('check: ' + line));
    promptNote.textContent = notes.join(' · ');
    promptNote.style.color = item.error ? 'var(--warn)' : '';
    promptPreview.hidden = true;
  }
  promptName.onchange = showPrompt;
  $('#stPromptSave').onclick = () => run(
    () => op.promptSave(promptName.value, promptText.value), 'Saving the prompt…',
    (result) => { if (result.ok) say(`Saved the ${promptName.value} prompt.`); });
  $('#stPromptReset').onclick = () => run(
    () => op.promptReset(promptName.value), 'Restoring the default prompt…',
    (result) => { if (result.ok) say(`Restored the default ${promptName.value} prompt.`); });
  $('#stPromptPreview').onclick = async () => {
    const answer = await op.promptPreview(promptName.value);
    promptPreview.hidden = false;
    promptPreview.textContent = answer.ok ? answer.prompt
      : 'Error: ' + (answer.error || 'could not render this prompt');
  };

  /* ---------- the editor dialog ---------- */
  function showEditNote(text, bad) {
    editNote.textContent = text || '';
    editNote.style.color = bad ? 'var(--warn)' : '';
  }
  function showDiff(answer) {
    const sample = answer.sample || { added: [], removed: [] };
    const lines = [];
    (sample.added || []).forEach((line) => lines.push('+ ' + line));
    if (sample.more_added) lines.push(`+ … ${sample.more_added} more addition(s)`);
    (sample.removed || []).forEach((line) => lines.push('- ' + line));
    if (sample.more_removed) lines.push(`- … ${sample.more_removed} more removal(s)`);
    (answer.warnings || []).forEach((line) => lines.push('! ' + line));
    (answer.errors || []).forEach((line) => lines.push('x ' + line));
    editDiff.hidden = !lines.length;
    editDiff.textContent = lines.join('\n');
  }
  function forgetEdit() {
    editPatch = null;
    editApply.disabled = true;
  }
  function loadEditor() {
    return run(() => op.editCurrent(), 'Reading the data graph…', (result) => {
      if (!result.ok) { showEditNote(result.error || 'could not read the graph', true); return; }
      editText.value = result.turtle;
      forgetEdit();
      showDiff({});
      showEditNote(`${result.triples} triples, ${Math.round(result.bytes / 1024)} kB. `
        + 'Edit, then Preview changes.');
      say(`Read the data graph: ${result.triples} triples.`);
    });
  }
  $('#stEditLoad').onclick = loadEditor;
  $('#stEditPreview').onclick = () => run(
    () => op.editPreview(editText.value, editAllow.checked),
    'Checking the patch…', (result) => {
      forgetEdit();
      showDiff(result);
      if (result.ok) {
        editPatch = result.patch_id;
        editApply.disabled = false;
        showEditNote(`Ready: ${result.counts.added} addition(s), `
          + `${result.counts.removed} removal(s). Apply to write exactly this.`);
        say(`Patch checked: +${result.counts.added} −${result.counts.removed}. Nothing written yet.`);
      } else {
        showEditNote(result.error || 'the patch is not valid', true);
      }
    });
  $('#stEditApply').onclick = () => {
    if (!editPatch) { showEditNote('Preview the patch first.', true); return; }
    run(() => op.editApply(editPatch), 'Applying the patch…', (result) => {
      if (!result.ok) return;
      editText.value = result.turtle || editText.value;
      forgetEdit();
      showDiff({});
      showEditNote('Applied and recorded in the provenance graph.');
      say('Patch applied and recorded in the provenance graph.');
    });
  };
  editText.addEventListener('input', () => {
    if (editPatch) showEditNote('The text changed since the preview: preview again.');
    forgetEdit();
  });

  /* ---------- the conversation ---------- */
  function shortName(iri) {
    return String(iri).split(/[#/]/).filter(Boolean).pop() || String(iri);
  }
  function avatar() { return `<div class="savatar" aria-hidden="true">${MARK}</div>`; }

  function scopeNote(turn) {
    const scope = turn.scope;
    if (!scope) return '';
    const parts = [`${scope.triples} triples selected`];
    if (scope.dropped) parts.push(`${scope.dropped} beyond the limit`);
    if (scope.rendered) parts.push(`${scope.rendered} reached the model`);
    if (scope.nodes && scope.nodes.length) parts.push('focus: ' + esc(shortName(scope.nodes[0])));
    const buttons = turn.view
      ? `<button class="lnk" type="button" data-scope="${turn.index}">Show the subgraph</button>`
        + `<button class="lnk" type="button" data-scope-full="${turn.index}">With the full graph</button>`
      : '<span class="smeta">(no subgraph stored)</span>';
    return `<div class="sfoot"><span class="smeta">${parts.join(' · ')}</span>${buttons}</div>`;
  }
  function proposalNote(turn) {
    const proposal = turn.proposal;
    if (!proposal) return '';
    if (!proposal.ok) {
      return `<div class="sfoot"><span class="smeta">proposed change could not be checked: `
        + `${esc(proposal.error || 'not valid')}</span></div>`;
    }
    const counts = proposal.counts || {};
    return `<div class="sfoot"><span class="smeta">proposed change: +${counts.added} −${counts.removed}</span>`
      + ` <button class="lnk" type="button" data-proposal="${turn.index}">Apply this patch</button></div>`;
  }
  function bubble(turn) {
    if (turn.role === 'you') {
      return `<div class="msg you"><div class="bubble">${esc(turn.text)}</div></div>`;
    }
    return `<div class="msg graph">${avatar()}<div class="bubble">${esc(turn.text)}`
      + scopeNote(turn) + proposalNote(turn) + '</div></div>';
  }
  function welcome() {
    const ready = lastStatus && lastStatus.ready;
    const classes = (lastStatus && lastStatus.classes) || [];
    const intro = ready
      ? 'Hi. Ask me anything about the graph. Every answer comes from the relevant part of it, and I can show you exactly which triples I used.'
      : 'Hi. There is no ontology yet. Use <b>Starter ontology…</b> in the top bar to create one and <b>Add sources…</b> to fill it, then ask me anything about it.';
    const questions = ready ? [
      'What kinds of things does the graph describe?',
      'How are those kinds related to each other?',
      classes.length ? `What do we know about every ${classes[0]}?` : null,
    ].filter(Boolean) : [];
    const chips = questions.map((q) =>
      `<button class="schip" type="button" data-ask="${esc(q)}">${esc(q)}</button>`).join('');
    return `<div class="msg graph">${avatar()}<div class="bubble">${intro}`
      + (chips ? `<div class="schips">${chips}</div>` : '') + '</div></div>';
  }
  function pendingBubbles(question) {
    return `<div class="msg you"><div class="bubble">${esc(question)}</div></div>`
      + `<div class="msg graph pending">${avatar()}<div class="bubble">`
      + '<span class="sdots"><i></i><i></i><i></i></span>'
      + '<span class="sthink" id="stThinkText"></span></div></div>';
  }
  function errorBubble(text, question) {
    const asked = question
      ? `<div class="msg you"><div class="bubble">${esc(question)}</div></div>` : '';
    return asked + `<div class="msg graph error">${avatar()}<div class="bubble">`
      + `Sorry, that did not work: ${esc(text || 'unknown error')}</div></div>`;
  }
  function thinking(state) {
    const el = $('#stThinkText');
    if (el) el.textContent = state.detail || state.label || '';
  }

  function renderChat(list, extra) {
    turns = list || [];
    scopes = {};
    proposals = {};
    turns.forEach((turn) => {
      if (turn.role === 'graph' && turn.view) scopes[turn.index] = turn;
      if (turn.role === 'graph' && turn.proposal) proposals[turn.index] = turn.proposal;
    });
    chatLog.innerHTML = (turns.length ? turns.map(bubble).join('') : welcome()) + (extra || '');
    chatLog.scrollTop = chatLog.scrollHeight;
  }
  async function reloadChat() {
    const chat = await op.chatState();
    if (chat && chat.turns) renderChat(chat.turns);
  }

  function visibleNodes() {
    const lens = window.__lens;
    if (!lens || !lens.S || !lens.S.vis || !lens.S.vis.nodes) return null;
    return lens.S.vis.nodes.length;
  }
  function showScope(turn, withFullGraph) {
    const lens = window.__lens;
    if (!lens || !turn || !turn.view) return;
    const scope = turn.scope || {};
    if (withFullGraph) {
      lens.applyView({ ...turn.view, clearFilters: true, hideIsolated: false });
      say(`Added the subgraph used for this answer (${scope.triples} triples) beside the full graph.`);
    } else {
      // Only the subgraph: the canvas is exactly what the model was shown.
      lens.applyView({ replace: true, files: turn.view.files,
                       mode: turn.view.mode, clearFilters: true,
                       hideIsolated: false, focus: turn.view.focus });
      say(`Showing only the subgraph used for this answer: ${scope.triples} triples`
        + (scope.dropped ? ` (${scope.dropped} more were beyond the scope limit)` : '') + '.');
    }
    const shown = visibleNodes();
    if (shown === 0) {
      say(logEl.textContent + '\nNothing is visible with the current filters: press '
        + '"Show the full graph again" to go back.');
    }
    chatBack.hidden = false;
  }

  chatLog.addEventListener('click', (event) => {
    const chip = event.target.closest('[data-ask]');
    if (chip) { ask(chip.dataset.ask); return; }
    const onlyButton = event.target.closest('[data-scope]');
    const fullButton = event.target.closest('[data-scope-full]');
    if (onlyButton || fullButton) {
      const key = (onlyButton || fullButton).dataset[onlyButton ? 'scope' : 'scopeFull'];
      showScope(scopes[+key], !!fullButton);
      return;
    }
    const applyButton = event.target.closest('[data-proposal]');
    if (applyButton) {
      const proposal = proposals[+applyButton.dataset.proposal];
      if (!proposal) return;
      run(() => op.editApply(proposal.patch_id), 'Applying the proposed patch…',
        (result) => {
          if (result.ok) showEditNote('The proposed patch was applied and recorded.');
          else renderChat(turns, errorBubble(result.error));
          if (result.ok) reloadChat();
        });
    }
  });

  function ask(message) {
    message = String(message || '').trim();
    if (!message || busy) return;
    chatText.value = '';
    autosize();
    renderChat(turns, pendingBubbles(message));
    run(() => op.chat(message, chatBudget.value), 'Thinking about the graph…',
      (result) => {
        if (!result.turns) { renderChat(turns, errorBubble(result.error, message)); return; }
        renderChat(result.turns);
        if (chatAuto.checked) {
          const latest = result.turns.filter((turn) => turn.role === 'graph').pop();
          if (latest) showScope(latest, false);
        }
      }, { quiet: true });
    chatText.focus();
  }
  function autosize() {
    chatText.style.height = 'auto';
    chatText.style.height = Math.min(chatText.scrollHeight, 160) + 'px';
  }
  chatSend.onclick = () => ask(chatText.value);
  chatText.addEventListener('input', autosize);
  chatText.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      ask(chatText.value);
    }
  });
  chatEverything.onclick = async () => {
    const lens = window.__lens;
    const names = [];
    Object.keys(scopes).forEach((key) => {
      const replaced = scopes[key].view.replace;
      if (Array.isArray(replaced)) replaced.forEach((name) => names.push(name));
    });
    if (lens) lens.applyView({ replace: names, files: [], clearFilters: true });
    await loadDataset();          // brings the dataset back with fresh defaults
    say('Showing the full graph again.');
  };
  $('#stChatReset').onclick = async () => {
    const answer = await op.chatReset();
    renderChat(answer && answer.turns ? answer.turns : []);
    say('Conversation cleared.');
    chatText.focus();
  };
  $('#stCollapse').onclick = () => {
    const collapsed = panel.classList.toggle('collapsed');
    $('#stCollapse').innerHTML = collapsed ? '&#8676;' : '&#8677;';
  };

  /* ---------- connect ---------- */
  (async function connect() {
    try {
      const status = await op.status();
      bar.hidden = false;
      panel.hidden = false;
      renderStatus(status);
      await loadDataset();
      await refreshPrompts();
      const chat = await op.chatState();
      renderChat(chat && chat.turns ? chat.turns : []);
      say(status.triples > 0
        ? `Loaded ${fileName(status.graph)} with ${fmt(status.triples)} triples.`
        : 'Empty dataset. Start with Starter ontology…, then Add sources…');
    } catch (error) {
      bar.hidden = true;     // served without a studio behind it: plain viewer
      panel.hidden = true;
    }
  })();
})();
