// D2 spike. Plain JS, no build. Temporary: delete frontend/public/spike before the pilot.
(() => {
  'use strict';

  const MIC_FLAT_PEAK = 0.0005; // master plan 7.8, layer 2 starting value
  const CHUNK_MS = 10000;
  const MIME = 'video/webm;codecs=vp8,opus';

  const $ = (id) => document.getElementById(id);
  const logEl = $('log');
  const pending = []; // log lines not yet sent to the server
  const allLines = [];

  function log(msg, data) {
    const stamp = new Date().toISOString().slice(11, 23);
    const text = data === undefined ? msg : `${msg} ${safeJson(data)}`;
    const div = document.createElement('div');
    div.textContent = `${stamp}  ${text}`;
    logEl.prepend(div);
    const row = { t: new Date().toISOString(), msg, data: data === undefined ? null : data };
    pending.push(row);
    allLines.push(`${stamp}  ${text}`);
    console.log(msg, data === undefined ? '' : data);
  }

  function safeJson(value) {
    try { return JSON.stringify(value); } catch { return String(value); }
  }

  // ---------------------------------------------------------------- 1. environment
  function envRow(label, value) {
    const tr = document.createElement('tr');
    const a = document.createElement('td');
    const b = document.createElement('td');
    a.textContent = label;
    b.textContent = value;
    tr.append(a, b);
    $('env').append(tr);
  }

  function readEnvironment() {
    $('env').textContent = '';
    envRow('User agent', navigator.userAgent);
    envRow('"SEB" in user agent', String(/SEB/.test(navigator.userAgent)));
    envRow('Location', location.href);
    envRow('window.SafeExamBrowser present', String(!!window.SafeExamBrowser));
    envRow('mediaDevices available', String(!!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)));
    envRow('MediaRecorder available', String(typeof MediaRecorder !== 'undefined'));
    envRow(`isTypeSupported(${MIME})`, String(typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(MIME)));
    envRow('Secure context', String(window.isSecureContext));
  }

  function readSebApi() {
    const api = window.SafeExamBrowser;
    if (!api) { log('SafeExamBrowser JS API: absent'); return; }
    log('SafeExamBrowser JS API: present', { keys: Object.keys(api), version: api.version });
    const security = api.security;
    if (!security) { log('SafeExamBrowser.security: absent'); return; }
    const dump = () => log('SafeExamBrowser.security', {
      configKey: security.configKey,
      browserExamKey: security.browserExamKey,
    });
    if (typeof security.updateKeys === 'function') {
      security.updateKeys(dump);
    } else {
      dump();
    }
  }

  // ---------------------------------------------------------------- IndexedDB
  function openDb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open('spike', 1);
      req.onupgradeneeded = () => req.result.createObjectStore('chunks');
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  function tx(db, mode, fn) {
    return new Promise((resolve, reject) => {
      const t = db.transaction('chunks', mode);
      const result = fn(t.objectStore('chunks'));
      t.oncomplete = () => resolve(result.result !== undefined ? result.result : undefined);
      t.onerror = () => reject(t.error);
      t.onabort = () => reject(t.error);
    });
  }

  async function storedSummary(db) {
    const rows = await tx(db, 'readonly', (s) => s.getAll());
    return { count: rows.length, bytes: rows.reduce((sum, r) => sum + (r.bytes || 0), 0), rows };
  }

  // ---------------------------------------------------------------- survival markers
  function readCookie(name) {
    const m = document.cookie.split('; ').find((c) => c.startsWith(name + '='));
    return m ? decodeURIComponent(m.split('=')[1]) : null;
  }

  function showMarkers() {
    const rows = [
      ['localStorage spike_marker', safe(() => localStorage.getItem('spike_marker'))],
      ['sessionStorage spike_marker', safe(() => sessionStorage.getItem('spike_marker'))],
      ['cookie spike_marker', safe(() => readCookie('spike_marker'))],
    ];
    const table = $('markers');
    table.textContent = '';
    for (const [label, value] of rows) {
      const tr = document.createElement('tr');
      const a = document.createElement('td');
      const b = document.createElement('td');
      a.textContent = label;
      b.textContent = value === null ? '(none)' : value;
      tr.append(a, b);
      table.append(tr);
    }
    log('markers at page load', Object.fromEntries(rows));
  }

  function safe(fn) {
    try { return fn(); } catch (e) { return 'error: ' + e.message; }
  }

  function writeMarkers() {
    const value = new Date().toISOString();
    safe(() => localStorage.setItem('spike_marker', value));
    safe(() => sessionStorage.setItem('spike_marker', value));
    safe(() => { document.cookie = `spike_marker=${encodeURIComponent(value)}; max-age=86400; path=/`; });
    log('markers written', value);
  }

  // ---------------------------------------------------------------- recording
  let db = null;
  let stream = null;
  let recorder = null;
  let audioCtx = null;
  let analyserTimer = null;
  let nextSeq = 0;
  let runChunks = 0;
  let runBytes = 0;
  let recordStartedAt = 0;
  let flatSince = null;

  async function refreshDbCounts() {
    const s = await storedSummary(db);
    $('dbChunks').textContent = `${s.count} chunks, ${s.bytes} bytes`;
    return s;
  }

  async function startRecording() {
    $('btnStart').disabled = true;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 320, height: 240, frameRate: 15 },
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      });
    } catch (e) {
      log('getUserMedia FAILED', { name: e.name, message: e.message });
      $('btnStart').disabled = false;
      return;
    }
    $('preview').srcObject = stream;
    const [video] = stream.getVideoTracks();
    const [audio] = stream.getAudioTracks();
    log('getUserMedia ok', { video: video && video.label, audio: audio && audio.label });
    if (video) log('video settings', video.getSettings());
    if (audio) {
      const s = audio.getSettings();
      log('audio settings (check 12: constraints honoured?)', {
        echoCancellation: s.echoCancellation,
        noiseSuppression: s.noiseSuppression,
        autoGainControl: s.autoGainControl,
        sampleRate: s.sampleRate,
      });
    }
    for (const track of stream.getTracks()) {
      track.onmute = () => log(`TRACK MUTE (${track.kind})`);
      track.onunmute = () => log(`TRACK UNMUTE (${track.kind})`);
      track.onended = () => log(`TRACK ENDED (${track.kind})`);
    }

    startLevelWatch();

    if (typeof MediaRecorder === 'undefined' || !MediaRecorder.isTypeSupported(MIME)) {
      log('MediaRecorder cannot record ' + MIME);
      return;
    }
    recorder = new MediaRecorder(stream, {
      mimeType: MIME,
      videoBitsPerSecond: 150000,
      audioBitsPerSecond: 24000,
    });
    recorder.onerror = (e) => log('recorder error', { name: e.error && e.error.name });
    recorder.onstop = () => log('recorder stopped');
    recorder.ondataavailable = async (e) => {
      if (!e.data || e.data.size === 0) return;
      const seq = nextSeq++;
      runChunks += 1;
      runBytes += e.data.size;
      try {
        await tx(db, 'readwrite', (s) => s.put({ seq, bytes: e.data.size, at: Date.now(), blob: e.data }, seq));
      } catch (err) {
        log('IndexedDB write FAILED', { seq, message: String(err) });
      }
      updateRunStats();
      refreshDbCounts();
      log('chunk', { seq, bytes: e.data.size });
    };
    recordStartedAt = performance.now();
    recorder.start(CHUNK_MS);
    $('btnStop').disabled = false;
    log('recording started', { mimeType: recorder.mimeType, chunkMs: CHUNK_MS });
  }

  function updateRunStats() {
    $('runChunks').textContent = String(runChunks);
    $('runBytes').textContent = String(runBytes);
    const seconds = (performance.now() - recordStartedAt) / 1000;
    if (seconds > 5 && runBytes > 0) {
      $('mbHour').textContent = ((runBytes / seconds) * 3600 / 1e6).toFixed(1);
    }
  }

  function startLevelWatch() {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx || stream.getAudioTracks().length === 0) { log('no AudioContext or no audio track'); return; }
    audioCtx = new AudioCtx();
    const source = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 2048;
    source.connect(analyser);
    const buf = new Float32Array(analyser.fftSize);
    analyserTimer = setInterval(() => {
      analyser.getFloatTimeDomainData(buf);
      let peak = 0;
      for (let i = 0; i < buf.length; i++) peak = Math.max(peak, Math.abs(buf[i]));
      $('peak').textContent = peak.toFixed(5);
      const flat = peak < MIC_FLAT_PEAK;
      if (flat && flatSince === null) flatSince = performance.now();
      if (!flat && flatSince !== null) {
        log('level back above flat threshold', { flatForS: Math.round((performance.now() - flatSince) / 1000), peak });
        flatSince = null;
      }
      $('flat').textContent = flatSince === null ? '0' : String(Math.round((performance.now() - flatSince) / 1000));
      updateRunStats();
    }, 250);
    log('level watch started', { audioContextState: audioCtx.state });
  }

  function stopRecording() {
    if (recorder && recorder.state !== 'inactive') recorder.stop();
    if (stream) stream.getTracks().forEach((t) => t.stop());
    if (analyserTimer) clearInterval(analyserTimer);
    if (audioCtx) audioCtx.close();
    $('btnStart').disabled = false;
    $('btnStop').disabled = true;
    log('stopped by user');
  }

  async function clearChunks() {
    await tx(db, 'readwrite', (s) => s.clear());
    nextSeq = 0;
    await refreshDbCounts();
    log('stored chunks cleared');
  }

  // ---------------------------------------------------------------- 3. observed events
  function selectionLength() {
    const sel = window.getSelection();
    return sel ? String(sel).length : 0; // length only, never the text
  }

  function wireObservers() {
    for (const type of ['copy', 'cut', 'paste', 'contextmenu']) {
      document.addEventListener(type, (e) => {
        const inText = !!(e.target && e.target.closest && e.target.closest('#testText'));
        log(`EVENT ${type}`, { inTestParagraph: inText, selectionLength: selectionLength() });
      });
    }
    window.addEventListener('blur', () => log('EVENT window blur'));
    window.addEventListener('focus', () => log('EVENT window focus'));
    document.addEventListener('visibilitychange', () => log('EVENT visibilitychange', { state: document.visibilityState }));
    window.addEventListener('online', () => log('EVENT online'));
    window.addEventListener('offline', () => log('EVENT offline'));
    const interesting = new Set(['PrintScreen', 'Meta', 'OS', 'Alt', 'Tab', 'Escape', 'ContextMenu', 'F12', 'F11', 'F5']);
    for (const type of ['keydown', 'keyup']) {
      document.addEventListener(type, (e) => {
        if (interesting.has(e.key) || e.ctrlKey || e.metaKey) {
          log(`EVENT ${type}`, { key: e.key, code: e.code, ctrl: e.ctrlKey, alt: e.altKey, shift: e.shiftKey, meta: e.metaKey });
        }
      });
    }
  }

  // ---------------------------------------------------------------- 4. server echo
  async function ping() {
    const extra = $('testKey').value.trim();
    const url = '/api/spike/echo' + (extra ? '?key=' + encodeURIComponent(extra) : '');
    try {
      const res = await fetch(url, { cache: 'no-store' });
      const body = await res.json();
      $('echo').textContent = JSON.stringify(body, null, 2);
      const sebHeaders = Object.fromEntries(Object.entries(body.all_headers || {}).filter(([k]) => k.startsWith('x-safeexambrowser')));
      log('echo', { status: res.status, sebHeaders, received: body.received, keyResults: body.key_results, urlTheServerRebuilt: body.url_the_server_rebuilt });
    } catch (e) {
      $('echo').textContent = 'fetch failed: ' + e;
      log('echo FAILED', String(e));
    }
  }

  async function sendLog() {
    const lines = pending.splice(0, pending.length);
    if (lines.length === 0) { log('nothing new to send'); return; }
    try {
      const res = await fetch('/api/spike/log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lines }),
      });
      log('log sent', await res.json());
    } catch (e) {
      pending.unshift(...lines);
      log('log send FAILED', String(e));
    }
  }

  // ---------------------------------------------------------------- start
  async function init() {
    $('flatPeak').textContent = String(MIC_FLAT_PEAK);
    $('quitUrl').value = `${location.origin}/spike/quit.html`;
    readEnvironment();
    readSebApi();
    showMarkers();
    wireObservers();

    $('btnApi').addEventListener('click', () => { readEnvironment(); readSebApi(); });
    $('btnStart').addEventListener('click', startRecording);
    $('btnStop').addEventListener('click', stopRecording);
    $('btnClear').addEventListener('click', clearChunks);
    $('btnMarkers').addEventListener('click', writeMarkers);
    $('btnPing').addEventListener('click', ping);
    $('btnSend').addEventListener('click', sendLog);
    $('btnCopyLog').addEventListener('click', () => {
      const text = allLines.slice().reverse().join('\n');
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => log('log copied'), (e) => log('copy FAILED', String(e)));
      } else {
        log('clipboard API not available');
      }
    });
    $('btnQuit').addEventListener('click', () => {
      log('navigating to quit URL', $('quitUrl').value);
      sendLog().finally(() => { window.location.href = $('quitUrl').value; });
    });

    try {
      db = await openDb();
      const s = await refreshDbCounts();
      nextSeq = s.rows.length ? Math.max(...s.rows.map((r) => r.seq)) + 1 : 0;
      $('preexisting').textContent = `${s.count} chunks, ${s.bytes} bytes`;
      log('IndexedDB chunks present at page load (check 4)', { count: s.count, bytes: s.bytes });
    } catch (e) {
      $('preexisting').textContent = 'IndexedDB unavailable: ' + e;
      log('IndexedDB open FAILED', String(e));
    }
  }

  init();
})();
