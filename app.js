/* 백수톡 디코봇 — 상태판 (127.0.0.1:8771 전용) */
(() => {
  'use strict';

  const HUB_PORT = 8771;
  const HUB_BASE = location.port === String(HUB_PORT) ? '' : `http://127.0.0.1:${HUB_PORT}`;
  const $  = (sel, root = document) => root.querySelector(sel);

  let status = null;
  let busy = false;
  let currentLogBot = '';

  function toast(msg, ms = 2600) {
    const el = $('#toast');
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.hidden = true; }, ms);
  }

  function withTimeout(promise, ms) {
    return new Promise((resolve, reject) => {
      const t = setTimeout(() => reject(new Error('timeout')), ms);
      promise.then(v => { clearTimeout(t); resolve(v); },
                   e => { clearTimeout(t); reject(e); });
    });
  }

  async function getJSON(url, ms = 2500) {
    const res = await withTimeout(fetch(url, { cache: 'no-store' }), ms);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return res.json();
  }

  async function postJSON(url, body = {}, ms = 8000) {
    const res = await withTimeout(fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }), ms);
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, data };
  }

  const STATE_PILL = {
    online: 'on', starting: 'warn', offline: 'off', token: 'warn', error: 'warn',
  };

  /* 로컬 런처가 꺼져 있을 때(공개 페이지 등) 보여 줄 카드 기본 정보 */
  const STATIC_BOTS = [
    {
      id: 'log-bot', name: '료그봇', meta: '백수톡 로그 · 사진 원본 보존',
      desc: '백수톡의 사진·파일·삭제·수정·입퇴장·음성까지 내 개인 서버 #백수톡-로그에 원본 그대로 남겨요.',
    },
    {
      id: 'music-bot', name: '뮤직봇', meta: '유튜브 음악 · /r /s /q /x',
      desc: '음성 채널에서 유튜브 곡을 틀어 줘요. /r 재생 · /s 스킵 · /q 대기열 · /x 나가기.',
    },
  ];

  function renderCard(bot, offline = false) {
    const grid = $('#cards');
    grid.querySelectorAll('.skeleton').forEach(el => el.remove());
    let card = grid.querySelector(`[data-bot="${bot.id}"]`);
    if (!card) {
      card = document.createElement('article');
      card.className = 'card';
      card.dataset.bot = bot.id;
      card.innerHTML = `
        <div class="ch">
          <span class="num"></span>
          <div class="ct"><b></b><span class="meta"></span></div>
          <span class="pill off" data-pill><i></i><span data-label>확인 중</span></span>
        </div>
        <p class="cd"></p>
        <p class="cdetail" data-detail></p>
        <div class="ca">
          <button class="btn sm primary" type="button" data-start>켜기</button>
          <button class="btn sm ghost" type="button" data-stop hidden>끄기</button>
          <button class="btn sm ghost" type="button" data-token>토큰 넣기</button>
          <button class="link-btn" type="button" data-log>로그</button>
        </div>`;
      grid.appendChild(card);
      bindCard(card);
    }
    card.classList.toggle('offline', offline);

    card.classList.toggle('on', bot.state === 'online');
    $('.num', card).textContent = bot.id === 'log-bot' ? '1' : '2';
    $('.ct b', card).textContent = bot.name;
    $('.ct .meta', card).textContent = bot.meta || bot.folder;
    $('.cd', card).innerHTML = bot.desc || '';
    $('[data-detail]', card).textContent = bot.detail || '';

    const pill = $('[data-pill]', card);
    pill.className = 'pill ' + (STATE_PILL[bot.state] || 'off');
    $('[data-label]', card).textContent = bot.label;
    if (bot.error) pill.title = bot.error; else pill.removeAttribute('title');

    $('[data-start]', card).hidden = offline || bot.running || !bot.tokenSet;
    $('[data-stop]', card).hidden = offline || !bot.running;
    const tokBtn = $('[data-token]', card);
    tokBtn.textContent = bot.tokenSet ? '토큰 바꾸기' : '토큰 넣기';
    tokBtn.classList.toggle('primary', !bot.tokenSet && !offline);
    tokBtn.classList.toggle('ghost', bot.tokenSet || offline);
    tokBtn.disabled = offline;
    $('[data-log]', card).disabled = offline;
  }

  function renderOffline() {
    STATIC_BOTS.forEach(b => renderCard(Object.assign({}, b, {
      folder: '', state: 'offline', label: '런처 꺼짐',
      detail: '내 PC에서 실행하기.bat 을 켜면 여기에 상태가 표시돼요',
      tokenSet: false, running: false, error: '',
    }), true));
  }

  function bindCard(card) {
    const botId = () => card.dataset.bot;

    $('[data-start]', card).addEventListener('click', async ev => {
      const btn = ev.currentTarget;
      btn.disabled = true;
      btn.textContent = '켜는 중…';
      const { ok, data } = await postJSON(`${HUB_BASE}/api/start`, { bot: botId() });
      toast(ok ? '켰어요. 몇 초 뒤 온라인으로 바뀝니다.' : (data.result && data.result.error) || data.error || '켜지 못했어요.');
      btn.disabled = false;
      btn.textContent = '켜기';
      setTimeout(() => refresh(true), 1200);
    });

    $('[data-stop]', card).addEventListener('click', async () => {
      const { ok } = await postJSON(`${HUB_BASE}/api/stop`, { bot: botId() });
      toast(ok ? '껐어요.' : '끄지 못했어요.');
      setTimeout(() => refresh(true), 900);
    });

    $('[data-token]', card).addEventListener('click', () => openTokenModal(botId()));

    $('[data-log]', card).addEventListener('click', () => loadLog(botId()));
  }

  function renderSummary(bots) {
    const online = bots.filter(b => b.online).length;
    const sum = $('#sum');
    sum.className = 'sum ' + (online === bots.length && bots.length ? 'on' : online > 0 ? 'wait' : 'off');
    $('#sum b').textContent = online === 0
      ? (bots.every(b => b.state === 'token') ? '토큰 미설정' : '봇 꺼짐')
      : `${online}/${bots.length} 온라인`;
  }

  function paintVersion(info) {
    if (!info || !info.version) return;
    $('#footVer').textContent = 'v' + info.version;
    const meta = document.querySelector('meta[name="app-version"]');
    if (meta) meta.content = info.version;
  }

  async function refresh(manual = false) {
    if (busy) return;
    busy = true;
    if (manual) $('#refresh').classList.add('spin');
    try {
      status = await getJSON(`${HUB_BASE}/api/status`, 2600);
      const bots = status.bots || [];
      bots.forEach(renderCard);
      renderSummary(bots);
      paintVersion({ version: status.version });
      if (currentLogBot) loadLog(currentLogBot, true);
    } catch (err) {
      const sum = $('#sum');
      sum.className = 'sum off';
      $('#sum b').textContent = '런처 꺼짐';
      renderOffline();
    } finally {
      busy = false;
      if (manual) setTimeout(() => $('#refresh').classList.remove('spin'), 400);
    }
  }

  async function loadLog(botId, silent = false) {
    currentLogBot = botId;
    const bot = (status && (status.bots || []).find(b => b.id === botId)) || { name: botId };
    $('#logName').textContent = bot.name;
    $('#logName').className = 'pill ' + (STATE_PILL[bot.state] || 'off');
    try {
      const data = await getJSON(`${HUB_BASE}/api/log?bot=${encodeURIComponent(botId)}`, 3000);
      $('#logBox').textContent = (data.log || '').trim() || '(아직 기록이 없어요)';
      $('#logBox').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } catch (err) {
      if (!silent) $('#logBox').textContent = '로그를 읽지 못했어요.';
    }
  }

  /* 토큰 모달 */
  let tokenBot = '';
  function openTokenModal(botId) {
    const bot = (status && (status.bots || []).find(b => b.id === botId)) || {};
    tokenBot = botId;
    $('#tokenTitle').textContent = `${bot.name || '봇'} 토큰 넣기`;
    $('#tokenWhere').textContent = '저장 위치: ' + (bot.envPath || '—');
    $('#tokenPortal').href = bot.tokenUrl || 'https://discord.com/developers/applications';
    $('#tokenText').value = '';
    $('#tokenMsg').textContent = bot.tokenSet ? `지금 저장된 토큰: ${bot.tokenHint}` : '';
    $('#tokenMsg').className = 'msg';
    const dlg = $('#tokenModal');
    if (typeof dlg.showModal === 'function') dlg.showModal();
    else dlg.setAttribute('open', '');
    setTimeout(() => $('#tokenText').focus(), 60);
  }

  function closeTokenModal() {
    const dlg = $('#tokenModal');
    if (typeof dlg.close === 'function') dlg.close();
    else dlg.removeAttribute('open');
  }

  $('#tokenClose').addEventListener('click', closeTokenModal);
  $('#tokenModal').addEventListener('click', ev => {
    if (ev.target === $('#tokenModal')) closeTokenModal();
  });

  $('#tokenForm').addEventListener('submit', async ev => {
    ev.preventDefault();
    const text = $('#tokenText').value.trim();
    const msg = $('#tokenMsg');
    if (!text) { msg.className = 'msg err'; msg.textContent = '내용을 붙여넣어 주세요.'; return; }
    const btn = $('#tokenSave');
    btn.disabled = true;
    btn.textContent = '저장 중…';
    const { ok, data } = await postJSON(`${HUB_BASE}/api/env`, { bot: tokenBot, text });
    btn.disabled = false;
    btn.textContent = '저장하고 켜기';
    if (ok) {
      msg.className = 'msg ok';
      msg.textContent = data.started || data.restarted ? '저장했어요. 봇을 켜는 중입니다.' : '저장했어요.';
      toast('토큰을 저장했어요. 몇 초 뒤 온라인으로 바뀝니다.', 3200);
      setTimeout(() => { closeTokenModal(); refresh(true); }, 900);
    } else {
      msg.className = 'msg err';
      msg.textContent = data.error || '저장하지 못했어요.';
    }
  });

  $('#refresh').addEventListener('click', () => refresh(true));

  $('#updateCheck').addEventListener('click', async ev => {
    ev.preventDefault();
    toast('새 버전을 확인하는 중…', 1400);
    const { data } = await postJSON(`${HUB_BASE}/api/update/check`, {}, 9000);
    if (data && data.updateAvailable) toast(`새 버전 v${data.latest} 이 있어요. 다음 실행 때 자동으로 업데이트됩니다.`, 4200);
    else if (data && data.error) toast('확인하지 못했어요: ' + data.error);
    else toast('이미 최신 버전이에요.' + (data && data.checkedAt ? ` (${data.checkedAt})` : ''));
  });

  setInterval(() => { if (!document.hidden) refresh(false); }, 4000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(false); });

  refresh(true);
})();
