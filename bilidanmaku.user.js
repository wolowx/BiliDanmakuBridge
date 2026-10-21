// ==UserScript==
// @name         B站弹幕同传助手（LiveTranslate 译文自动发送）
// @namespace    https://github.com/wolowx/BiliDanmakuBridge
// @version      1.2.0
// @description  监听本地服务，把 LiveTranslate 的译文自动填进直播间弹幕框并发送
// @author       wolowx
// @match        https://live.bilibili.com/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @connect      localhost
// @run-at       document-idle
// @noframes
// ==/UserScript==

/*
 * 用法一（油猴）：装好 Tampermonkey 后新建脚本，把本文件全部内容粘进去保存。
 * 用法二（控制台）：打开直播间页面，F12 → 控制台，粘贴本文件全部内容，回车。
 *                  注意：页面刷新后需要重新粘贴。
 *
 * 需要先启动本地服务（双击 run.bat）。
 * 热键：F9 暂停/继续
 */

(function () {
  'use strict';

  if (window.top !== window) return;                       // 只在主框架运行
  if (window.__biliDanmakuBridge) {                        // 防止重复注入
    console.warn('[弹幕同传] 已经在运行了，忽略本次注入');
    return;
  }
  window.__biliDanmakuBridge = true;

  // ────────── 配置 ──────────
  const SERVER = 'http://127.0.0.1:8770';
  const POLL_MS = 800;          // 轮询间隔
  const DRY_CLEAR_MS = 1200;    // 试发模式：填入后多久清空
  const VERIFY_MS = [400, 900, 1500];  // 发送后的检查时点

  // 直播间弹幕输入框（用户提供，可能随页面改版失效，仅作首选）
  const XPATH = '/html/body/div[1]/main/div[2]/section/div[2]/div[10]/div/div[3]/div[2]/textarea';

  // ────────── 状态 ──────────
  const state = {
    paused: false,
    dryRun: false,        // 试发模式：只填入不发送
    sent: 0,
    failed: 0,
    waiting: 0,
    lastSent: '',
    lastResult: '',
    connected: false,
    log: [],
    busy: false,
  };

  function logLine(msg, isErr) {
    const t = new Date().toTimeString().slice(0, 8);
    state.log.unshift(`[${t}] ${msg}`);
    if (state.log.length > 6) state.log.pop();
    (isErr ? console.warn : console.log)(`[弹幕同传] ${msg}`);
    render();
  }

  // ────────── 与本地服务通信 ──────────
  function api(path, body) {
    const url = SERVER + path;
    if (typeof GM_xmlhttpRequest === 'function') {
      return new Promise((resolve) => {
        GM_xmlhttpRequest({
          method: body ? 'POST' : 'GET',
          url: url,
          headers: body ? { 'Content-Type': 'application/json' } : undefined,
          data: body ? JSON.stringify(body) : undefined,
          timeout: 5000,
          onload: (r) => {
            try { resolve(JSON.parse(r.responseText)); } catch (e) { resolve(null); }
          },
          onerror: () => resolve(null),
          ontimeout: () => resolve(null),
        });
      });
    }
    // 控制台模式：用 fetch（http://127.0.0.1 属于可信来源，一般不会被混合内容拦截）
    const opts = body
      ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
      : {};
    return fetch(url, opts).then((r) => r.json()).catch(() => null);
  }

  // ────────── 找输入框 ──────────
  function visible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 30 || r.height < 8) return false;
    const st = getComputedStyle(el);
    return st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
  }

  function findInput() {
    // 1) 首选：用户给的 XPath
    try {
      const r = document.evaluate(XPATH, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
      if (r.singleNodeValue && visible(r.singleNodeValue)) return r.singleNodeValue;
    } catch (e) { /* XPath 失效就走兜底 */ }

    const boxes = Array.from(document.querySelectorAll(
      'textarea, input[type="text"], [contenteditable="true"]'
    )).filter(visible);

    // 2) 其次：提示文字里带"弹幕"的
    for (const el of boxes) {
      const hint = el.getAttribute('placeholder') || el.getAttribute('data-placeholder')
        || el.getAttribute('aria-label') || '';
      if (hint.indexOf('弹幕') >= 0) return el;
    }

    // 3) 最后：可见 textarea 里最靠下的那个（弹幕框通常在页面底部）
    const tas = boxes.filter((el) => el.tagName === 'TEXTAREA');
    if (tas.length) {
      tas.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
      return tas[0];
    }
    return null;
  }

  function getText(el) {
    return (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') ? el.value : el.textContent;
  }

  function setText(el, text) {
    el.focus();
    if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
      const proto = el.tagName === 'TEXTAREA'
        ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(el, text);     // 绕过框架的 value 劫持，让 Vue/React 能收到
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
      const sel = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(el);
      sel.removeAllRanges();
      sel.addRange(range);
      document.execCommand('insertText', false, text);
      el.dispatchEvent(new InputEvent('input', {
        bubbles: true, data: text, inputType: 'insertText'
      }));
    }
  }

  function pressEnter(el) {
    const o = {
      key: 'Enter', code: 'Enter', keyCode: 13, which: 13,
      bubbles: true, cancelable: true, composed: true,
    };
    el.dispatchEvent(new KeyboardEvent('keydown', o));
    el.dispatchEvent(new KeyboardEvent('keypress', o));
    el.dispatchEvent(new KeyboardEvent('keyup', o));
  }

  function findSendButton(el) {
    const btns = Array.from(document.querySelectorAll('button, [role="button"]'));
    for (const b of btns) {
      const t = (b.textContent || '').replace(/\s/g, '');
      if ((t === '发送' || t === '发射') && visible(b)) return b;
    }
    return null;
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ────────── 发送一条 ──────────
  async function sendOne(text) {
    const el = findInput();
    if (!el) {
      logLine('找不到弹幕输入框，请确认已打开直播间页面', true);
      return false;
    }

    if (state.dryRun) {
      setText(el, text);
      logLine(`试发（未回车）：${text}`);
      await sleep(DRY_CLEAR_MS);
      setText(el, '');
      return true;
    }

    setText(el, text);
    pressEnter(el);

    let elapsed = 0;
    for (const target of VERIFY_MS) {
      await sleep(Math.max(0, target - elapsed));
      elapsed = target;
      if (!getText(el)) return true;      // 框空了 = 发出去了
    }

    // 回车没生效，退回点击"发送"按钮
    const btn = findSendButton(el);
    if (btn) {
      logLine('回车无效，改用发送按钮');
      btn.click();
      await sleep(900);
      if (!getText(el)) return true;
    }
    return false;
  }

  // ────────── 主循环 ──────────
  async function tick() {
    if (state.paused || state.busy) return;
    state.busy = true;
    try {
      const data = await api('/pending');
      if (!data || !data.ok) {
        if (state.connected) logLine('本地服务断开了（run.bat 还在跑吗？）', true);
        state.connected = false;
        render();
        return;
      }
      if (!state.connected) {
        state.connected = true;
        logLine('已连接本地服务');
      }
      const items = data.items || [];
      state.waiting = items.length;
      render();

      for (const item of items) {
        const ok = await sendOne(item.text);
        if (ok) {
          await api('/ack', { ids: [item.id] });
          state.sent += 1;
          state.lastSent = item.text;
          state.lastResult = 'ok';
          logLine(`已发送：${item.text}`);
        } else {
          state.failed += 1;
          state.lastResult = 'fail';
          logLine(`发送失败，已自动暂停：${item.text}`, true);
          setPaused(true);
          break;
        }
        if (state.paused) break;
      }
    } finally {
      state.busy = false;
      render();
    }
  }

  // ────────── 面板 ──────────
  let panel, body, titleEl;

  function render() {
    if (!body) return;
    const dot = state.paused ? '#f66' : (state.connected ? '#3c6' : '#fa3');
    const txt = state.paused ? '已暂停' : (state.connected ? '运行中' : '未连接');
    titleEl.innerHTML = `<span style="color:${dot}">●</span> 弹幕同传 `
      + `<span style="opacity:.7">${txt}</span>`
      + (state.dryRun ? ' <span style="color:#fb3">[试发]</span>' : '');
    body.innerHTML = `
      <div>待发 ${state.waiting} ｜ 已发 <b>${state.sent}</b> ｜ 失败 ${state.failed}</div>
      <div style="margin-top:2px;opacity:.85;word-break:break-all">最近：${state.lastSent || '—'}</div>
      <div style="margin-top:6px;display:flex;gap:6px">
        <button id="bdb-toggle" data-act="toggle">${state.paused ? '继续' : '暂停'}</button>
        <button id="bdb-dry" data-act="dry">${state.dryRun ? '试发：开' : '试发：关'}</button>
        <button id="bdb-min" data-act="min">收起</button>
      </div>
      <div style="margin-top:6px;opacity:.65;font-size:11px;line-height:1.5">
        ${state.log.map((l) => l.replace(/</g, '&lt;')).join('<br>') || '等待译文…'}
      </div>`;
  }

  function setPaused(v) {
    if (state.paused === v) return;
    state.paused = v;
    if (v) {
      state.waiting = 0;
      // 告诉服务端：暂停期间别排队，只记住最新一条
      api('/pause', {}).then((r) => {
        if (!r || !r.ok) logLine('暂停状态没同步到本地服务', true);
      });
    } else {
      // 服务端会把暂停期间最新的一条放回队列，立刻取一次
      api('/resume', {}).then((r) => {
        if (!r || !r.ok) logLine('恢复状态没同步到本地服务', true);
        tick();
      });
    }
    render();
  }

  function syncPausedState() {
    // 页面刷新后，如果本地服务还停在暂停状态，面板要跟着显示
    api('/status').then((d) => {
      if (d && d.ok && d.paused && !state.paused) {
        state.paused = true;
        state.waiting = 0;
        render();
        logLine('本地服务处于暂停状态（F9 继续）');
      }
    });
  }

  function buildPanel() {
    panel = document.createElement('div');
    panel.style.cssText = [
      'position:fixed', 'right:14px', 'top:96px', 'z-index:2147483647',
      'background:rgba(28,28,38,.92)', 'color:#ddd', 'border:1px solid #555',
      'border-radius:8px', 'padding:8px 10px', 'font:12px/1.6 "Microsoft YaHei",sans-serif',
      'box-shadow:0 4px 14px rgba(0,0,0,.4)', 'max-width:250px', 'cursor:move',
      'user-select:none',
    ].join(';');

    titleEl = document.createElement('div');
    titleEl.style.cssText = 'font-weight:bold;margin-bottom:4px';
    body = document.createElement('div');

    const style = document.createElement('style');
    style.textContent = `#bdb-panel button {
      background:#3a3a4e;color:#ddd;border:1px solid #666;border-radius:4px;
      padding:2px 8px;font-size:12px;cursor:pointer;font-family:inherit;
    }
    #bdb-panel button:hover { background:#4a4a5e; }`;
    document.head.appendChild(style);
    panel.id = 'bdb-panel';

    panel.appendChild(titleEl);
    panel.appendChild(body);
    document.body.appendChild(panel);

    panel.addEventListener('click', (e) => {
      const act = e.target && e.target.getAttribute && e.target.getAttribute('data-act');
      if (act === 'toggle') setPaused(!state.paused);
      else if (act === 'dry') { state.dryRun = !state.dryRun; render(); }
      else if (act === 'min') {
        const collapsed = body.style.display === 'none';
        body.style.display = collapsed ? '' : 'none';
        e.target.textContent = collapsed ? '收起' : '展开';
      }
    });

    // 拖动
    let drag = null;
    panel.addEventListener('mousedown', (e) => {
      if (e.target.tagName === 'BUTTON') return;
      drag = { x: e.clientX, y: e.clientY,
               r: panel.getBoundingClientRect() };
      e.preventDefault();
    });
    window.addEventListener('mousemove', (e) => {
      if (!drag) return;
      panel.style.left = (drag.r.left + e.clientX - drag.x) + 'px';
      panel.style.top = (drag.r.top + e.clientY - drag.y) + 'px';
      panel.style.right = 'auto';
    });
    window.addEventListener('mouseup', () => { drag = null; });

    render();
  }

  // ────────── 热键 ──────────
  window.addEventListener('keydown', (e) => {
    if (e.key === 'F9' && !e.ctrlKey && !e.altKey) {
      e.preventDefault();
      setPaused(!state.paused);
      logLine(state.paused ? '已暂停（F9 继续）' : '已继续');
    }
  }, true);

  // ────────── 启动 ──────────
  function boot() {
    buildPanel();
    logLine('脚本已加载，等待本地服务…');
    syncPausedState();
    setInterval(tick, POLL_MS);
    tick();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
