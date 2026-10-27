// The listen bar: renders of the drawing on a short loop, in the background, and A/B.
//
// B is the drawing as it is, A the render before the last edit, Dry the input; all three
// loudness-matched (CLAUDE.md: loudness lies) and switched at the same position of the
// loop. The first edit renders the unedited drawing too (often from the cache). The time
// from an edit to hearing it is measured and shown (B4a's done-when; B8).

import { esc } from './eng.js';

const $ = s => document.querySelector(s);

export class Listen {
  constructor({ api, store, onState }) {
    this.api = api; this.store = store; this.onState = onState;
    this.ctx = null; this.buffers = {}; this.sel = 'b'; this.node = null; this.playing = false;
    this.offset = 0; this.startedAt = 0; this.data = null;
    this.reset();
    this.wave = $('#wave');
    for (const b of document.querySelectorAll('.transport [data-k]')) b.addEventListener('click', () => this.choose(b.dataset.k));
    $('#play').addEventListener('click', () => this.toggle());
    for (const id of ['#lsource', '#lstart', '#llen']) $(id).addEventListener('change', () => { this.saveSettings(); this.rerender(); });
    this.wave.addEventListener('pointerdown', e => {
      const r = this.wave.getBoundingClientRect(), d = this.duration();
      if (!d) return;
      this.offset = Math.max(0, Math.min(d - 0.01, d * (e.clientX - r.left) / r.width));
      if (this.playing) this.start();
    });
    window.addEventListener('resize', () => this.draw());
    const tick = () => { this.draw(); requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  }

  async init() {
    const r = await this.api('/api/editor/sources');
    this.engine = r.engine; this.rtf = r.realtime_factor;
    const sel = $('#lsource');
    sel.innerHTML = r.sources.map(s => `<option value="${esc(s)}">${esc(s.replace(':', ': '))}</option>`).join('');
    const saved = this.store.get('listen', {});
    sel.value = r.sources.includes(saved.source) ? saved.source : r.sources[0];
    if (saved.start !== undefined) $('#lstart').value = saved.start;
    if (saved.len !== undefined) $('#llen').value = saved.len;
    this.status(`Edit a value to hear it. <kbd>R</kbd> renders now (${esc(this.engine)}).`);
  }

  saveSettings() { this.store.set('listen', { source: $('#lsource').value, start: +$('#lstart').value, len: +$('#llen').value }); }

  /** A new circuit: forget its renders. */
  reset(base = null) {
    this.base = base; // the unedited drawing (JSON text)
    this.a = null; this.b = null; this.lastHeard = null; // {id, drawing, label, t0}
    this.pending = []; // submitted, not yet heard
    this.seq = 0;
    this.stopNode(); this.playing = false; this.offset = 0; this.buffers = {}; this.data = null;
    this.updateButtons();
    this.onState?.(this);
  }

  excerpt() { return { source: $('#lsource').value, start_s: +$('#lstart').value || 0, seconds: +$('#llen').value || 4 }; }

  /** The drawing changed by an edit labelled `label` at time t0 (performance.now()). */
  edited(drawing, label, t0) {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.render(drawing, label, t0), 450);
  }

  async render(drawing, label, t0 = performance.now()) {
    const snapshot = JSON.parse(JSON.stringify(drawing));
    if (!this.b && this.base && JSON.stringify(snapshot) !== this.base && !this.pending.some(p => p.role === 'base'))
      this.submit(JSON.parse(this.base), 'as drawn', t0, 'base');
    this.submit(snapshot, label, t0, 'edit');
  }

  /** The same drawings again on a new excerpt. */
  rerender() {
    const t0 = performance.now(), a = this.a, b = this.b;
    this.a = this.b = null; this.buffers = {}; this.data = null; this.updateButtons();
    if (a) this.submit(a.drawing, a.label, t0, 'base');
    if (b) this.submit(b.drawing, b.label, t0, 'edit');
  }

  async submit(drawing, label, t0, role) {
    const seq = ++this.seq, ex = this.excerpt();
    const p = { seq, role, drawing, label, t0, id: null, progress: 0, status: 'queued' };
    this.pending.push(p);
    this.status(`rendering <b>${esc(label)}</b>…`, 0);
    try {
      const job = await this.api('/api/editor/render', { drawing, origin: this.origin, ...ex });
      p.id = job.id; p.status = job.status;
      p.submitted = performance.now();
    } catch (e) {
      this.pending = this.pending.filter(q => q !== p);
      this.status(`<span style="color:var(--fault)">can't render: ${esc(String(e.message).replace(/^\d+ /, ''))}</span>`);
      return;
    }
    this.poll();
  }

  async poll() {
    clearTimeout(this.pollTimer);
    const live = this.pending.filter(p => p.id !== null);
    if (!live.length) return;
    const jobs = await this.api(`/api/jobs?ids=${live.map(p => p.id).join(',')}`);
    for (const j of jobs) {
      const p = live.find(q => q.id === j.id); if (!p) continue;
      p.status = j.status; p.progress = j.progress; p.job = j;
    }
    const newest = this.pending.filter(p => p.role === 'edit').at(-1) || this.pending.at(-1);
    if (newest?.status === 'running' || newest?.status === 'queued')
      this.status(`rendering <b>${esc(newest.label)}</b> ${Math.round((newest.progress || 0) * 100)}%`, newest.progress || 0);
    for (const p of [...this.pending]) {
      if (p.status === 'failed') {
        this.pending = this.pending.filter(q => q !== p);
        this.status(`<span style="color:var(--fault)">render failed: ${esc(p.job?.error || '')}</span>`);
      } else if (p.status === 'done') {
        this.pending = this.pending.filter(q => q !== p);
        this.finished(p);
      }
    }
    if (this.pending.some(p => p.id !== null)) this.pollTimer = setTimeout(() => this.poll(), 400);
  }

  finished(p) {
    const r = { id: p.id, drawing: p.drawing, label: p.label, t0: p.t0, seq: p.seq, job: p.job };
    if (p.role === 'base') {
      if (!this.a || this.a.seq < p.seq) this.a = r;
    } else {
      if (this.b && this.b.seq > p.seq) return; // superseded by a newer edit already heard
      if (this.b) this.a = this.b;
      this.b = r;
    }
    if (this.b) this.compare(r);
  }

  async compare(latest) {
    const ids = [this.a?.id, this.b?.id].filter(Boolean);
    const r = await this.api(`/api/editor/compare?ids=${ids.join(',')}`);
    this.ctx = this.ctx || new AudioContext();
    const keys = ['dry', ...(this.a ? ['a'] : []), 'b'];
    const buffers = {};
    await Promise.all(r.audio.map(async (url, i) => {
      const ab = await (await fetch(url)).arrayBuffer();
      buffers[keys[i]] = await this.ctx.decodeAudioData(ab);
    }));
    const wasPlaying = this.playing;
    if (this.playing) { this.offset = this.pos(); this.stopNode(); this.playing = false; }
    this.buffers = buffers; this.data = r; this.envelopes = Object.fromEntries(keys.map((k, i) => [k, r.envelopes[i]]));
    if (!this.buffers[this.sel]) this.sel = 'b';
    this.updateButtons();
    if (wasPlaying) this.start();
    // Tweak to hear: from the edit to B's audio being ready to play.
    if (latest === this.b) {
      const j = latest.job;
      this.lastHeard = { seconds: (performance.now() - latest.t0) / 1000, render_s: j?.wall_s,
                         realtime_factor: j?.realtime_factor, cached: !!j?.cached, label: latest.label };
      window.__tweakToHear = [...(window.__tweakToHear || []), this.lastHeard];
    }
    const h = this.lastHeard, g = r.match.gains_db;
    if (h) this.status(`<b>B</b> ${esc(h.label)}: heard ${h.seconds.toFixed(1)} s after the edit` +
                       `${h.cached ? ' (from the cache)' : h.render_s ? ` (render ${h.render_s.toFixed(1)} s)` : ''}` +
                       `<br>matched to ${r.match.target_lufs} LUFS${this.a ? `: A ${fmtDb(g[1])}, B ${fmtDb(g.at(-1))}` : ''}`);
    this.onState?.(this);
  }

  status(html, progress = null) {
    $('#lstatus').innerHTML = `${html}<div class="bar"><div id="lbar"></div></div>`;
    if (progress !== null) $('#lbar').style.width = `${Math.round(progress * 100)}%`;
  }

  updateButtons() {
    for (const b of document.querySelectorAll('.transport [data-k]')) {
      b.disabled = !this.buffers[b.dataset.k];
      b.classList.toggle('on', b.dataset.k === this.sel && !!this.buffers[b.dataset.k]);
    }
    $('#play').disabled = !Object.keys(this.buffers).length;
  }

  // --- Playback (WebAudio, looped; switching keeps the position) ---

  duration() { const b = this.buffers.b || this.buffers.dry; return b ? b.duration : 0; }
  pos() {
    const d = this.duration(); if (!d) return 0;
    return this.playing ? (this.offset + this.ctx.currentTime - this.startedAt) % d : this.offset;
  }
  stopNode() { if (this.node) { try { this.node.stop(); } catch { /* not started */ } this.node.disconnect(); this.node = null; } }
  start() {
    const b = this.buffers[this.sel]; if (!b) return;
    this.stopNode();
    this.node = this.ctx.createBufferSource(); this.node.buffer = b; this.node.loop = true;
    this.node.connect(this.ctx.destination);
    this.node.start(0, Math.min(this.offset, b.duration - 0.001));
    this.startedAt = this.ctx.currentTime; this.playing = true;
    $('#play').firstChild.textContent = '❚❚ Pause ';
  }
  choose(k) {
    if (!this.buffers[k]) return;
    if (this.playing) { this.offset = this.pos(); this.sel = k; this.start(); } else this.sel = k;
    this.updateButtons();
  }
  toggle() {
    if (!this.ctx || !Object.keys(this.buffers).length) return;
    if (this.ctx.state === 'suspended') this.ctx.resume();
    if (this.playing) { this.offset = this.pos(); this.stopNode(); this.playing = false; $('#play').firstChild.textContent = '▶ Play '; }
    else this.start();
  }

  draw() {
    const cv = this.wave, dpr = devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    const css = getComputedStyle(document.documentElement), col = n => css.getPropertyValue(n).trim();
    g.fillStyle = col('--chrome2'); g.fillRect(0, 0, W, H);
    if (!this.envelopes) { g.fillStyle = col('--faint'); g.font = '11px system-ui'; g.fillText('no render yet', 8, H / 2 + 4); return; }
    let peak = 1e-9;
    for (const e of Object.values(this.envelopes)) for (const [lo, hi] of e) peak = Math.max(peak, -lo, hi);
    const order = ['dry', 'a', 'b'].filter(k => this.envelopes[k] && k !== this.sel).concat([this.sel]);
    for (const k of order) {
      const e = this.envelopes[k]; if (!e) continue;
      const on = k === this.sel;
      g.fillStyle = on ? col('--accent') : (k === 'dry' ? col('--faint') : col('--muted'));
      g.globalAlpha = on ? 0.95 : 0.35;
      const n = e.length;
      for (let i = 0; i < n; i++) {
        const x = i / n * W, y0 = H / 2 - e[i][1] / peak * (H / 2 - 2), y1 = H / 2 - e[i][0] / peak * (H / 2 - 2);
        g.fillRect(x, y0, Math.max(1, W / n), Math.max(1, y1 - y0));
      }
    }
    g.globalAlpha = 1;
    const d = this.duration();
    if (d) { const x = this.pos() / d * W; g.fillStyle = col('--ink'); g.fillRect(x, 0, 1.5, H); }
  }
}

const fmtDb = x => `${x >= 0 ? '+' : ''}${x.toFixed(1)} dB`;
