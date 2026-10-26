'use strict';
// Rendezvous lab view. Everything drawn here is a projection of the stored lab event log:
// the same reducer drives live, recorded and replay views. Nothing is scripted or simulated.
(() => {
  const SVG = 'http://www.w3.org/2000/svg';
  const AGENTS = ['physics', 'environment', 'mathematics'];
  const META = {physics: {letter: 'A', name: 'Physics'}, environment: {letter: 'B', name: 'Environment'}, mathematics: {letter: 'C', name: 'Mathematics'}};
  const POS = {mathematics: {x: 360, y: 118}, physics: {x: 150, y: 352}, environment: {x: 570, y: 352}};
  const ACTIVE = ['running', 'pausing', 'paused', 'stepping', 'stopping'];
  const MODES = {isolated: 'A · Isolated baseline', communication: 'B · Communication', intervention: 'C · Intervention'};
  const STATUS = {accepted: ['✓', 'accepted'], uncertain: ['?', 'uncertain'], rejected: ['✕', 'rejected'], duplicate: ['=', 'already known'], superseded: ['⤓', 'superseded']};
  const $ = id => document.getElementById(id);
  const h = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined && text !== null) n.textContent = String(text); return n; };
  const s = (tag, attrs = {}, text) => { const n = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); if (text !== undefined) n.textContent = String(text); return n; };
  const num = v => typeof v === 'number' ? (Number.isInteger(v) ? String(v) : String(Number(v.toFixed(4)))) : String(v);
  const clock = iso => iso ? new Date(iso).toLocaleTimeString([], {hour12: false}) + '.' + iso.slice(20, 23) : '—';
  const name = a => META[a] ? `${META[a].letter} · ${META[a].name}` : a;
  const short = id => id ? id.slice(0, 8) : '—';
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const factText = f => `${f.key} = ${num(f.value)}${f.unit ? ' ' + f.unit : ''}`;
  const trialLabel = t => !t ? '—' : t.kind === 'fixed' ? 'fixed inputs (120 W · 21 °C · 0.18 K/W)' : `fresh inputs · seed ${t.seed}`;

  const ui = {config: null, runs: [], runId: null, run: null, events: [], seq: 0, view: fresh(), cursor: 0, gen: 0, pumping: false,
              mode: 'idle', animate: false, speed: 2, selected: null, toggles: {}, compare: null, compareKey: null, rendered: 0,
              lastPoll: 0, polling: false, ready: false, message: ''};

  async function api(path, options = {}) {
    const response = await fetch(path, {credentials: 'same-origin', ...options,
      headers: options.body ? {'Content-Type': 'application/json', ...(options.headers || {})} : options.headers});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`);
    return body;
  }
  const say = text => { ui.message = text; $('lab-message').textContent = text; };

  // ---------------------------------------------------------------- projection
  function fresh() {
    const v = {meta: null, status: 'none', agents: {}, messages: new Map(), transcript: [], results: null, injections: [], paused: null,
               counters: {turns: 0, model_calls: 0, delivered: 0, attempts: 0}, ended: null};
    for (const a of AGENTS) v.agents[a] = {facts: new Map(), before: [], answer: null, pending: [], queued: [], thinking: null, turns: 0, arrived: 0};
    return v;
  }
  function note(v, e, kind, text, agent, detail) { v.transcript.push({seq: e.seq, at: e.at, kind, text, agent, detail}); }

  function apply(v, e) {
    const A = e.agent ? v.agents[e.agent] : null;
    switch (e.kind) {
      case 'run.created':
        v.meta = e; v.status = 'running';
        note(v, e, 'run', `Run created · ${MODES[e.mode]} · ${e.backend === 'claude' ? 'live Claude CLI (' + e.model + ')' : 'fixture brains, no model'} · ${trialLabel(e.trial)}`);
        if (e.approval) note(v, e, 'run', `Operator approved live inference: at most ${e.limits.max_inferences} model calls, ${e.limits.max_deliveries} delivered messages, ${e.limits.active_seconds} s active time.`);
        break;
      case 'agent.seeded':
        for (const f of e.facts) A.facts.set(f.fact_id, f);
        A.before = e.facts.map(f => ({...f}));
        note(v, e, 'seed', `${name(e.agent)} homebase seeded with private knowledge: ${e.facts.map(factText).join(' · ')}`, e.agent);
        break;
      case 'run.started':
        note(v, e, 'run', e.communication ? 'Agents may exchange messages. Each turn is one independent inference in that agent\'s own context.' : 'Communication disabled: each agent answers from its own memory only.');
        break;
      case 'turn.started':
        A.thinking = e; v.counters.turns += 1; if (e.brain === 'claude') v.counters.model_calls += 1;
        note(v, e, 'think', `${name(e.agent)} · turn ${e.turn_no} started · ${e.brain === 'claude' ? 'Claude CLI call (' + e.model + ')' : 'fixture policy'}${e.unread_inputs ? ' · ' + e.unread_inputs + ' new input(s)' : ''}`, e.agent);
        break;
      case 'turn.finished': {
        A.thinking = null; A.turns = Math.max(A.turns, e.turn_no || 0);
        for (const f of e.facts || []) A.facts.set(f.fact_id, f);
        const consumed = new Set(e.consumed_messages || []);
        A.pending = A.pending.filter(p => !consumed.has(p.message_id));
        if (e.answer) A.answer = e.answer;
        for (const q of e.queued || []) { v.messages.set(q.message_id, {...q, status: 'queued'}); A.queued.push(q.message_id); }
        note(v, e, e.status === 'ok' ? 'turn' : 'error', e.status === 'ok' ? `${name(e.agent)} · turn ${e.turn_no} finished` : `${name(e.agent)} · turn ${e.turn_no} failed (${e.error}) · not retried`, e.agent, e);
        break; }
      case 'delivery.started': { const m = v.messages.get(e.message_id); if (m) m.status = 'sending'; v.counters.attempts += 1; break; }
      case 'message.delivered': {
        const env = e.envelope;
        const m = v.messages.get(e.message_id) || {message_id: e.message_id, sender: e.sender, recipient: e.recipient, intent: env.intent, content: env.content, evidence: env.evidence};
        Object.assign(m, {status: 'delivered', delivered_at: e.delivered_at, sent_at: e.sent_at, received_at: e.received_at, queued_at: e.queued_at, latency_ms: e.latency_ms, transport: e.transport});
        v.messages.set(e.message_id, m);
        v.agents[e.sender].queued = v.agents[e.sender].queued.filter(id => id !== e.message_id);
        v.agents[e.recipient].pending.push({message_id: e.message_id, from: e.sender, intent: env.intent, evidence: env.evidence, at: e.received_at});
        v.agents[e.recipient].arrived += 1;
        v.counters.delivered += 1;
        note(v, e, 'message', '', e.sender, e);
        break; }
      case 'message.failed': {
        const m = v.messages.get(e.message_id); if (m) m.status = 'failed';
        v.agents[e.sender].queued = v.agents[e.sender].queued.filter(id => id !== e.message_id);
        note(v, e, 'error', `Delivery ${short(e.message_id)} ${name(e.sender)} → ${name(e.recipient)} failed (${e.error}); not retried.`, e.sender);
        break; }
      case 'run.pause_requested': v.status = 'pausing'; note(v, e, 'pause', 'Pause requested. It takes effect at the next event boundary; an in-flight model call finishes first.'); break;
      case 'run.paused': v.status = 'paused'; v.paused = e;
        note(v, e, 'pause', `Paused · ${e.reason}. Gates closed on all three agents: no inference, delivery or inbound message until resumed. ${e.queued.length} message(s) queued, not delivered.`);
        break;
      case 'run.resumed': v.status = 'running'; note(v, e, 'pause', 'Resumed.'); break;
      case 'run.step': v.status = 'stepping'; note(v, e, 'pause', 'Step: exactly one turn or delivery, then paused again.'); break;
      case 'fact.injected': {
        if (e.replaced) { const old = A.facts.get(e.replaced.fact_id); if (old) A.facts.set(old.fact_id, {...old, status: 'superseded', superseded_by: e.fact.fact_id}); }
        A.facts.set(e.fact.fact_id, e.fact); v.injections.push(e);
        note(v, e, 'inject', `Operator injected into ${name(e.agent)} only: ${e.key} = ${num(e.value)} ${e.unit}${e.replaced ? ' (was ' + num(e.replaced.value) + ' in ' + e.replaced.fact_id + ', kept as history)' : ''}. Ground truth ${num(e.truth_before_c)} → ${num(e.truth_after_c)} °C (hidden from agents).`, e.agent);
        break; }
      case 'run.stop_requested': v.status = 'stopping'; note(v, e, 'limit', 'Stop requested by the operator. Queued messages will be withheld.'); break;
      case 'run.deadline': case 'budget.exhausted': note(v, e, 'limit', e.reason); break;
      case 'run.interrupted': v.status = 'interrupted'; note(v, e, 'error', `Interrupted: ${e.reason}. Nothing continues until the operator resumes or stops it.`); break;
      case 'run.resynced': note(v, e, 'run', 'Run state rebuilt from the agents\' own stores after a restart.'); break;
      case 'run.error': note(v, e, 'error', e.error); break;
      case 'run.completed': case 'run.stopped': case 'run.failed': {
        v.status = e.kind.slice(4); v.results = e.results || null; v.ended = e;
        for (const id of e.withheld || []) { const m = v.messages.get(id); if (m) m.status = 'withheld'; }
        for (const a of AGENTS) v.agents[a].queued = [];
        const r = e.results;
        note(v, e, 'done', r ? `Run ${v.status}. ${r.correct_agents}/3 agents hold a correct final answer · ${r.messages.delivered} messages delivered · ${r.inference.turns} turns · audit ${r.event_audit.ok ? 'consistent' : 'found problems'}.` : `Run ${v.status}.`);
        break; }
      default: break;
    }
  }

  // ---------------------------------------------------------------- network drawing
  function curve(a, b) {
    const p = POS[a], q = POS[b], dx = q.x - p.x, dy = q.y - p.y, len = Math.hypot(dx, dy), ux = dx / len, uy = dy / len, r = 64, off = 30;
    const sx = p.x + ux * r, sy = p.y + uy * r, ex = q.x - ux * r, ey = q.y - uy * r;
    const cx = (sx + ex) / 2 - uy * off, cy = (sy + ey) / 2 + ux * off;
    return {sx, sy, cx, cy, ex, ey, d: `M${sx.toFixed(1)} ${sy.toFixed(1)} Q${cx.toFixed(1)} ${cy.toFixed(1)} ${ex.toFixed(1)} ${ey.toFixed(1)}`};
  }
  const at = (c, t) => { const u = 1 - t; return {x: u * u * c.sx + 2 * u * t * c.cx + t * t * c.ex, y: u * u * c.sy + 2 * u * t * c.cy + t * t * c.ey}; };

  function buildSvg() {
    const svg = $('lab-svg');
    for (const n of [...svg.children]) if (!['title', 'desc'].includes(n.tagName)) n.remove();
    const lanes = s('g', {class: 'lanes'}), nodes = s('g', {class: 'nodes'}), packets = s('g', {id: 'lab-packets'});
    for (const a of AGENTS) for (const b of AGENTS) if (a !== b) {
      const c = curve(a, b);
      lanes.append(s('path', {d: c.d, class: `lane from-${a}`, id: `lane-${a}-${b}`}));
    }
    for (const a of AGENTS) {
      const {x, y} = POS[a];
      const g = s('g', {class: `node agent-${a}`, id: `node-${a}`, tabindex: '0', role: 'button', 'aria-label': `${name(a)} homebase`});
      g.append(s('title', {}, `${name(a)} · open homebase`));
      g.append(s('circle', {cx: x, cy: y, r: 74, class: 'halo'}), s('circle', {cx: x, cy: y, r: 60, class: 'ring'}), s('circle', {cx: x, cy: y, r: 52, class: 'core'}));
      g.append(s('text', {x, y: y - 10, class: 'letter'}, META[a].letter), s('text', {x, y: y + 16, class: 'role'}, META[a].name));
      g.append(s('text', {x, y: y + 34, class: 'facts', id: `facts-${a}`}, ''));
      g.append(s('text', {x, y: a === 'mathematics' ? y - 82 : y + 94, class: 'answer', id: `answer-${a}`}, ''));
      g.append(s('text', {x, y: a === 'mathematics' ? y - 100 : y + 112, class: 'state', id: `state-${a}`}, ''));
      g.append(s('g', {class: 'queue', id: `queue-${a}`}), s('g', {class: 'inbox', id: `inbox-${a}`}));
      g.addEventListener('click', () => focusHome(a));
      g.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); focusHome(a); } });
      nodes.append(g);
    }
    svg.append(lanes, nodes, packets);
  }
  function focusHome(a) { const card = $('home-' + a); if (card) { card.scrollIntoView({behavior: reduced ? 'auto' : 'smooth', block: 'nearest'}); card.classList.remove('flash'); void card.offsetWidth; card.classList.add('flash'); } }

  function renderNetwork() {
    const v = ui.view;
    for (const a of AGENTS) {
      const A = v.agents[a], node = $('node-' + a);
      if (!node) continue;
      node.classList.toggle('thinking', !!A.thinking);
      const current = [...A.facts.values()].filter(f => ['accepted', 'duplicate'].includes(f.status));
      const learned = [...A.facts.values()].filter(f => f.origin_kind === 'received' && f.status === 'accepted').length;
      $('facts-' + a).textContent = A.facts.size ? `${current.length} facts · ${learned} learned` : 'empty';
      const ans = A.answer;
      $('answer-' + a).textContent = !ans ? '' : ans.status === 'final' ? `answer ${num(ans.value_celsius)} °C` : ans.status === 'provisional' ? 'provisional' : 'cannot answer yet';
      const correct = v.results?.agents?.[a];
      $('answer-' + a).setAttribute('class', 'answer' + (correct ? (correct.correct ? ' good' : ans?.status === 'final' ? ' bad' : '') : ''));
      $('state-' + a).textContent = A.thinking ? (A.thinking.brain === 'claude' ? 'Claude call in progress…' : 'fixture turn…') : '';
      const queue = $('queue-' + a); queue.replaceChildren();
      A.queued.forEach((id, i) => {
        const m = v.messages.get(id); if (!m) return;
        const c = curve(a, m.recipient), p = at(c, 0.02 + i * 0.07);
        const dot = s('circle', {cx: p.x, cy: p.y, r: 6, class: `queued from-${a}`}); dot.append(s('title', {}, `Queued, not delivered: ${m.intent} to ${name(m.recipient)}`));
        queue.append(dot);
      });
      const inbox = $('inbox-' + a); inbox.replaceChildren();
      const n = A.pending.reduce((t, p) => t + Math.max(1, p.evidence.length), 0);
      if (n) {
        const {x, y} = POS[a];
        inbox.append(s('circle', {cx: x + 46, cy: y - 42, r: 13, class: 'badge'}), s('text', {x: x + 46, y: y - 38, class: 'badge-text'}, n));
        inbox.lastChild.append(s('title', {}, `${n} delivered item(s) awaiting this agent's next turn`));
      }
    }
  }

  function arrive(a) {
    const node = $('node-' + a); if (!node) return;
    node.classList.remove('arrived'); void node.getBoundingClientRect(); node.classList.add('arrived');
  }

  function animate(e, gen) {
    return new Promise(resolve => {
      const host = $('lab-packets');
      if (!host || reduced || gen !== ui.gen) { arrive(e.recipient); return resolve(); }
      const c = curve(e.sender, e.recipient), lane = $(`lane-${e.sender}-${e.recipient}`);
      const g = s('g', {class: `packet from-${e.sender}`});
      g.append(s('title', {}, `${e.envelope.intent} · ${name(e.sender)} → ${name(e.recipient)} · delivered ${clock(e.delivered_at)}`));
      g.append(s('circle', {r: 11}), s('text', {y: -17, class: 'packet-label'}, e.envelope.intent + (e.envelope.evidence.length ? ` · ${e.envelope.evidence.length} evidence` : '')));
      host.append(g); lane?.classList.add('active');
      const duration = 1500 / (ui.mode === 'replay' ? ui.speed : 1), start = performance.now();
      const frame = now => {
        const t = Math.min(1, (now - start) / duration), eased = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2, p = at(c, eased);
        g.setAttribute('transform', `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})`);
        if (t < 1 && gen === ui.gen) requestAnimationFrame(frame);
        else { g.remove(); lane?.classList.remove('active'); arrive(e.recipient); resolve(); }
      };
      requestAnimationFrame(frame);
    });
  }

  // ---------------------------------------------------------------- player
  const wait = ms => new Promise(r => setTimeout(r, ms));
  async function pump() {
    if (ui.pumping) return;
    ui.pumping = true;
    const gen = ui.gen;
    try {
      while (gen === ui.gen && ui.cursor < ui.events.length) {
        const e = ui.events[ui.cursor];
        if (ui.mode === 'replay' && ui.cursor > 0) {
          const gap = (Date.parse(e.at) - Date.parse(ui.events[ui.cursor - 1].at)) / ui.speed;
          await wait(Math.max(60, Math.min(gap, 1400)));
          if (gen !== ui.gen) break;
        }
        if (ui.animate && e.kind === 'message.delivered') {
          // The packet leaves the sender's outbox, travels, and the delivery is applied on arrival.
          const sender = ui.view.agents[e.sender];
          if (sender) sender.queued = sender.queued.filter(id => id !== e.message_id);
          renderNetwork();
          await animate(e, gen);
          if (gen !== ui.gen) break;
        }
        apply(ui.view, e);
        ui.cursor += 1;
        if (!ui.animate && ui.cursor < ui.events.length) continue;
        renderAll();
      }
      if (gen === ui.gen) {
        renderAll();
        if (ui.mode === 'replay' && ui.cursor >= ui.events.length) { ui.mode = 'recorded'; say('Replay finished. Showing the recorded run.'); renderAll(); }
      }
    } finally { ui.pumping = false; }
    if (gen !== ui.gen) pump();
  }

  function reset(mode) {
    ui.gen += 1; ui.view = fresh(); ui.cursor = 0; ui.rendered = 0; ui.mode = mode; ui.selected = null;
    $('lab-transcript').replaceChildren(); $('lab-records').hidden = true;
    for (const p of [...($('lab-packets')?.children || [])]) p.remove();
  }

  async function select(runId, {live = false} = {}) {
    ui.runId = runId || null; ui.run = null; ui.events = []; ui.seq = 0; ui.compare = null; ui.compareKey = null;
    reset(runId ? 'loading' : 'idle'); ui.animate = false;
    $('lab-run').value = runId || '';
    renderAll();
    if (runId) await poll(true, live);
  }

  async function poll(first = false, live = false) {
    if (!ui.runId || ui.polling) return;
    ui.polling = true;
    try {
      const body = await api(`/lab/runs/${ui.runId}?after=${ui.seq}`);
      if (body.run.id !== ui.runId) return;
      ui.run = body.run;
      if (first) { ui.mode = ACTIVE.includes(body.run.status) || live ? 'live' : 'recorded'; ui.animate = ui.mode === 'live'; }
      if (body.events.length) { ui.events.push(...body.events); ui.seq = body.events[body.events.length - 1].seq; }
      if (ui.mode === 'live' && !ACTIVE.includes(body.run.status) && body.run.status !== 'interrupted' && ui.cursor >= ui.events.length) ui.mode = 'recorded';
      if (body.run.results && ui.compareKey !== body.run.trial_key + body.run.status) loadCompare();
      if (ui.mode !== 'replay') pump(); else renderAll();
    } catch (e) { say(e.message); }
    finally { ui.polling = false; }
  }

  async function loadCompare() {
    if (!ui.run) return;
    ui.compareKey = ui.run.trial_key + ui.run.status;
    try { ui.compare = (await api('/lab/compare?trial_key=' + encodeURIComponent(ui.run.trial_key))).runs; renderResults(); } catch (e) { say(e.message); }
  }

  async function loadRuns() {
    try {
      const body = await api('/lab/runs');
      ui.runs = body.runs;
      const select = $('lab-run'), keep = ui.runId || '';
      const options = [h('option', '', 'New run…')]; options[0].value = '';
      for (const r of ui.runs) {
        const o = h('option', '', `${r.created_at.slice(5, 16).replace('T', ' ')} · ${MODES[r.mode]} · ${r.backend === 'claude' ? 'Claude' : 'fixture'} · ${r.trial.kind === 'fixed' ? 'fixed' : 'seed ' + r.trial.seed} · ${r.status}${r.correct_agents != null ? ' · ' + r.correct_agents + '/3' : ''}`);
        o.value = r.id; options.push(o);
      }
      select.replaceChildren(...options); select.value = keep;
      const active = ui.runs.find(r => ACTIVE.includes(r.status));
      if (active && !ui.runId) await select_(active.id);
    } catch (e) { if (e.message !== 'Request failed (401)') say(e.message); }
  }
  const select_ = id => select(id, {live: true});

  // ---------------------------------------------------------------- rendering
  function renderAll() {
    renderBadges(); renderMeters(); renderNetwork(); renderTranscript(); renderHomes(); renderLineage(); renderResults(); renderButtons();
  }

  function renderBadges() {
    const v = ui.view, run = ui.run, src = $('lab-source'), brain = $('lab-brain-badge');
    const label = ui.mode === 'replay' ? 'REPLAY' : !run ? 'IDLE' : run.backend !== 'claude' ? 'FIXTURE' : ui.mode === 'live' ? 'LIVE' : 'RECORDED';
    src.textContent = label; src.className = 'source-badge ' + label.toLowerCase();
    brain.hidden = !run; $('lab-inputs-badge').hidden = !run;
    if (run) brain.textContent = run.backend === 'claude' ? `CLAUDE CLI · ${run.model}` : 'FIXTURE BRAINS · NO MODEL';
    const status = ui.mode === 'replay' ? `replaying ${ui.cursor}/${ui.events.length} events` : run ? `${MODES[run.mode]} · ${run.status}${run.pause_reason && run.status === 'paused' ? ' — ' + run.pause_reason : ''}` : 'No run selected';
    $('lab-status').textContent = status;
    $('lab-status').className = 'lab-status ' + (run ? (ui.mode === 'replay' ? 'replay' : run.status) : '');
  }

  function meter(label, value, limit, hint) {
    const box = h('div', 'lab-meter'), bar = h('div', 'lab-bar'), fill = h('span');
    box.append(h('span', 'lab-meter-label', label), h('b', '', limit != null ? `${value} / ${limit}` : value));
    if (limit) { fill.style.width = Math.min(100, value / limit * 100) + '%'; bar.append(fill); box.append(bar); }
    if (hint) box.append(h('small', '', hint));
    return box;
  }
  function renderMeters() {
    const host = $('lab-meters'), run = ui.run, v = ui.view, limits = run?.limits || ui.config?.limits;
    if (!limits) return host.replaceChildren();
    const queued = [...v.messages.values()].filter(m => m.status === 'queued' || m.status === 'sending').length;
    const delivered = [...v.messages.values()].filter(m => m.status === 'delivered').length;
    const active = run ? Math.round((run.clock.active_ms + (run.clock.running_since && ACTIVE.includes(run.status) && run.status !== 'paused' ? Date.now() - run.clock.running_since * 1000 : 0)) / 1000) : 0;
    host.replaceChildren(
      meter(run?.backend === 'claude' ? 'Model calls' : 'Agent turns', v.counters.turns, limits.max_inferences, run?.backend === 'claude' ? 'each = one CLI invocation' : 'fixture: no model calls'),
      meter('Delivered messages', delivered, limits.max_deliveries, 'over A2A HTTP'),
      meter('Queued, not delivered', queued, null, queued ? 'waiting at the sender' : 'none'),
      meter('Active time (s)', ui.mode === 'live' ? active : Math.round((v.results?.latency?.active_seconds) ?? active), limits.active_seconds, 'paused time excluded'));
  }

  function chip(status, corrected) {
    if (corrected) return h('span', 'lab-chip st-accepted st-corrected', '↻ corrected');
    const [icon, label] = STATUS[status] || ['•', status];
    return h('span', 'lab-chip st-' + status, `${icon} ${label}`);
  }

  function evidenceChips(list) {
    const wrap = h('span', 'lab-evidence');
    for (const e of list || []) {
      const c = h('span', 'lab-ev', `${e.key} = ${num(e.value)}${e.unit ? ' ' + e.unit : ''}`);
      c.title = `Evidence ${e.evidence_id} · origin ${e.origin.agent} ${e.origin.fact_id} (${e.origin.kind}) · digest ${e.digest.slice(0, 12)}…`;
      wrap.append(c);
    }
    return wrap;
  }

  function renderTranscript() {
    const host = $('lab-transcript'), items = ui.view.transcript;
    if (ui.rendered > items.length) { host.replaceChildren(); ui.rendered = 0; }
    const stick = host.scrollHeight - host.scrollTop - host.clientHeight < 40;
    for (const item of items.slice(ui.rendered)) host.append(transcriptItem(item));
    ui.rendered = items.length;
    $('lab-transcript-count').textContent = items.length ? `${ui.view.counters.delivered} messages · ${ui.view.counters.turns} turns` : '';
    if (stick) host.scrollTop = host.scrollHeight;
  }

  function transcriptItem(item) {
    const li = h('li', 'lab-line k-' + item.kind + (item.agent ? ' agent-' + item.agent : ''));
    li.append(h('time', '', clock(item.at)));
    const body = h('div', 'lab-line-body');
    const e = item.detail;
    if (item.kind === 'message') {
      const head = h('p', 'lab-msg-head');
      head.append(h('span', 'dot from-' + e.sender), h('b', '', `${name(e.sender)} → ${name(e.recipient)}`), h('span', 'lab-intent', e.envelope.intent));
      body.append(head, h('p', 'lab-content', e.envelope.content || '(no text)'));
      if (e.envelope.evidence.length) body.append(evidenceChips(e.envelope.evidence));
      body.append(h('small', 'lab-meta', `queued ${clock(e.queued_at)} → delivered ${clock(e.delivered_at)} · ${e.latency_ms} ms A2A SendMessage · message ${short(e.message_id)} · ack ${short(e.transport?.reply_message_id)}`));
    } else if (item.kind === 'turn' && e) {
      body.append(h('p', 'lab-turn-head', item.text));
      for (const d of e.decisions || []) {
        const row = h('p', 'lab-decision');
        row.append(chip(d.status), h('span', '', ` ${d.key} = ${num(d.value)} ${d.unit} from ${name(d.from)} → ${d.fact_id}`), h('small', '', ` ${d.reason}`));
        body.append(row);
      }
      for (const f of (e.facts || []).filter(f => f.origin_kind === 'derived')) body.append(h('p', 'lab-derived', `derived ${f.fact_id}: ${factText(f)} from ${f.depends_on.join(', ') || 'nothing cited'}`));
      for (const q of e.queued || []) body.append(h('p', 'lab-queued', `queued → ${name(q.recipient)} (${q.intent}): “${q.content}”${q.evidence.length ? ' + ' + q.evidence.map(factText).join(', ') : ''}`));
      for (const x of e.suppressed || []) body.append(h('p', 'lab-warn', `suppressed duplicate message to ${name(x.to)}`));
      for (const x of e.dropped || []) body.append(h('p', 'lab-warn', `dropped message to ${name(x.to)}: ${x.reason}`));
      if (e.answer) body.append(h('p', 'lab-answer', `answer: ${e.answer.status === 'final' ? 'FINAL ' + num(e.answer.value_celsius) + ' °C' : e.answer.status.replace('_', ' ')} — ${e.answer.justification}`));
      if (e.note) body.append(h('p', 'lab-note', `note to self: ${e.note}`));
      if (e.call && e.call.call_id) body.append(h('small', 'lab-meta', `${e.call.observed_model || e.call.requested_model} · ${e.call.latency_ms} ms · call ${short(e.call.call_id)} · ${e.call.cli_internal_turns ?? '?'} CLI turns${e.call.usage ? ' · ' + (e.call.usage.output_tokens ?? '?') + ' output tokens' : ''}`));
      else body.append(h('small', 'lab-meta', `fixture policy · ${e.latency_ms ?? '?'} ms · no model`));
      for (const w of e.warnings || []) body.append(h('p', 'lab-warn', w));
    } else if (item.kind === 'error' && e) {
      body.append(h('p', '', item.text), h('small', 'lab-meta', e.detail || ''));
    } else body.append(h('p', '', item.text));
    li.append(body);
    return li;
  }

  function renderHomes() {
    const host = $('lab-homebases'), v = ui.view;
    if (!host.children.length) for (const a of AGENTS) {
      const card = h('article', 'lab-home agent-' + a); card.id = 'home-' + a;
      const head = h('div', 'lab-home-head'), title = h('div');
      title.append(h('h4', '', `Agent ${META[a].letter} · ${META[a].name}`), h('small', 'lab-home-meta', ''));
      const toggle = h('div', 'lab-toggle'); toggle.setAttribute('role', 'group'); toggle.setAttribute('aria-label', 'Memory view');
      for (const [key, label] of [['after', 'Now / after'], ['before', 'Before']]) {
        const b = h('button', 'quiet small', label); b.type = 'button'; b.dataset.view = key;
        b.addEventListener('click', () => { ui.toggles[a] = key; renderHomes(); });
        toggle.append(b);
      }
      head.append(title, toggle);
      card.append(head, h('div', 'lab-home-body'));
      host.append(card);
    }
    for (const a of AGENTS) {
      const card = $('home-' + a), A = v.agents[a], view = ui.toggles[a] || 'after', body = card.querySelector('.lab-home-body');
      const peer = ui.config?.agents?.find(x => x.id === a);
      card.querySelector('.lab-home-meta').textContent = `${a} · own process ${peer ? peer.url.replace('http://', '') : ''} · own SQLite memory`;
      for (const b of card.querySelectorAll('.lab-toggle button')) b.setAttribute('aria-pressed', String(b.dataset.view === view));
      card.classList.toggle('thinking', !!A.thinking);
      const list = h('ul', 'lab-facts');
      const facts = view === 'before' ? A.before : [...A.facts.values()];
      const beforeIds = new Set(A.before.map(f => f.fact_id));
      for (const f of facts) {
        const li = h('li', 'lab-fact' + (f.status === 'superseded' ? ' superseded' : '') + (ui.selected && ui.selected.agent === a && ui.selected.id === f.fact_id ? ' selected' : ''));
        const btn = h('button', 'lab-fact-btn'); btn.type = 'button';
        btn.append(h('code', '', f.fact_id), h('span', 'lab-fact-text', factText(f)));
        const tags = h('span', 'lab-tags');
        tags.append(chip(f.status, !!(f.supersedes && f.status === 'accepted')));
        tags.append(h('span', 'lab-origin', f.origin_kind === 'initial' ? 'private' : f.origin_kind === 'operator' ? 'operator' : f.origin_kind === 'derived' ? 'derived' : `from ${META[f.sender]?.name || f.sender}`));
        if (view === 'after' && !beforeIds.has(f.fact_id) && f.origin_kind === 'received' && f.status === 'accepted') tags.append(h('span', 'lab-new', 'learned'));
        btn.append(tags);
        btn.title = f.reason || f.note || '';
        btn.addEventListener('click', () => { ui.selected = {agent: a, id: f.fact_id}; renderHomes(); renderLineage(); $('lab-lineage').scrollIntoView({behavior: reduced ? 'auto' : 'smooth', block: 'nearest'}); });
        li.append(btn); list.append(li);
      }
      const pieces = [list];
      if (!facts.length) pieces.unshift(h('p', 'muted', 'No facts stored for this run yet.'));
      if (view === 'after') {
        for (const p of A.pending) {
          const box = h('p', 'lab-pending'); box.append(h('span', '', `📥 delivered from ${META[p.from]?.name || p.from} (${p.intent}), awaiting this agent's next turn: `), evidenceChips(p.evidence));
          if (!p.evidence.length) box.append(h('span', 'muted', 'no evidence attached'));
          pieces.push(box);
        }
        for (const id of A.queued) { const m = v.messages.get(id); if (m) pieces.push(h('p', 'lab-outq', `📤 queued, not delivered → ${name(m.recipient)} (${m.intent})`)); }
        const ans = A.answer, res = v.results?.agents?.[a], box = h('div', 'lab-answerbox');
        if (ans) {
          box.append(h('b', '', ans.status === 'final' ? `Final answer: ${num(ans.value_celsius)} °C` : ans.status === 'provisional' ? 'Provisional — no final value' : 'Cannot answer yet'));
          if (res) box.append(h('span', 'lab-verdict ' + (res.correct ? 'good' : 'bad'), res.correct ? '✓ matches ground truth' : res.answered ? '✕ does not match ground truth' : '✕ no final answer'));
          box.append(h('small', '', ans.justification));
        } else box.append(h('small', 'muted', 'No answer recorded yet.'));
        pieces.push(box);
      } else pieces.push(h('small', 'muted', 'Private knowledge at seed time, before any exchange.'));
      body.replaceChildren(...pieces);
    }
  }

  function findFact(agent, id) { return ui.view.agents[agent]?.facts.get(id); }
  function renderLineage() {
    const host = $('lab-lineage');
    if (!ui.selected) { host.replaceChildren(h('p', 'muted', 'Select any fact in a homebase to trace where it came from.')); return; }
    const {agent, id} = ui.selected, root = findFact(agent, id);
    if (!root) { host.replaceChildren(h('p', 'muted', 'Select any fact in a homebase to trace where it came from.')); return; }
    const out = h('ol', 'lab-chain');
    const seen = new Set();
    const walk = (a, fid, depth) => {
      const f = findFact(a, fid), key = a + ':' + fid;
      if (!f || seen.has(key) || depth > 8) return;
      seen.add(key);
      if (f.origin_kind === 'received') walk(f.sender, f.via_fact, depth + 1);
      if (f.origin_kind === 'derived') for (const d of f.depends_on) walk(a, d, depth + 1);
      const li = h('li', 'lab-hop agent-' + a + (a === agent && fid === id ? ' target' : ''));
      const how = f.origin_kind === 'initial' ? 'private initial knowledge' : f.origin_kind === 'operator' ? 'operator injection' :
        f.origin_kind === 'derived' ? `derived from ${f.depends_on.join(', ') || 'nothing cited'}${f.reason ? ' — ' + f.reason : ''}` :
        `received from ${name(f.sender)} as evidence ${f.via_fact} in message ${short(f.source_message)}; decision: ${f.status}${f.reason ? ' — ' + f.reason : ''}`;
      li.append(h('b', '', `${name(a)} · ${fid}`), h('span', '', ` ${factText(f)} `), chip(f.status));
      li.append(h('small', '', `${how} · stored ${clock(f.created_at)}${f.supersedes ? ' · supersedes ' + f.supersedes : ''}${f.superseded_by ? ' · superseded by ' + f.superseded_by : ''}`));
      out.append(li);
    };
    walk(agent, id, 0);
    const hops = root.lineage || [];
    const path = h('p', 'muted', 'Recorded path: ' + hops.map(x => `${META[x.agent]?.name || x.agent} ${x.fact_id} (${x.kind}${x.from ? ' from ' + x.from : ''})`).join(' → '));
    host.replaceChildren(h('p', '', `Where ${name(agent)} ${id} (${factText(root)}) came from, origin first:`), out, path);
  }

  function renderResults() {
    const host = $('lab-results'), run = ui.run, base = $('lab-baseline');
    base.hidden = true;
    if (!run || !ui.view.results) {
      host.replaceChildren(h('p', 'muted', run && ACTIVE.includes(run.status) ? 'Results appear when this run completes; the independent check runs against ground truth the agents never see.'
        : 'Results appear when a run completes. Runs with the same inputs are compared side by side.'));
      return;
    }
    if (!ui.compare) return;
    const runs = [...ui.compare].filter(r => r.results).sort((a, b) => a.created_at.localeCompare(b.created_at));
    const pick = mode => runs.filter(r => r.mode === mode && r.backend === run.backend).pop();
    const columns = [];
    for (const mode of ['isolated', 'communication', 'intervention']) {
      const r = run.mode === mode ? runs.find(x => x.id === run.id) : pick(mode);
      if (r) columns.push(r);
    }
    if (!columns.length) return;
    base.hidden = run.mode === 'isolated' || columns.some(c => c.mode === 'isolated');
    const table = h('table', 'lab-table'), head = h('tr');
    head.append(h('th', '', 'Same inputs: ' + (run.trial.kind === 'fixed' ? 'fixed trial' : 'seed ' + run.trial.seed)));
    for (const c of columns) { const th = h('th', c.id === run.id ? 'current' : '', MODES[c.mode]); th.append(h('small', '', (c.id === run.id ? 'this run' : 'run ' + short(c.id)) + ' · ' + (c.backend === 'claude' ? 'Claude' : 'fixture'))); head.append(th); }
    table.append(head);
    const rows = [
      ['Agents with a correct final answer', c => `${c.correct_agents}/3`],
      ['Final answers (A · B · C)', c => AGENTS.map(a => c.results.answers[a] == null ? '—' : num(c.results.answers[a])).join(' · ')],
      ['Ground truth °C (hidden from agents)', c => num(c.results.truth_c) + (c.results.truth_c !== c.results.original_truth_c ? ` (was ${num(c.results.original_truth_c)})` : '')],
      ['Delivered messages', c => c.results.delivered + (c.results.withheld ? ` (+${c.results.withheld} withheld)` : '')],
      ['Inference calls', c => c.backend === 'claude' ? `${c.results.model_calls}` : `${c.results.turns} fixture turns`],
      ['Active time', c => `${c.results.active_seconds} s`],
      ['Facts learned from others', c => c.results.facts_learned],
      ['Unverified claims', c => `${c.unverified_claims}/${c.results.claims}`],
      ['Leakage findings', c => c.leakage],
      ['Event audit', c => c.results.audit_ok ? 'consistent' : 'PROBLEMS'],
    ];
    for (const [label, fn] of rows) {
      const tr = h('tr'); tr.append(h('th', '', label));
      for (const c of columns) tr.append(h('td', c.id === run.id ? 'current' : '', fn(c)));
      table.append(tr);
    }
    const wrap = h('div', 'lab-table-wrap'); wrap.append(table);
    const parts = [wrap];
    const prop = ui.view.results?.propagation;
    if (prop) for (const p of prop) {
      const box = h('div', 'lab-prop');
      box.append(h('b', '', `Intervention: ${p.injection.key} ${num(p.original_value)} → ${num(p.injection.value)} ${p.injection.unit} into ${name(p.injection.agent)} only`));
      for (const a of AGENTS) {
        const r = p.reached[a];
        box.append(h('p', '', `${name(a)}: ${r.holds_revised_value ? 'holds the revised value (' + r.how.join(', ') + ')' : 'never received the revised value'} · final answer ${r.final_answer_matches_revised_truth ? 'matches' : 'does not match'} the revised truth${p.still_holding_original_value[a] ? ' · still treats the original value as current' : ''}`));
      }
      parts.push(box);
    }
    const leaks = ui.view.results?.leakage;
    if (leaks?.findings?.length) {
      const box = h('details', 'lab-prop');
      box.append(h('summary', '', `Leakage scan: ${leaks.findings.length} finding(s) · ${leaks.count} unexplained${leaks.detector ? '' : ' (detector v1: inference not separated)'}`));
      for (const f of leaks.findings) box.append(h('p', '', `${name(f.agent)} ${f.turn_id}: ${num(f.value)} (private to ${name(f.owner)}) in ${f.where} — ${f.assessment}`));
      parts.push(box);
    }
    if (!columns.some(c => c.mode === 'isolated')) parts.push(h('p', 'muted', 'No isolated baseline with these inputs yet.'));
    host.replaceChildren(...parts);
  }

  function renderButtons() {
    const run = ui.run, st = run?.status, cfg = ui.config, live = $('lab-brain').value === 'claude';
    const anyActive = ui.runs.some(r => ACTIVE.includes(r.status)) || (run && ACTIVE.includes(st));
    $('lab-approval').hidden = !live;
    if (cfg) $('lab-approval-text').textContent = `I approve a live run: up to ${cfg.limits.max_inferences} Claude CLI calls (${cfg.model}, existing subscription login, no API key), ${cfg.limits.max_deliveries} delivered messages and ${cfg.limits.active_seconds} s of active time. No retries.`;
    $('lab-start').disabled = !cfg || anyActive || (live && !$('lab-approve').checked) || ($('lab-trial').value === 'match' && !run);
    $('lab-pause').disabled = !(st === 'running' || st === 'stepping') || ui.mode === 'replay';
    $('lab-step').disabled = st !== 'paused' || ui.mode === 'replay';
    $('lab-inject-open').disabled = st !== 'paused' || ui.mode === 'replay';
    $('lab-resume').disabled = !(st === 'paused' || st === 'interrupted') || ui.mode === 'replay';
    $('lab-stop').disabled = !(ACTIVE.includes(st) && st !== 'stopping' || st === 'interrupted') || ui.mode === 'replay';
    $('lab-replay').disabled = !run || ACTIVE.includes(st) || !ui.events.length;
    $('lab-replay').textContent = ui.mode === 'replay' ? 'Stop replay' : 'Replay';
    if (st !== 'paused') $('lab-inject').hidden = true;
  }

  // ---------------------------------------------------------------- controls
  async function action(name_) {
    try { await api(`/lab/runs/${ui.runId}/${name_}`, {method: 'POST'}); if (ui.mode !== 'replay') { ui.mode = 'live'; ui.animate = true; } say({pause: 'Pause requested; it takes effect at the next boundary.', resume: 'Resumed.', step: 'Stepping one action.', stop: 'Stop requested.'}[name_]); await poll(); }
    catch (e) { say(e.message); }
  }

  async function start(modeOverride) {
    const cfg = ui.config, live = $('lab-brain').value === 'claude', kind = $('lab-trial').value;
    const body = {mode: modeOverride || $('lab-mode').value, backend: live ? 'claude' : 'fixture'};
    body.trial = kind === 'match' || modeOverride ? {kind: ui.run.trial.kind, ...(ui.run.trial.kind === 'random' ? {seed: ui.run.trial.seed} : {})} : {kind};
    if (live) {
      if (!$('lab-approve').checked) return say('Tick the approval box to start a live run.');
      body.approval = {approve: true, binding: cfg.approval_binding};
    }
    try {
      $('lab-start').disabled = true;
      const run = await api('/lab/runs', {method: 'POST', body: JSON.stringify(body)});
      $('lab-approve').checked = false;
      say(`Run ${short(run.id)} started · ${MODES[run.mode]} · ${live ? 'live Claude agents' : 'fixture agents'}.`);
      await loadRuns(); await select(run.id, {live: true});
    } catch (e) { say(e.message); renderButtons(); }
  }

  function suggest() {
    const iv = ui.run?.trial?.intervention; if (!iv) return;
    $('inject-agent').value = iv.agent; $('inject-key').value = iv.key; $('inject-value').value = iv.value; $('inject-unit').value = iv.unit; $('inject-note').value = iv.note;
  }

  async function inject(ev) {
    ev.preventDefault();
    const raw = $('inject-value').value.trim(), value = raw !== '' && Number.isFinite(Number(raw)) ? Number(raw) : raw;
    const body = {agent: $('inject-agent').value, key: $('inject-key').value.trim(), value, unit: $('inject-unit').value.trim(), note: $('inject-note').value.trim()};
    try {
      const r = await api(`/lab/runs/${ui.runId}/inject`, {method: 'POST', body: JSON.stringify(body)});
      say(`Injected ${r.key} = ${num(r.value)} ${r.unit} into ${name(r.agent)} as ${r.fact.fact_id}${r.replaced ? ', superseding ' + r.replaced.fact_id + ' (kept)' : ''}. Resume to see whether it propagates.`);
      $('lab-inject').hidden = true; await poll();
    } catch (e) { say(e.message); }
  }

  function replay() {
    if (ui.mode === 'replay') { const events = ui.events; reset('recorded'); ui.animate = false; ui.events = events; pump(); say('Replay stopped.'); return; }
    const events = ui.events; reset('replay'); ui.events = events; ui.animate = true; ui.speed = Number($('lab-speed').value);
    say('Replaying the stored event log. No new inference or messages are created.');
    renderAll(); pump();
  }

  async function inspect() {
    if (!ui.runId) return;
    try {
      const body = await api(`/lab/runs/${ui.runId}/memory`), host = $('lab-records-body');
      const readAt = new Date().toLocaleTimeString([], {hour12: false});
      $('lab-records').querySelector('summary').textContent = `Stored homebase records · read at ${readAt} while the run was ${ui.run?.status || 'unknown'}`;
      const parts = [h('p', 'muted', `${body.source} at ${readAt}. Prompts are omitted here. Click “Inspect stored records” again to re-read; this view does not update by itself.`)];
      for (const a of AGENTS) {
        const m = body.agents[a], d = h('details'); d.open = true;
        d.append(h('summary', '', `${name(a)} · ${m.facts.length} facts · ${m.inbox.length} inbox · ${m.outbox.length} outbox (${m.outbox.filter(o => o.status === 'queued').length} queued) · ${m.turns.length} turns`));
        const table = h('table', 'lab-table compact'), head = h('tr');
        for (const t of ['fact', 'key', 'value', 'status', 'origin', 'via', 'rev', 'supersedes', 'superseded by']) head.append(h('th', '', t));
        table.append(head);
        for (const f of m.facts) { const tr = h('tr'); for (const x of [f.fact_id, f.key, num(f.value) + (f.unit ? ' ' + f.unit : ''), f.status, `${f.origin_kind} (${f.origin_agent} ${f.origin_fact})`, f.sender ? `${f.sender} ${f.via_fact}` : '—', f.revision, f.supersedes || '—', f.superseded_by || '—']) tr.append(h('td', '', x)); table.append(tr); }
        const wrap = h('div', 'lab-table-wrap'); wrap.append(table); d.append(wrap);
        const box = h('pre', 'payload');
        box.textContent = JSON.stringify({inbox: m.inbox.map(r => ({message_id: r.message_id, from: r.sender, received_at: r.received_at, consumed_by_turn: r.consumed_turn})),
          outbox: m.outbox.map(r => ({message_id: r.message_id, to: r.recipient, status: r.status, delivered_at: r.delivered_at})), answers: m.answers, snapshots: Object.keys(m.snapshots)}, null, 2);
        d.append(box); parts.push(d);
      }
      host.replaceChildren(...parts); $('lab-records').hidden = false; $('lab-records').open = true;
      $('lab-records').scrollIntoView({behavior: reduced ? 'auto' : 'smooth', block: 'nearest'});
    } catch (e) { say(e.message); }
  }

  function wire() {
    $('lab-run').addEventListener('change', e => select(e.target.value));
    for (const id of ['lab-brain', 'lab-trial', 'lab-mode', 'lab-approve']) $(id).addEventListener('change', renderButtons);
    $('lab-start').addEventListener('click', () => start());
    $('lab-pause').addEventListener('click', () => action('pause'));
    $('lab-step').addEventListener('click', () => action('step'));
    $('lab-resume').addEventListener('click', () => action('resume'));
    $('lab-stop').addEventListener('click', () => action('stop'));
    $('lab-replay').addEventListener('click', replay);
    $('lab-speed').addEventListener('change', e => { ui.speed = Number(e.target.value); });
    $('lab-inject-open').addEventListener('click', () => { const f = $('lab-inject'); f.hidden = !f.hidden; if (!f.hidden && !ui.view.injections.length) suggest(); });
    $('lab-inject').addEventListener('submit', inject);
    $('inject-suggest').addEventListener('click', suggest);
    $('inject-cancel').addEventListener('click', () => { $('lab-inject').hidden = true; });
    $('inject-key').addEventListener('change', e => { const unit = ui.config?.inputs?.[e.target.value]?.unit; if (unit) $('inject-unit').value = unit; });
    $('lab-inspect').addEventListener('click', inspect);
    $('lab-baseline').addEventListener('click', () => {
      if (ui.run.backend === 'claude' && !$('lab-approve').checked) { $('lab-brain').value = 'claude'; renderButtons(); return say('Tick the approval box above, then click the baseline button again (3 live calls).'); }
      $('lab-brain').value = ui.run.backend === 'claude' ? 'claude' : 'fixture'; start('isolated');
    });
  }

  async function tick() {
    const unlocked = !$('workspace').hidden;
    if (!unlocked) { if (ui.ready) { ui.ready = false; ui.config = null; } return; }
    if (!ui.ready) {
      ui.ready = true;
      try { ui.config = await api('/lab/config'); $('lab-task').textContent = ui.config.task; } catch (e) { ui.ready = false; return; }
      buildSvg(); renderAll(); await loadRuns();
    }
    const now = Date.now();
    if (ui.runId && (ui.mode === 'live' || ui.mode === 'loading') && now - ui.lastPoll > 700) { ui.lastPoll = now; await poll(); }
    if (now - (ui.lastList || 0) > (ui.mode === 'live' ? 3000 : 5000)) { ui.lastList = now; await loadRuns(); }
    if (ui.mode === 'live') renderMeters();
  }

  document.addEventListener('DOMContentLoaded', () => { wire(); setInterval(() => { if (!document.hidden) tick(); }, 350); });
})();
