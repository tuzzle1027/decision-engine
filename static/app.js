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
  // 정상 보드 OR LLM 폴백 보드 둘 다 감지
  const hasE = text.includes('[E 직접입력]');
  const hasBoard = text.includes('조건을 선택해주세요');
  const hasLlmBoard = hasE && /\[[^\]]+\]/.test(text); // [라벨] 형식 있으면
  return (hasBoard && hasE) || hasLlmBoard;
}

function renderBoard(fullText) {
  // '조건을 선택해주세요' 있으면 그 앞은 공감멘트
  // 없으면(LLM 폴백) 첫 [라벨] 앞이 공감멘트
  let boardStart = fullText.indexOf('조건을 선택해주세요');
  if (boardStart < 0) {
    const firstLabel = fullText.search(/\[[^\]]+\]/);
    boardStart = firstLabel;
  }
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
  title.textContent = '▶ 조건을 선택해주세요';
  board.appendChild(title);

  const selections = {};
  let directInput = null;

  // 라벨과 옵션이 각각 다른 줄인 구조 파싱
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const labelMatch = line.match(/^\[([^\]]+)\]\s*(.*)$/);
    if (!labelMatch || !labelMatch[1].trim()) { i++; continue; }

    const label = labelMatch[1].trim();
    const isE = label === 'E 직접입력' || label === 'E';

    // 옵션은 같은 줄 또는 다음 줄
    let optionLine = labelMatch[2].trim();
    if (!optionLine && i + 1 < lines.length && !lines[i+1].match(/^\[/)) {
      i++;
      optionLine = lines[i].trim();
    }

    const row = document.createElement('div');
    row.className = 'board-row';
    const lbl = document.createElement('div');
    lbl.className = isE ? 'board-label label-e' : 'board-label';
    lbl.textContent = `[${label}]`;
    row.appendChild(lbl);

    if (isE) {
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
      // CHECKED:값 파싱 (가성비/자연어 자동 선택)
      const checkedMatch = optionLine.match(/CHECKED:([^/\n]+)/);
      const preChecked = checkedMatch ? checkedMatch[1].trim() : null;
      const cleanContent = optionLine.replace(/\s*CHECKED:[^\n/]*/g, '').trim();
      cleanContent.split('/').map(o => o.trim().replace(/\s+/g, ' ')).filter(o => o && o !== '[' && o.length > 0).forEach(opt => {
        const btn = document.createElement('div');
        btn.className = 'opt-btn';
        btn.textContent = opt;
        if (preChecked && opt === preChecked) {
          btn.classList.add('selected');
          selections[label] = opt;
        }
        btn.onclick = () => {
          opts.querySelectorAll('.opt-btn').forEach(b => b.classList.remove('selected'));
          btn.classList.add('selected');
          selections[label] = opt;
        };
        opts.appendChild(btn);
      });
      row.appendChild(opts);
      board.appendChild(row);
    }
    i++;
  }

  const confirmBtn = document.createElement('button');
  confirmBtn.className = 'board-confirm';
  confirmBtn.textContent = '선택 완료 →';
  confirmBtn.onclick = () => {
    const parts = [];
    Object.entries(selections).forEach(([k, v]) => { if (v) parts.push(`${k}:${v}`); });
    if (directInput && directInput.value.trim()) parts.push(`직접입력:${directInput.value.trim()}`);
    if (parts.length === 0) { alert('조건을 하나 이상 선택해주세요'); return; }
    send(parts.join(' '));
  };
  board.appendChild(confirmBtn);
  mi.appendChild(av); mi.appendChild(board);
  wrap.appendChild(mi);
  chat.appendChild(wrap);
}

// ── 확인 버튼 ──
function isConfirm(text) { return text.includes('CONFIRM_BUTTONS') && !text.includes('ANTI_CONFIRM_BUTTONS'); }

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
  add.onclick = () => {
    // 입력창이 이미 있으면 중복 생성 방지
    if (box.querySelector('.add-input-row')) return;
    const addRow = document.createElement('div');
    addRow.className = 'add-input-row';
    addRow.style.cssText = 'display:flex; gap:8px; margin-top:12px;';
    const addInput = document.createElement('input');
    addInput.type = 'text';
    addInput.placeholder = '추가 조건을 입력하세요...';
    addInput.style.cssText = 'flex:1; padding:8px 12px; border:1px solid #ccc; border-radius:20px; font-size:14px;';
    const addBtn = document.createElement('button');
    addBtn.textContent = '추가';
    addBtn.className = 'confirm-btn btn-yes';
    addBtn.onclick = () => {
      const val = addInput.value.trim();
      if (!val) return;
      send('추가 ' + val);
    };
    addInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') addBtn.click();
    });
    addRow.appendChild(addInput);
    addRow.appendChild(addBtn);
    // btns 다음에 삽입 (버튼들 아래에 입력창 위치)
    btns.insertAdjacentElement('afterend', addRow);
    addInput.focus();
  };
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
function renderAntiConfirm(text) {
  // ANTI_CONFIRM_BUTTONS 앞은 AI 답변, 뒤는 상황판
  const parts = text.split('ANTI_CONFIRM_BUTTONS');
  let aiRaw = parts[0].trim();
  const boardText = parts[1] ? parts[1].trim() : '';

  // IMAGE_RESULTS 포함된 경우 제거 (이미 renderImageResults에서 처리)
  if (aiRaw.startsWith('IMAGE_RESULTS:') || aiRaw.startsWith('IMAGE_SEARCH:')) {
    aiRaw = '';
  }

  // ITEM_SELECT 파싱
  let itemSelectData = null;
  let aiText = aiRaw;
  if (aiRaw.includes('ITEM_SELECT:')) {
    const itemParts = aiRaw.split('\n\nITEM_SELECT:');
    aiText = itemParts[0].trim();
    if (itemParts[1]) {
      const [groupName, itemsStr] = itemParts[1].split(':');
      itemSelectData = { groupName, items: itemsStr ? itemsStr.split(',') : [] };
    }
  }

  // AI 답변 버블
  if (aiText) {
    const wrap = document.createElement('div');
    wrap.className = 'msg-wrap';
    const mi = document.createElement('div');
    mi.className = 'msg-inner';
    const av = document.createElement('div');
    av.className = 'av av-ai'; av.textContent = '🛍️';
    const bubble = document.createElement('div');
    bubble.className = 'bubble bubble-ai';

    // 📌SOURCE:: 파싱
    if (aiText.includes('📌SOURCE::')) {
      const sp = aiText.split('\n\n📌SOURCE::');
      const mainText = sp[0].trim();
      const sourceStr = sp[1] || '';
      bubble.textContent = mainText;
      const sourceDiv = document.createElement('div');
      sourceDiv.style.cssText = 'margin-top:6px; font-size:11px; opacity:0.65;';
      sourceDiv.textContent = '📌 출처: ';
      sourceStr.split('|').forEach(src => {
        const [name, url] = src.split('::');
        if (!name || !url) return;
        const a = document.createElement('a');
        a.href = url; a.target = '_blank'; a.textContent = name;
        a.style.cssText = 'color:inherit; text-decoration:underline; margin-right:8px;';
        sourceDiv.appendChild(a);
      });
      bubble.appendChild(sourceDiv);
    } else {
      bubble.textContent = aiText;
    }

    // ITEM_SELECT 버튼 (상황판에 추가 제안)
    if (itemSelectData && itemSelectData.items.length >= 2) {
      const itemDiv = document.createElement('div');
      itemDiv.style.cssText = 'margin-top:10px; font-size:12px;';
      const label = document.createElement('div');
      label.style.cssText = 'opacity:0.7; margin-bottom:6px;';
      label.textContent = '상황판에 추가할까요?';
      itemDiv.appendChild(label);
      const itemBtns = document.createElement('div');
      itemBtns.style.cssText = 'display:flex; flex-wrap:wrap; gap:6px;';
      itemSelectData.items.forEach(item => {
        const btn = document.createElement('button');
        btn.style.cssText = 'padding:4px 10px; border-radius:20px; border:1px solid #ccc; background:white; font-size:12px; cursor:pointer;';
        btn.textContent = `+ ${item}`;
        btn.onclick = () => {
          // ADD_ITEM:그룹명:선택값:전체옵션 (채팅창에 안보이게 silent)
          sendSilent(`ADD_ITEM:${itemSelectData.groupName}:${item}:${itemSelectData.items.join(',')}`);
          btn.style.background = '#e8f4e8';
          btn.textContent = `✓ ${item}`;
        };
        itemBtns.appendChild(btn);
      });
      itemDiv.appendChild(itemBtns);
      bubble.appendChild(itemDiv);
    }

    mi.appendChild(av); mi.appendChild(bubble);
    wrap.appendChild(mi);
    chat.appendChild(wrap);
  }

  // 3가지 버튼
  const wrap2 = document.createElement('div');
  wrap2.className = 'msg-wrap';
  const mi2 = document.createElement('div');
  mi2.className = 'msg-inner full';
  const av2 = document.createElement('div');
  av2.className = 'av av-ai'; av2.textContent = '🛍️';
  const box = document.createElement('div');
  box.className = 'confirm-wrap';
  const btns = document.createElement('div');
  btns.className = 'confirm-btns';

  const yes = document.createElement('button');
  yes.className = 'confirm-btn btn-yes';
  yes.textContent = '네, 찾아주세요! 🔍';
  yes.onclick = () => send('네, 찾아주세요');

  const more = document.createElement('button');
  more.className = 'confirm-btn btn-add';
  more.textContent = '더 물어볼게요 💬';
  more.onclick = () => send('더 물어볼게요');

  const no = document.createElement('button');
  no.className = 'confirm-btn btn-no';
  no.textContent = '안 살래요';
  no.onclick = () => send('안 살래요');

  btns.appendChild(yes); btns.appendChild(more); btns.appendChild(no);
  box.appendChild(btns);
  mi2.appendChild(av2); mi2.appendChild(box);
  wrap2.appendChild(mi2);
  chat.appendChild(wrap2);
}

function renderMultiSelect(text) {
  // MULTI_SELECT:소파/책상 렌더링
  const lines = text.split('\n');
  let empathy = '';
  let options = [];
  lines.forEach(line => {
    if (line.startsWith('MULTI_SELECT:')) {
      options = line.replace('MULTI_SELECT:', '').split('/').map(o => o.trim()).filter(Boolean);
    } else if (line.trim()) {
      empathy = line.trim();
    }
  });

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
  title.textContent = '▶ 먼저 찾을 제품을 선택해주세요';
  board.appendChild(title);

  const opts = document.createElement('div');
  opts.className = 'board-options';
  opts.style.cssText = 'flex-wrap:wrap; gap:8px;';
  options.forEach(opt => {
    const btn = document.createElement('div');
    btn.className = 'opt-btn';
    btn.textContent = opt;
    btn.onclick = () => send(opt);
    opts.appendChild(btn);
  });
  board.appendChild(opts);
  mi.appendChild(av); mi.appendChild(board);
  wrap.appendChild(mi);
  chat.appendChild(wrap);
}

function renderContextSelect(text) {
  // CONTEXT_SELECT:옵션1/옵션2 렌더링
  const lines = text.split('\n');
  let empathy = '';
  let options = [];
  lines.forEach(line => {
    if (line.startsWith('CONTEXT_SELECT:')) {
      options = line.replace('CONTEXT_SELECT:', '').split('/').map(o => o.trim()).filter(Boolean);
    } else if (line.trim()) {
      empathy = line.trim();
    }
  });

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
  title.textContent = '▶ 선택해주세요';
  board.appendChild(title);

  const opts = document.createElement('div');
  opts.className = 'board-options';
  opts.style.cssText = 'flex-wrap:wrap; gap:8px;';
  options.forEach(opt => {
    const btn = document.createElement('div');
    btn.className = 'opt-btn';
    btn.textContent = opt;
    btn.onclick = () => sendSilent(opt);
    opts.appendChild(btn);
  });
  board.appendChild(opts);
  mi.appendChild(av); mi.appendChild(board);
  wrap.appendChild(mi);
  chat.appendChild(wrap);
}

// ── VS 질문 렌더링 ──
function renderVsQuestion(text) {
  const lines = text.split('\n').filter(l => l.trim());
  const header = lines[0]; // VS_QUESTION:q_id
  const qId = header.replace('VS_QUESTION:', '').trim();

  // 질문과 옵션 파싱
  let questionLines = [];
  const options = [];

  lines.slice(1).forEach(line => {
    // 이모지로 시작하는 줄은 옵션
    if (/^[\u{1F000}-\u{1FFFF}✅💚💛🧡❤️🚫👨👫🧑🐶🐱🍕🎮😴]/u.test(line.trim())) {
      options.push(line.trim());
    } else if (line.trim()) {
      questionLines.push(line.trim());
    }
  });

  const wrap = document.createElement('div');
  wrap.className = 'msg-wrap';
  const mi = document.createElement('div');
  mi.className = 'msg-inner';
  const av = document.createElement('div');
  av.className = 'av av-ai'; av.textContent = '🛍️';
  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-ai';

  // 질문 텍스트
  const qDiv = document.createElement('div');
  qDiv.style.cssText = 'margin-bottom:12px; line-height:1.6; white-space:pre-line;';
  qDiv.textContent = questionLines.join('\n');
  bubble.appendChild(qDiv);

  // 옵션 버튼들
  const btnWrap = document.createElement('div');
  btnWrap.style.cssText = 'display:flex; flex-direction:column; gap:8px;';

  options.forEach((opt, idx) => {
    const btn = document.createElement('button');
    btn.style.cssText = `
      background: var(--bg-card, #f5f5f5);
      border: 1.5px solid var(--border, #ddd);
      border-radius: 10px;
      padding: 10px 14px;
      text-align: left;
      cursor: pointer;
      font-size: 14px;
      transition: all 0.2s;
      width: 100%;
    `;
    btn.textContent = opt;
    btn.onmouseover = () => btn.style.background = '#e8f0fe';
    btn.onmouseout = () => btn.style.background = 'var(--bg-card, #f5f5f5)';
    btn.onclick = () => {
      btnWrap.querySelectorAll('button').forEach(b => {
        b.style.opacity = '0.5';
        b.disabled = true;
      });
      btn.style.opacity = '1';
      btn.style.borderColor = '#4285f4';
      btn.style.background = '#e8f0fe';
      sendSilent(`VS_CHOICE:${qId}:${idx}`);
    };
    btnWrap.appendChild(btn);
  });

  bubble.appendChild(btnWrap);
  mi.appendChild(av); mi.appendChild(bubble);
  wrap.appendChild(mi);
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
}

// ── VS 결과 렌더링 ──
function renderVsResult(text) {
  const jsonStr = text.replace('VS_RESULT:', '').trim();
  let result;
  try { result = JSON.parse(jsonStr); } catch(e) {
    console.error('VS_RESULT 파싱 오류:', e);
    return;
  }

  const wrap = document.createElement('div');
  wrap.className = 'msg-wrap';
  const mi = document.createElement('div');
  mi.className = 'msg-inner';
  const av = document.createElement('div');
  av.className = 'av av-ai'; av.textContent = '🛍️';
  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-ai';

  // 추천 제목
  const winner = result.winner === 'fabric' ? '🛋️ 패브릭 소파 추천!' : '🛋️ 가죽 소파 추천!';
  const titleDiv = document.createElement('div');
  titleDiv.style.cssText = 'font-size:16px; font-weight:700; margin-bottom:10px;';
  titleDiv.textContent = winner;
  bubble.appendChild(titleDiv);

  // 이유 목록
  if (result.reasons && result.reasons.length > 0) {
    const reasonDiv = document.createElement('div');
    reasonDiv.style.cssText = 'font-size:13px; line-height:1.8; margin-bottom:14px; opacity:0.85; white-space:pre-line;';
    reasonDiv.textContent = result.reasons.join('\n');
    bubble.appendChild(reasonDiv);
  }

  // 두 버튼
  const btnRow = document.createElement('div');
  btnRow.style.cssText = 'display:flex; gap:10px; margin-top:8px;';

  const btn1 = document.createElement('button');
  btn1.style.cssText = `
    flex:1; padding:12px;
    background:#4285f4; color:white;
    border:none; border-radius:12px;
    font-size:14px; font-weight:600; cursor:pointer;
  `;
  btn1.textContent = result.winner === 'fabric' ? '✅ 패브릭 소파 찾기' : '✅ 가죽 소파 찾기';
  btn1.onclick = () => {
    const checked = result.winner === 'fabric' ? result.fabric_checked : result.leather_checked;
    sendSilent(`VS_SELECT:${JSON.stringify(checked)}`);
  };

  const btn2 = document.createElement('button');
  btn2.style.cssText = `
    flex:1; padding:12px;
    background:#f5f5f5; border:1.5px solid #ddd;
    border-radius:12px; font-size:14px; cursor:pointer;
  `;
  btn2.textContent = result.winner === 'fabric' ? '💛 가죽 소파도 볼게요' : '💛 패브릭 소파도 볼게요';
  btn2.onclick = () => {
    const checked = result.winner === 'fabric' ? result.leather_checked : result.fabric_checked;
    sendSilent(`VS_SELECT:${JSON.stringify(checked)}`);
  };

  btnRow.appendChild(btn1);
  btnRow.appendChild(btn2);
  bubble.appendChild(btnRow);

  mi.appendChild(av); mi.appendChild(bubble);
  wrap.appendChild(mi);
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
}

// ── 인스타그램 이미지 결과 렌더링 ──
function renderImageResults(text) {
  // JSON 부분만 추출 (ANTI_CONFIRM_BUTTONS 이전까지)
  const jsonStr = text.replace('IMAGE_RESULTS:', '').split('\n')[0].trim();
  let images = [];
  try { images = JSON.parse(jsonStr); } catch(e) {
    console.error('IMAGE_RESULTS 파싱 오류:', e);
    return;
  }

  if (!images.length) return;

  const wrap = document.createElement('div');
  wrap.className = 'msg-wrap';
  const mi = document.createElement('div');
  mi.className = 'msg-inner';
  const av = document.createElement('div');
  av.className = 'av av-ai'; av.textContent = '🛍️';
  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-ai';
  bubble.style.cssText = 'padding:10px; max-width:340px;';

  const title = document.createElement('div');
  title.style.cssText = 'font-size:13px; color:#888; margin-bottom:10px;';
  title.textContent = '📸 이미지 검색 결과';
  bubble.appendChild(title);

  const grid = document.createElement('div');
  grid.style.cssText = 'display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px;';

  images.forEach(img => {
    const imgWrap = document.createElement('div');
    imgWrap.style.cssText = 'border-radius:8px; overflow:hidden; aspect-ratio:1; cursor:pointer;';

    const imgEl = document.createElement('img');
    imgEl.src = img.url;
    imgEl.style.cssText = 'width:100%; height:100%; object-fit:cover;';
    imgEl.onerror = () => { imgWrap.style.display = 'none'; };

    // 클릭하면 적당한 크기 팝업
    imgWrap.onclick = () => {
      const overlay = document.createElement('div');
      overlay.style.cssText = `
        position:fixed; top:0; left:0; right:0; bottom:0;
        background:rgba(0,0,0,0.7); z-index:9999;
        display:flex; align-items:center; justify-content:center;
        padding:40px;
      `;

      const popup = document.createElement('div');
      popup.style.cssText = `
        position:relative;
        max-width:380px; width:100%;
        border-radius:16px; overflow:hidden;
        background:white;
      `;

      // X 닫기 버튼
      const closeBtn = document.createElement('button');
      closeBtn.textContent = '✕';
      closeBtn.style.cssText = `
        position:absolute; top:8px; right:8px;
        background:rgba(0,0,0,0.5); color:white;
        border:none; border-radius:50%;
        width:28px; height:28px;
        font-size:14px; cursor:pointer;
        display:flex; align-items:center; justify-content:center;
        z-index:1;
      `;
      closeBtn.onclick = (e) => { e.stopPropagation(); overlay.remove(); };

      const bigImg = document.createElement('img');
      bigImg.src = img.url;
      bigImg.style.cssText = 'width:100%; display:block;';

      // 캡션
      if (img.caption) {
        const cap = document.createElement('div');
        cap.style.cssText = 'padding:8px 12px; font-size:12px; color:#555;';
        cap.textContent = img.caption;
        popup.appendChild(bigImg);
        popup.appendChild(cap);
      } else {
        popup.appendChild(bigImg);
      }

      popup.appendChild(closeBtn);
      overlay.appendChild(popup);
      overlay.onclick = () => overlay.remove();
      popup.onclick = (e) => e.stopPropagation();
      document.body.appendChild(overlay);
    };

    imgWrap.appendChild(imgEl);
    grid.appendChild(imgWrap);
  });

  bubble.appendChild(grid);
  mi.appendChild(av); mi.appendChild(bubble);
  wrap.appendChild(mi);
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
}

function addAiMsg(text) {
  if (text.startsWith('BOARD_UPDATE')) {
    return;
  } else if (text.startsWith('IMAGE_RESULTS:')) {
    renderImageResults(text);
    // 이미지 후 버튼 없음
  } else if (text.startsWith('IMAGE_SEARCH:')) {
    // 이미지 없을 때 로딩 메시지
    const query = text.replace('IMAGE_SEARCH:', '').split('\n')[0].trim();
    const wrap = document.createElement('div');
    wrap.className = 'msg-wrap';
    const mi = document.createElement('div');
    mi.className = 'msg-inner';
    const av = document.createElement('div');
    av.className = 'av av-ai'; av.textContent = '🛍️';
    const bubble = document.createElement('div');
    bubble.className = 'bubble bubble-ai';
    bubble.textContent = `🔍 "${query}" 이미지 검색 중...`;
    mi.appendChild(av); mi.appendChild(bubble);
    wrap.appendChild(mi);
    chat.appendChild(wrap);
    chat.scrollTop = chat.scrollHeight;
    if (text.includes('ANTI_CONFIRM_BUTTONS')) {
      renderAntiConfirm(text);
    }
  } else if (text.startsWith('VS_QUESTION:')) {
    renderVsQuestion(text);
  } else if (text.startsWith('VS_RESULT:')) {
    renderVsResult(text);
  } else if (isConfirm(text)) {
    chat.appendChild(renderConfirm(text));
  } else if (text.includes('ANTI_CONFIRM_BUTTONS')) {
    renderAntiConfirm(text);
  } else if (text.includes('MULTI_SELECT:')) {
    renderMultiSelect(text);
  } else if (text.includes('CONTEXT_SELECT:')) {
    renderContextSelect(text);
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

      // 📌SOURCE:: 파싱 → 출처 링크 렌더링
      if (text.includes('📌SOURCE::')) {
        const parts = text.split('\n\n📌SOURCE::');
        const mainText = parts[0].trim();
        const sourceStr = parts[1] || '';
        bubble.textContent = mainText;

        // 출처 링크 컨테이너
        const sourceDiv = document.createElement('div');
        sourceDiv.style.cssText = 'margin-top:6px; font-size:11px; opacity:0.65;';
        sourceDiv.textContent = '📌 출처: ';

        const sources = sourceStr.split('|');
        sources.forEach((src, i) => {
          const [name, url] = src.split('::');
          if (!name || !url) return;
          const a = document.createElement('a');
          a.href = url;
          a.target = '_blank';
          a.textContent = name;
          a.style.cssText = 'color:inherit; text-decoration:underline; margin-right:8px;';
          sourceDiv.appendChild(a);
        });
        bubble.appendChild(sourceDiv);
      } else {
        bubble.textContent = text;
      }
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

// 채팅창에 안 보이게 조용히 전송 (ADD_ITEM 등 내부 명령)
async function sendSilent(msg) {
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
    const resp = data.response || '';
    if (resp.startsWith('BOARD_UPDATE')) {
      const boardText = resp.replace('BOARD_UPDATE', '').trim();
      // 마지막 .board를 새 내용으로 교체
      const allBoards = document.querySelectorAll('.board');
      if (allBoards.length > 0) {
        const lastBoard = allBoards[allBoards.length - 1];
        // 임시 컨테이너에 렌더링
        const tmp = document.createElement('div');
        const origChat = chat;
        chat = tmp;
        renderBoard(boardText);
        chat = origChat;
        const newBoard = tmp.querySelector('.board');
        if (newBoard) lastBoard.replaceWith(newBoard);
      }
    } else {
      addAiMsg(resp);
    }
  } catch(e) {
    document.getElementById('typing')?.remove();
    addAiMsg('연결 오류가 발생했어요. 다시 시도해주세요.');
  }
}
