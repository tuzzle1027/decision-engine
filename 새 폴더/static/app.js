// ── 버전 자동 표시 ──
fetch('/version').then(r => r.json()).then(d => {
  document.getElementById('versionTag').textContent = d.version + ' live';
}).catch(() => {});

// ── 전역 변수 ──
const chatPage   = document.getElementById('chat-page');
const startPage  = document.getElementById('start-page');
const chat       = document.getElementById('chat');
const input      = document.getElementById('input');
const sendBtn    = document.getElementById('sendBtn');
const startInput = document.getElementById('start-input');
let session = null;
const EMOJIS = ['🥇','🥈','🥉','4️⃣','5️⃣'];

// ── 시작 페이지 ──
function showChatPage() {
  startPage.classList.add('hidden');
  chatPage.classList.add('visible');
  setTimeout(() => { startPage.style.display = 'none'; }, 400);
}

function startChat() {
  const text = startInput.value.trim();
  if (!text) return;
  showChatPage();
  setTimeout(() => send(text), 100);
}

function startWithChip(text) {
  showChatPage();
  setTimeout(() => send(text), 100);
}

startInput.addEventListener('input', () => {
  startInput.style.height = 'auto';
  startInput.style.height = Math.min(startInput.scrollHeight, 120) + 'px';
});
startInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); startChat(); }
});

// ── 입력창 자동 높이 ──
input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 120) + 'px';
});
input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});

// ── 유틸 ──
function scroll() { chat.scrollTop = chat.scrollHeight; }

// ── 메시지 렌더링 ──
function addUserMsg(text) {
  const wrap = document.createElement('div');
  wrap.className = 'msg-wrap';
  const mi = document.createElement('div');
  mi.className = 'msg-inner user';
  const av = document.createElement('div');
  av.className = 'av av-user';
  av.textContent = '나';
  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-user';
  bubble.textContent = text;
  mi.appendChild(av);
  mi.appendChild(bubble);
  wrap.appendChild(mi);
  chat.appendChild(wrap);
  scroll();
}

function addTyping() {
  const wrap = document.createElement('div');
  wrap.className = 'msg-wrap'; wrap.id = 'typing';
  const mi = document.createElement('div');
  mi.className = 'msg-inner';
  const av = document.createElement('div');
  av.className = 'av av-ai'; av.textContent = '🛍️';
  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-ai';
  bubble.innerHTML = '<div class="typing"><span></span><span></span><span></span></div>';
  mi.appendChild(av); mi.appendChild(bubble);
  wrap.appendChild(mi);
  chat.appendChild(wrap);
  scroll();
}

// ── 상황판 ──
function isBoard(text) {
  return text.includes('[A ') && text.includes('[D ') && text.includes('[E 직접입력]');
}

function renderBoard(fullText) {
  const boardStart = fullText.indexOf('[A ');
  const empathy = boardStart > 0 ? fullText.substring(0, boardStart).trim() : '';
  const boardText = boardStart > 0 ? fullText.substring(boardStart) : fullText;

  if (empathy) {
    const wrap = document.createElement('div');
    wrap.className = 'msg-wrap';
    const mi = document.createElement('div');
    mi.className = 'msg-inner';
    const av = document.createElement('div');
    av.className = 'av av-ai'; av.textContent = '🛍️';
    const bubble = document.createElement('div');
    bubble.className = 'bubble bubble-ai';
    bubble.textContent = empathy;
    mi.appendChild(av); mi.appendChild(bubble);
    wrap.appendChild(mi);
    chat.appendChild(wrap);
  }

  const lines = boardText.split('\n').filter(l => l.trim());
  const wrap = document.createElement('div');
  wrap.className = 'msg-wrap';
  const mi = document.createElement('div');
  mi.className = 'msg-inner full';
  const av = document.createElement('div');
  av.className = 'av av-ai'; av.textContent = '🛍️';
  const board = document.createElement('div');
  board.className = 'board';
  const title = document.createElement('div');
  title.className = 'board-title';
  title.textContent = '조건을 선택해주세요';
  board.appendChild(title);

  const selections = {};
  let directInput = null;

  lines.forEach(line => {
    const match = line.match(/\[([A-E][^\]]*)\]\s*(.*)/);
    if (!match) return;
    const label = match[1].trim();
    const content = match[2].trim();
    const key = label[0];
    const row = document.createElement('div');
    row.className = 'board-row';
    const lbl = document.createElement('div');
    lbl.className = key === 'E' ? 'board-label label-e' : 'board-label';
    lbl.textContent = `[${label}]`;
    row.appendChild(lbl);

    if (key === 'E') {
      const inp = document.createElement('input');
      inp.className = 'board-direct';
      inp.placeholder = '직접 입력하세요...';
      inp.type = 'text';
      directInput = inp;
      row.appendChild(inp);
      board.appendChild(row);
      const help = document.createElement('div');
      help.className = 'board-help';
      help.textContent = '✍️ 여기에 적어주신 한 마디가 더 정확한 제품을 찾는데 도움이 됩니다';
      board.appendChild(help);
    } else {
      const opts = document.createElement('div');
      opts.className = 'board-options';
      content.split('/').map(o => o.trim()).filter(Boolean).forEach(opt => {
        const btn = document.createElement('div');
        btn.className = 'opt-btn';
        btn.textContent = opt;
        btn.onclick = () => {
          opts.querySelectorAll('.opt-btn').forEach(b => b.classList.remove('selected'));
          btn.classList.add('selected');
          selections[key] = opt;
        };
        opts.appendChild(btn);
      });
      row.appendChild(opts);
      board.appendChild(row);
    }
  });

  const confirmBtn = document.createElement('button');
  confirmBtn.className = 'board-confirm';
  confirmBtn.textContent = '선택 완료 →';
  confirmBtn.onclick = () => {
    const parts = [];
    ['A','B','C','D'].forEach(k => { if (selections[k]) parts.push(`${k}:${selections[k]}`); });
    if (directInput && directInput.value.trim()) parts.push(`E:${directInput.value.trim()}`);
    if (parts.length === 0) { alert('조건을 하나 이상 선택해주세요'); return; }
    send(parts.join(' '));
  };
  board.appendChild(confirmBtn);
  mi.appendChild(av); mi.appendChild(board);
  wrap.appendChild(mi);
  chat.appendChild(wrap);
}

// ── 확인 버튼 ──
function isConfirm(text) { return text.includes('CONFIRM_BUTTONS'); }

function renderConfirm(text) {
  const summaryText = text.replace('CONFIRM_BUTTONS', '').trim();
  const wrap = document.createElement('div');
  wrap.className = 'msg-wrap';
  const mi = document.createElement('div');
  mi.className = 'msg-inner full';
  const av = document.createElement('div');
  av.className = 'av av-ai'; av.textContent = '🛍️';
  const box = document.createElement('div');
  box.className = 'confirm-wrap';
  const txt = document.createElement('div');
  txt.className = 'confirm-text';
  txt.textContent = summaryText;
  box.appendChild(txt);
  const btns = document.createElement('div');
  btns.className = 'confirm-btns';
  const yes = document.createElement('button');
  yes.className = 'confirm-btn btn-yes';
  yes.textContent = '네, 찾아주세요! 🔍';
  yes.onclick = () => send('네');
  const add = document.createElement('button');
  add.className = 'confirm-btn btn-add';
  add.textContent = '추가할게요 ✏️';
  add.onclick = () => send('추가');
  const no = document.createElement('button');
  no.className = 'confirm-btn btn-no';
  no.textContent = '다시 선택할게요';
  no.onclick = () => send('아니요');
  btns.appendChild(yes); btns.appendChild(add); btns.appendChild(no);
  box.appendChild(btns);
  mi.appendChild(av); mi.appendChild(box);
  wrap.appendChild(mi);
  return wrap;
}

// ── 제품 카드 ──
function parseProducts(text) {
  const lines = text.split('\n');
  const products = [];
  let cur = null;
  for (const line of lines) {
    const tm = line.match(/^(\d+)\. (.+)/);
    if (tm) {
      if (cur) products.push(cur);
      cur = { rank:parseInt(tm[1]), title:tm[2].trim(), price:'', store:'', positive:'0', negative:'0', score:'0', link:'#' };
      continue;
    }
    if (!cur) continue;
    const price = line.match(/가격[:\s]+([0-9,원~]+)/);
    if (price) cur.price = price[1];
    const lnk = line.match(/[Ll]ink[:\s]+(.+)/);
    if (lnk) cur.link = lnk[1].trim();
  }
  if (cur) products.push(cur);
  return products;
}

function renderProducts(products) {
  const wrap = document.createElement('div');
  wrap.className = 'msg-wrap';
  const mi = document.createElement('div');
  mi.className = 'msg-inner full';
  const av = document.createElement('div');
  av.className = 'av av-ai'; av.textContent = '🛍️';
  const pw = document.createElement('div');
  pw.className = 'products-wrap';
  const title = document.createElement('div');
  title.className = 'products-title';
  title.textContent = '🏆 리뷰 역추적 Top 3';
  pw.appendChild(title);
  products.slice(0,3).forEach((p, i) => {
    const card = document.createElement('div');
    card.className = 'product-card';
    const imgBox = document.createElement('div');
    imgBox.className = 'product-img';
    imgBox.onclick = () => { if (p.link && p.link !== '#') window.open(p.link,'_blank'); };
    imgBox.textContent = EMOJIS[i] || '📦';
    const info = document.createElement('div');
    info.className = 'product-info';
    info.innerHTML = `
      <div class="product-store">${p.store||'추천'}</div>
      <div class="product-name">${p.title}</div>
      ${p.price ? `<div class="product-price">${p.price}</div>` : ''}
      <div class="badges">
        <span class="badge badge-pos">👍 ${p.positive}</span>
        <span class="badge badge-neg">👎 ${p.negative}</span>
        <span class="badge badge-score">⭐ ${p.score}</span>
      </div>
      <a href="${p.link||'#'}" target="_blank" class="btn-view">자세히 보기 →</a>
    `;
    card.appendChild(imgBox); card.appendChild(info);
    pw.appendChild(card);
  });
  mi.appendChild(av); mi.appendChild(pw);
  wrap.appendChild(mi);
  return wrap;
}

// ── AI 메시지 ──
function addAiMsg(text) {
  if (isConfirm(text)) {
    chat.appendChild(renderConfirm(text));
  } else if (isBoard(text)) {
    renderBoard(text);
  } else {
    const prods = parseProducts(text);
    if (prods.length > 0 && text.match(/^\d+\./m)) {
      chat.appendChild(renderProducts(prods));
    } else {
      const wrap = document.createElement('div');
      wrap.className = 'msg-wrap';
      const mi = document.createElement('div');
      mi.className = 'msg-inner';
      const av = document.createElement('div');
      av.className = 'av av-ai'; av.textContent = '🛍️';
      const bubble = document.createElement('div');
      bubble.className = 'bubble bubble-ai';
      bubble.textContent = text;
      mi.appendChild(av); mi.appendChild(bubble);
      wrap.appendChild(mi);
      chat.appendChild(wrap);
    }
  }
  scroll();
}

// ── 음성 인식 (시작 페이지) ──
function toggleStartVoice() {
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    alert('Chrome 브라우저를 사용해주세요!');
    return;
  }
  const btn = document.getElementById('startMicBtn');
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const rec = new SpeechRecognition();
  rec.lang = 'ko-KR';
  rec.continuous = false;
  rec.interimResults = false;
  rec.onstart = () => {
    btn.style.background = '#c0392b';
    btn.style.borderColor = '#c0392b';
    startInput.placeholder = '🎤 말씀해주세요...';
  };
  rec.onresult = (e) => {
    startInput.value = e.results[0][0].transcript;
  };
  rec.onend = () => {
    btn.style.background = '';
    btn.style.borderColor = '';
    startInput.placeholder = '찾으시는 제품을 입력해주세요...';
    if (startInput.value.trim()) startChat();
  };
  rec.start();
}

// ── 음성 인식 (채팅 페이지) ──
let recognition = null;
let isRecording = false;

function toggleVoice() {
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    alert('이 브라우저는 음성 인식을 지원하지 않아요. Chrome을 사용해주세요!');
    return;
  }
  if (isRecording) {
    recognition.stop();
    return;
  }
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRecognition();
  recognition.lang = 'ko-KR';
  recognition.continuous = false;
  recognition.interimResults = true;

  recognition.onstart = () => {
    isRecording = true;
    document.getElementById('micBtn').classList.add('recording');
    document.getElementById('micModal').classList.add('active');
    document.getElementById('micInterim').textContent = '';
  };
  recognition.onresult = (e) => {
    let interim = '';
    let final = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (e.results[i].isFinal) final += e.results[i][0].transcript;
      else interim += e.results[i][0].transcript;
    }
    document.getElementById('micInterim').textContent = final || interim;
    if (final) input.value = final;
  };
  recognition.onend = () => {
    isRecording = false;
    document.getElementById('micBtn').classList.remove('recording');
    document.getElementById('micModal').classList.remove('active');
    document.getElementById('micInterim').textContent = '';
    if (input.value.trim()) {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 120) + 'px';
      send();
    }
  };
  recognition.onerror = () => {
    isRecording = false;
    document.getElementById('micBtn').classList.remove('recording');
    document.getElementById('micModal').classList.remove('active');
  };
  recognition.start();
}

// ── 전송 ──
async function send(overrideText) {
  const msg = overrideText || input.value.trim();
  if (!msg) return;
  addUserMsg(msg);
  if (!overrideText) { input.value = ''; input.style.height = 'auto'; }
  sendBtn.disabled = true;
  addTyping();
  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, session: session })
    });
    const data = await res.json();
    document.getElementById('typing')?.remove();
    session = data.session;
    addAiMsg(data.response || '');
  } catch(e) {
    document.getElementById('typing')?.remove();
    addAiMsg('연결 오류가 발생했어요. 다시 시도해주세요.');
  }
  sendBtn.disabled = false;
  input.focus();
}
