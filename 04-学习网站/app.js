/* AI FULLSTACK QUEST · 交互主逻辑
   存档：localStorage('ai-quest-save-v1')，可导出/导入 JSON。
   规则：前一关未通关，后一关锁定（一章一检验）。 */
(function () {
  'use strict';

  var DATA = window.QUEST_DATA;
  var CHAPTERS = DATA.chapters;
  var TOTAL_XP = CHAPTERS.reduce(function (s, c) { return s + c.xp; }, 0);
  var SAVE_KEY = 'ai-quest-save-v1';
  var COLS = 4;

  var state = {
    completed: {},      // { ch01: true }
    checks: {},         // { ch01: [true,false,true] }
    cursor: 0,
  };

  // 闸门实测（来自 API /api/gates，非本地勾选）：{ ch01: {status,passed,total,duration_s} }
  var gates = {
    ready: false,
    error: '',
    generatedAt: '',
    passed: 0,
    total: 0,
    chapters: {},
  };

  var els = {
    map: document.getElementById('map'),
    level: document.getElementById('level'),
    xpFill: document.getElementById('xpFill'),
    xpText: document.getElementById('xpText'),
    clearCount: document.getElementById('clearCount'),
    nextName: document.getElementById('nextName'),
    bars: document.getElementById('bars'),
    panelNote: document.getElementById('panelNote'),
    line: document.getElementById('line'),
    overlay: document.getElementById('overlay'),
    ovCode: document.getElementById('ovCode'),
    ovTitle: document.getElementById('ovTitle'),
    ovBody: document.getElementById('ovBody'),
    ovFootNote: document.getElementById('ovFootNote'),
    btnClear: document.getElementById('btnClear'),
    btnClose: document.getElementById('btnClose'),
    btnBack: document.getElementById('btnBack'),
    btnSave: document.getElementById('btnSave'),
    btnLoad: document.getElementById('btnLoad'),
    btnVerify: document.getElementById('btnVerify'),
    tokenInput: document.getElementById('tokenInput'),
    gateSummary: document.getElementById('gateSummary'),
    fileLoad: document.getElementById('fileLoad'),
    tip: document.getElementById('tip'),
  };

  var currentChapter = null;
  var typingTimer = null;

  /* ---------------- 存档 ---------------- */
  function loadSave() {
    try {
      var raw = localStorage.getItem(SAVE_KEY);
      if (!raw) return;
      var s = JSON.parse(raw);
      if (s && typeof s === 'object') {
        state.completed = s.completed || {};
        state.checks = s.checks || {};
        state.cursor = typeof s.cursor === 'number' ? s.cursor : 0;
      }
    } catch (e) { /* 忽略损坏存档 */ }
  }

  function persist() {
    try {
      localStorage.setItem(SAVE_KEY, JSON.stringify({
        completed: state.completed, checks: state.checks, cursor: state.cursor, at: new Date().toISOString(),
      }));
    } catch (e) { /* 隐私模式下降级为内存态 */ }
  }

  /* ---------------- 状态计算 ---------------- */
  function unlocked(index) {
    if (index === 0) return true;
    return !!state.completed[CHAPTERS[index - 1].id];
  }

  function checkCount(ch) {
    var arr = state.checks[ch.id] || [];
    return arr.filter(Boolean).length;
  }

  function clearedCount() {
    return CHAPTERS.filter(function (c) { return state.completed[c.id]; }).length;
  }

  function xpEarned() {
    return CHAPTERS.reduce(function (s, c) { return s + (state.completed[c.id] ? c.xp : 0); }, 0);
  }

  function nextChapter() {
    for (var i = 0; i < CHAPTERS.length; i++) {
      if (!state.completed[CHAPTERS[i].id] && unlocked(i)) return CHAPTERS[i];
    }
    return null;
  }

  /* ---------------- 闸门实测（API） ---------------- */
  function applyGates(d) {
    gates.ready = d.status === 'ready';
    gates.error = d.status === 'missing' ? '闸门报告未生成' : '';
    gates.generatedAt = d.generated_at || '';
    gates.passed = d.passed || 0;
    gates.total = d.total || 0;
    gates.chapters = {};
    (d.chapters || []).forEach(function (c) { gates.chapters[c.id] = c; });
    gates.fetchedAt = new Date().toISOString();   // 时间以浏览器本地为准，容器时钟不可信
    renderAll();
  }

  function fetchGates() {
    if (location.protocol === 'file:') {
      gates.error = 'file:// 离线模式，未连接 API';
      renderAll();
      return;
    }
    fetch('/api/gates', { cache: 'no-store' }).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    }).then(function (d) {
      applyGates(d);
    }).catch(function () {
      gates.error = 'API 未连接（确认 8080 服务在跑，且通过 8081 站点访问）';
      gates.ready = false;
      renderAll();
    });
  }

  function verifyGates() {
    if (location.protocol === 'file:') {
      say('离线模式不能校验：请用 8081 站点或本地 http 服务打开，再点校验。');
      return;
    }
    var token = (els.tokenInput && els.tokenInput.value || '').trim();
    if (!token) { say('先在侧栏填校验令牌（部署默认 dev-token），再点校验。'); return; }
    els.btnVerify.disabled = true;
    els.btnVerify.textContent = '校验中';
    say('正在重跑 8 章闸门，每章都要跑一遍 check.py，约 10 秒…');
    fetch('/api/gates/refresh', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token },
    }).then(function (res) {
      return res.json().then(function (j) { return { ok: res.ok, status: res.status, body: j }; });
    }).then(function (r) {
      if (!r.ok) {
        var msg = r.status === 401 ? '令牌无效（401）：和部署时的 APP_TOKEN 对一下。'
          : r.status === 429 ? '已有一次校验在跑，等它结束再来。'
            : '校验失败：' + ((r.body && r.body.error && r.body.error.message) || ('HTTP ' + r.status));
        say(msg);
        return;
      }
      applyGates(Object.assign({ status: 'ready' }, r.body));
      say('闸门重跑完成：' + r.body.passed + '/' + r.body.total + ' 通过，耗时 ' +
        (r.body.runner_seconds || r.body.duration_s) + ' 秒。');
      if (!els.overlay.hidden && currentChapter !== null) openChapter(currentChapter);
    }).catch(function () {
      say('校验请求失败：确认 API 在 8080 运行、站点经 8081 访问。');
    }).then(function () {
      els.btnVerify.disabled = false;
      els.btnVerify.textContent = '校验';
    });
  }

  function gateLineFor(id) {
    if (gates.error) {
      return '<p class="gate-line mute">' + esc(gates.error) + '</p>';
    }
    if (!gates.ready) return '<p class="gate-line mute">正在读取闸门报告…</p>';
    var g = gates.chapters[id];
    if (!g) return '<p class="gate-line mute">该章暂无报告，点右上「校验」生成。</p>';
    var cls = g.status === 'PASS' ? 'ok' : 'bad';
    return '<p class="gate-line ' + cls + '">' + esc(g.status) + ' ' + g.passed + '/' + g.total +
      ' · ' + (g.duration_s || 0) + 's</p>' +
      '<p class="gate-line mute">服务端 check.py 实跑 · 页面读取于 ' + esc(fmtTime(gates.fetchedAt)) + '</p>';
  }

  function fmtTime(iso) {
    if (!iso) return '未知时间';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString('zh-CN', { hour12: false });
  }

  /* ---------------- 渲染 ---------------- */
  function renderHud() {
    var xp = xpEarned();
    var lv = 1 + clearedCount();
    els.level.textContent = String(lv);
    els.xpFill.style.width = Math.round(xp / TOTAL_XP * 100) + '%';
    els.xpText.textContent = xp + ' / ' + TOTAL_XP + ' XP';
    els.clearCount.textContent = clearedCount() + ' / ' + CHAPTERS.length;
    var nx = nextChapter();
    els.nextName.textContent = nx ? (nx.code + ' ' + nx.short) : '全部通关';
    els.gateSummary.textContent = gates.error ? '离线' : gates.ready ? (gates.passed + '/' + gates.total + ' PASS') : '连接中…';
  }

  function renderBars() {
    els.bars.innerHTML = '';
    CHAPTERS.forEach(function (ch) {
      var pct = state.completed[ch.id] ? 100 : Math.round(checkCount(ch) / ch.checks.length * 100);
      var row = document.createElement('div');
      row.className = 'bar-row';
      var lab = document.createElement('span');
      lab.textContent = ch.code;
      var track = document.createElement('div');
      track.className = 'bar-track';
      var fill = document.createElement('div');
      fill.className = 'bar-fill' + (state.completed[ch.id] ? ' on' : '');
      fill.style.width = pct + '%';
      track.appendChild(fill);
      row.appendChild(lab);
      row.appendChild(track);
      els.bars.appendChild(row);
    });
  }

  function renderMap() {
    els.map.innerHTML = '';
    CHAPTERS.forEach(function (ch, i) {
      var tile = document.createElement('button');
      tile.type = 'button';
      tile.className = 'tile';
      tile.dataset.index = String(i);
      tile.setAttribute('role', 'gridcell');

      var isUnlocked = unlocked(i);
      var isClear = !!state.completed[ch.id];
      var isCurrent = !isClear && isUnlocked;

      tile.classList.add(isClear ? 'tile--clear' : isCurrent ? 'tile--current' : 'tile--locked');
      if (i === state.cursor) tile.classList.add('tile--selected');

      var footText = isClear ? 'CLEAR' : isUnlocked ? (checkCount(ch) + '/' + ch.checks.length + ' 检验') : 'LOCKED';
      var verified = gates.chapters[ch.id] && gates.chapters[ch.id].status === 'PASS';
      tile.innerHTML =
        '<div class="tile-top"><span class="tile-num">' + ch.code + '</span><span class="tile-xp">' + ch.xp + ' XP</span></div>' +
        '<div class="tile-name">' + esc(ch.short) + '</div>' +
        '<div class="tile-foot"><span class="tile-badge">' + footText + '</span></div>' +
        (verified ? '<span class="tile-ver" title="服务端闸门已通过">✓ 闸门</span>' : '');

      tile.addEventListener('click', function () {
        state.cursor = i;
        blip();
        if (!unlocked(i)) {
          say('第 ' + ch.code + ' 关还是锁定状态：先通关第 ' + CHAPTERS[i - 1].code + ' 关（' + CHAPTERS[i - 1].short + '）。');
          renderMap();
          return;
        }
        openChapter(i);
        renderMap();
      });

      els.map.appendChild(tile);
    });
  }

  function renderTip() {
    var ch = CHAPTERS[state.cursor];
    var st = state.completed[ch.id] ? '已通关' : unlocked(state.cursor) ? checkCount(ch) + '/' + ch.checks.length + ' 检验' : '未解锁';
    els.tip.textContent = '游标 ' + ch.code + ' · ' + st;
  }

  function renderPanelNote() {
    var nx = nextChapter();
    if (!nx) {
      els.panelNote.textContent = '八关全清。下一步：把 8 条通关凭证拼成作品集，按 01-JD 报告的映射表回填简历。';
      return;
    }
    var cc = checkCount(nx);
    els.panelNote.textContent = '当前关卡：' + nx.code + ' ' + nx.short + '（' + cc + '/' + nx.checks.length + ' 检验项已勾）。' +
      (cc === 0 ? '先过 L1 概念口试，别急着写代码。' : '继续完成剩余检验，全部勾选才能通关。');
  }

  function renderAll() {
    renderMap();
    renderHud();
    renderBars();
    renderPanelNote();
    renderTip();
  }

  /* ---------------- 关卡弹层 ---------------- */
  function openChapter(index) {
    var ch = CHAPTERS[index];
    currentChapter = index;

    els.ovCode.textContent = ch.code;
    els.ovTitle.textContent = ch.title;

    var checks = state.checks[ch.id] || [];
    var body = [];

    body.push('<div class="sec"><h3>岗位锚点 · JD</h3><p>' + esc(ch.jd) + '</p></div>');
    body.push('<div class="sec"><h3>必掌握（' + ch.points.length + ' 条）</h3><ul>' +
      ch.points.map(function (p) { return '<li>' + esc(p) + '</li>'; }).join('') + '</ul></div>');

    body.push('<div class="sec"><h3>一章一检验</h3>' +
      ch.checks.map(function (c, i) {
        var on = checks[i] ? ' checked' : '';
        return '<label class="check-item"><input type="checkbox" data-check="' + i + '"' + on + ' />' +
          '<span class="layer">' + c.layer + '</span>' +
          '<span class="txt"><b>' + esc(c.name) + '</b><br><span>' + esc(c.detail) + '</span></span></label>';
      }).join('') + '</div>');

    body.push('<div class="sec"><h3>代码闸门</h3><div class="cmd"><span>$ ' + esc(ch.run) + '</span>' +
      '<button class="px-btn small copy" type="button" data-copy="' + esc(ch.run) + '">复制</button></div>' +
      '<p style="margin-top:6px">期望输出：' + esc(ch.gate) + '</p></div>');

    body.push('<div class="sec"><h3>闸门实测 · 服务端</h3>' + gateLineFor(ch.id) + '</div>');

    body.push('<div class="sec"><h3>文件位置</h3><p>文档：' + esc(ch.doc) + '<br>代码：' + esc(ch.codePath) + '</p></div>');
    body.push('<div class="sec"><h3>通关凭证（可直接写进简历）</h3><p style="color:var(--green)">“' + esc(ch.proof) + '”</p></div>');

    els.ovBody.innerHTML = body.join('');
    els.overlay.hidden = false;

    els.ovBody.querySelectorAll('input[data-check]').forEach(function (box) {
      box.addEventListener('change', function () {
        var i = Number(box.dataset.check);
        var arr = state.checks[ch.id] || [];
        while (arr.length < ch.checks.length) arr.push(false);
        arr[i] = box.checked;
        state.checks[ch.id] = arr;
        persist();
        updateClearButton();
        renderBars();
        renderPanelNote();
        blip();
      });
    });

    els.ovBody.querySelectorAll('[data-copy]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        copyText(btn.dataset.copy);
        btn.textContent = '已复制';
        setTimeout(function () { btn.textContent = '复制'; }, 1200);
      });
    });

    updateClearButton();
  }

  function updateClearButton() {
    if (currentChapter === null) return;
    var ch = CHAPTERS[currentChapter];
    var done = checkCount(ch) >= ch.checks.length;
    var already = !!state.completed[ch.id];
    els.btnClear.disabled = !done || already;
    els.btnClear.textContent = already ? '已通关' : '完成本关';
    els.ovFootNote.textContent = already ? '本关已通关，可随时回看检验卡。' : done ? '三项检验已勾选，可以通关了。' : '需勾选全部检验项才能通关。';
  }

  function closeOverlay() {
    els.overlay.hidden = true;
    currentChapter = null;
    renderAll();
  }

  function clearChapter() {
    if (currentChapter === null) return;
    var ch = CHAPTERS[currentChapter];
    if (checkCount(ch) < ch.checks.length) return;
    state.completed[ch.id] = true;
    persist();
    blip(880);
    renderAll();
    updateClearButton();
    var next = CHAPTERS[currentChapter + 1];
    say(next ? '关卡 ' + ch.code + ' 通关，+' + ch.xp + ' XP。下一关解锁：' + next.code + ' ' + next.title + '。' : '全部八关通关，+' + ch.xp + ' XP。该打包作品集了。');
  }

  /* ---------------- 键盘 ---------------- */
  function moveCursor(delta) {
    var next = state.cursor + delta;
    if (next < 0 || next >= CHAPTERS.length) return;
    state.cursor = next;
    persist();
    blip();
    renderMap();
    renderPanelNote();
    renderTip();
  }

  document.addEventListener('keydown', function (e) {
    if (!els.overlay.hidden) {
      if (e.key === 'Escape') { e.preventDefault(); closeOverlay(); }
      return;
    }
    var move = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: COLS, ArrowUp: -COLS };
    if (move[e.key] !== undefined) {
      e.preventDefault();
      moveCursor(move[e.key]);
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      var i = state.cursor;
      if (!unlocked(i)) { say('前一关未通关，先完成第 ' + CHAPTERS[i - 1].code + ' 关。'); return; }
      openChapter(i);
    }
  });

  /* ---------------- 打字机对话框 ---------------- */
  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function say(text) {
    if (typingTimer) { clearInterval(typingTimer); typingTimer = null; }
    var i = 0;
    els.line.textContent = '';
    var speed = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 1 : 1000 / 28;
    typingTimer = setInterval(function () {
      i += 1;
      els.line.textContent = text.slice(0, i);
      if (i >= text.length) { clearInterval(typingTimer); typingTimer = null; }
    }, speed);
  }

  /* ---------------- 音效（像素风 beep） ---------------- */
  var audioCtx = null;
  function blip(freq) {
    try {
      if (!audioCtx) {
        var AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) return;
        audioCtx = new AC();
      }
      var o = audioCtx.createOscillator();
      var g = audioCtx.createGain();
      o.type = 'square';
      o.frequency.value = freq || 440;
      g.gain.value = 0.04;
      o.connect(g);
      g.connect(audioCtx.destination);
      o.start();
      o.stop(audioCtx.currentTime + 0.06);
    } catch (e) { /* 静默失败 */ }
  }

  /* ---------------- 存档按钮 ---------------- */
  function exportSave() {
    var payload = JSON.stringify({ app: 'ai-fullstack-quest', version: 1, savedAt: new Date().toISOString(), completed: state.completed, checks: state.checks }, null, 2);
    var blob = new Blob([payload], { type: 'application/json' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'ai-quest-save.json';
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
    say('存档已导出：ai-quest-save.json（可交给面试官，或换电脑继续）。');
  }

  function importSave(file) {
    var reader = new FileReader();
    reader.onload = function () {
      try {
        var s = JSON.parse(String(reader.result));
        state.completed = s.completed || {};
        state.checks = s.checks || {};
        persist();
        renderAll();
        say('读档成功：已恢复 ' + clearedCount() + ' 个通关关卡。');
      } catch (e) {
        say('读档失败：文件不是有效的存档 JSON。');
      }
    };
    reader.readAsText(file, 'utf-8');
  }

  function copyText(t) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(t).catch(function () {});
      return;
    }
    var ta = document.createElement('textarea');
    ta.value = t;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(ta);
  }

  /* ---------------- 启动 ---------------- */
  els.btnClear.addEventListener('click', clearChapter);
  els.btnClose.addEventListener('click', closeOverlay);
  els.btnVerify.addEventListener('click', verifyGates);
  els.btnBack.addEventListener('click', closeOverlay);
  els.btnSave.addEventListener('click', exportSave);
  els.btnLoad.addEventListener('click', function () { els.fileLoad.click(); });
  els.fileLoad.addEventListener('change', function () {
    if (els.fileLoad.files && els.fileLoad.files[0]) importSave(els.fileLoad.files[0]);
    els.fileLoad.value = '';
  });
  els.overlay.addEventListener('click', function (e) { if (e.target === els.overlay) closeOverlay(); });

  loadSave();
  state.cursor = Math.min(Math.max(state.cursor || 0, 0), CHAPTERS.length - 1);
  try {
    var savedToken = localStorage.getItem('ai-quest-token');
    if (savedToken) els.tokenInput.value = savedToken;
  } catch (e) { /* 隐私模式 */ }
  els.tokenInput.addEventListener('change', function () {
    try { localStorage.setItem('ai-quest-token', els.tokenInput.value.trim()); } catch (e) {}
  });
  renderAll();
  fetchGates();
  say('欢迎回到第 1 世界。8 关对应 JD 的 9 个能力簇；一关不过，下一关不解锁。按 ENTER 进入当前关卡。');
})();
