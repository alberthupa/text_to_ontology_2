"use strict";
/* ===================== studio control panel =====================
   The right-hand column. Loaded only when this page is served by
   text_to_ontology.studio; opened from disk the page is the plain viewer.

   This file holds the controls and nothing else. It:

     * talks to the backend only through named operations
       (POST api/op/<name>, GET api/op/<name>?args), and
     * changes the picture only through the lens view API
       (window.__lens.applyView / clearFiles / fileNames),

   so no domain logic lives here: switching a capability on in the backend
   never needs a change to this file beyond the button that calls it. */
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

  /* ---------- the panel ---------- */
  const PANEL = `
  <div class="shead"><span>Studio</span><button class="btn quiet" id="stCollapse" title="Hide or show the studio column" aria-label="Hide or show the studio column">&#8677;</button></div>
  <div id="stProgress" hidden role="status" aria-live="polite">
    <div class="sptop"><span id="stPLabel">Working\u2026</span><b id="stPPct"></b></div>
    <div class="sptrack"><div class="spfill" id="stPFill"></div></div>
    <div class="spdetail" id="stPDetail"></div>
  </div>
  <div class="sbody">
    <section>
      <h3>Dataset</h3>
      <p class="smuted" id="stStatus">Looking for the studio server\u2026</p>
      <div class="sactions">
        <button class="btn" id="stClear" title="Unload the dataset from the graph view; nothing is deleted">Clear view</button>
        <button class="btn danger" id="stReset" title="Delete the dataset file and every source in the inbox">Reset everything</button>
      </div>
      <p class="smuted" style="margin-top:6px">Reset deletes the dataset and the inbox and leaves the view empty. There is no undo.</p>
    </section>
    <section>
      <h3>1 \u00b7 Starter ontology</h3>
      <p class="smuted">Describe the world in a few sentences. The model proposes the classes and relationships, and ingestion may then only use them.</p>
      <textarea id="stText" spellcheck="false" placeholder="Example: We are a coffee roaster. We track roasters, farms, coffee lots, retailers, and the shipments between them. A lot is grown at one farm, has a roast level and a price, and is sold by retailers."></textarea>
      <div class="sactions"><button class="btn primary" id="stCreate">Create starter ontology</button></div>
      <div id="stImportDrop"><b>Drop an RDF / Turtle / TriG file here to import it</b><span>its classes and relations become the starter vocabulary, its individuals become data</span></div>
      <div class="sactions"><button class="btn" id="stImportPick">Import RDF file\u2026</button><input type="file" id="stImportFiles" accept=".ttl,.turtle,.trig,.nt,.nq,.n3,.rdf,.owl,.jsonld,.json" hidden></div>
      <p class="smuted" id="stWarn" style="margin-top:6px"></p>
      <div class="svocab" id="stVocab" hidden></div>
    </section>
    <section>
      <h3>2 \u00b7 Add sources</h3>
      <div id="stDrop"><b>Drop .txt or .md files here</b><span>only the data graph grows: classes and relationships stay as the starter defines them. An RDF/Turtle file belongs in section 1.</span></div>
      <div class="sactions"><button class="btn" id="stPick">Choose files\u2026</button><input type="file" id="stFiles" multiple accept=".txt,.md,.rst,.csv,.json,.jsonl,.yaml,.yml,.xml,.html,.log" hidden></div>
      <p class="smuted" id="stReady"></p>
    </section>
    <section>
      <h3>3 \u00b7 Ingestion prompt</h3>
      <p class="smuted">The prompt sent for every source window. Placeholders stay in the text; anything else is yours to change. Saved edits live in <code>prompts.local.json</code> next to the dataset.</p>
      <div class="srow">
        <select id="stPromptName" aria-label="Which prompt to edit"></select>
        <button class="btn" id="stPromptPreview">Preview</button>
      </div>
      <textarea id="stPromptText" spellcheck="false" class="scode"></textarea>
      <p class="smuted" id="stPromptNote"></p>
      <div class="sactions">
        <button class="btn primary" id="stPromptSave">Save prompt</button>
        <button class="btn" id="stPromptReset">Back to default</button>
      </div>
      <pre class="slog" id="stPromptPreviewBox" hidden></pre>
    </section>
    <section>
      <h3>4 \u00b7 Chat with the graph</h3>
      <p class="smuted">Ask about the graph. Each question is answered from only the relevant part of it: every answer says how many triples were selected, and <b>show the subgraph</b> draws exactly that part, so you can see what the answer was based on.</p>
      <div id="stChatLog" class="schat"></div>
      <textarea id="stChatText" class="schatbox" spellcheck="false" placeholder="What do we know about Poland and its population?"></textarea>
      <div class="sactions">
        <button class="btn primary" id="stChatSend">Ask</button>
        <select id="stChatBudget" title="How much of the subgraph the model may see">
          <option value="2500">compact subgraph</option>
          <option value="6000" selected>normal subgraph</option>
          <option value="12000">wide subgraph</option>
        </select>
        <button class="btn" id="stChatEverything" hidden>Show the full graph again</button>
        <button class="btn" id="stChatReset">Clear conversation</button>
      </div>
      <p class="smuted" id="stChatNote"></p>
      <label class="scheck"><input type="checkbox" id="stChatAuto" checked> show the subgraph after every answer</label>
    </section>
    <section>
      <h3>5 \u00b7 Edit the graph</h3>
      <p class="smuted">The data graph as Turtle. Additions are ordinary statements; a line starting with <code>- </code> removes one. Nothing changes until you preview it and then apply exactly what you saw.</p>
      <div class="sactions">
        <button class="btn" id="stEditLoad">Load the graph</button>
        <button class="btn primary" id="stEditPreview">Preview changes</button>
        <button class="btn" id="stEditApply" disabled>Apply changes</button>
      </div>
      <label class="scheck"><input type="checkbox" id="stEditAllow"> allow new classes and relations</label>
      <textarea id="stEditText" class="scode" spellcheck="false" placeholder="Load the graph, then change it here. Example:&#10;entity:new-thing a class:Tool ; skos:prefLabel &quot;New thing&quot; .&#10;- entity:old-thing skos:prefLabel &quot;Old thing&quot; ."></textarea>
      <p class="smuted" id="stEditNote"></p>
      <pre class="slog" id="stEditDiff" hidden></pre>
    </section>
    <section>
      <h3>Run log</h3>
      <pre class="slog" id="stLog">Nothing yet.</pre>
    </section>
  </div>`;

  const workspace = $('#workspace') || document.body;
  const panel = document.createElement('aside');
  panel.id = 'studio';
  panel.hidden = true;
  panel.setAttribute('aria-label', 'Studio');
  panel.innerHTML = PANEL;
  workspace.appendChild(panel);

  const toggle = document.createElement('button');
  toggle.className = 'btn';
  toggle.id = 'btnStudio';
  toggle.hidden = true;
  toggle.title = 'Starter ontology, ingestion, and reset';
  toggle.textContent = 'Studio';
  const toolbar = $('#top .row');
  if (toolbar) toolbar.appendChild(toggle);

  const statusEl = $('#stStatus'), logEl = $('#stLog'), vocabEl = $('#stVocab');
  const warnEl = $('#stWarn'), readyEl = $('#stReady'), dropEl = $('#stDrop');
  const importDrop = $('#stImportDrop'), importFiles = $('#stImportFiles');
  const chatLog = $('#stChatLog'), chatText = $('#stChatText');
  const chatEverything = $('#stChatEverything'), chatAuto = $('#stChatAuto');
  const chatBudget = $('#stChatBudget'), chatNote = $('#stChatNote');
  const editText = $('#stEditText'), editNote = $('#stEditNote');
  const editDiff = $('#stEditDiff'), editAllow = $('#stEditAllow');
  const editApply = $('#stEditApply');
  const progressEl = $('#stProgress'), pLabel = $('#stPLabel'), pPct = $('#stPPct');
  const pFill = $('#stPFill'), pDetail = $('#stPDetail');
  const promptName = $('#stPromptName'), promptText = $('#stPromptText');
  const promptNote = $('#stPromptNote'), promptPreview = $('#stPromptPreviewBox');
  let busy = false, lastStatus = null, prompts = [], scopes = {};
  let editPatch = null, proposals = {};

  /* ---------- progress ---------- */
  function showProgress(state) {
    if (!state || !state.running) { progressEl.hidden = true; return; }
    progressEl.hidden = false;
    progressEl.classList.add('running');
    pLabel.textContent = state.label || 'Working\u2026';
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
    ['#stCreate', '#stPick', '#stReset', '#stClear', '#stCollapse',
     '#stImportPick', '#stPromptSave', '#stPromptReset', '#stPromptPreview',
     '#stChatSend', '#stChatReset', '#stEditLoad', '#stEditPreview'].forEach((s) => {
      const button = $(s); if (button) button.disabled = on;
    });
    dropEl.classList.toggle('busy', on);
    if (on && message) logEl.textContent = message;
    if (!on) hideProgress();
  }
  async function follow(jobId, message) {
    logEl.textContent = message;
    let state = { running: true, label: message, percent: 0, detail: '' };
    showProgress(state);
    while (state.running) {
      await sleep(400);
      state = await op.progress(jobId);
      showProgress(state);
    }
    hideProgress();
    return state.result || { ok: false, error: 'the job ended without an answer' };
  }
  async function run(action, message, onResult) {
    if (busy) return;
    setBusy(true, message);
    try {
      const started = await action();
      const result = started && started.job_id ? await follow(started.job_id, message) : started;
      if (result.log) logEl.textContent = result.log;
      if (!result.ok) logEl.textContent = (result.log || '') + '\nError: ' + (result.error || 'unknown error');
      if (result.prompts) renderPrompts(result.prompts);
      if (result.status) renderStatus(result.status);
      if (result.ok && (result.status || result.sources || result.proposal
                        || result.summary)) {
        await loadDataset();
      }
      if (onResult) onResult(result);
    } catch (error) {
      hideProgress();
      logEl.textContent = 'Error: ' + error.message;
    } finally {
      setBusy(false);
    }
  }

  async function refreshPrompts() {
    const answer = await op.prompts();
    if (answer && answer.prompts) renderPrompts(answer.prompts);
  }

  /* ---------- views ---------- */
  function renderStatus(status) {
    if (!status) return;
    lastStatus = status;
    const classes = status.classes || [], relations = status.relations || [], facts = status.facts || [];
    statusEl.innerHTML = `<b>${esc(status.graph)}</b> \u00b7 ${fmt(status.triples)} triples`
      + (status.sources && status.sources.length ? `<br>${status.sources.length} source file(s) in the inbox` : '');
    vocabEl.hidden = false;
    if (status.ready) {
      vocabEl.innerHTML = `<div class="tagline">Classes: <code>${esc(classes.join(', '))}</code></div>`
        + `<div class="tagline">Relations: <code>${esc(relations.join(', ') || 'none')}</code></div>`
        + `<div class="tagline">Facts: <code>${esc(facts.join(', ') || 'none')}</code></div>`;
      readyEl.textContent = 'Ready. Dropped files may only use this vocabulary.';
      warnEl.textContent = status.triples > 0
        ? `A starter replaces the whole dataset, so this deletes the ${fmt(status.triples)} triples it holds now. Press Reset everything first if you want a clean start.`
        : '';
    } else {
      vocabEl.innerHTML = '<div class="tagline">No starter ontology yet. Create one above first: ingestion has no classes or relationships to use until then.</div>';
      readyEl.textContent = '';
      warnEl.textContent = status.triples > 0
        ? `This dataset has ${fmt(status.triples)} triples but no starter vocabulary. Reset everything before creating one.`
        : '';
    }
  }
  async function loadDataset() {
    const data = await op.dataset();
    const lens = window.__lens;
    if (!lens) return;
    const name = data.name || 'dataset.trig';   // the backend names the file
    const files = data.trig && data.trig.trim()
      ? [{ name, trig: data.trig }] : [];
    lens.applyView({ replace: true, files, resetFilters: true });
  }
  function clearView(message) {
    const lens = window.__lens;
    if (lens) lens.applyView({ replace: true, files: [] });
    if (message) logEl.textContent = message;
  }

  /* ---------- actions ---------- */
  $('#stCreate').onclick = () => {
    const text = $('#stText').value.trim();
    if (!text) { logEl.textContent = 'Error: paste some initial information first'; return; }
    const held = lastStatus ? lastStatus.triples : 0;
    if (held > 0 && !confirm(`A starter replaces the whole dataset and deletes its ${fmt(held)} triples.\n\nContinue?`)) {
      logEl.textContent = 'Cancelled. Nothing was changed.';
      return;
    }
    run(() => op.starter(text), 'Asking the model for a starter ontology. This can take a minute\u2026');
  };

  $('#stPick').onclick = () => $('#stFiles').click();
  $('#stFiles').onchange = () => {
    const files = [...$('#stFiles').files];
    $('#stFiles').value = '';
    ingest(files);
  };

  /* A dropped file is RDF when its suffix says so; the backend also sniffs
     the content, so a mislabelled file still lands in the right place. */
  const RDF_SUFFIX = /\.(ttl|turtle|trig|nt|nq|n3|rdf|owl|jsonld|json)$/i;
  function looksRdf(name) { return RDF_SUFFIX.test(name || ''); }

  async function importStarter(file) {
    const text = await file.text();
    return run(() => op.starterImport(file.name, text),
      `Importing ${file.name}. No model is asked: the file is parsed and checked\u2026`);
  }

  $('#stImportPick').onclick = () => importFiles.click();
  importFiles.onchange = () => {
    const file = importFiles.files[0];
    importFiles.value = '';
    if (file) importStarter(file);
  };
  ['dragenter', 'dragover'].forEach((type) => importDrop.addEventListener(type, (event) => {
    if (!event.dataTransfer || [...event.dataTransfer.types].indexOf('Files') < 0) return;
    event.preventDefault(); event.stopPropagation(); importDrop.classList.add('over');
  }));
  ['dragleave', 'dragend'].forEach((type) => importDrop.addEventListener(type, (event) => {
    event.stopPropagation(); importDrop.classList.remove('over');
  }));
  importDrop.addEventListener('drop', (event) => {
    event.preventDefault(); event.stopPropagation();
    importDrop.classList.remove('over');
    const file = (event.dataTransfer ? event.dataTransfer.files : [])[0];
    if (!file) return;
    if (looksRdf(file.name)) importStarter(file);
    else file.text().then((text) => {
      $('#stText').value = text;
      logEl.textContent = `${file.name} is not RDF, so it was put in the box above: `
        + 'read it, then press Create starter ontology.';
    });
  });

  async function ingest(fileList) {
    const rdf = fileList.filter((file) => looksRdf(file.name));
    if (rdf.length) {
      logEl.textContent = `${rdf.map((f) => f.name).join(', ')} is RDF, not source text. `
        + 'Drop it in section 1 (Starter ontology) to import it.';
      return;
    }
    const files = [];
    for (const file of fileList) files.push({ name: file.name, text: await file.text() });
    if (!files.length) return;
    return run(() => op.ingest(files),
      `Ingesting ${files.length} file${files.length > 1 ? 's' : ''}. This can take a minute per file\u2026`);
  }

  $('#stClear').onclick = () => clearView('View cleared. The dataset is untouched \u2014 press Reset everything to delete it.');
  $('#stReset').onclick = () => {
    if (!confirm('Delete the dataset and every ingested source? This cannot be undone.')) return;
    run(() => op.reset(), 'Deleting the dataset and the inbox\u2026');
  };

  ['dragenter', 'dragover'].forEach((type) => dropEl.addEventListener(type, (event) => {
    if (!event.dataTransfer || [...event.dataTransfer.types].indexOf('Files') < 0) return;
    event.preventDefault(); event.stopPropagation(); dropEl.classList.add('over');
  }));
  ['dragleave', 'dragend'].forEach((type) => dropEl.addEventListener(type, (event) => {
    event.stopPropagation(); dropEl.classList.remove('over');
  }));
  dropEl.addEventListener('drop', (event) => {
    event.preventDefault(); event.stopPropagation();
    dropEl.classList.remove('over');
    const files = [...(event.dataTransfer ? event.dataTransfer.files : [])];
    if (files.length) ingest(files);
  });

  $('#stCollapse').onclick = () => panel.classList.toggle('collapsed');
  toggle.onclick = () => { panel.hidden = !panel.hidden; };

  /* ---------- the prompt editor ---------- */
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
    promptNote.textContent = notes.join(' \u00b7 ');
    promptNote.style.color = item.error ? 'var(--warn)' : '';
    promptPreview.hidden = true;
  }
  promptName.onchange = showPrompt;
  $('#stPromptSave').onclick = () => run(
    () => op.promptSave(promptName.value, promptText.value), 'Saving the prompt\u2026');
  $('#stPromptReset').onclick = () => run(
    () => op.promptReset(promptName.value), 'Restoring the default prompt\u2026');
  $('#stPromptPreview').onclick = async () => {
    const answer = await op.promptPreview(promptName.value);
    promptPreview.hidden = false;
    promptPreview.textContent = answer.ok ? answer.prompt
      : 'Error: ' + (answer.error || 'could not render this prompt');
  };

  /* ---------- the chat ---------- */
  function shortName(iri) {
    return String(iri).split(/[#/]/).filter(Boolean).pop() || String(iri);
  }

  function scopeNote(turn, scope) {
    if (!scope) return '';
    const focus = scope.nodes && scope.nodes.length
      ? ` \u00b7 focus: ${esc(shortName(scope.nodes[0]))}` : '';
    const dropped = scope.dropped ? `, ${scope.dropped} beyond the scope limit` : '';
    const buttons = turn.view
      ? `<div class="sact">`
        + `<button class="btn primary" data-scope="${turn.index}">Show the subgraph</button>`
        + `<button class="btn" data-scope-full="${turn.index}">With the full graph</button>`
        + `</div>` : '';
    const seen = (scope && scope.rendered)
      ? ` \u00b7 ${scope.rendered} of them reached the model` : '';
    return `<div class="smeta">${scope.triples} triples selected${dropped}${focus}${seen}`
      + `<br>what the answer was based on${buttons ? '' : ' (no subgraph stored)'}${buttons}</div>`;
  }

  function proposalNote(turn) {
    const proposal = turn.proposal;
    if (!proposal) return '';
    if (!proposal.ok) {
      return `<div class="smeta">proposed change could not be checked: `
        + `${esc(proposal.error || 'not valid')}</div>`;
    }
    const counts = proposal.counts || {};
    return `<div class="smeta">proposed change: +${counts.added} \u2212${counts.removed}`
      + ` <button class="lnk" data-proposal="${turn.index}">Apply this patch</button></div>`;
  }

  function renderChat(turns) {
    const list = turns || [];
    scopes = {};
    proposals = {};
    list.forEach((turn) => {
      if (turn.role === 'graph' && turn.view) scopes[turn.index] = turn;
      if (turn.role === 'graph' && turn.proposal) proposals[turn.index] = turn.proposal;
    });
    chatLog.innerHTML = list.length ? list.map((turn) =>
      `<div class="msg ${turn.role === 'you' ? 'you' : 'graph'}">`
      + `<div class="who">${turn.role === 'you' ? 'you' : 'graph'}</div>`
      + `<div class="body">${esc(turn.text)}</div>`
      + (turn.role === 'graph' ? scopeNote(turn, turn.scope) : '')
      + (turn.role === 'graph' ? proposalNote(turn) : '')
      + '</div>').join('')
      : '<div class="sempty">Nothing yet. Ask a question about the graph.</div>';
    chatLog.scrollTop = chatLog.scrollHeight;
    chatEverything.hidden = !Object.keys(scopes).length;
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
      logEl.textContent = `Added the subgraph used for this answer `
        + `(${scope.triples} triples) beside the full graph.`;
    } else {
      // Only the subgraph: the canvas is exactly what the model was shown.
      lens.applyView({ replace: true, files: turn.view.files,
                       mode: turn.view.mode, clearFilters: true,
                       hideIsolated: false, focus: turn.view.focus });
      logEl.textContent = `Showing only the subgraph used for this answer: `
        + `${scope.triples} triples`
        + (scope.dropped ? ` (${scope.dropped} more were beyond the scope limit)` : '')
        + `. Press "Show the full graph again" to go back.`;
    }
    const shown = visibleNodes();
    if (shown === 0) {
      logEl.textContent += '\nNothing is visible with the current filters - press '
        + '"Show the full graph again" to go back.';
    } else if (shown !== null) {
      logEl.textContent += `\n${shown} node(s) on the canvas.`;
    }
    chatEverything.hidden = false;
  }

  chatLog.addEventListener('click', (event) => {
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
      run(() => op.editApply(proposal.patch_id),
        'Applying the proposed patch\u2026', (result) => {
          if (result.ok) showEditNote('The proposed patch was applied and recorded.');
          reloadChat();
        });
      return;
    }
  });

  $('#stChatSend').onclick = () => {
    const message = chatText.value.trim();
    if (!message) { logEl.textContent = 'Type a question first.'; return; }
    chatText.value = '';
    run(() => op.chat(message, chatBudget.value), 'Selecting the relevant subgraph\u2026',
      (result) => {
        if (!result.turns) return;
        renderChat(result.turns);
        if (chatAuto.checked) {
          const latest = result.turns.filter((turn) => turn.role === 'graph').pop();
          if (latest) showScope(latest, false);
        }
      });
  };
  chatText.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      $('#stChatSend').click();
    }
  });
  chatEverything.onclick = async () => {
    const lens = window.__lens;
    const names = [];
    Object.keys(scopes).forEach((key) => {
      (scopes[key].view.replace || []).forEach((name) => names.push(name));
    });
    if (lens) lens.applyView({ replace: names, files: [], clearFilters: true });
    await loadDataset();          // brings the dataset back with fresh defaults
    chatEverything.hidden = true;
    logEl.textContent = 'Showing the full graph again.';
  };
  async function reloadChat() {
    const chat = await op.chatState();
    if (chat && chat.turns) renderChat(chat.turns);
  }

  $('#stChatReset').onclick = async () => {
    const answer = await op.chatReset();
    renderChat(answer && answer.turns ? answer.turns : []);
    logEl.textContent = 'Conversation cleared.';
  };

  /* ---------- the editor ---------- */
  function showEditNote(text, bad) {
    editNote.textContent = text || '';
    editNote.style.color = bad ? 'var(--warn)' : '';
  }

  function showDiff(answer) {
    const sample = answer.sample || { added: [], removed: [] };
    const lines = [];
    (sample.added || []).forEach((line) => lines.push('+ ' + line));
    if (sample.more_added) lines.push(`+ \u2026 ${sample.more_added} more addition(s)`);
    (sample.removed || []).forEach((line) => lines.push('- ' + line));
    if (sample.more_removed) lines.push(`- \u2026 ${sample.more_removed} more removal(s)`);
    (answer.warnings || []).forEach((line) => lines.push('! ' + line));
    (answer.errors || []).forEach((line) => lines.push('x ' + line));
    editDiff.hidden = !lines.length;
    editDiff.textContent = lines.join('\n');
  }

  function forgetEdit() {
    editPatch = null;
    editApply.disabled = true;
  }

  $('#stEditLoad').onclick = () => run(() => op.editCurrent(),
    'Reading the data graph\u2026', (result) => {
      if (!result.ok) return;
      editText.value = result.turtle;
      forgetEdit();
      showDiff({});
      showEditNote(`${result.triples} triples, ${Math.round(result.bytes / 1024)} kB. `
        + 'Edit, then Preview changes.');
    });

  $('#stEditPreview').onclick = () => run(
    () => op.editPreview(editText.value, editAllow.checked),
    'Checking the patch\u2026', (result) => {
      forgetEdit();
      showDiff(result);
      if (result.ok) {
        editPatch = result.patch_id;
        editApply.disabled = false;
        showEditNote(`Ready: ${result.counts.added} addition(s), `
          + `${result.counts.removed} removal(s). Apply to write exactly this.`);
      } else {
        showEditNote(result.error || 'the patch is not valid', true);
      }
    });

  $('#stEditApply').onclick = () => {
    if (!editPatch) { showEditNote('Preview the patch first.', true); return; }
    run(() => op.editApply(editPatch), 'Applying the patch\u2026', (result) => {
      if (result.ok) {
        editText.value = result.turtle || editText.value;
        forgetEdit();
        showDiff({});
        showEditNote('Applied and recorded in the provenance graph.');
      }
    });
  };
  editText.addEventListener('input', () => {
    if (editPatch) showEditNote('The text changed since the preview: preview again.');
    forgetEdit();
  });

  /* ---------- connect ---------- */
  (async function connect() {
    try {
      const status = await op.status();
      panel.hidden = false;
      toggle.hidden = false;
      renderStatus(status);
      await loadDataset();
      await refreshPrompts();
      const chat = await op.chatState();
      if (chat && chat.turns) renderChat(chat.turns);
      chatNote.textContent = 'A wider subgraph means a more complete answer and more tokens '
        + 'per question. The answer always says how many triples were selected and how '
        + 'many reached the model.';
      logEl.textContent = status.triples > 0
        ? `Loaded ${status.graph} with ${fmt(status.triples)} triples.\n`
          + 'To start from scratch: Reset everything, paste a starter description, then drop sources.\n'
        : 'Empty dataset. Paste a starter description above, then drop sources below.\n';
    } catch (error) {
      panel.hidden = true;   // opened from disk: the lens works as always
      toggle.hidden = true;
    }
  })();
})();
