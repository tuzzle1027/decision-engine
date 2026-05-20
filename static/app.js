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

function goHome() {
  // 채팅 초기화 + 첫 화면으로
  document.getElementById('chat').innerHTML = '';
  session = {};
  startPage.style.display = '';
  startPage.classList.remove('hidden');
  chatPage.classList.remove('visible');
  startInput.value = '';
  startInput.focus();
}


// ── user_profile (테스트용: 세션 기반, 새로고침 시 초기화)
// ⚠️ 서비스 시 localStorage or 서버 캐시로 확장 필요
let userProfile = {};

function saveUserProfile(data) {
  userProfile = Object.assign(userProfile, data);
  if (session) session.user_profile = userProfile;
}

// ── 퀵 질문 팝업 ──
function startChat() {
  const text = startInput.value.trim();
  if (!text) return;
  showChatPage();
  setTimeout(() => sendWithQuickQ(text), 100);
}

function startWithChip(text) {
  showChatPage();
  setTimeout(() => sendWithQuickQ(text), 100);
}

// ── 마음 상황판 (분기 구조) ──
var QQ_COLOR = '#c2b099';

function sendWithQuickQ(text) {
  if (userProfile._answered) { send(text); return; }

  var qqWrap = document.createElement('div');
  qqWrap.className = 'msg-wrap';
  var qqInner = document.createElement('div');
  qqInner.className = 'msg-inner';
  qqInner.style.cssText = 'display:block;';
  qqWrap.appendChild(qqInner);
  chat.appendChild(qqWrap);

  var intro = document.createElement('div');
  intro.style.cssText = 'padding:8px 0 4px;font-size:14px;color:#888;';
  intro.textContent = '더 잘 찾아드리려고 몇 가지만 여쭤볼게요 😊';
  qqInner.appendChild(intro);

  var loadMsg = document.createElement('div');
  loadMsg.style.cssText = 'padding:8px 0;font-size:13px;color:#aaa;';
  loadMsg.textContent = '질문 준비 중...';
  qqInner.appendChild(loadMsg);
  chat.scrollTop = chat.scrollHeight;

  var answers = {};

  // ★ 잔머리 2.0: Q1 → Q2맵 백그라운드 → Q3 → 고민
  fetch('/mind_chat', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ product: text, step: 'q1', history: '' })
  })
  .then(function(r){ return r.json(); })
  .then(function(q1Data){
    loadMsg.remove();
    if (!q1Data || !q1Data.opts || q1Data.opts.length === 0) { send(text); return; }

    // ★ Q1 표시하는 동안 Q2맵 백그라운드 준비!
    var q2MapReady = null;
    var q2MapLoading = true;
    fetch('/mind_chat', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ product: text, step: 'q2map', history: q1Data.opts.join(', ') })
    })
    .then(function(r){ return r.json(); })
    .then(function(data){ q2MapReady = data.q2_map || {}; q2MapLoading = false; })
    .catch(function(){ q2MapReady = {}; q2MapLoading = false; });

    // Q1 표시
    _showQ(qqInner, q1Data.q, q1Data.opts, false, function(q1Answer) {
      answers.q1 = q1Answer;

      function showQ2(q2Data) {
        _showQ(qqInner, q2Data.q, q2Data.opts, false, function(q2Answer) {
          answers.q2 = q2Answer;

          // Q3
          var q3Load = document.createElement('div');
          q3Load.style.cssText = 'padding:8px 0;font-size:13px;color:#aaa;';
          q3Load.textContent = '...';
          qqInner.appendChild(q3Load);

          fetch('/mind_chat', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ product: text, step: 'q3', history: 'Product: '+text+'\n사용자: '+q1Answer+'\n환경: '+q2Answer })
          })
          .then(function(r){ return r.json(); })
          .then(function(data){
            q3Load.remove();
            if (!data || !data.opts) { data = {q: '걱정되는 부분이요?', opts: ['가격','품질','내구성'], multi: true}; }

            _showQ(qqInner, data.q, data.opts, true, function(q3Answer) {
              answers.q3 = q3Answer;
              var q3Text = Array.isArray(q3Answer) ? q3Answer.join(', ') : q3Answer;

              // 고민
              var cLoad = document.createElement('div');
              cLoad.style.cssText = 'padding:8px 0;font-size:13px;color:#aaa;';
              cLoad.textContent = '...';
              qqInner.appendChild(cLoad);

              fetch('/mind_chat', {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({ product: text, step: 'concerns', history: 'Product: '+text+'\n사용자: '+q1Answer+'\n환경: '+q2Answer+'\n걱정: '+q3Text })
              })
              .then(function(r){ return r.json(); })
              .then(function(data){
                cLoad.remove();
                var concerns = (data && data.concerns) || ['가격','내구성','관리'];
                var example = (data && data.example) || '고민을 자유롭게 입력해주세요';
                _showConcerns(qqInner, text, answers, concerns, example);
              })
              .catch(function(){ cLoad.remove(); _finishQuickQ(qqInner, text, answers); });
            });
          })
          .catch(function(){ q3Load.remove(); _finishQuickQ(qqInner, text, answers); });
        });
      }

      // Q2맵 체크
      if (!q2MapLoading && q2MapReady && q2MapReady[q1Answer] && q2MapReady[q1Answer].opts && q2MapReady[q1Answer].opts.length > 0) {
        // ★ 즉시! (백그라운드 준비 완료)
        showQ2(q2MapReady[q1Answer]);
      } else if (q2MapLoading) {
        // 아직 로딩 중 → 대기
        var waitLoad = document.createElement('div');
        waitLoad.style.cssText = 'padding:8px 0;font-size:13px;color:#aaa;';
        waitLoad.textContent = '...';
        qqInner.appendChild(waitLoad);
        var waitTimer = setInterval(function() {
          if (!q2MapLoading) {
            clearInterval(waitTimer);
            waitLoad.remove();
            if (q2MapReady && q2MapReady[q1Answer] && q2MapReady[q1Answer].opts && q2MapReady[q1Answer].opts.length > 0) {
              showQ2(q2MapReady[q1Answer]);
            } else {
              // 매핑 실패 → LLM으로 Q2 생성
              var q2Load2 = document.createElement('div');
              q2Load2.style.cssText = 'padding:8px 0;font-size:13px;color:#aaa;';
              q2Load2.textContent = '...';
              qqInner.appendChild(q2Load2);
              fetch('/mind_chat', {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({ product: text, step: 'q2', history: 'Product: '+text+'\n사용자 유형: '+q1Answer })
              })
              .then(function(r){ return r.json(); })
              .then(function(data){ q2Load2.remove(); showQ2(data.opts ? data : {q:'주로 어디서 사용하세요?', opts:['집','야외','사무실']}); })
              .catch(function(){ q2Load2.remove(); showQ2({q:'주로 어디서 사용하세요?', opts:['집','야외','사무실']}); });
            }
          }
        }, 200);
      } else {
        // 매핑 실패 → LLM으로 Q2 생성
        var q2Load3 = document.createElement('div');
        q2Load3.style.cssText = 'padding:8px 0;font-size:13px;color:#aaa;';
        q2Load3.textContent = '...';
        qqInner.appendChild(q2Load3);
        fetch('/mind_chat', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({ product: text, step: 'q2', history: 'Product: '+text+'\n사용자 유형: '+q1Answer })
        })
        .then(function(r){ return r.json(); })
        .then(function(data){ q2Load3.remove(); showQ2(data.opts ? data : {q:'주로 어디서 사용하세요?', opts:['집','야외','사무실']}); })
        .catch(function(){ q2Load3.remove(); showQ2({q:'주로 어디서 사용하세요?', opts:['집','야외','사무실']}); });
      }
    });
  })
  .catch(function(){ loadMsg.remove(); send(text); });
}




// 질문 표시 헬퍼
function _showQ(container, qText, opts, isMulti, onDone) {
  var qd = document.createElement('div');
  qd.style.cssText = 'padding:12px 0 4px;font-size:15px;font-weight:500;color:#333;';
  qd.textContent = qText;
  container.appendChild(qd);

  var bw = document.createElement('div');
  bw.style.cssText = 'display:flex;flex-direction:column;gap:8px;padding:8px 0;';
  var sel = [];

  for (var j = 0; j < opts.length; j++) {
    (function(opt) {
      var b = document.createElement('button');
      b.textContent = opt;
      b.style.cssText = 'padding:7px 16px;border-radius:20px;border:0.5px solid #d4c5b8;background:transparent;color:#5a4a40;font-size:13px;cursor:pointer;text-align:left;width:fit-content;';
      var pIdx = opt.indexOf('(');
      if (pIdx > 0) {
        b.innerHTML = '<b>' + opt.substring(0, pIdx) + '</b>' + opt.substring(pIdx);
      }
      b.onclick = function() {
        if (isMulti) {
          var idx = sel.indexOf(opt);
          if (idx >= 0) { sel.splice(idx, 1); b.style.background='transparent'; b.style.color='#5a4a40'; b.style.borderColor='#d4c5b8'; }
          else { sel.push(opt); b.style.background=QQ_COLOR; b.style.color='#fff'; b.style.borderColor=QQ_COLOR; }
        } else {
          b.style.background = QQ_COLOR; b.style.color = '#fff'; b.style.borderColor = QQ_COLOR;
          var btns = bw.getElementsByTagName('button');
          for (var k = 0; k < btns.length; k++) btns[k].disabled = true;
          if (fw) fw.style.display = 'none';
          onDone(opt);
        }
      };
      bw.appendChild(b);
    })(opts[j]);
  }
  container.appendChild(bw);

  var fw = document.createElement('div');
  fw.style.cssText = 'display:flex;align-items:center;gap:12px;padding:4px 0 8px;';

  if (isMulti) {
    var nb = document.createElement('button');
    nb.textContent = '다음 →';
    nb.style.cssText = 'padding:7px 20px;border-radius:20px;border:none;background:'+QQ_COLOR+';color:#fff;font-size:13px;cursor:pointer;';
    nb.onclick = function() {
      var btns = bw.getElementsByTagName('button');
      for (var k = 0; k < btns.length; k++) btns[k].disabled = true;
      fw.style.display = 'none';
      onDone(sel);
    };
    fw.appendChild(nb);
  }

  var sk = document.createElement('button');
  sk.textContent = '건너뛸게요';
  sk.style.cssText = 'border:none;background:none;color:#aaa;font-size:12px;cursor:pointer;';
  sk.onclick = function() {
    userProfile._answered = true;
    userProfile._skipped = true;
    var btns = bw.getElementsByTagName('button');
    for (var k = 0; k < btns.length; k++) btns[k].disabled = true;
    fw.style.display = 'none';
    send(text);
  };
  fw.appendChild(sk);
  container.appendChild(fw);
  chat.scrollTop = chat.scrollHeight;
}

// 고민 키워드 표시
function _showConcerns(container, text, answers, concerns, example) {
  var qd = document.createElement('div');
  qd.style.cssText = 'padding:12px 0 4px;font-size:15px;font-weight:500;color:#333;';
  qd.textContent = '특별히 고민하시는 것 있으세요? 💭';
  container.appendChild(qd);

  var bw = document.createElement('div');
  bw.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;padding:8px 0;';
  var cSel = [];

  for (var j = 0; j < concerns.length; j++) {
    (function(opt) {
      var b = document.createElement('button');
      b.textContent = opt;
      b.style.cssText = 'padding:7px 16px;border-radius:20px;border:0.5px solid #d4c5b8;background:transparent;color:#5a4a40;font-size:13px;cursor:pointer;';
      b.onclick = function() {
        var idx = cSel.indexOf(opt);
        if (idx >= 0) { cSel.splice(idx, 1); b.style.background='transparent'; b.style.color='#5a4a40'; }
        else { cSel.push(opt); b.style.background=QQ_COLOR; b.style.color='#fff'; }
      };
      bw.appendChild(b);
    })(concerns[j]);
  }
  container.appendChild(bw);

  var inp = document.createElement('input');
  inp.type = 'text';
  inp.placeholder = '예) ' + example;
  inp.style.cssText = 'width:100%;padding:10px 14px;border:1px solid #d4c5b8;border-radius:12px;font-size:13px;margin:8px 0;outline:none;box-sizing:border-box;color:#5a4a40;';
  container.appendChild(inp);

  var fw = document.createElement('div');
  fw.style.cssText = 'display:flex;align-items:center;gap:12px;padding:4px 0 8px;';
  var nb = document.createElement('button');
  nb.textContent = '완료 →';
  nb.style.cssText = 'padding:7px 20px;border-radius:20px;border:none;background:'+QQ_COLOR+';color:#fff;font-size:13px;cursor:pointer;';
  nb.onclick = function() {
    if (inp.value.trim()) cSel.push(inp.value.trim());
    answers.concerns = cSel;
    var btns = bw.getElementsByTagName('button');
    for (var k = 0; k < btns.length; k++) btns[k].disabled = true;
    inp.disabled = true;
    fw.style.display = 'none';
    _finishQuickQ(container, text, answers);
  };
  fw.appendChild(nb);

  var sk = document.createElement('button');
  sk.textContent = '건너뛸게요';
  sk.style.cssText = 'border:none;background:none;color:#aaa;font-size:12px;cursor:pointer;';
  sk.onclick = function() {
    var btns = bw.getElementsByTagName('button');
    for (var k = 0; k < btns.length; k++) btns[k].disabled = true;
    inp.disabled = true;
    fw.style.display = 'none';
    _finishQuickQ(container, text, answers);
  };
  fw.appendChild(sk);
  container.appendChild(fw);
  chat.scrollTop = chat.scrollHeight;
}

// 완료
function _finishQuickQ(container, text, answers) {
  saveUserProfile(answers);
  userProfile._answered = true;
  var d = document.createElement('div');
  d.style.cssText = 'padding:8px 0;font-size:13px;color:#999;';
  d.textContent = '고마워요! 지금 바로 찾아드릴게요 🔍';
  container.appendChild(d);
  chat.scrollTop = chat.scrollHeight;

  // ★ 마음 Q1을 검색어에 합치기 (2구역 건너뛰기)
  var enriched = text;
  if (answers.q1) {
    var q1Short = answers.q1;
    var pi = q1Short.indexOf('(');
    if (pi > 0) q1Short = q1Short.substring(0, pi).trim();
    enriched = q1Short + ' ' + text;
  }
  setTimeout(function(){ send(enriched); }, 300);
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

// ★ 픽코 스트리밍 로딩 CSS
(function() {
  const style = document.createElement('style');
  style.textContent = `
    .picko-loading { padding: 12px 0; width: 100%; }
    .step-label {
      display: flex; justify-content: space-between;
      font-size: 13px; margin-bottom: 8px;
      color: #a38d72; transition: color 0.5s ease;
    }
    .step-label.done { color: #a38d72; }
    .bar-wrap {
      width: 100%; height: 6px;
      background: #ede9e3; border-radius: 3px;
      overflow: hidden; margin-bottom: 16px;
    }
    .bar {
      height: 100%; width: 0%;
      background: #a38d72; border-radius: 3px;
      transition: background 0.5s ease;
    }
    .bar.done { background: #a38d72; }
    .board-stream-section { margin-bottom: 10px; }
    .board-stream-label {
      font-size: 11px; font-weight: 500;
      color: #9e8e82; letter-spacing: 0.04em;
      margin-bottom: 6px;
    }
    .board-stream-btns { display: flex; gap: 6px; flex-wrap: wrap; }
    .board-stream-btn {
      padding: 7px 16px; border-radius: 20px;
      border: 0.5px solid #d4c5b8; font-size: 13px;
      cursor: pointer; background: transparent; color: #5a4a40;
      opacity: 0; transform: translateY(4px);
      transition: opacity 0.25s ease, transform 0.25s ease;
    }
    .board-stream-btn.show { opacity: 1; transform: translateY(0); }
    @keyframes fadeInStep {
      from { opacity: 0; transform: translateY(5px); }
      to   { opacity: 1; transform: translateY(0); }
    }
  `;
  document.head.appendChild(style);
})();


// 회색 → 먹색, 숫자 카운터 애니메이션
function addStreamingLoader() {
  // ★ msg-wrap 구조 유지 + bubble 대신 심플 div로 빠만!
  const wrap = document.createElement('div');
  wrap.className = 'msg-wrap'; wrap.id = 'streaming-loader';
  const mi = document.createElement('div'); mi.className = 'msg-inner';
  const av = document.createElement('div'); av.className = 'av av-ai'; av.textContent = '🛍️';

  const loader = document.createElement('div');
  loader.style.cssText = 'flex:1; min-width:0; padding: 4px 0;';
  loader.innerHTML = `
    <div class="step-label" id="pk-lbl">
      <span id="pk-txt" style="color:#a38d72;">제품 데이터 분석 중</span>
      <span id="pk-cnt" style="color:#a38d72;"></span>
    </div>
    <div class="bar-wrap"><div class="bar" id="pk-bar"></div></div>
  `;
  mi.appendChild(av); mi.appendChild(loader);
  wrap.appendChild(mi); chat.appendChild(wrap);

  // 1단계 숫자 + 빠 애니메이션
  let count = 0;
  const timer = setInterval(() => {
    count += Math.floor(Math.random() * 18) + 6;
    const pkCnt = document.getElementById('pk-cnt');
    const pkBar = document.getElementById('pk-bar');
    if (pkCnt) pkCnt.textContent = count;
    if (pkBar) pkBar.style.width = Math.min(count / 5, 88) + '%';
  }, 110);
  wrap._phase1Timer = timer;
  scroll();
  return wrap;
}

function updateStreamingStep(key) {
  const lbl = document.getElementById('pk-lbl');
  const txt = document.getElementById('pk-txt');
  const cnt = document.getElementById('pk-cnt');
  const bar = document.getElementById('pk-bar');
  if (!lbl) return;

  // 현재 단계 완료
  lbl.classList.add('done');
  if (bar) { bar.style.width = '100%'; bar.classList.add('done'); }

  setTimeout(() => {
    if (!document.getElementById('pk-lbl')) return;
    lbl.classList.remove('done');
    if (bar) { bar.classList.remove('done'); bar.style.width = '0%'; }

    if (key === 'review') {
      if (txt) txt.textContent = '제품 옵션 확인 중';
      if (txt) txt.style.color = '#a38d72';
      let c2 = 0;
      const t2 = setInterval(() => {
        c2 += Math.floor(Math.random() * 5) + 2;
        if (cnt) { cnt.textContent = c2; cnt.style.color = '#a38d72'; }
        if (bar) bar.style.width = Math.min(c2 * 3, 88) + '%';
        if (c2 >= 28) clearInterval(t2);
      }, 130);

    } else if (key === 'price') {
      if (txt) txt.textContent = '가격 구간 확인 중';
      if (txt) txt.style.color = '#a38d72';
      let c3 = 0;
      const t3 = setInterval(() => {
        c3 += Math.floor(Math.random() * 8) + 3;
        if (cnt) { cnt.textContent = c3; cnt.style.color = '#a38d72'; }
        if (bar) bar.style.width = Math.min(c3 * 5, 88) + '%';
        if (c3 >= 18) clearInterval(t3);
      }, 100);
    }
  }, 300);
}

// ★ 상황판 섹션 파싱
function parseBoardSections(boardText) {
  const sections = [];
  const lines = boardText.split('\n');
  let current = null;
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const m = trimmed.match(/^\[(.+?)\]$/);
    if (m) {
      if (current) sections.push(current);
      current = { label: m[1], btns: [] };
    } else if (current && trimmed.includes('/')) {
      current.btns.push(...trimmed.split('/').map(b => b.trim()).filter(Boolean));
    } else if (current && trimmed) {
      current.btns.push(trimmed);
    } else if (!current && trimmed) {
      sections.push({ label: '', header: trimmed, btns: [] });
    }
  }
  if (current) sections.push(current);
  return sections;
}

// ★ 상황판 텍스트 스트리밍 → 버튼 변신
function streamBoardSections(container, sections, onDone) {
  let idx = 0;
  function nextSection() {
    if (idx >= sections.length) { if (onDone) onDone(); return; }
    const sec = sections[idx++];
    if (!sec.label && sec.header) {
      const h = document.createElement('div');
      h.style.cssText = 'font-size:13px;color:#9e8e82;margin-bottom:8px;';
      container.appendChild(h);
      let i = 0;
      const t = setInterval(() => {
        h.textContent += sec.header[i++];
        if (i >= sec.header.length) { clearInterval(t); setTimeout(nextSection, 150); }
      }, 25);
      return;
    }
    const wrap = document.createElement('div');
    wrap.className = 'board-stream-section';
    const labelEl = document.createElement('div');
    labelEl.className = 'board-stream-label';
    const row = document.createElement('div');
    row.className = 'board-stream-btns';
    wrap.appendChild(labelEl); wrap.appendChild(row);
    container.appendChild(wrap);

    const labelText = '[' + sec.label + ']';
    let li = 0;
    const lt = setInterval(() => {
      labelEl.textContent += labelText[li++];
      scroll();
      if (li >= labelText.length) {
        clearInterval(lt);
        sec.btns.forEach((b, i) => {
          setTimeout(() => {
            const btn = document.createElement('button');
            btn.className = 'board-stream-btn';
            btn.textContent = b;
            row.appendChild(btn);
            requestAnimationFrame(() => setTimeout(() => btn.classList.add('show'), 20));
            btn.addEventListener('click', () => sendMessage('BOARD_UPDATE ' + sec.label + ':' + b));
            scroll();
            if (i === sec.btns.length - 1) setTimeout(nextSection, 250);
          }, i * 75);
        });
        if (!sec.btns.length) setTimeout(nextSection, 150);
      }
    }, 35);
  }
  nextSection();
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

  // ★ 공감멘트는 SSE empathy 이벤트에서 이미 표시!
  // 상황판만 바로 렌더링!
  _renderBoardContent(boardText);
}

function _renderBoardContent(boardText) {
  // ★ 가격 금액 → 저가/중가/고가/최고가 강제 치환
  boardText = boardText.replace(/\[가격\]\n[^\[]+/g, function(match) {
    if (/\d+만원/.test(match)) {
      return '[가격]\n저가 / 중가 / 고가 / 최고가';
    }
    return match;
  });

  // ★ 누락된 변수 복구!
  const cleanBoardText = boardText.replace(/\nPRICE_MAP:{.*}/, '');
  const hasMdfPb = /\bMDF\b|\bPB\b|\bLPM\b/.test(cleanBoardText);
  const BASIC_COLORS = ['화이트', '라이트그레이', '그레이', '블랙'];
  const lines = cleanBoardText.split('\n').filter(l => l.trim());
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
  const _prod = (session && session.raw_product) ? session.raw_product : '';
  const _titleText = _prod ? '▶ ' + _prod + ' 조건을 선택해주세요' : '▶ 조건을 선택해주세요';
  board.appendChild(title);

  // ★ title 타이핑 효과 (조금 느리게 = 있어 보임!)
  let ti = 0;
  const titleTimer = setInterval(() => {
    title.textContent += _titleText[ti++];
    if (ti >= _titleText.length) clearInterval(titleTimer);
  }, 38);

  const selections = {};
  let directInput = null;
  const pendingRows = []; // ★ row 모아두기!

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
      inp.placeholder = '✍️ 여기에 적어주신 한 마디가 더 정확한 제품을 찾는데 도움이 됩니다';
      inp.type = 'text';
      // ★ 마음 상황판에서 저장된 내용 자동 채우기
      if (userProfile && userProfile.concerns && userProfile.concerns.length > 0) {
        inp.value = userProfile.concerns.join(', ');
      }
      directInput = inp;
      row.style.marginTop = '12px';
      row.appendChild(inp);
      pendingRows.push(row); // ★
    } else {
      const opts = document.createElement('div');
      opts.className = 'board-options';
      // CHECKED:값 파싱 (가성비/자연어 자동 선택)
      const checkedMatch = optionLine.match(/CHECKED:([^/\n]+)/);
      const preChecked = checkedMatch ? checkedMatch[1].trim() : null;
      const cleanContent = optionLine.replace(/\s*CHECKED:[^\n/]*/g, '').trim();

      // 색상 항목 → 컬러칩 렌더링 (범용 - 하드코딩 없음)
      // 색상 이름 → hex 변환 테이블 (LLM이 내려준 옵션값 기반)
      const NAME_TO_HEX = {
        // 흰색 계열
        '화이트':'#F8F8F8','흰색':'#F8F8F8','아이보리':'#F0EBE0',
        '크림':'#FFF3D6','오프화이트':'#F2EEE9','밀키화이트':'#F5F0E8',
        '연아이보리':'#F5EFE0','내추럴화이트':'#F0EDE5',
        // 베이지/브라운 계열
        '베이지':'#E8D5B7','샌드':'#D4B896','카멜':'#C19A6B',
        '브라운':'#8B6914','갈색':'#8B6914','모카':'#7B5E52',
        '초콜릿':'#5C3317','다크브라운':'#3C1F0A','코코아':'#6B4226',
        '누드':'#E8C9A0','스킨':'#FDBCB4','피치':'#FFCBA4',
        // 그레이 계열
        '그레이':'#A8A8A8','회색':'#A8A8A8','라이트그레이':'#D4D4D4',
        '다크그레이':'#696969','실버그레이':'#C0C0C0','쿨그레이':'#B0B8C1',
        '웜그레이':'#B8AFA8','스틸그레이':'#7A8B8B',
        // 블랙 계열
        '블랙':'#2C2C2C','검정':'#2C2C2C','검은색':'#2C2C2C',
        '무광블랙':'#1A1A1A','차콜':'#36454F','앤트라사이트':'#2F3640',
        // 우드/원목 계열
        '원목':'#C19A6B','우드':'#A0714F','원목색':'#C19A6B','우드색':'#A0714F','우드톤':'#C19A6B','자연색':'#DEB887','오크':'#C8A97E','내추럴':'#DEB887',
        '라이트우드':'#DEB887','미디엄우드':'#A0714F','다크우드':'#5C3D2E',
        '월넛':'#5C3317','오크':'#C8A97E','편백':'#D4C4A0',
        '내추럴':'#DEB887','밝은톤':'#E8D5B7','중간톤':'#A8A8A8','어두운톤':'#36454F',
        // 골드/실버
        '골드':'#D4AF37','금색':'#D4AF37','실버':'#C0C0C0',
        '은색':'#C0C0C0','로즈골드':'#B76E79','건메탈':'#808080',
        '크롬':'#DBE2E9','브론즈':'#CD7F32',
        // 네이비/블루 계열
        '네이비':'#2C3E6B','남색':'#2C3E6B','블루':'#6B8CAE',
        '스카이블루':'#87CEEB','베이비블루':'#B0D4E8','로얄블루':'#4169E1',
        '더스티블루':'#6B8CAE','인디고':'#4B0082','데님':'#1560BD',
        '코발트':'#0047AB','틸':'#008080','피콕블루':'#005F6B',
        // 그린 계열
        '그린':'#6B7C4E','올리브':'#6B7C4E','올리브그린':'#6B7C4E',
        '카키':'#8B8B6B','민트':'#B2D8D8','세이지':'#87AE73',
        '포레스트그린':'#2D5A27','에메랄드':'#50C878','모스그린':'#8A9A5B',
        '다크그린':'#006400','애플그린':'#8DB600','연두':'#ADFF2F',
        // 핑크/레드 계열
        '핑크':'#E8A0A0','베이비핑크':'#FFB6C1','로즈':'#FF007F',
        '코랄':'#FF7F7F','살몬':'#FA8072','버건디':'#722F37',
        '와인':'#722F37','레드':'#CC3333','빨강':'#CC3333',
        '빨간색':'#CC3333','체리':'#DE3163','마젠타':'#FF00FF',
        '핫핑크':'#FF69B4','더스티핑크':'#DCAE96','머브':'#E0B0FF',
        // 퍼플/라벤더 계열
        '라벤더':'#B8A8D8','퍼플':'#800080','바이올렛':'#EE82EE',
        '라일락':'#C8A2C8','플럼':'#DDA0DD',
        // 옐로우/오렌지 계열
        '옐로우':'#D4AC0D','노랑':'#FFD700','노란색':'#FFD700',
        '머스타드':'#FFDB58','마스터드':'#C9A84C','오렌지':'#FF8C00',
        '레몬':'#FFF44F','바나나':'#FFE135','어스':'#8B7355',
        '테라코타':'#C17755','러스트':'#B7410E',
        // 기타
        '멀티':'#FF6B6B','멀티컬러':'#FF6B6B','컬러풀':'#FF6B6B',
        '파스텔':'#F0D9FF','파스텔톤':'#F0D9FF','혼합색상':'#FF6B6B',
        '투명':'#FFFFFF','클리어':'#F0F8FF',
      };
      const WHITE_NAMES = ['화이트','흰색','아이보리','크림','오프화이트'];
      if (label === '가격') {
        row.dataset.priceRow = '1';
      }
      if (label === '색상' || label === '목재톤' || label === '색상계열' || label === '프레임색상') {
        row.dataset.colorRow = '1'; // 소재 선택 시 hide/show 대상
        opts.style.cssText = 'display:flex; flex-wrap:wrap; gap:10px 12px; padding:4px 0;';
        let chipSelected = null;
        // PB/MDF 보드면 기본 4색만
        const EXCLUDE_FROM_CHIP = ['기타', '기타색상', '기타색', '해당없음', '상관없음', '무지개', '하트', '별', '구름', '플라워', '체크', '스트라이프', '컬러', '컬러풀', '패턴', '프린트'];
        const rawColorOpts = hasMdfPb ? BASIC_COLORS : cleanContent.split('/').map(o => o.trim()).filter(o => o);
        // 기타/모르는 색상 → 일반 버튼으로 분리
        const colorOpts = rawColorOpts.map(o=>o.trim()).filter(o => !EXCLUDE_FROM_CHIP.includes(o) && NAME_TO_HEX[o]);
        const extraOpts = rawColorOpts.map(o=>o.trim()).filter(o => EXCLUDE_FROM_CHIP.includes(o) || !NAME_TO_HEX[o]);
        colorOpts.forEach(opt => {
          const hex = NAME_TO_HEX[opt] || '#cccccc';
          const isWhite = WHITE_NAMES.includes(opt);
          const wrap = document.createElement('div');
          wrap.dataset.chipName = opt;
          wrap.style.cssText = 'display:flex; flex-direction:column; align-items:center; gap:6px; cursor:pointer;';
          const chip = document.createElement('div');
          chip.style.cssText = `width:32px; height:32px; border-radius:50%; background:${hex}; transition:transform 0.15s; flex-shrink:0;${isWhite ? 'box-shadow:0 0 0 1px #d0ccc6;' : ''}`;
          const lbl2 = document.createElement('div');
          lbl2.style.cssText = 'font-size:9px; color:#999; white-space:nowrap; text-align:center;';
          lbl2.textContent = opt;
          wrap.appendChild(chip); wrap.appendChild(lbl2);
          wrap.onclick = () => {
            if (chipSelected) chipSelected.style.transform = 'scale(1)';
            if (chipSelected === chip) {
              chipSelected = null;
              delete selections[label];
              return;
            }
            chip.style.transform = 'scale(0.62)';
            chipSelected = chip;
            selections[label] = opt;
          };
          if (preChecked && opt === preChecked) {
            chip.style.transform = 'scale(0.62)';
            chipSelected = chip;
            selections[label] = opt;
          }
          opts.appendChild(wrap);
        });
        // 기타/모르는 색상 → 칩 아래 별도 행에 일반 버튼으로
        row.appendChild(opts);
        if (extraOpts.length > 0) {
          const extraRow = document.createElement('div');
          extraRow.style.cssText = 'display:flex; flex-wrap:wrap; gap:6px; margin-top:6px;';
          extraOpts.forEach(opt => {
            const btn = document.createElement('div');
            btn.className = 'opt-btn';
            btn.textContent = opt;
            btn.onclick = () => {
              opts.querySelectorAll('[data-chip-name]').forEach(w => {
                w.querySelector('div').style.transform = 'scale(1)';
              });
              extraRow.querySelectorAll('.opt-btn').forEach(b => b.classList.remove('selected'));
              btn.classList.add('selected');
              selections[label] = opt;
            };
            extraRow.appendChild(btn);
          });
          row.appendChild(extraRow);
        }
        board.appendChild(row);
        i++;
        continue;
      }

      // 슬래시 없으면 LLM fallback이 공백으로 구분한 것 → 재파싱 시도 안 함 (프롬프트로 방어)
      // 방어막: 옵션이 1개인데 너무 길면 경고
      // 괄호 안 슬래시 무시: 원목(고무나무/편백나무) → 버튼 1개로 처리
      const rawOpts = cleanContent.includes('/') ? cleanContent.split(/\/(?![^(]*\))/) : cleanContent.split('  ').filter(o => o.trim());
      rawOpts.map(o => o.trim().replace(/\s+/g, ' ')).filter(o => o && o !== '[' && o.length > 0).forEach(opt => {
        const btn = document.createElement('div');
        btn.className = 'opt-btn';
        // 가격 항목: "저가|20만~45만" → 레이블만 표시, 금액은 data 속성
        let displayText = opt;
        let priceValue = opt;
        if (label === '가격' && opt.includes('|')) {
          const parts = opt.split('|');
          displayText = parts[0];  // "저가"
          priceValue = parts[1];   // "20만~45만"
          btn.dataset.priceRange = priceValue;
        }
        btn.textContent = displayText;
        if (preChecked && opt === preChecked) {
          btn.classList.add('selected');
          selections[label] = priceValue;
        }
        btn.onclick = () => {
          opts.querySelectorAll('.opt-btn').forEach(b => b.classList.remove('selected'));
          btn.classList.add('selected');
          // 가격은 등급(저가/중가/고가/최고가)만 저장, range는 표시용
          selections[label] = label === '가격' ? (opt.includes('|') ? opt.split('|')[0] : opt) : opt;
          const displayOpt = label === '가격' && opt.includes('|') ? opt.split('|')[0] : opt;

          // 가격 선택 시 → 미선택 항목 체크 팝업 + LLM 맥락 설명
          if (label === '가격') {
            let rawProduct = (typeof session !== 'undefined' && session.raw_product) ? session.raw_product : '';
            // 등급 판단
            let grade = '';
            if (opt.includes('저가')) grade = '저가';
            else if (opt.includes('중가')) grade = '중가';
            else if (opt.includes('고가') && !opt.includes('최고가')) grade = '고가';
            else if (opt.includes('최고가')) grade = '최고가';

            // ★ 가격 행동 센서: 클릭 기록 + 의미 부여
            if (!userProfile.price_actions) userProfile.price_actions = [];
            userProfile.price_actions.push(grade);

            // 패턴 분석
            var pa = userProfile.price_actions;
            if (pa.length >= 3) {
              userProfile.price_sensor = '갈등(왔다갔다)';
            } else if (pa.length === 1) {
              if (grade === '저가') userProfile.price_sensor = '예산제한';
              else if (grade === '최고가') userProfile.price_sensor = '품질최우선';
              else if (grade === '중가') userProfile.price_sensor = '안전주의';
              else if (grade === '고가') userProfile.price_sensor = '품질중시';
            } else if (pa.length === 2) {
              var prev = pa[0];
              if (prev === '저가' && grade === '최고가' || prev === '최고가' && grade === '저가') userProfile.price_sensor = '비교탐색';
              else if (prev === '최고가' && grade === '중가') userProfile.price_sensor = '최고가부담';
              else if (prev === '저가' && grade === '중가') userProfile.price_sensor = '예산있지만불안';
            }
            if (session) session.user_profile = userProfile;
            console.log('[가격센서]', grade, userProfile.price_sensor, pa);

            // ★ 저가/최고가 선택 시 추가 질문 팝업
            if (grade === '저가' || grade === '최고가') {
              var priceOpts = grade === '저가'
                ? ['가성비 추구', '예산이 정해져 있어서', '일단 구경해볼래요']
                : ['품질이 중요해서', '오래 쓸 거라서', '선물이에요'];

              // 기존 팝업 있으면 제거
              var existingPQ = document.getElementById('price-q-popup');
              if (existingPQ) existingPQ.remove();

              var pqWrap = document.createElement('div');
              pqWrap.id = 'price-q-popup';
              pqWrap.style.cssText = 'padding:10px 0 8px;';

              var pqText = document.createElement('div');
              pqText.style.cssText = 'font-size:13px;color:#5a4a40;margin-bottom:8px;';
              pqText.textContent = grade === '저가' ? '혹시 이유가 있으신가요? 😊' : '어떤 이유로 선택하셨나요? 😊';
              pqWrap.appendChild(pqText);

              var pqBtns = document.createElement('div');
              pqBtns.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;';
              priceOpts.forEach(function(po) {
                var pb = document.createElement('button');
                pb.textContent = po;
                pb.style.cssText = 'padding:6px 14px;border-radius:16px;border:0.5px solid #d4c5b8;background:transparent;color:#5a4a40;font-size:12px;cursor:pointer;';
                pb.onclick = function() {
                  userProfile.price_reason = po;
                  if (session) session.user_profile = userProfile;
                  pb.style.background = '#c2b099';
                  pb.style.color = '#fff';
                  pb.style.borderColor = '#c2b099';
                  pqBtns.querySelectorAll('button').forEach(function(b){ b.disabled = true; });
                  setTimeout(function(){ pqWrap.style.opacity = '0.5'; }, 300);
                  console.log('[가격이유]', po);
                };
                pqBtns.appendChild(pb);
              });
              pqWrap.appendChild(pqBtns);

              // 가격 버튼 아래에 삽입
              btn.parentElement.parentElement.appendChild(pqWrap);
            }

            // ── 미선택 항목 감지 팝업 (보드에 실제 있는 항목만 동적 감지) ──
            const SKIP_LABELS = new Set(['가격', 'E 직접입력', 'E', '직접입력']);
            const boardRows = board.querySelectorAll('.board-row');
            const unselected = [];
            boardRows.forEach(row => {
              const lblEl = row.querySelector('.board-label');
              if (!lblEl) return;
              const lbl = lblEl.textContent.replace(/[\[\]]/g, '').trim();
              if (SKIP_LABELS.has(lbl)) return;
              if (!selections[lbl]) unselected.push(lbl);
            });
            if (unselected.length > 0) {
              // 팝업 생성
              const overlay = document.createElement('div');
              overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.38);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px;';
              const popup = document.createElement('div');
              popup.style.cssText = 'background:var(--surface);border-radius:20px;padding:28px 24px;max-width:300px;width:100%;border:1px solid var(--border);';
              popup.innerHTML = `
                <div style="text-align:center;margin-bottom:16px;">
                  <div style="width:44px;height:44px;border-radius:50%;background:#fef3e2;display:flex;align-items:center;justify-content:center;margin:0 auto 12px;font-size:20px;">💡</div>
                  <div style="font-size:15px;font-weight:500;color:var(--text);margin-bottom:6px;">조건을 더 고르면 더 정확해요!</div>
                  <div style="font-size:13px;color:var(--text-dim);line-height:1.6;">
                    <span style="color:var(--accent);font-weight:500;">${unselected.join(', ')}</span>을(를) 선택하면<br>딱 맞는 제품을 찾아드릴 수 있어요!
                  </div>
                </div>
                <div style="height:0.5px;background:var(--border);margin:16px 0;"></div>
                <div style="display:flex;gap:8px;">
                  <button id="pickoBtnMore" style="flex:1;padding:11px 8px;background:var(--surface2);border:0.5px solid var(--border);border-radius:12px;font-size:13px;font-weight:500;color:var(--text-dim);cursor:pointer;">조건 더 고를게요 ↩</button>
                  <button id="pickoBtnGo" style="flex:1;padding:11px 8px;background:var(--selected);border:none;border-radius:12px;font-size:13px;font-weight:500;color:white;cursor:pointer;">이대로 찾아주세요!</button>
                </div>
              `;
              overlay.appendChild(popup);
              document.body.appendChild(overlay);

              // 조건 더 고를게요 → 가격 선택 취소 + 팝업 닫기
              popup.querySelector('#pickoBtnMore').onclick = () => {
                btn.classList.remove('selected');
                delete selections['가격'];
                overlay.remove();
              };
              // 이대로 찾아주세요 → 팝업 닫고 LLM 설명으로 진행
              popup.querySelector('#pickoBtnGo').onclick = () => {
                overlay.remove();
                _runPriceComment();
              };
              // 오버레이 클릭 시 닫기 (조건 더 고르기와 동일)
              overlay.onclick = (e) => {
                if (e.target === overlay) {
                  btn.classList.remove('selected');
                  delete selections['가격'];
                  overlay.remove();
                }
              };
            } else {
              _runPriceComment();
            }

            function _runPriceComment() {
            if (rawProduct && grade) {
              // 현재 상황판 선택 맥락 수집
              const ctx = Object.entries(selections)
                .filter(([k,v]) => k !== '가격')
                .map(([k,v]) => `${k}:${v}`)
                .join(', ');

              // LLM에 맥락 전달해서 설명 생성
              fetch('/price_grade_comment', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({product: rawProduct, grade, context: ctx, price_range: btn.dataset.priceRange || ''})
              })
              .then(r => r.json())
              .then(data => {
                let gradeEl = board.querySelector('.price-grade-info');
                if (!gradeEl) {
                  gradeEl = document.createElement('div');
                  gradeEl.className = 'price-grade-info';
                  gradeEl.style.cssText = 'font-size:13px;color:var(--text-sub);margin:10px 0 4px;padding:10px 16px 10px 108px;line-height:1.8;white-space:pre-line;border-top:1px solid var(--border);border-bottom:1px solid var(--border);';
                  const priceRow = board.querySelector('[data-price-row]');
                  if (priceRow) priceRow.after(gradeEl);
                }
                const commentText = (data.comment || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                gradeEl.innerHTML = commentText;
              })
              .catch(e => console.log('[가격등급오류]', e));
            }
            } // end _runPriceComment
          }

          // 가격 트리거 - 값(value) 기반 범용 방식
          const PRICE_TRIGGER_VALUES = [
            '1인용','2인용','3인용','4인용','6인용',
            '1단','2단','3단','4단','5단','6단',
            '싱글','슈퍼싱글','퀸','킹',
            '소형','중형','대형','미니',
            '900','1000','1200','1400','1600','1800','2000',
            '원목','철제','가죽','대리석','세라믹','강화유리','스테인레스','알루미늄','라탄',
            '전동','수동','접이식',
            '라텍스','메모리폼','스프링','독립스프링',
            '서랍형','리프트형','수납형',
          ];
          // 소재/재질 선택 시 색상 칩 show/hide
          const MATERIAL_LABELS = ['상판재질', '소재', '가죽종류', '프레임소재'];
          const MATERIAL_HIDE_COLOR = ['원목', '라텍스', '천연라텍스'];
          const MATERIAL_FILTER_COLOR = {
            'MDF':  ['화이트', '라이트그레이', '그레이', '블랙'],
            'PB':   ['화이트', '라이트그레이', '그레이', '블랙'],
            'LPM':  ['화이트', '라이트그레이', '그레이', '블랙'],
            '혼합': ['화이트', '라이트그레이', '그레이', '블랙'],
          };
          // 소재 선택 시 가격 행 동적 교체
          if (MATERIAL_LABELS.includes(label)) {
            const colorRow = board.querySelector('[data-color-row]');
            if (colorRow) {
              if (MATERIAL_HIDE_COLOR.includes(opt)) {
                colorRow.style.display = 'none';
                delete selections['색상'];
              } else {
                colorRow.style.display = '';
                // MDF/PB 등 단순 재질 → 기본 색상만 표시
                const filterColors = MATERIAL_FILTER_COLOR[opt];
                colorRow.querySelectorAll('[data-chip-name]').forEach(w => {
                  w.style.display = filterColors
                    ? (filterColors.includes(w.dataset.chipName) ? '' : 'none')
                    : '';
                });
                if (filterColors && selections['색상'] && !filterColors.includes(selections['색상'])) {
                  delete selections['색상'];
                }
              }
            }
          }

          // 이율배반 자동 비활성화!
          const CONFLICTS = {
            '전동': ['서랍형', '서랍'],
            '접이식': ['서랍형', '수납형'],
            '리클라이너': ['코너형', '모듈형'],
          };
          if (CONFLICTS[opt]) {
            // 현재 board에서 충돌 버튼 찾아서 비활성화
            board.querySelectorAll('.opt-btn').forEach(b => {
              if (CONFLICTS[opt].includes(b.textContent.trim())) {
                b.classList.remove('selected');
                b.style.opacity = '0.3';
                b.style.pointerEvents = 'none';
                b.title = `${opt} 선택 시 사용 불가`;
                // selections에서도 제거
                Object.keys(selections).forEach(k => {
                  if (CONFLICTS[opt].includes(selections[k])) {
                    delete selections[k];
                  }
                });
              }
            });
          }
          // 이율배반 해제 (전동 → 수동으로 변경 시)
          const CONFLICT_KEYS = Object.keys(CONFLICTS);
          if (!CONFLICT_KEYS.includes(opt)) {
            // 같은 그룹에서 다른 것 선택 → 제한 해제
            board.querySelectorAll('.opt-btn').forEach(b => {
              if (b.style.pointerEvents === 'none') {
                b.style.opacity = '';
                b.style.pointerEvents = '';
                b.title = '';
              }
            });
          }
        };
        opts.appendChild(btn);
      });
      row.appendChild(opts);
      pendingRows.push(row); // ★
    }
    i++;
  }

  const confirmBtn = document.createElement('button');
  confirmBtn.className = 'board-confirm';
  confirmBtn.textContent = '선택 완료 →';
  confirmBtn.onclick = () => {
    const parts = [];
    Object.entries(selections).forEach(([k, v]) => { if (v) parts.push(`${k}:${v}`); });
    const directText = directInput ? directInput.value.trim() : '';
    if (directText) parts.push(`직접입력:${directText}`);
    if (parts.length === 0) { alert('조건을 하나 이상 선택해주세요'); return; }
    if (directText) {
      send(parts.join(' '));
    } else {
      sendSilent(parts.join(' '));
    }
  };
  board.appendChild(confirmBtn);
  mi.appendChild(av); mi.appendChild(board);
  wrap.appendChild(mi);
  chat.appendChild(wrap);
  scroll();

  // ★ 섹션별 순차 등장! 텍스트 스르륵!
  confirmBtn.style.opacity = '0';
  pendingRows.forEach((row, idx) => {
    row.style.opacity = '0';
    row.style.transform = 'translateY(8px)';
    setTimeout(() => {
      board.insertBefore(row, confirmBtn);
      requestAnimationFrame(() => {
        row.style.transition = 'opacity 0.25s ease, transform 0.25s ease';
        row.style.opacity = '1';
        row.style.transform = 'translateY(0)';
        scroll();
      });
    }, idx * 150);
  });

  // 확인버튼은 마지막에!
  setTimeout(() => {
    confirmBtn.style.transition = 'opacity 0.25s ease';
    confirmBtn.style.opacity = '1';
    scroll();
  }, pendingRows.length * 150 + 100);
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
  btns.style.cssText = 'display:flex; flex-direction:column; gap:8px;';
  const yes = document.createElement('button');
  yes.className = 'confirm-btn btn-yes';
  yes.textContent = '✅ 네, 찾아주세요!';
  yes.onclick = () => startRecommendStream();
  const img = document.createElement('button');
  img.className = 'confirm-btn btn-add';
  img.textContent = '📸 이미지로 함께 찾기';
  img.style.cssText = 'margin-top:8px;';
  img.onclick = async () => {
    addTyping();
    try {
      const startRes = await fetch('/desire_start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          product: session?.raw_product || session?.product_name || '소파',
          session: session
        })
      });
      const startData = await startRes.json();

      // ★ 이미지 부족 → 욕망보드 스킵! 바로 추천으로!
      if (startData.status === 'skip') {
        document.getElementById('typing')?.remove();
        addAiMsg(startData.message || '이 조건은 이미지가 부족해서 바로 추천해드릴게요! 🛋️');
        session.stage = 'recommendation';
        setTimeout(() => startRecommendStream(), 500);
        return;
      }

      // 캐시 히트 → 즉시 표시!
      if (startData.status === 'done' && startData.images?.length > 0) {
        document.getElementById('typing')?.remove();
        // stage 업데이트!
        if (startData.set_stage) session.stage = startData.set_stage;
        try {
          renderDesireBoard('DESIRE_BOARD:' + JSON.stringify(startData.images));
          scroll();
        } catch(e) { addAiMsg('이미지 표시 오류: ' + e.message); }
        return;
      }

      // 캐시 없음 → 폴링
      const job_id = startData.job_id;
      if (!job_id) {
        document.getElementById('typing')?.remove();
        addAiMsg('이미지를 불러오는 중 문제가 생겼어요. 다시 시도해주세요 😊');
        return;
      }

      const poll = async () => {
        try {
          const res = await fetch(`/desire_poll/${job_id}`);
          if (res.status === 404) {
            // 아직 job 준비 안됐을 수 있음 → 2번 더 재시도
            if (!poll._retries) poll._retries = 0;
            poll._retries++;
            if (poll._retries <= 3) {
              setTimeout(poll, 1500);
            } else {
              document.getElementById('typing')?.remove();
              addAiMsg('이미지를 불러오는 중 문제가 생겼어요. 다시 시도해주세요 😊');
            }
            return;
          }
          const data = await res.json();
          if (data.status === 'done') {
            document.getElementById('typing')?.remove();
            if (data.images && data.images.length > 0) {
              try {
                renderDesireBoard('DESIRE_BOARD:' + JSON.stringify(data.images));
                scroll();
              } catch(e) { addAiMsg('이미지 표시 오류: ' + e.message); }
            } else {
              addAiMsg('이미지를 불러오는 중 문제가 생겼어요. 다시 시도해주세요 😊');
            }
          } else if (data.status === 'pending') {
            setTimeout(poll, 1000);
          } else {
            document.getElementById('typing')?.remove();
            addAiMsg('이미지를 불러오는 중 문제가 생겼어요. 다시 시도해주세요 😊');
          }
        } catch(e) {
          document.getElementById('typing')?.remove();
          addAiMsg('연결 오류가 발생했어요. 다시 시도해주세요.');
        }
      };
      setTimeout(poll, 1000);
    } catch(e) {
      document.getElementById('typing')?.remove();
      addAiMsg('연결 오류가 발생했어요. 다시 시도해주세요.');
    }
  };
  btns.appendChild(yes); btns.appendChild(img);
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
  const aiRaw = parts[0].trim();
  const boardText = parts[1] ? parts[1].trim() : '';

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
      label.textContent = '검색 조건에 추가할까요?';
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

function renderBrandProducts(data) {
  const wrap = document.createElement('div');
  wrap.className = 'msg-wrap';
  const mi = document.createElement('div');
  mi.className = 'msg-inner';
  const av = document.createElement('div');
  av.className = 'av av-ai'; av.textContent = '🛍️';

  // bubble 클래스 없이 완전 커스텀 컨테이너
  const container = document.createElement('div');
  container.style.cssText = 'width:100%;';

  // 헤더
  const header = document.createElement('div');
  header.style.cssText = 'padding:0 0 12px 14px;';
  const label = document.createElement('div');
  label.style.cssText = 'font-size:11px; color:var(--color-text-tertiary); margin-bottom:2px;';
  label.textContent = '브랜드 보드';
  const title = document.createElement('div');
  title.style.cssText = 'font-size:14px; color:var(--color-text-primary);';
  title.textContent = data.text || (data.brand + ' ' + data.category + ' 제품이에요 😊');
  header.appendChild(label); header.appendChild(title);
  container.appendChild(header);

  // 리스트
  const list = document.createElement('div');
  list.style.cssText = 'background:#fefefd; border-radius:12px; overflow:hidden; border:0.5px solid rgba(0,0,0,0.1);';

  (data.products || []).forEach((prod, idx) => {
    if (idx > 0) {
      const sep = document.createElement('div');
      sep.style.cssText = 'margin:0 14px; height:0.5px; background:rgba(0,0,0,0.08);';
      list.appendChild(sep);
    }

    const row = document.createElement('div');
    row.style.cssText = 'display:flex; align-items:center; gap:14px; padding:12px 14px; cursor:pointer; background:#fefefd;';
    row.onmouseenter = () => { row.style.background = 'rgba(194,176,153,0.06)'; arrowBtn.style.background = '#c2b099'; arrowBtn.style.borderColor = '#c2b099'; arrowSvg.style.stroke = 'white'; };
    row.onmouseleave = () => { row.style.background = '#fefefd'; arrowBtn.style.background = 'transparent'; arrowBtn.style.borderColor = 'rgba(0,0,0,0.15)'; arrowSvg.style.stroke = 'rgba(0,0,0,0.4)'; };

    // 썸네일
    const thumb = document.createElement('div');
    thumb.style.cssText = 'width:64px; height:64px; border-radius:8px; background:#f5f3ef; flex-shrink:0; overflow:hidden;';
    if (prod.image) {
      const img = document.createElement('img');
      img.src = prod.image;
      img.style.cssText = 'width:100%; height:100%; object-fit:cover;';
      img.onerror = () => { img.style.display='none'; };
      thumb.appendChild(img);
    }
    row.appendChild(thumb);

    // 정보
    const info = document.createElement('div');
    info.style.cssText = 'flex:1; min-width:0;';
    const name = document.createElement('div');
    name.style.cssText = 'font-size:13px; font-weight:500; color:#1a1a1a; line-height:1.4;';
    name.textContent = prod.full_name || prod.name;
    const price = document.createElement('div');
    price.style.cssText = 'font-size:12px; color:#8a6f5e; margin-top:3px;';
    price.textContent = prod.price ? parseInt(prod.price).toLocaleString() + '원' : '';
    info.appendChild(name);
    if (prod.price) info.appendChild(price);
    row.appendChild(info);

    // 동그라미 화살표
    const arrowBtn = document.createElement('div');
    arrowBtn.style.cssText = 'width:26px; height:26px; border-radius:50%; border:0.5px solid rgba(0,0,0,0.15); display:flex; align-items:center; justify-content:center; flex-shrink:0; background:transparent; transition:background 0.15s, border-color 0.15s;';
    const arrowSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    arrowSvg.setAttribute('width', '12'); arrowSvg.setAttribute('height', '12');
    arrowSvg.setAttribute('viewBox', '0 0 24 24'); arrowSvg.setAttribute('fill', 'none');
    arrowSvg.style.cssText = 'stroke:rgba(0,0,0,0.4); stroke-width:2; transition:stroke 0.15s;';
    const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    poly.setAttribute('points', '9 18 15 12 9 6');
    arrowSvg.appendChild(poly);
    arrowBtn.appendChild(arrowSvg);
    row.appendChild(arrowBtn);

    // 클릭
    row.onclick = async () => {
      if (!session) session = {};
      session.raw_product = prod.full_name || prod.name;
      session.selections = '';
      session.single_product = true;
      session.single_brand = data.brand;
      session.stage = 'direct_recommend';
      await send('DIRECT_RECOMMEND:' + (prod.full_name || prod.name));
    };

    list.appendChild(row);
  });

  container.appendChild(list);
  mi.appendChild(av); mi.appendChild(container);
  wrap.appendChild(mi);
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
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
  title.textContent = '📸 인스타그램 실제 이미지';
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

    // 클릭하면 크게 보기
    imgWrap.onclick = () => {
      const overlay = document.createElement('div');
      overlay.style.cssText = `
        position:fixed; top:0; left:0; right:0; bottom:0;
        background:rgba(0,0,0,0.85); z-index:9999;
        display:flex; align-items:center; justify-content:center;
        padding:20px;
      `;
      overlay.onclick = () => overlay.remove();

      const bigImg = document.createElement('img');
      bigImg.src = img.url;
      bigImg.style.cssText = 'max-width:100%; max-height:80vh; border-radius:12px;';

      overlay.appendChild(bigImg);
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

// ── VS 카드 렌더링 ──
// ★ 비교해드려요 섹션 공통 함수
function _appendCompareSection(container, currentName, allProducts) {
  const otherProducts = (allProducts || [])
    .filter(op => op.name && op.name !== currentName)
    .slice(0, 3);

  const wrap = document.createElement('div');
  wrap.style.cssText = 'padding:10px 14px 14px; border-top:0.5px solid var(--color-border-tertiary);';

  const title = document.createElement('div');
  title.style.cssText = 'font-size:13px; font-weight:500; color:var(--color-text-secondary); margin-bottom:8px;';
  title.textContent = '비교해드려요';
  wrap.appendChild(title);

  if (otherProducts.length > 0) {
    const btnRow = document.createElement('div');
    btnRow.style.cssText = 'display:flex; flex-wrap:wrap; gap:6px; margin-bottom:8px;';
    otherProducts.forEach(op => {
      const shortName = op.name.replace(/\[.*?\]/g, '').trim().split(' ').slice(0, 3).join(' ');
      const btn = document.createElement('button');
      btn.textContent = shortName;
      btn.style.cssText = 'padding:6px 12px; border-radius:20px; border:1px solid var(--color-border-secondary); background:var(--color-background-secondary); font-size:12px; color:var(--color-text-secondary); cursor:pointer; white-space:nowrap;';
      btn.onclick = () => _startCompare(currentName, op.name, wrap);
      btnRow.appendChild(btn);
    });
    wrap.appendChild(btnRow);
  }

  const inputRow = document.createElement('div');
  inputRow.style.cssText = 'display:flex; gap:6px;';
  const inp = document.createElement('input');
  inp.placeholder = '비교할 제품 직접 입력...';
  inp.style.cssText = 'flex:1; padding:8px 12px; border-radius:20px; border:1px solid var(--color-border-secondary); font-size:12px; color:var(--color-text-primary); background:var(--color-background-primary); outline:none;';
  const cmpBtn = document.createElement('button');
  cmpBtn.textContent = '비교';
  cmpBtn.style.cssText = 'padding:8px 14px; border-radius:20px; background:#c2b099; border:none; color:white; font-size:12px; font-weight:500; cursor:pointer; white-space:nowrap;';
  cmpBtn.onclick = () => { const v = inp.value.trim(); if (v) _startCompare(currentName, v, wrap); };
  inp.onkeydown = e => { if (e.key === 'Enter') cmpBtn.click(); };
  inputRow.appendChild(inp);
  inputRow.appendChild(cmpBtn);
  wrap.appendChild(inputRow);
  container.appendChild(wrap);
}

// ★ 비교 실행 함수
function _startCompare(productA, productB, wrap) {
  wrap.style.opacity = '0.5';
  wrap.style.pointerEvents = 'none';
  const loading = document.createElement('div');
  loading.style.cssText = 'font-size:12px; color:var(--color-text-tertiary); margin-top:6px;';
  loading.textContent = `${productB}와 비교 중...`;
  wrap.appendChild(loading);

  fetch('/compare_product', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ product_a: productA, product_b: productB })
  })
  .then(r => r.json())
  .then(d => {
    wrap.style.opacity = '1';
    wrap.style.pointerEvents = '';
    loading.remove();
    if (d.result?.startsWith('VS_CARDS:')) {
      renderVsCards(d.result);
      smartScroll();
    } else {
      loading.textContent = '비교 정보를 찾지 못했어요 😅';
      wrap.appendChild(loading);
    }
  })
  .catch(() => {
    wrap.style.opacity = '1';
    wrap.style.pointerEvents = '';
    loading.textContent = '다시 시도해주세요.';
    wrap.appendChild(loading);
  });
}

function renderVsCards(text) {
  const jsonStr = text.replace('VS_CARDS:', '').trim();
  let data;
  try { data = JSON.parse(jsonStr); } catch(e) {
    console.error('VS_CARDS 파싱 오류:', e);
    return;
  }

  const wrap = document.createElement('div');
  wrap.className = 'msg-wrap';
  const mi = document.createElement('div');
  mi.className = 'msg-inner full';
  const av = document.createElement('div');
  av.className = 'av av-ai'; av.textContent = '🛍️';

  const container = document.createElement('div');
  container.style.cssText = 'width:100%; max-width:420px; background:white; border-radius:20px; padding:20px;';

  // 제목
  const title = document.createElement('div');
  title.style.cssText = 'font-size:15px; font-weight:600; color:#1a1a1a; margin-bottom:4px;';
  title.textContent = '소파 선택이 고민되시는군요!';
  container.appendChild(title);

  const sub = document.createElement('div');
  sub.style.cssText = 'font-size:13px; color:#888; margin-bottom:16px;';
  sub.textContent = '상황별로 비교해보고 직접 선택해보세요 👇';
  container.appendChild(sub);

  // VS 제품 헤더
  const vsHeader = document.createElement('div');
  vsHeader.style.cssText = 'display:grid; grid-template-columns:1fr auto 1fr; gap:8px; align-items:center; margin-bottom:14px;';

  const labelA = document.createElement('div');
  labelA.style.cssText = 'background:#f0f0ee; border-radius:10px; padding:10px 12px; text-align:center; font-size:14px; font-weight:600; color:#333;';
  labelA.textContent = data.product_a;

  const vsBadge = document.createElement('div');
  vsBadge.style.cssText = 'font-size:12px; font-weight:700; color:#aaa; text-align:center;';
  vsBadge.textContent = 'VS';

  const labelB = document.createElement('div');
  labelB.style.cssText = 'background:#f0f0ee; border-radius:10px; padding:10px 12px; text-align:center; font-size:14px; font-weight:600; color:#333;';
  labelB.textContent = data.product_b;

  vsHeader.appendChild(labelA);
  vsHeader.appendChild(vsBadge);
  vsHeader.appendChild(labelB);
  container.appendChild(vsHeader);

  // 상황별 카드 리스트
  const list = document.createElement('div');
  list.style.cssText = 'display:flex; flex-direction:column; gap:8px; margin-bottom:16px;';

  data.cards.forEach(card => {
    const cardEl = document.createElement('div');
    cardEl.style.cssText = 'border:1.5px solid #eee; border-radius:12px; overflow:hidden; transition:border-color 0.2s;';

    const header = document.createElement('div');
    header.style.cssText = 'display:flex; align-items:center; justify-content:space-between; padding:14px 16px; cursor:pointer; background:white;';

    const left = document.createElement('div');
    left.style.cssText = 'display:flex; align-items:center; gap:10px;';

    const emoji = document.createElement('span');
    emoji.style.cssText = 'font-size:20px; width:32px; text-align:center;';
    emoji.textContent = card.emoji;

    const name = document.createElement('span');
    name.style.cssText = 'font-size:14px; font-weight:600; color:#333;';
    name.textContent = card.title;

    const arrow = document.createElement('span');
    arrow.style.cssText = 'font-size:12px; color:#bbb; transition:transform 0.3s;';
    arrow.textContent = '▼';

    left.appendChild(emoji);
    left.appendChild(name);
    header.appendChild(left);
    header.appendChild(arrow);

    const body = document.createElement('div');
    body.style.cssText = 'display:none; padding:0 16px 16px; background:#fafaf8;';

    const cols = document.createElement('div');
    cols.style.cssText = 'display:grid; grid-template-columns:1fr 1fr; gap:10px;';

    [{ label: data.product_a, items: card.a }, { label: data.product_b, items: card.b }].forEach(col => {
      const colEl = document.createElement('div');
      colEl.style.cssText = 'background:white; border-radius:10px; padding:12px;';

      const colTitle = document.createElement('div');
      colTitle.style.cssText = 'font-size:12px; font-weight:700; color:#888; margin-bottom:8px; text-align:center;';
      colTitle.textContent = col.label;
      colEl.appendChild(colTitle);

      col.items.forEach(item => {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex; align-items:flex-start; gap:6px; font-size:12px; color:#444; line-height:1.4; margin-bottom:6px;';
        const icon = document.createElement('span');
        icon.style.cssText = `font-size:11px; margin-top:1px; flex-shrink:0; color:${item.good ? '#22c55e' : '#ef4444'};`;
        icon.textContent = item.good ? '✓' : '✗';
        const txt = document.createElement('span');
        txt.textContent = item.text;
        row.appendChild(icon);
        row.appendChild(txt);
        colEl.appendChild(row);
      });

      cols.appendChild(colEl);
    });

    body.appendChild(cols);

    header.onclick = () => {
      const isOpen = body.style.display !== 'none';
      body.style.display = isOpen ? 'none' : 'block';
      arrow.style.transform = isOpen ? '' : 'rotate(180deg)';
      arrow.style.color = isOpen ? '#bbb' : '#ff6b35';
      cardEl.style.borderColor = isOpen ? '#eee' : '#ff6b35';
    };

    cardEl.appendChild(header);
    cardEl.appendChild(body);
    list.appendChild(cardEl);
  });

  container.appendChild(list);

  // 선택 버튼
  const btnRow = document.createElement('div');
  btnRow.style.cssText = 'display:grid; grid-template-columns:1fr 1fr; gap:10px;';

  [data.product_a, data.product_b].forEach(prod => {
    const btn = document.createElement('div');
    btn.style.cssText = 'padding:14px; border:2px solid #eee; border-radius:12px; background:white; font-size:14px; font-weight:600; color:#333; cursor:pointer; text-align:center; transition:all 0.2s;';
    btn.textContent = `🛋️ ${prod} 선택`;
    btn.onmouseover = () => { btn.style.borderColor = '#ff6b35'; btn.style.color = '#ff6b35'; btn.style.background = '#fff3ef'; };
    btn.onmouseout = () => { btn.style.borderColor = '#eee'; btn.style.color = '#333'; btn.style.background = 'white'; };
    btn.onclick = () => sendSilent(`VS_SELECT:${prod}`);
    btnRow.appendChild(btn);
  });

  container.appendChild(btnRow);

  const tip = document.createElement('div');
  tip.style.cssText = 'text-align:center; font-size:12px; color:#aaa; margin-top:12px;';
  tip.textContent = '상황카드 눌러보고 직접 판단해보세요!';
  container.appendChild(tip);

  mi.appendChild(av);
  mi.appendChild(container);
  wrap.appendChild(mi);
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
}

// ── 픽코 PICK 결과 렌더링 ──
function renderPickoResult(text, { streamMode = false } = {}) {
  const jsonStr = text.replace('PICKO_RESULT:', '').trim();
  let data = {};
  try { data = JSON.parse(jsonStr); } catch(e) { addAiMsg(jsonStr); return; }

  const products = data.products || [];
  const notice = data.notice || '';

  const wrap = document.createElement('div');
  wrap.className = 'msg-wrap';
  const mi = document.createElement('div');
  mi.className = 'msg-inner full';
  const av = document.createElement('div');
  av.className = 'av av-ai'; av.textContent = '🛍️';
  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-ai';
  bubble.style.cssText = 'padding:0; width:100%; max-width:100%; overflow:hidden;';

  if (notice) {
    const noticeEl = document.createElement('div');
    noticeEl.style.cssText = 'font-size:13px; color:var(--color-text-secondary); padding:10px 12px; background:var(--color-background-secondary); border-radius:0 8px 8px 0; margin:12px 12px 4px; line-height:1.6; border-left:2px solid var(--color-border-secondary);';
    noticeEl.textContent = notice;
    bubble.appendChild(noticeEl);
  }

  const BADGE_STYLES = [
    'background:#FAEEDA; color:#854F0B;',
    'background:#D3D1C7; color:#444441;',
    'background:#F5C4B3; color:#993C1D;'
  ];

  const pendingCards = []; // ★ 순차 등장용!

  products.forEach((p, idx) => {
    const sep = idx > 0 ? (() => {
      const s = document.createElement('div');
      s.style.cssText = 'height:8px; background:var(--color-background-secondary);';
      return s;
    })() : null;

    const card = document.createElement('div');
    card.style.cssText = 'background:#fefefd; overflow:hidden;';

    // 순위 헤더
    const rankHeader = document.createElement('div');
    rankHeader.style.cssText = 'display:flex; align-items:center; justify-content:space-between; padding:10px 14px;';
    const rankTitle = document.createElement('div');
    rankTitle.style.cssText = 'font-size:13px; font-weight:500; color:var(--color-text-primary); display:flex; align-items:center; gap:5px;';
    rankTitle.innerHTML = `🏆 <span>픽코3 — ${p.rank ? p.rank+'순위' : (['1순위','2순위','3순위'][idx] || (idx+1)+'순위')} 추천</span>`;

    // ★ 리뷰 출신 뱃지 (블로그 검증 제품 표시!)
    console.log(`[뱃지확인] ${p.name?.slice(0,20)} from_review=${p.from_review} original=${p.original}`);
    if (p.original) {
      const reviewBadge = document.createElement('span');
      reviewBadge.style.cssText = 'font-size:10px; padding:2px 7px; border-radius:10px; background:#ffebee; color:#c62828; font-weight:500; white-space:nowrap;';
      reviewBadge.textContent = '🔴 오리지널';
      rankTitle.appendChild(reviewBadge);
    } else if (p.direct_blog_verified) {
      const reviewBadge = document.createElement('span');
      reviewBadge.style.cssText = 'font-size:10px; padding:2px 7px; border-radius:10px; background:#e3f2fd; color:#1565c0; font-weight:500; white-space:nowrap;';
      reviewBadge.textContent = '🔵 리핏';
      rankTitle.appendChild(reviewBadge);
    } else if (p.from_review) {
      const reviewBadge = document.createElement('span');
      reviewBadge.style.cssText = 'font-size:10px; padding:2px 7px; border-radius:10px; background:#fff3e0; color:#e65100; font-weight:500; white-space:nowrap;';
      reviewBadge.textContent = '📝 블로그 검증';
      rankTitle.appendChild(reviewBadge);
    }

    rankHeader.appendChild(rankTitle);
    card.appendChild(rankHeader);

    const imageUrl = p.image_url || p.thumbnail || (p.naver_products && p.naver_products[0]?.url) || '';
    const detailUrl = p.product_url || p.detail_url || p.naver_url || '#';
    const desireImgs = window._desireSelectedImages || [];
    const isDesireCard = desireImgs.length > 0;

    const divider = () => { const d = document.createElement('div'); d.style.cssText = 'height:1px; background:#e0ddd8;'; return d; };

    // ── 카드1 (욕망보드 후): 이미지 두 칸 ──
    if (isDesireCard) {
      const imgGrid = document.createElement('div');
      imgGrid.style.cssText = 'display:grid; grid-template-columns:1fr 1fr;';
      function mkBox(url, label, borderRight) {
        const box = document.createElement('div');
        box.style.cssText = 'aspect-ratio:1; background:var(--color-background-secondary); position:relative; display:flex; align-items:center; justify-content:center; overflow:hidden;' + (borderRight ? 'border-right:0.5px solid var(--color-border-tertiary);' : '');
        const em = document.createElement('div');
        em.style.cssText = 'font-size:36px;';
        em.textContent = '🛋️';
        box.appendChild(em);
        if (url) {
          const im = document.createElement('img');
          im.src = url;
          im.style.cssText = 'width:100%; height:100%; object-fit:cover; position:absolute; top:0; left:0;';
          im.onerror = () => { im.style.display='none'; };
          box.appendChild(im);
        }
        const lbl = document.createElement('div');
        lbl.style.cssText = 'position:absolute; bottom:0; left:0; right:0; background:rgba(0,0,0,0.45); color:white; font-size:10px; padding:4px 8px; z-index:1;';
        lbl.textContent = label;
        box.appendChild(lbl);
        return box;
      }
      imgGrid.appendChild(mkBox(desireImgs[0]?.url || '', '내가 고른 스타일', true));
      imgGrid.appendChild(mkBox(imageUrl, '추천 제품', false));
      card.appendChild(imgGrid);
    } else {
      // ── 카드2 (욕망보드 없이): 썸네일 144px + 제품명 하단정렬 ──
      const top2 = document.createElement('div');
      top2.style.cssText = 'display:flex; gap:14px; padding:14px; align-items:flex-end; border-bottom:0.5px solid var(--color-border-tertiary);';
      const thumb2 = document.createElement('div');
      thumb2.style.cssText = 'width:144px; height:144px; border-radius:8px; background:var(--color-background-secondary); flex-shrink:0; position:relative; display:flex; align-items:center; justify-content:center; overflow:hidden; border:0.5px solid var(--color-border-tertiary); cursor:pointer;';
      const thumb2em = document.createElement('div');
      thumb2em.style.cssText = 'font-size:36px;';
      thumb2em.textContent = '🛍️';
      thumb2.appendChild(thumb2em);
      if (imageUrl) {
        const img2 = document.createElement('img');
        img2.src = imageUrl;
        img2.style.cssText = 'width:100%; height:100%; object-fit:cover; position:absolute; top:0; left:0;';
        img2.onerror = () => { img2.style.display='none'; };
        thumb2.appendChild(img2);
      }
      thumb2.onclick = () => { if (detailUrl !== '#') window.open(detailUrl, '_blank'); };
      const info2 = document.createElement('div');
      info2.style.cssText = 'flex:1; min-width:0;';
      const name2 = document.createElement('div');
      name2.style.cssText = 'font-size:15px; font-weight:500; color:var(--color-text-primary); margin-bottom:4px; line-height:1.4;';
      name2.textContent = p.name || '';
      const price2 = document.createElement('div');
      price2.style.cssText = 'font-size:14px; color:#8a6f5e; font-weight:500;';
      price2.textContent = p.price || '';
      info2.appendChild(name2);
      info2.appendChild(price2);
      top2.appendChild(thumb2);
      top2.appendChild(info2);
      card.appendChild(top2);
    }

    // ── 공통: 제품명 + 가격 + 픽코 평점 ──
    {
      card.appendChild(divider());
      const prodSec = document.createElement('div');
      prodSec.style.cssText = 'padding:10px 14px; background:var(--color-background-primary);';
      // 카드1만 제품명+가격 표시 (카드2는 썸네일 섹션에 이미 있음)
      if (isDesireCard) {
        const pname = document.createElement('div');
        pname.style.cssText = 'font-size:14px; font-weight:500; color:var(--color-text-primary); margin-bottom:2px;';
        pname.textContent = p.name || '';
        const pprice = document.createElement('div');
        pprice.style.cssText = 'font-size:13px; color:var(--color-text-secondary); margin-bottom:8px;';
        pprice.textContent = p.price || '';
        prodSec.appendChild(pname);
        prodSec.appendChild(pprice);
      }
      // ── 시장 데이터가 말해요 (trust) ──
      const trustBadge = p.trust_badge;
      const trustData  = p.trust;
      if (trustBadge && trustData) {
        const TRUST_STYLE = {
          '스테디셀러': { bg: '#fef3c7', color: '#92400e', border: '#fcd34d' },
          '숨은 명품':  { bg: '#f0fdf4', color: '#14532d', border: '#86efac' },
          '검증된 제품':{ bg: '#eff6ff', color: '#1e3a5f', border: '#93c5fd' },
          '신제품':     { bg: '#eff6ff', color: '#1e40af', border: '#93c5fd' },
          '행사 주의':  { bg: '#fff7ed', color: '#9a3412', border: '#fdba74' },
          '꾸준한 인기':{ bg: '#f5f3ff', color: '#4c1d95', border: '#c4b5fd' },
          '재구매 있음':{ bg: '#fdf4ff', color: '#701a75', border: '#e879f9' },
          '오래된 제품':{ bg: '#f9fafb', color: '#374151', border: '#d1d5db' },
        };
        const TRUST_STORY = {
          '스테디셀러': `${trustData.months}개월간 꾸준히 팔렸어요. 재구매 언급 ${trustData.rebuy_count}건 확인했어요.`,
          '숨은 명품':  `후기 ${trustData.total_posts}건으로 많지 않아요. 그 중 써본 사람 반응 ${trustData.q_count}건 나왔어요.`,
          '검증된 제품':`${trustData.months}개월간 후기 ${trustData.total_posts}건 축적됐어요.`,
          '신제품':     `출시 ${trustData.months}개월 됐어요. 장기 사용 데이터가 아직 없어요.`,
          '행사 주의':  `최근 3개월에 후기가 집중됐어요. 이벤트성일 수 있어요.`,
          '꾸준한 인기':`${trustData.months}개월간 후기가 꾸준히 쌓였어요.`,
          '재구매 있음':`재구매 언급 ${trustData.rebuy_count}건 확인했어요. 써본 사람이 또 사는 제품이에요.`,
          '오래된 제품':`${trustData.months}개월 전부터 팔린 제품이에요. 후기 ${trustData.total_posts}건 확인했어요.`,
        };
        const ts = TRUST_STYLE[trustBadge] || { bg: '#f9fafb', color: '#374151', border: '#d1d5db' };
        const story = TRUST_STORY[trustBadge] || '';
        // ★ padding 좌우 0 (prodSec가 이미 14px), 픽코 평점과 같은 라인
        const trustSec = document.createElement('div');
        trustSec.style.cssText = 'padding:8px 0 6px; border-top:0.5px solid var(--color-border-tertiary);';
        // ★ 폰트 픽코 평점과 동일 (14px, font-weight:500)
        const trustLabel = document.createElement('div');
        trustLabel.style.cssText = 'font-size:14px; font-weight:500; color:var(--color-text-secondary); margin-bottom:6px;';
        trustLabel.textContent = '시장 데이터가 말해요';
        // ★ 뱃지 + 스토리 한 줄 flex
        const trustRow = document.createElement('div');
        trustRow.style.cssText = 'display:flex; align-items:center; gap:8px; flex-wrap:wrap;';
        const trustBadgeEl = document.createElement('span');
        trustBadgeEl.style.cssText = `flex-shrink:0; font-size:11px; font-weight:600; padding:2px 9px; border-radius:20px; border:1px solid ${ts.border}; background:${ts.bg}; color:${ts.color};`;
        trustBadgeEl.textContent = trustBadge;
        const trustStoryEl = document.createElement('span');
        trustStoryEl.style.cssText = 'font-size:12px; color:var(--color-text-primary); line-height:1.6;';
        trustStoryEl.textContent = story;
        trustRow.appendChild(trustBadgeEl);
        trustRow.appendChild(trustStoryEl);
        trustSec.appendChild(trustLabel);
        trustSec.appendChild(trustRow);
        prodSec.appendChild(trustSec);
      }

      card.appendChild(prodSec);
    }





    // ── 공통: 진짜 사용자 목소리 (블로그 후기 기반) ──
    const userVoices = p.user_voices || data.user_voices || [];
    const pickoSummary = ''; // 총평 제거됨
    if (userVoices.length > 0) {
      card.appendChild(divider());
      const sec = document.createElement('div');
      sec.style.cssText = 'padding:12px 14px; background:var(--color-background-primary);';
      const title = document.createElement('div');
      title.style.cssText = 'font-size:14px; font-weight:500; color:var(--color-text-secondary); margin-bottom:10px;';
      title.textContent = '진짜 사용자 목소리';
      sec.appendChild(title);
      userVoices.forEach(r => {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex; gap:10px; align-items:flex-start; margin-bottom:10px;';
        const dot = document.createElement('div');
        const isPos = r.type === 'pos';
        dot.style.cssText = `width:18px; height:18px; border-radius:50%; flex-shrink:0; margin-top:1px; display:flex; align-items:center; justify-content:center; background:${isPos?'#e8f5e9':'#fdecea'};`;
        dot.innerHTML = `<span style="font-size:10px;color:${isPos?'#4caf50':'#e53935'};font-weight:500;">${isPos?'+':'−'}</span>`;
        const txt = document.createElement('div');
        const quote = document.createElement('div');
        quote.style.cssText = 'font-size:12px; color:var(--color-text-primary); line-height:1.6;';
        const rawText = '"' + (r.text||'') + '"';
        const keywords = r.keywords || [];
        if (keywords.length > 0) {
          let highlighted = rawText;
          keywords.forEach(kw => {
            if (!kw) return;
            const escaped = kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            highlighted = highlighted.replace(
              new RegExp(escaped, 'g'),
              `<span style="text-decoration:underline;text-underline-offset:2px;">${kw}</span>`
            );
          });
          quote.innerHTML = highlighted;
        } else {
          quote.textContent = rawText;
        }
        const src = document.createElement('div');
        src.style.cssText = 'font-size:10px; color:var(--color-text-tertiary); margin-top:3px;';
        src.textContent = (r.source == null) ? '네이버 블로그' : r.source;
        txt.appendChild(quote); txt.appendChild(src);
        row.appendChild(dot); row.appendChild(txt);
        sec.appendChild(row);
      });
      card.appendChild(sec);
    }

    // ── 공통: 이런 점이 마음에 드실 거예요 제거됨 ──
    // ── 공통: 좋다는 말 / 아쉽다는 말 / 픽코 한마디 + 금광 ──
    const pros = p.pros || [];
    const cons = p.cons || [];
    const oneLine = p.picko_one_line || '';
    const priceInfo = p.price_info || {};
    const situations = p.situations || [];
    const longTerm = p.long_term || '';
    if (pros.length || cons.length || oneLine || Object.keys(priceInfo).length || situations.length || longTerm) {
      const pcSec = document.createElement('div');
      pcSec.style.cssText = 'padding:10px 14px; border-top:0.5px solid var(--color-border-tertiary);';

      // 💰 가격 정보
      if (priceInfo.range || priceInfo.gonggu) {
        const pt = document.createElement('div');
        pt.style.cssText = 'font-size:13px; font-weight:500; color:var(--color-text-secondary); margin-bottom:6px;';
        pt.textContent = '💰 가격 정보';
        pcSec.appendChild(pt);
        if (priceInfo.range) {
          const row = document.createElement('div');
          row.style.cssText = 'font-size:12px; color:var(--color-text-primary); padding:2px 0; line-height:1.7;';
          row.textContent = `실구매가 ${priceInfo.range}`;
          pcSec.appendChild(row);
        }
        if (priceInfo.gonggu) {
          const row = document.createElement('div');
          row.style.cssText = 'font-size:12px; color:#b45309; padding:2px 0; line-height:1.7; font-weight:500;';
          row.textContent = '⚡ 공구 진행된 적 있어요';
          pcSec.appendChild(row);
        }
      }

      if (pros.length > 0) {
        const pt = document.createElement('div');
        pt.style.cssText = 'font-size:13px; font-weight:500; color:var(--color-text-secondary); margin:10px 0 6px;';
        pt.textContent = '좋다는 말';
        pcSec.appendChild(pt);
        pros.forEach(pr => {
          const row = document.createElement('div');
          row.style.cssText = 'font-size:12px; color:var(--color-text-primary); padding:2px 0; line-height:1.7;';
          row.textContent = `✓ ${pr}`;
          pcSec.appendChild(row);
        });
      }
      if (cons.length > 0) {
        const ct = document.createElement('div');
        ct.style.cssText = 'font-size:13px; font-weight:500; color:var(--color-text-secondary); margin:10px 0 6px;';
        ct.textContent = '아쉽다는 말';
        pcSec.appendChild(ct);
        cons.forEach(cn => {
          const row = document.createElement('div');
          row.style.cssText = 'font-size:12px; color:var(--color-text-tertiary); padding:2px 0; line-height:1.7;';
          row.textContent = `△ ${cn}`;
          pcSec.appendChild(row);
        });
      }

      if (situations.length > 0) {
        const st = document.createElement('div');
        st.style.cssText = 'font-size:13px; font-weight:500; color:var(--color-text-secondary); margin:10px 0 6px;';
        st.textContent = '이런 분께 맞아요';
        pcSec.appendChild(st);
        situations.forEach(s => {
          const row = document.createElement('div');
          row.style.cssText = 'font-size:12px; color:var(--color-text-primary); padding:2px 0; line-height:1.7;';
          row.textContent = `→ ${s}`;
          pcSec.appendChild(row);
        });
      }

      if (longTerm) {
        const lt = document.createElement('div');
        lt.style.cssText = 'font-size:13px; font-weight:500; color:var(--color-text-secondary); margin:10px 0 6px;';
        lt.textContent = '오래 쓴 사람 말';
        pcSec.appendChild(lt);
        const row = document.createElement('div');
        row.style.cssText = 'font-size:12px; color:var(--color-text-primary); padding:2px 0; line-height:1.7;';
        row.textContent = `⏳ ${longTerm}`;
        pcSec.appendChild(row);
      }

      if (oneLine) {
        const ol = document.createElement('div');
        ol.style.cssText = 'margin-top:10px; padding:8px 12px; background:#f5f0eb; border-radius:10px; font-size:12px; font-weight:500; color:var(--color-text-primary);';
        ol.textContent = `💬 ${oneLine}`;
        pcSec.appendChild(ol);
      }
      card.appendChild(pcSec);
    }

    // ── 공통: 상세페이지 버튼 ──
    const detailWrap = document.createElement('div');
    detailWrap.style.cssText = 'padding:14px;';
    const detailBtn = document.createElement('a');
    detailBtn.href = detailUrl;
    detailBtn.target = '_blank';
    detailBtn.style.cssText = 'display:block; width:100%; text-align:center; padding:12px 0; background:#c2b099; border-radius:20px; font-size:13px; font-weight:500; color:white; text-decoration:none; cursor:pointer; box-sizing:border-box;';
    detailBtn.textContent = '상세페이지 보러가기';
    detailWrap.appendChild(detailBtn);
    card.appendChild(detailWrap);

    // ── 비교해드려요 ──
    _appendCompareSection(card, p.name || '', data.products || []);

    // ★ 카드 내부 요소 순차 등장 준비!
    const cardChildren = Array.from(card.children);
    card.innerHTML = ''; // 비우기!

    pendingCards.push({ card, sep, children: cardChildren });
  });

  // ── 더보기 버튼 ──
  const moreWrap = document.createElement('div');
  moreWrap.style.cssText = 'display:flex; flex-wrap:wrap; gap:8px; padding:12px; border-top:1px solid var(--border);';
  moreWrap.setAttribute('data-more-wrap', '1'); // ★ 찾기용 속성
  const GRADES = ['저가', '중가', '고가', '최고가'];
  const currentGrade = (data.grade || '');
  const moreCacheKey = data.more_cache_key || '';
  GRADES.forEach(grade => {
    const btn = document.createElement('button');
    btn.style.cssText = 'flex:1; min-width:80px; padding:9px 12px; border-radius:20px; font-size:12px; font-weight:500; cursor:pointer; border:1px solid var(--border); background:' + (grade === currentGrade ? 'var(--user-bubble)' : 'var(--surface)') + '; color:' + (grade === currentGrade ? 'white' : 'var(--text)') + ';';
    btn.textContent = grade === currentGrade ? `${grade} 더보기` : `${grade}로 보기`;
    btn.onclick = () => {
      btn.disabled = true;
      btn.textContent = '불러오는 중...';
      fetch('/more_recommendations', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({grade, cache_key: moreCacheKey})
      })
      .then(r => r.json())
      .then(data => {
        if (data.error || !data.products?.length) {
          btn.textContent = '더 이상 없어요';
          return;
        }
        renderMoreProducts(data.products, grade);
        btn.textContent = grade === currentGrade ? `${grade} 더보기` : `${grade}로 보기`;
        btn.disabled = false;
        if (data.remaining === 0) {
          btn.textContent = '✓ 다 봤어요';
          btn.disabled = true;
        }
      })
      .catch(() => { btn.textContent = '오류'; btn.disabled = false; });
    };
    moreWrap.appendChild(btn);
  });
  bubble.appendChild(moreWrap);
  moreWrap.style.opacity = '0'; // ★ 처음엔 숨김!

  mi.appendChild(av); mi.appendChild(bubble);
  wrap.appendChild(mi);
  chat.appendChild(wrap);

  // ★ 카드 순차 등장! 1순위 → 2순위 → 3순위!
  pendingCards.forEach(({ card, sep, children }, idx) => {
    setTimeout(() => {
      if (sep) {
        sep.style.opacity = '0';
        bubble.insertBefore(sep, moreWrap);
        requestAnimationFrame(() => {
          sep.style.transition = 'opacity 0.3s ease';
          sep.style.opacity = '1';
        });
      }
      card.style.cssText += '; opacity:1;';
      bubble.insertBefore(card, moreWrap);
      scroll();

      // ★ 카드 내부 요소 순차 등장! (100ms 간격)
      children.forEach((child, ci) => {
        setTimeout(() => {
          child.style.opacity = '0';
          child.style.transform = 'translateY(4px)';
          card.appendChild(child);
          requestAnimationFrame(() => {
            requestAnimationFrame(() => {
              child.style.transition = 'opacity 0.25s ease, transform 0.25s ease';
              child.style.opacity = '1';
              child.style.transform = 'translateY(0)';
              scroll();
            });
          });
        }, ci * 100);
      });

      // ★ 마지막 카드 등장 후 더보기 버튼!
      // streamMode면 더보기 버튼은 숨김 (3순위 완료 후 processCard에서 켬)
      if (idx === pendingCards.length - 1 && !streamMode) {
        setTimeout(() => {
          moreWrap.style.transition = 'opacity 0.3s ease';
          moreWrap.style.opacity = '1';
          scroll();
        }, children.length * 100 + 300);
      }
    }, streamMode ? 0 : idx * 1200); // ★ 스트리밍 모드: 즉시 / 일반: 1200ms 간격
  });

  scroll();
}

// ── 더보기 제품 카드 렌더링 (브랜드 보드 스타일) ──
function renderMoreProducts(products, grade) {
  const wrap = document.createElement('div');
  wrap.className = 'msg-wrap';
  const mi = document.createElement('div');
  mi.className = 'msg-inner';
  const av = document.createElement('div');
  av.className = 'av av-ai'; av.textContent = '🛍️';

  const container = document.createElement('div');
  container.style.cssText = 'width:100%;';

  // 헤더
  const header = document.createElement('div');
  header.style.cssText = 'padding:0 0 10px 14px;';
  const label = document.createElement('div');
  label.style.cssText = 'font-size:11px; color:var(--color-text-tertiary); margin-bottom:2px;';
  label.textContent = `${grade} 추가 제품`;
  const title = document.createElement('div');
  title.style.cssText = 'font-size:13px; color:var(--color-text-primary);';
  title.textContent = `${grade} 구간에서 더 찾아봤어요 😊`;
  header.appendChild(label); header.appendChild(title);
  container.appendChild(header);

  // 리스트 - 브랜드 보드 동일 스타일
  const list = document.createElement('div');
  list.style.cssText = 'background:#fefefd; border-radius:12px; overflow:hidden; border:0.5px solid rgba(0,0,0,0.1);';

  products.forEach((p, idx) => {
    if (idx > 0) {
      const sep = document.createElement('div');
      sep.style.cssText = 'margin:0 14px; height:0.5px; background:rgba(0,0,0,0.08);';
      list.appendChild(sep);
    }

    const row = document.createElement('div');
    row.style.cssText = 'display:flex; align-items:center; gap:14px; padding:12px 14px; cursor:pointer; background:#fefefd;';

    // 썸네일
    const thumb = document.createElement('div');
    thumb.style.cssText = 'width:64px; height:64px; border-radius:8px; background:#f5f3ef; flex-shrink:0; overflow:hidden;';
    if (p.image_url) {
      const img = document.createElement('img');
      img.src = p.image_url;
      img.style.cssText = 'width:100%; height:100%; object-fit:cover;';
      img.onerror = () => { img.style.display='none'; };
      thumb.appendChild(img);
    }
    row.appendChild(thumb);

    // 정보
    const info = document.createElement('div');
    info.style.cssText = 'flex:1; min-width:0;';
    const name = document.createElement('div');
    name.style.cssText = 'font-size:13px; font-weight:500; color:#1a1a1a; line-height:1.4; overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical;';
    name.textContent = p.name;
    const price = document.createElement('div');
    price.style.cssText = 'font-size:12px; color:#8a6f5e; margin-top:3px;';
    price.textContent = p.price || '';
    info.appendChild(name);
    if (p.price) info.appendChild(price);
    row.appendChild(info);

    // 동그라미 화살표
    const arrowBtn = document.createElement('div');
    arrowBtn.style.cssText = 'width:26px; height:26px; border-radius:50%; border:0.5px solid rgba(0,0,0,0.15); display:flex; align-items:center; justify-content:center; flex-shrink:0; background:transparent; transition:background 0.15s, border-color 0.15s;';
    const arrowSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    arrowSvg.setAttribute('width', '12'); arrowSvg.setAttribute('height', '12');
    arrowSvg.setAttribute('viewBox', '0 0 24 24'); arrowSvg.setAttribute('fill', 'none');
    arrowSvg.style.cssText = 'stroke:rgba(0,0,0,0.4); stroke-width:2; transition:stroke 0.15s;';
    const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    poly.setAttribute('points', '9 18 15 12 9 6');
    arrowSvg.appendChild(poly);
    arrowBtn.appendChild(arrowSvg);

    row.onmouseenter = () => { row.style.background='rgba(194,176,153,0.06)'; arrowBtn.style.background='#c2b099'; arrowBtn.style.borderColor='#c2b099'; arrowSvg.style.stroke='white'; };
    row.onmouseleave = () => { row.style.background='#fefefd'; arrowBtn.style.background='transparent'; arrowBtn.style.borderColor='rgba(0,0,0,0.15)'; arrowSvg.style.stroke='rgba(0,0,0,0.4)'; };
    row.onclick = async () => {
      if (!session) session = {};
      session.raw_product = p.name;
      session.single_product = true;
      session.stage = 'direct_recommend';
      await sendSilent('DIRECT_RECOMMEND:' + p.name);
    };

    row.appendChild(arrowBtn);
    list.appendChild(row);
  });

  container.appendChild(list);
  mi.appendChild(av); mi.appendChild(container);
  wrap.appendChild(mi);
  chat.appendChild(wrap);
  scroll();
}

function renderDesireBoard(text) {
  const jsonStr = text.replace('DESIRE_BOARD:', '').trim();
  let parsed = null;
  try { parsed = JSON.parse(jsonStr); } catch(e) {
    console.error('DESIRE_BOARD 파싱 오류:', e);
    return;
  }

  let allImages = Array.isArray(parsed) ? parsed : (parsed?.images || parsed?.style || []);
  if (!allImages.length) return;

  // 6장만 표시, 나머지 예비 보관
  const images = allImages.slice(0, 6);
  let spareImages = allImages.slice(6);  // 예비 이미지!

  const wrap = document.createElement('div');
  wrap.className = 'msg-wrap';
  const mi = document.createElement('div');
  mi.className = 'msg-inner';
  const av = document.createElement('div');
  av.className = 'av av-ai'; av.textContent = '🛍️';
  const bubble = document.createElement('div');
  bubble.className = 'bubble bubble-ai';
  bubble.style.cssText = 'padding:12px; max-width:' + (window.innerWidth >= 600 ? '560px' : '360px') + ';';
  window.addEventListener('resize', () => {
    bubble.style.maxWidth = window.innerWidth >= 600 ? '560px' : '360px';
  });

  // 타이틀
  const title = document.createElement('div');
  title.style.cssText = 'font-size:14px; font-weight:600; margin-bottom:8px; color:var(--color-text-primary);';
  title.textContent = '✨ 어떤 스타일이 마음에 드세요?';
  bubble.appendChild(title);

  const sub = document.createElement('div');
  sub.style.cssText = 'font-size:11px; color:#888; margin-bottom:10px;';
  sub.textContent = '이미지 클릭 → 확대 | 동그라미 클릭 → 선택';
  bubble.appendChild(sub);

  // 2열 그리드
  const selectedImages = new Set();
  let activeCount = images.length;
  const MAX_COUNT = 6;

  const grid = document.createElement('div');
  grid.className = 'desire-grid';
  grid.style.cssText = 'display:grid; grid-template-columns:1fr 1fr; gap:8px;';
  // PC에서 3열로 변경
  function updateGridCols() {
    grid.style.gridTemplateColumns = window.innerWidth >= 600 ? '1fr 1fr 1fr' : '1fr 1fr';
  }
  updateGridCols();
  window.addEventListener('resize', updateGridCols);
  grid._activeCount = activeCount;
  grid._selected = selectedImages;

  // 선택 완료 버튼 (미리 생성)
  const btnWrap = document.createElement('div');
  btnWrap.style.cssText = 'display:none; gap:8px; margin-top:12px; flex-direction:column;';
  const countMsg = document.createElement('div');
  countMsg.style.cssText = 'font-size:12px; color:#888; text-align:center;';

  const fillBtn = document.createElement('button');
  fillBtn.style.cssText = 'background:transparent; color:#ff6b35; border:2px solid #ff6b35; border-radius:20px; padding:9px 16px; font-size:14px; cursor:pointer; width:100%; display:none;';
  fillBtn.onclick = () => {
    const need = MAX_COUNT - activeCount;
    send(`${need}장 더 찾기`);
  };

  function updateButtons() {
    const need = MAX_COUNT - activeCount;
    if (selectedImages.size > 0 || need > 0) {
      btnWrap.style.display = 'flex';
    } else {
      btnWrap.style.display = 'none';
    }
    countMsg.textContent = selectedImages.size > 0 ? `${selectedImages.size}개 선택됨` : '';
    if (need > 0) {
      fillBtn.style.display = 'block';
      fillBtn.textContent = `🔄 ${need}장 더 찾기`;
    } else {
      fillBtn.style.display = 'none';
    }
  }

  // 자동 추가 함수
  function autoAddImage() {
    if (spareImages.length > 0) {
      // 예비 이미지에서 바로 추가!
      const spare = spareImages.shift();
      spare.style = spare.style || '추가';
      addCardToGrid(spare, Date.now());
      activeCount++;
      grid._activeCount = activeCount;
      updateButtons();
    } else {
      // 예비 없으면 서버에서 1장 추가 검색!
      const loader = document.createElement('div');
      loader.id = 'desire-loader';
      loader.style.cssText = 'border-radius:10px; background:var(--color-background-secondary); aspect-ratio:1; display:flex; align-items:center; justify-content:center; font-size:12px; color:#888;';
      loader.textContent = '🔍 찾는 중...';
      grid.appendChild(loader);

      // 상판 조건 + 제품명으로 검색, 기존 URL 제외
      const product = session?.raw_product || '소파';
      const selections = session?.selections || '';
      const existingUrls = Array.from(grid.querySelectorAll('img')).map(i => i.src);
      fetch('/desire_add_one', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ product, selections, session, existing_urls: existingUrls })
      }).then(r => r.json()).then(data => {
        const loader = document.getElementById('desire-loader');
        if (loader) loader.remove();
        if (data.image) {
          addCardToGrid(data.image, Date.now());
          activeCount++;
          grid._activeCount = activeCount;
          updateButtons();
        }
      }).catch(() => {
        const loader = document.getElementById('desire-loader');
        if (loader) loader.remove();
      });
    }
  }

  // grid에 함수 연결 (선언 후!)
  grid._updateButtons = updateButtons;
  grid._autoAdd = autoAddImage;

  // 카드 생성 함수 (재사용 가능)
  function addCardToGrid(img, idx) {
    const card = document.createElement('div');
    card.style.cssText = 'border-radius:10px; overflow:hidden; border:2px solid transparent; position:relative; transition:border-color 0.2s; background:var(--color-background-secondary);';

    const imgEl = document.createElement('img');
    imgEl.src = img.url;
    imgEl.style.cssText = 'width:100%; aspect-ratio:1; object-fit:cover; display:block; cursor:pointer; transform:scale(1.08); transition:transform 0.3s; filter:brightness(1.05) saturate(1.15) sepia(0.08);';
    imgEl.onerror = () => { card.style.display = 'none'; activeCount--; updateButtons(); };

    imgEl.onclick = () => {
      const overlay = document.createElement('div');
      overlay.style.cssText = 'position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.8); z-index:9999; display:flex; align-items:center; justify-content:center; padding:40px;';
      const popup = document.createElement('div');
      popup.style.cssText = 'position:relative; max-width:360px; width:100%; border-radius:16px; overflow:hidden; background:white;';
      const closeBtn = document.createElement('button');
      closeBtn.textContent = '✕';
      closeBtn.style.cssText = 'position:absolute; top:8px; right:8px; background:rgba(0,0,0,0.5); color:white; border:none; border-radius:50%; width:28px; height:28px; font-size:14px; cursor:pointer; z-index:1;';
      closeBtn.onclick = (e) => { e.stopPropagation(); overlay.remove(); };
      const bigImg = document.createElement('img');
      bigImg.src = img.url;
      bigImg.style.cssText = 'width:100%; display:block;';
      if (img.style) {
        const cap = document.createElement('div');
        cap.style.cssText = 'padding:8px 12px; font-size:12px; color:#555;';
        cap.textContent = img.style;
        popup.appendChild(bigImg); popup.appendChild(cap);
      } else { popup.appendChild(bigImg); }
      popup.appendChild(closeBtn);
      overlay.appendChild(popup);
      overlay.onclick = () => overlay.remove();
      popup.onclick = (e) => e.stopPropagation();
      document.body.appendChild(overlay);
    };

    const labelBar = document.createElement('div');
    labelBar.style.cssText = 'background:rgba(0,0,0,0.25); padding:6px 8px; display:flex; justify-content:space-between; align-items:center; gap:6px;';
    const labelText = document.createElement('span');
    labelText.style.cssText = 'font-size:11px; color:white; font-weight:500; flex:1; text-shadow:0 1px 2px rgba(0,0,0,0.5);';
    labelText.textContent = img.style || `스타일`;
    const btnRow = document.createElement('div');
    btnRow.style.cssText = 'display:flex; gap:5px; align-items:center; flex-shrink:0;';

    const delBtn = document.createElement('button');
    delBtn.style.cssText = 'background:rgba(220,50,50,0.9); border:none; color:white; font-size:10px; font-weight:500; cursor:pointer; border-radius:4px; padding:3px 7px;';
    delBtn.textContent = '삭제';
    delBtn.onclick = (e) => {
      e.stopPropagation();
      card.style.display = 'none';
      selectedImages.delete(img);
      activeCount--;
      grid._activeCount = activeCount;
      updateButtons();
      autoAddImage();
    };

    const checkBtn = document.createElement('button');
    checkBtn.style.cssText = 'background:transparent; border:1.5px solid white; color:white; font-size:10px; font-weight:500; cursor:pointer; border-radius:4px; padding:3px 7px; transition:all 0.2s;';
    checkBtn.textContent = '선택';
    checkBtn.onclick = (e) => {
      e.stopPropagation();
      if (selectedImages.has(img)) {
        selectedImages.delete(img);
        checkBtn.style.background = 'transparent';
        checkBtn.style.color = 'white';
        checkBtn.style.borderColor = 'white';
        checkBtn.textContent = '선택';
        card.style.borderColor = 'transparent';
      } else {
        selectedImages.add(img);
        checkBtn.style.background = '#ff6b35';
        checkBtn.style.color = 'white';
        checkBtn.textContent = '✓';
        card.style.borderColor = '#ff6b35';
      }
      updateButtons();
    };

    btnRow.appendChild(delBtn); btnRow.appendChild(checkBtn);
    labelBar.appendChild(labelText); labelBar.appendChild(btnRow);
    card.appendChild(imgEl); card.appendChild(labelBar);
    grid.appendChild(card);
  }

  images.forEach((img, idx) => addCardToGrid(img, idx));

  bubble.appendChild(grid);
  bubble.appendChild(countMsg);

  const confirmBtn = document.createElement('button');
  confirmBtn.textContent = '이 스타일로 찾아주세요';
  confirmBtn.style.cssText = 'background:#ff6b35; color:white; border:none; border-radius:20px; padding:11px 16px; font-size:14px; font-weight:600; cursor:pointer; width:100%;';
  confirmBtn.onclick = () => {
    const selected = Array.from(selectedImages);
    // 스타일 매칭용으로 저장
    window._desireSelectedImages = selected;
    send(`DESIRE_SELECT:${JSON.stringify(selected)}`);
  };

  btnWrap.appendChild(confirmBtn);
  btnWrap.appendChild(fillBtn);
  bubble.appendChild(btnWrap);

  mi.appendChild(av); mi.appendChild(bubble);
  wrap.appendChild(mi);
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
}

function addAiMsg(text) {
  if (text.startsWith('BOARD_UPDATE')) {
    return;
  } else if (text.includes('INPUT_HINT:')) {
    // 입력창 힌트 + 메시지 표시
    const parts = text.split('INPUT_HINT:');
    const msg = parts[0].trim();
    const hint = parts[1] ? parts[1].trim() : '';
    if (msg) {
      const w = document.createElement('div'); w.className = 'msg-wrap';
      const mi = document.createElement('div'); mi.className = 'msg-inner';
      const av = document.createElement('div'); av.className = 'av av-ai'; av.textContent = '🛍️';
      const b = document.createElement('div'); b.className = 'bubble bubble-ai'; b.textContent = msg;
      mi.appendChild(av); mi.appendChild(b); w.appendChild(mi); chat.appendChild(w);
    }
    if (hint) {
      input.placeholder = hint;
      input.focus();
    }
    chat.scrollTop = chat.scrollHeight;
    return;
  } else if (text.includes('BOARD_KEEP:')) {
    // 답변 + 상황판 유지
    const parts = text.split('BOARD_KEEP:');
    const answer = parts[0].trim();
    const boardText = parts[1] ? parts[1].trim() : '';
    if (answer) {
      const w = document.createElement('div'); w.className = 'msg-wrap';
      const mi = document.createElement('div'); mi.className = 'msg-inner';
      const av = document.createElement('div'); av.className = 'av av-ai'; av.textContent = '🛍️';
      const b = document.createElement('div'); b.className = 'bubble bubble-ai';
      b.textContent = answer;
      // 처음으로 다시 가기 버튼
      const homeBtn = document.createElement('button');
      homeBtn.textContent = '🔄 처음부터 다시 찾기';
      homeBtn.style.cssText = 'display:block;margin-top:10px;padding:7px 16px;background:var(--surface2);border:1.5px solid var(--border);border-radius:20px;font-size:12px;color:var(--text-dim);cursor:pointer;transition:all 0.15s;';
      homeBtn.onmouseover = () => { homeBtn.style.borderColor = 'var(--accent)'; homeBtn.style.color = 'var(--accent)'; };
      homeBtn.onmouseout = () => { homeBtn.style.borderColor = 'var(--border)'; homeBtn.style.color = 'var(--text-dim)'; };
      homeBtn.onclick = () => send('처음부터 다시 찾아줘');
      b.appendChild(homeBtn);
      mi.appendChild(av); mi.appendChild(b); w.appendChild(mi); chat.appendChild(w);
    }
    if (boardText) renderBoard(boardText);
    chat.scrollTop = chat.scrollHeight;
    return;
  } else if (text.startsWith('PICKO_RESULT:')) {
    renderPickoResult(text);
  } else if (text.startsWith('DESIRE_BOARD:')) {
    renderDesireBoard(text);
  } else if (text.startsWith('VS_CARDS:')) {
    renderVsCards(text);
  } else if (text.startsWith('DESIRE_BOARD_ADD:')) {
    const jsonStr = text.replace('DESIRE_BOARD_ADD:', '').trim();
    const loader = document.getElementById('desire-loader');
    if (loader) loader.remove();
    try {
      const newImages = JSON.parse(jsonStr);
      const lastGrid = document.querySelector('.desire-grid');
      const lastBtnWrap = lastGrid ? lastGrid.closest('.bubble-ai')?.querySelector('.desire-btnwrap') : null;
      const lastUpdateFn = lastGrid?._updateButtons;

      if (lastGrid && newImages.length > 0) {
        newImages.forEach((img, addIdx) => {
          const card = document.createElement('div');
          card.style.cssText = 'border-radius:10px; overflow:hidden; border:2px solid transparent; position:relative; background:var(--color-background-secondary);';

          const imgEl = document.createElement('img');
          imgEl.src = img.url;
          imgEl.style.cssText = 'width:100%; aspect-ratio:1; object-fit:cover; display:block; cursor:pointer; transform:scale(1.08); transition:transform 0.3s; filter:brightness(1.05) saturate(1.15) sepia(0.08);';
          imgEl.onerror = () => { card.style.display = 'none'; };

          // 확대 팝업
          imgEl.onclick = () => {
            const overlay = document.createElement('div');
            overlay.style.cssText = 'position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.8); z-index:9999; display:flex; align-items:center; justify-content:center; padding:40px;';
            const popup = document.createElement('div');
            popup.style.cssText = 'position:relative; max-width:360px; width:100%; border-radius:16px; overflow:hidden;';
            const closeBtn = document.createElement('button');
            closeBtn.textContent = '✕';
            closeBtn.style.cssText = 'position:absolute; top:8px; right:8px; background:rgba(0,0,0,0.5); color:white; border:none; border-radius:50%; width:28px; height:28px; cursor:pointer; z-index:1;';
            closeBtn.onclick = (e) => { e.stopPropagation(); overlay.remove(); };
            const bigImg = document.createElement('img');
            bigImg.src = img.url;
            bigImg.style.cssText = 'width:100%; display:block;';
            popup.appendChild(bigImg);
            popup.appendChild(closeBtn);
            overlay.appendChild(popup);
            overlay.onclick = () => overlay.remove();
            popup.onclick = (e) => e.stopPropagation();
            document.body.appendChild(overlay);
          };

          // 라벨바 + 삭제/선택 버튼
          const labelBar = document.createElement('div');
          labelBar.style.cssText = 'background:rgba(0,0,0,0.25); padding:6px 8px; display:flex; justify-content:space-between; align-items:center; gap:6px;';

          const labelText = document.createElement('span');
          labelText.style.cssText = 'font-size:11px; color:white; font-weight:500; flex:1;';
          labelText.textContent = img.style || '추가';

          const btnRow = document.createElement('div');
          btnRow.style.cssText = 'display:flex; gap:5px;';

          const delBtn = document.createElement('button');
          delBtn.style.cssText = 'background:rgba(220,50,50,0.9); border:none; color:white; font-size:10px; font-weight:500; cursor:pointer; border-radius:4px; padding:3px 7px;';
          delBtn.textContent = '삭제';
          delBtn.onclick = (e) => {
            e.stopPropagation();
            card.style.display = 'none';
            if (lastGrid._activeCount !== undefined) {
              lastGrid._activeCount--;
              if (lastGrid._updateButtons) lastGrid._updateButtons();
              lastGrid._autoAdd();
            }
          };

          const chkBtn = document.createElement('button');
          chkBtn.style.cssText = 'background:transparent; border:1.5px solid white; color:white; font-size:10px; font-weight:500; cursor:pointer; border-radius:4px; padding:3px 7px;';
          chkBtn.textContent = '선택';
          chkBtn.onclick = (e) => {
            e.stopPropagation();
            const uid = `add_${Date.now()}_${addIdx}`;
            if (lastGrid._selected && lastGrid._selected.has(uid)) {
              lastGrid._selected.delete(uid);
              chkBtn.style.background = 'transparent';
              chkBtn.style.color = 'white';
              chkBtn.textContent = '선택';
              card.style.borderColor = 'transparent';
            } else {
              if (lastGrid._selected) lastGrid._selected.add(uid);
              chkBtn.style.background = '#ff6b35';
              chkBtn.style.color = 'white';
              chkBtn.textContent = '✓';
              card.style.borderColor = '#ff6b35';
            }
            if (lastGrid._updateButtons) lastGrid._updateButtons();
          };

          btnRow.appendChild(delBtn);
          btnRow.appendChild(chkBtn);
          labelBar.appendChild(labelText);
          labelBar.appendChild(btnRow);
          card.appendChild(imgEl);
          card.appendChild(labelBar);
          lastGrid.appendChild(card);

          // activeCount 업데이트
          if (lastGrid._activeCount !== undefined) {
            lastGrid._activeCount++;
            if (lastGrid._updateButtons) lastGrid._updateButtons();
          }
        });
      }
    } catch(e) { console.error('DESIRE_BOARD_ADD 오류:', e); }
  } else if (text.startsWith('IMAGE_RESULTS:')) {
    renderImageResults(text);
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
  } else if (typeof data === 'object' && data.type === 'brand_products') {
    renderBrandProducts(data);
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
  // user_profile 항상 세션에 포함
  if (Object.keys(userProfile).length > 0) {
    session = session || {};
    session.user_profile = userProfile;
  }
  const msg = overrideText || input.value.trim();
  if (!msg) return;
  const hiddenPrefixes = ['DESIRE_SELECT:', 'MULTI_SELECT:', 'BOARD_UPDATE'];
  const isHidden = hiddenPrefixes.some(p => msg.startsWith(p));
  if (!isHidden) addUserMsg(msg);
  if (!overrideText) { input.value = ''; input.style.height = 'auto'; }
  sendBtn.disabled = true;

  // ★ 상황판 생성 요청만 /chat_stream!
  // 선택합산(key:value 형식) 은 /chat으로!
  const isboardRequest = !msg.startsWith('DESIRE_SELECT:') &&
                         !msg.startsWith('MULTI_SELECT:') &&
                         !msg.startsWith('BOARD_UPDATE') &&
                         !msg.startsWith('네, 찾아주세요') &&
                         !msg.startsWith('DIRECT_RECOMMEND') &&
                         !/^\S+:\S+/.test(msg); // ★ 선택합산 제외!

  if (isboardRequest) {
    // ★ 스트리밍 로딩 UI 표시
    const loader = addStreamingLoader();

    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 90000);
      const res = await fetch('/chat_stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg, session: session }),
        signal: controller.signal
      });
      clearTimeout(timeout);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const event = JSON.parse(line.slice(6));
            if (event.type === 'progress') {
              updateStreamingStep(event.key, event.msg);
            } else if (event.type === 'empathy') {
              // ★ 공감멘트 즉시! 빠와 동시에!
              const empWrap = document.createElement('div');
              empWrap.className = 'msg-wrap';
              const empMi = document.createElement('div');
              empMi.className = 'msg-inner';
              const empAv = document.createElement('div');
              empAv.className = 'av av-ai'; empAv.textContent = '🛍️';
              const empDiv = document.createElement('div');
              empDiv.style.cssText = 'font-size:14px;color:var(--text,#333);line-height:1.7;padding-top:6px;white-space:pre-wrap;';
              empMi.appendChild(empAv); empMi.appendChild(empDiv);
              empWrap.appendChild(empMi); chat.appendChild(empWrap);
              // 타이핑 효과!
              let ei = 0, em = event.msg;
              const et = setInterval(() => {
                empDiv.textContent += em[ei++];
                scroll();
                if (ei >= em.length) clearInterval(et);
              }, 30);
            } else if (event.type === 'done') {
              if (loader._phase1Timer) clearInterval(loader._phase1Timer);
              session = event.session || session;
              const _resp = event.response || '';

              // ★ 네/아니요 확인 버튼
              if (event.show_confirm) {
                const btnWrap = document.createElement('div');
                btnWrap.style.cssText = 'display:flex;gap:8px;padding:8px 14px 12px;width:100%;box-sizing:border-box;justify-content:flex-start;';
                ['네, 찾아줘요!', '아니요, 괜찮아요'].forEach((label, i) => {
                  const btn = document.createElement('button');
                  btn.textContent = label;
                  btn.style.cssText = `padding:8px 16px;border-radius:20px;border:1.5px solid ${i===0?'#a38d72':'#ccc'};background:${i===0?'#a38d72':'white'};color:${i===0?'white':'#666'};font-size:13px;cursor:pointer;`;
                  btn.onclick = () => {
                    btnWrap.remove();
                    sendMessage(label);
                  };
                  btnWrap.appendChild(btn);
                });
                chat.appendChild(btnWrap);
                smartScroll();
              }

              // ★ 빠 100% 완료 표시
              const lbl = document.getElementById('pk-lbl');
              const bar = document.getElementById('pk-bar');
              if (lbl) lbl.classList.add('done');
              if (bar) { bar.style.width = '100%'; bar.classList.add('done'); }

              // ★ 즉시! 대기 없이!
              loader.remove();
              if (_resp === 'CONTEXT_REPLY') {
                // 맥락 대화 출처 표시
                if (event.source_voice) {
                  const srcDiv = document.createElement('div');
                  srcDiv.style.cssText = 'font-size:10px;color:var(--color-text-tertiary);padding:2px 0 8px 28px;';
                  const v = event.source_voice;
                  if (v.url) {
                    srcDiv.innerHTML = `<a href="${v.url}" target="_blank" style="color:var(--color-text-tertiary);text-decoration:underline;">${v.source || '네이버 블로그'}</a> 후기 기반`;
                  } else {
                    srcDiv.textContent = (v.source || '네이버 블로그') + ' 후기 기반';
                  }
                  chat.appendChild(srcDiv);
                  smartScroll();
                }
              } else if (_resp.startsWith('BRAND_PRODUCTS:')) {
                try {
                  const bpData = JSON.parse(_resp.slice('BRAND_PRODUCTS:'.length));
                  document.getElementById('start-page').style.display = 'none';
                  document.getElementById('chat-page').style.display = 'flex';
                  renderBrandProducts(bpData);
                } catch(e) { addAiMsg('제품 목록 오류: ' + e.message); }
              } else {
                addAiMsg(_resp);
              }
            } else if (event.type === 'error') {
              loader.remove();
              addAiMsg('오류가 발생했어요. 다시 시도해주세요.');
            }
          } catch(e) {}
        }
      }
    } catch(e) {
      const l = document.getElementById('streaming-loader');
      if (l) l.remove();
      if (e.name === 'AbortError') {
        addAiMsg('응답이 오래 걸리고 있어요. 다시 시도해주세요.');
      } else {
        addAiMsg('연결 오류가 발생했어요. 다시 시도해주세요.');
      }
    }
  } else {
    // 추천/욕망보드 등 - 빠 로딩 추가!
    const recLoader = addStreamingLoader();
    // 추천용 메시지로 교체!
    const pkTxt = document.getElementById('pk-txt');
    if (pkTxt) pkTxt.textContent = '후기 읽어보는 중';

    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 90000);
      const res = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg, session: session }),
        signal: controller.signal
      });
      clearTimeout(timeout);
      const data = await res.json();

      // 빠 완료!
      if (recLoader._phase1Timer) clearInterval(recLoader._phase1Timer);
      const rl = document.getElementById('pk-lbl');
      const rb = document.getElementById('pk-bar');
      if (rl) rl.classList.add('done');
      if (rb) { rb.style.width = '100%'; rb.classList.add('done'); }
      setTimeout(() => recLoader.remove(), 200);

      session = data.session;
      const _resp = data.response || '';

      if (_resp.startsWith('BRAND_PRODUCTS:')) {
        try {
          const bpData = JSON.parse(_resp.slice('BRAND_PRODUCTS:'.length));
          document.getElementById('start-page').style.display = 'none';
          document.getElementById('chat-page').style.display = 'flex';
          renderBrandProducts(bpData);
        } catch(e) { addAiMsg('제품 목록 오류: ' + e.message); }

      } else if (_resp.startsWith('PICKO_RESULT:')) {
        // ★ condition_desc 먼저 타이핑 출력 후 카드!
        try {
          const _d = JSON.parse(_resp.replace('PICKO_RESULT:', '').trim());
          const condDesc = _d.condition_desc || '';
          if (condDesc) {
            const cdWrap = document.createElement('div');
            cdWrap.className = 'msg-wrap';
            const cdMi = document.createElement('div'); cdMi.className = 'msg-inner';
            const cdAv = document.createElement('div'); cdAv.className = 'av av-ai'; cdAv.textContent = '🛍️';
            const cdDiv = document.createElement('div');
            cdDiv.style.cssText = 'font-size:14px; color:var(--text,#333); line-height:1.7; padding-top:6px; font-style:italic;';
            cdMi.appendChild(cdAv); cdMi.appendChild(cdDiv);
            cdWrap.appendChild(cdMi); chat.appendChild(cdWrap);
            // 타이핑 후 카드!
            let ci = 0;
            const ct = setInterval(() => {
              cdDiv.textContent += condDesc[ci++];
              scroll();
              if (ci >= condDesc.length) {
                clearInterval(ct);
                setTimeout(() => addAiMsg(_resp), 300);
              }
            }, 20);
          } else {
            addAiMsg(_resp);
          }
        } catch(e) { addAiMsg(_resp); }

      } else {
        addAiMsg(_resp);
      }
    } catch(e) {
      recLoader?.remove();
      if (e.name === 'AbortError') {
        addAiMsg('응답이 오래 걸리고 있어요. 다시 시도해주세요.');
      } else {
        addAiMsg('연결 오류가 발생했어요. 다시 시도해주세요.');
      }
    }
  }
  sendBtn.disabled = false;
  input.focus();
}

// 채팅창에 안 보이게 조용히 전송 (ADD_ITEM 등 내부 명령)
async function sendSilent(msg) {
  // ★ 빠 로딩 추가!
  const silentLoader = addStreamingLoader();
  const pkTxt = document.getElementById('pk-txt');
  if (pkTxt) pkTxt.textContent = '후기 읽어보는 중';

  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, session: session })
    });
    const data = await res.json();

    // ★ 빠 완료!
    if (silentLoader._phase1Timer) clearInterval(silentLoader._phase1Timer);
    const sl = document.getElementById('pk-lbl');
    const sb = document.getElementById('pk-bar');
    if (sl) sl.classList.add('done');
    if (sb) { sb.style.width = '100%'; sb.classList.add('done'); }
    setTimeout(() => silentLoader.remove(), 200);

    session = data.session;
    const resp = data.response || '';
    if (resp.startsWith('BOARD_UPDATE')) {
      const boardText = resp.replace('BOARD_UPDATE', '').trim();
      const allBoards = document.querySelectorAll('.board');
      if (allBoards.length > 0) {
        const lastBoard = allBoards[allBoards.length - 1];
        const tmp = document.createElement('div');
        const origChat = chat;
        chat = tmp;
        renderBoard(boardText);
        chat = origChat;
        const newBoard = tmp.querySelector('.board');
        if (newBoard) lastBoard.replaceWith(newBoard);
      }
    } else if (resp.startsWith('BRAND_PRODUCTS:')) {
      try {
        const bpJson = resp.slice('BRAND_PRODUCTS:'.length);
        const bpData = JSON.parse(bpJson);
        document.getElementById('start-page').style.display = 'none';
        document.getElementById('chat-page').style.display = 'flex';
        renderBrandProducts(bpData);
      } catch(e) { addAiMsg('❌ 오류: ' + e.message); }
    } else if (resp.startsWith('PICKO_RESULT:')) {
      // ★ condition_desc 먼저 타이핑 출력!
      try {
        const _d = JSON.parse(resp.replace('PICKO_RESULT:', '').trim());
        const condDesc = _d.condition_desc || '';
        if (condDesc) {
          const cdWrap = document.createElement('div'); cdWrap.className = 'msg-wrap';
          const cdMi = document.createElement('div'); cdMi.className = 'msg-inner';
          const cdAv = document.createElement('div'); cdAv.className = 'av av-ai'; cdAv.textContent = '🛍️';
          const cdDiv = document.createElement('div');
          cdDiv.style.cssText = 'font-size:14px;color:var(--text,#333);line-height:1.7;padding-top:6px;';
          cdMi.appendChild(cdAv); cdMi.appendChild(cdDiv);
          cdWrap.appendChild(cdMi); chat.appendChild(cdWrap);
          let ci = 0;
          const ct = setInterval(() => {
            cdDiv.textContent += condDesc[ci++];
            scroll();
            if (ci >= condDesc.length) {
              clearInterval(ct);
              setTimeout(() => renderPickoResult(resp), 300);
            }
          }, 20);
        } else {
          renderPickoResult(resp);
        }
      } catch(e) { renderPickoResult(resp); }
    } else if (resp.startsWith('DESIRE_BOARD:')) {
      renderDesireBoard(resp);
    } else if (resp.startsWith('VS_CARDS:')) {
      renderVsCards(resp);
    } else {
      addAiMsg(resp);
    }
  } catch(e) {
    if (silentLoader._phase1Timer) clearInterval(silentLoader._phase1Timer);
    silentLoader?.remove();
    addAiMsg('연결 오류가 발생했어요. 다시 시도해주세요.');
  }
}

// ★ 픽코3 스트리밍 추천
// 1순위 완성 → 즉시 표시 → 2순위 → 3순위
// streamMode로 애니메이션 없이 즉시 렌더링 (충돌 방지!)
async function startRecommendStream() {
  // ★ 스마트 스크롤 - 사용자가 읽는 중이면 화면 점프 금지!
  const smartScroll = () => {
    const distFromBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight;
    if (distFromBottom < 300) chat.scrollTop = chat.scrollHeight;
  };
  const loader = addStreamingLoader();
  const pkTxt = document.getElementById('pk-txt');
  if (pkTxt) pkTxt.textContent = '후기 읽어보는 중...';

  let firstNotice = '';
  let globalGrade = '';
  let globalMoreCacheKey = '';
  let globalMatchKeywords = [];
  let condDescShown = false;
  let lastRenderedCount = 0;

  // ★ rank별 이벤트 큐 + 순서 보장
  const rankEvents = { 1: [], 2: [], 3: [] };
  const cardShells = {};   // rank → bubble DOM
  let currentRank = 1;     // 지금 처리 중인 rank
  let isProcessing = false;

  // ★ 구분선 헬퍼 (기존 renderPickoResult divider()와 동일)
  const mkDiv = () => { const d = document.createElement('div'); d.style.cssText = 'height:1px;background:#e0ddd8;'; return d; };

  // ★ 픽코3 카드 섹션 핸들러 맵
  // 새 섹션 추가: 키 하나 추가하면 끝!
  // 섹션 제거: 해당 줄 주석 처리하면 끝!
  // recommendation.py에서 해당 type 전송 → 자동 처리!
  const CARD_HANDLERS = {

    // ── rating: 픽코 평점 ──
    rating: async (item, shell) => {
      if (shell.placeholder) { shell.placeholder.remove(); delete shell.placeholder; }
      if (pkTxt) pkTxt.textContent = `${item.rank}순위 별점 계산 중...`;
      shell.bubble.appendChild(mkDiv());
      const ratingWrap = document.createElement('div');
      ratingWrap.style.cssText = 'padding:12px 14px;';
      const rHdr = document.createElement('div');
      rHdr.style.cssText = 'display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;';
      const rTitle = document.createElement('div');
      rTitle.style.cssText = 'font-size:14px;font-weight:500;color:var(--color-text-secondary);';
      rTitle.textContent = '픽코 평점';
      const rCount = document.createElement('div');
      rCount.style.cssText = 'font-size:10px;color:var(--color-text-tertiary);';
      rCount.textContent = '후기 분석 기반';
      rHdr.appendChild(rTitle); rHdr.appendChild(rCount);
      ratingWrap.appendChild(rHdr);
      const BADGE_MAP = {'선택':'background:#f0ebe5;color:#8a6f5e;','입력':'background:#e8f0fe;color:#4a6fa5;','기본':'background:#f0f0f0;color:#888;'};
      for (const [ri, r] of (item.data || []).entries()) {
        if (ri === 3) ratingWrap.appendChild(mkDiv());
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:8px;';
        const badge = document.createElement('span');
        badge.style.cssText = `font-size:10px;padding:1px 6px;border-radius:10px;white-space:nowrap;${BADGE_MAP[r.badge]||BADGE_MAP['기본']}`;
        badge.textContent = r.badge;
        const label = document.createElement('span');
        label.style.cssText = 'font-size:12px;color:var(--color-text-primary);white-space:nowrap;';
        label.textContent = r.label;
        const stars = document.createElement('span');
        stars.style.cssText = 'color:#c2b099;font-size:12px;white-space:nowrap;margin-left:auto;';
        stars.textContent = r.stars || '★★★☆☆';
        const pct = document.createElement('span');
        pct.style.cssText = 'font-size:10px;color:var(--color-text-tertiary);white-space:nowrap;';
        pct.textContent = r.pct ? r.pct+'%' : '';
        row.appendChild(badge); row.appendChild(label); row.appendChild(stars); row.appendChild(pct);
        ratingWrap.appendChild(row);
        await new Promise(resolve => setTimeout(resolve, 150));
        smartScroll();
      }
      shell.bubble.appendChild(ratingWrap);
      smartScroll();
    },

    // ── voices: 진짜 사용자 목소리 ──
    voices: async (item, shell) => {
      if (pkTxt) pkTxt.textContent = `${item.rank}순위 후기 정리 중...`;
      shell.bubble.appendChild(mkDiv());
      const sec = document.createElement('div');
      sec.style.cssText = 'padding:12px 14px;background:var(--color-background-primary);';
      const vTitle = document.createElement('div');
      vTitle.style.cssText = 'font-size:14px;font-weight:500;color:var(--color-text-secondary);margin-bottom:10px;';
      vTitle.textContent = '진짜 사용자 목소리';
      sec.appendChild(vTitle);

      // 공식몰 + 블로그 분리 구조 or 기존 배열 호환
      const data = item.data || [];
      const officialList = Array.isArray(data) ? [] : (data.official || []);
      const blogList     = Array.isArray(data) ? data : (data.blog || []);

      const _renderVoice = async (r, isOfficial) => {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;gap:10px;align-items:flex-start;margin-bottom:10px;';
        const dot = document.createElement('div');
        const isPos = r.type === 'pos';
        dot.style.cssText = `width:18px;height:18px;border-radius:50%;flex-shrink:0;margin-top:1px;display:flex;align-items:center;justify-content:center;background:${isPos?'#e8f5e9':'#fdecea'};`;
        dot.innerHTML = `<span style="font-size:10px;color:${isPos?'#4caf50':'#e53935'};font-weight:500;">${isPos?'+':'−'}</span>`;
        const txtDiv = document.createElement('div');
        const quote = document.createElement('div');
        quote.style.cssText = 'font-size:12px;color:var(--color-text-primary);line-height:1.6;';
        quote.textContent = '"' + (r.text||'') + '"';
        const src = document.createElement('div');
        src.style.cssText = 'font-size:10px;color:var(--color-text-tertiary);margin-top:3px;';
        if (isOfficial) {
          // 공식몰: "구매자 fee****" 형태
          const nick = r.bloggername || '구매자';
          src.textContent = nick.startsWith('구매자') ? nick : `구매자 ${nick}`;
        } else {
          // 블로그/카페: 기존 방식
          src.textContent = (r.source == null) ? '네이버 블로그' : r.source;
        }
        txtDiv.appendChild(quote); txtDiv.appendChild(src);
        row.appendChild(dot); row.appendChild(txtDiv);
        sec.appendChild(row);
        await new Promise(resolve => setTimeout(resolve, 200));
        smartScroll();
      };

      // 공식몰 후기 (있을 때만)
      if (officialList.length > 0) {
        for (const r of officialList) await _renderVoice(r, true);
        if (blogList.length > 0) {
          const div = document.createElement('div');
          div.style.cssText = 'border-top:0.5px solid var(--color-border-tertiary);margin:6px 0 10px;';
          sec.appendChild(div);
        }
      }

      // 블로그/카페 후기
      for (const r of blogList) await _renderVoice(r, false);

      shell.bubble.appendChild(sec);
      shell.voicesSec = sec;
      smartScroll();
    },

    // ── critique: 픽코 총평 비평 ──
    critique: async (item, shell) => {
      if (!item.text) return;
      const wrap = document.createElement('div');
      wrap.style.cssText = 'margin:12px 0 4px;padding:14px 16px;background:var(--color-background-primary);border-radius:14px;border-left:3px solid #a38d72;';
      const title = document.createElement('div');
      title.style.cssText = 'font-size:12px;font-weight:600;color:#a38d72;margin-bottom:8px;letter-spacing:0.3px;';
      title.textContent = '픽코 총평';
      const text = document.createElement('div');
      text.style.cssText = 'font-size:13px;color:var(--color-text-primary);line-height:1.8;white-space:pre-wrap;';
      text.textContent = item.text;
      wrap.appendChild(title);
      wrap.appendChild(text);
      // 마지막 카드 버블 다음에 삽입
      const chatArea = document.getElementById('chat-messages') || document.querySelector('.chat-messages');
      if (chatArea) chatArea.appendChild(wrap);
      else document.querySelector('.bubble-wrap')?.appendChild(wrap);
      smartScroll();
    },

    // ── reason: 이런 점이 마음에 드실 거예요 제거됨 ──
    reason: async (item, shell) => {},

    // ── trust: 시장 데이터가 말해요 ──
    trust: async (item, shell) => {
      const BADGE_STYLE = {
        '스테디셀러': { bg: '#fef3c7', color: '#92400e', border: '#fcd34d' },
        '숨은 명품':  { bg: '#f0fdf4', color: '#14532d', border: '#86efac' },
        '검증된 제품':{ bg: '#eff6ff', color: '#1e3a5f', border: '#93c5fd' },
        '신제품':     { bg: '#eff6ff', color: '#1e40af', border: '#93c5fd' },
        '행사 주의':  { bg: '#fff7ed', color: '#9a3412', border: '#fdba74' },
        '꾸준한 인기':{ bg: '#f5f3ff', color: '#4c1d95', border: '#c4b5fd' },
        '재구매 있음':{ bg: '#fdf4ff', color: '#701a75', border: '#e879f9' },
        '오래된 제품':{ bg: '#f9fafb', color: '#374151', border: '#d1d5db' },
      };
      const stories = {
        '스테디셀러': `${item.months}개월간 꾸준히 팔렸어요. 재구매 언급 ${item.rebuy_count}건 확인했어요.`,
        '숨은 명품':  `후기 ${item.total_posts}건으로 많지 않아요. 그 중 써본 사람 반응 ${item.q_count}건 나왔어요.`,
        '검증된 제품':`${item.months}개월간 후기 ${item.total_posts}건 축적됐어요.`,
        '신제품':     `출시 ${item.months}개월 됐어요. 장기 사용 데이터가 아직 없어요.`,
        '행사 주의':  `최근 3개월에 후기가 집중됐어요. 이벤트성일 수 있어요.`,
        '꾸준한 인기':`${item.months}개월간 후기가 꾸준히 쌓였어요.`,
        '재구매 있음':`재구매 언급 ${item.rebuy_count}건 확인했어요. 써본 사람이 또 사는 제품이에요.`,
        '오래된 제품':`${item.months}개월 전부터 팔린 제품이에요. 후기 ${item.total_posts}건 확인했어요.`,
      };
      const style = BADGE_STYLE[item.badge] || { bg: '#f9fafb', color: '#374151', border: '#d1d5db' };
      const story = stories[item.badge] || '';

      const sec = document.createElement('div');
      sec.style.cssText = 'padding:10px 14px 8px; border-top:0.5px solid var(--color-border-tertiary);';

      // ★ 폰트 픽코 평점과 동일
      const titleRow = document.createElement('div');
      titleRow.style.cssText = 'font-size:14px; font-weight:500; color:var(--color-text-secondary); margin-bottom:6px;';
      titleRow.textContent = '시장 데이터가 말해요';

      // ★ 뱃지 + 스토리 한 줄 flex
      const row = document.createElement('div');
      row.style.cssText = 'display:flex; align-items:center; gap:8px; flex-wrap:wrap;';
      const badgeEl = document.createElement('span');
      badgeEl.style.cssText = `flex-shrink:0; font-size:11px; font-weight:600; padding:2px 9px; border-radius:20px; border:1px solid ${style.border}; background:${style.bg}; color:${style.color};`;
      badgeEl.textContent = item.badge;
      const storyEl = document.createElement('span');
      storyEl.style.cssText = 'font-size:12px; color:var(--color-text-primary); line-height:1.6;';

      row.appendChild(badgeEl);
      row.appendChild(storyEl);
      sec.appendChild(titleRow);
      sec.appendChild(row);
      shell.bubble.appendChild(sec);
      smartScroll();

      if (story) {
        await new Promise(resolve => {
          let ci = 0;
          const ct = setInterval(() => {
            storyEl.textContent += story[ci++];
            smartScroll();
            if (ci >= story.length) { clearInterval(ct); setTimeout(resolve, 100); }
          }, 22);
        });
      }
    },

    // ── features: 이 제품의 특징 ──
    features: async (item, shell) => {
      const features = item.data || [];
      if (!features.length) return;
      shell.bubble.appendChild(mkDiv());
      const sec = document.createElement('div');
      sec.style.cssText = 'padding:12px 14px;background:var(--color-background-primary);border-top:0.5px solid var(--color-border-tertiary);';
      const title = document.createElement('div');
      title.style.cssText = 'font-size:13px;font-weight:500;color:var(--color-text-secondary);margin-bottom:8px;';
      title.textContent = '이 제품의 특징';
      sec.appendChild(title);
      features.forEach(f => {
        const row = document.createElement('div');
        row.style.cssText = 'padding:4px 0 6px;border-bottom:0.5px solid var(--color-border-tertiary);margin-bottom:2px;';
        // "특징명: 설명" 형태로 분리
        const colonIdx = f.indexOf(':');
        if (colonIdx > 0) {
          const namePart = f.substring(0, colonIdx).trim();
          const desc = f.substring(colonIdx + 1).trim();

          // "특징명 (태그)" 분리
          const tagMatch = namePart.match(/^(.+?)\s*(\(.+?\))\s*$/);
          const nameEl = document.createElement('div');
          nameEl.style.cssText = 'font-size:13px;font-weight:500;color:var(--color-text-primary);line-height:1.6;';
          if (tagMatch) {
            nameEl.innerHTML = `• ${tagMatch[1].trim()} <span style="font-size:13px;font-weight:400;color:var(--color-text-primary);">${tagMatch[2]}</span>`;
          } else {
            nameEl.textContent = `• ${namePart}`;
          }

          const descEl = document.createElement('div');
          descEl.style.cssText = 'font-size:12px;color:var(--color-text-secondary);line-height:1.7;padding-left:10px;margin-top:2px;';
          descEl.innerHTML = desc
            .replace(/\*\*(.+?)\*\*/g, '$1')
            .replace(/__(.+?)__/g, '<u style="text-underline-offset:2px;">$1</u>');
          row.appendChild(nameEl);
          row.appendChild(descEl);
        } else {
          const nameEl = document.createElement('div');
          nameEl.style.cssText = 'font-size:12px;color:var(--color-text-primary);line-height:1.6;';
          nameEl.textContent = `• ${f}`;
          row.appendChild(nameEl);
        }
        sec.appendChild(row);
      });
      shell.bubble.appendChild(sec);
      smartScroll();
    },

    // ── pros_cons: 좋다는 말 / 아쉽다는 말 / 픽코 한마디 ──
    pros_cons: async (item, shell) => {
      const pros = item.pros || [];
      const cons = item.cons || [];
      const oneLine = item.one_line || '';
      const priceInfo = item.price_info || {};
      const situations = item.situations || [];
      const notFit = item.not_fit || [];
      const longTerm = item.long_term || '';
      if (!pros.length && !cons.length && !oneLine && !Object.keys(priceInfo).length && !situations.length && !longTerm) return;

      const sec = document.createElement('div');
      sec.style.cssText = 'padding:10px 14px; border-top:0.5px solid var(--color-border-tertiary);';

      // 좋다는 말
      if (pros.length > 0) {
        const pt = document.createElement('div');
        pt.style.cssText = 'font-size:13px; font-weight:500; color:var(--color-text-secondary); margin:10px 0 6px;';
        pt.textContent = '좋다는 말';
        sec.appendChild(pt);
        pros.forEach(p => {
          const row = document.createElement('div');
          row.style.cssText = 'font-size:12px; color:var(--color-text-primary); padding:2px 0; line-height:1.7;';
          row.textContent = `✓ ${p}`;
          sec.appendChild(row);
        });
      }

      // 아쉽다는 말
      if (cons.length > 0) {
        const ct = document.createElement('div');
        ct.style.cssText = 'font-size:13px; font-weight:500; color:var(--color-text-secondary); margin:10px 0 6px;';
        ct.textContent = '아쉽다는 말';
        sec.appendChild(ct);
        cons.forEach(c => {
          const row = document.createElement('div');
          row.style.cssText = 'font-size:12px; color:var(--color-text-tertiary); padding:2px 0; line-height:1.7;';
          row.textContent = `△ ${c}`;
          sec.appendChild(row);
        });
      }

      shell.bubble.appendChild(sec);

      // ★ 총평 placeholder - pros_cons 바로 다음, 상세페이지 앞
      const critiquePlaceholder = document.createElement('div');
      critiquePlaceholder.setAttribute('data-critique-placeholder', item.rank);
      shell.bubble.appendChild(critiquePlaceholder);

      smartScroll();
    },

  }; // CARD_HANDLERS 끝

  // ★ 필드별 스트리밍 - rank 순서대로 처리
  function _renderCritiques() {
    const critiques = window._pendingCritiques || [];
    if (!critiques.length) return;
    [1, 2, 3].forEach((rank, i) => {
      const shell = cardShells[rank];
      let text = (critiques[i] || '').trim();
      if (!shell || !text) return;
      text = text.split('\n').filter(l => !l.trim().startsWith('#')).join('\n').trim();
      text = text.replace(/\*\*(.+?)\*\*/g, '$1');
      if (!text) return;

      // placeholder에 채우기 (위치 보장)
      const placeholder = shell.bubble.querySelector(`[data-critique-placeholder="${rank}"]`);

      const cWrap = document.createElement('div');
      cWrap.style.cssText = 'padding:4px 14px 10px;';
      const cTitle = document.createElement('div');
      cTitle.style.cssText = 'font-size:13px;font-weight:500;color:var(--color-text-secondary);margin:10px 0 6px;';
      cTitle.textContent = '픽코 총평';
      const cText = document.createElement('div');
      cText.style.cssText = 'font-size:12px;color:var(--color-text-primary);line-height:1.7;white-space:pre-wrap;';
      cText.textContent = text;
      cWrap.appendChild(cTitle);
      cWrap.appendChild(cText);

      if (placeholder) {
        placeholder.appendChild(cWrap);
      } else {
        const insertTarget = shell.bubble.querySelector('[data-detail-wrap]') || shell.bubble.querySelector('[data-more-wrap]');
        if (insertTarget) shell.bubble.insertBefore(cWrap, insertTarget);
        else shell.bubble.appendChild(cWrap);
      }
    });
    window._pendingCritiques = null;
    smartScroll();
  }

  const processRankEvents = async () => {
    if (isProcessing) return;
    isProcessing = true;

    while (currentRank <= 3) {
      const events = rankEvents[currentRank];
      if (events.length === 0) break;

      const item = events.shift();
      const { type, rank } = item;
      const shell = cardShells[rank];

      // ── header: 이미지+제목+가격 즉시 표시! ──
      if (type === 'header') {
        if (pkTxt) pkTxt.textContent = `${rank}순위 후기 분석 중...`;
        if (rank === 1 && item.condition_desc && !condDescShown) {
          condDescShown = true;
          firstNotice = item.notice || '';
          const cdWrap = document.createElement('div'); cdWrap.className = 'msg-wrap';
          const cdMi = document.createElement('div'); cdMi.className = 'msg-inner';
          const cdAv = document.createElement('div'); cdAv.className = 'av av-ai'; cdAv.textContent = '🛍️';
          const cdDiv = document.createElement('div');
          cdDiv.style.cssText = 'font-size:14px;color:var(--text,#333);line-height:1.7;padding-top:6px;';
          cdMi.appendChild(cdAv); cdMi.appendChild(cdDiv);
          cdWrap.appendChild(cdMi); chat.appendChild(cdWrap);
          await new Promise(resolve => {
            let ci = 0;
            const ct = setInterval(() => {
              cdDiv.textContent += item.condition_desc[ci++];
              smartScroll();
              if (ci >= item.condition_desc.length) { clearInterval(ct); setTimeout(resolve, 200); }
            }, 38);
          });
        }
        const wrap = document.createElement('div'); wrap.className = 'msg-wrap';
        const mi = document.createElement('div'); mi.className = 'msg-inner';
        const av = document.createElement('div'); av.className = 'av av-ai'; av.textContent = '🛍️';
        const bubble = document.createElement('div');
        bubble.className = 'bubble bubble-ai';
        bubble.style.cssText = 'padding:0;width:100%;overflow:hidden;';
        const rankHdr = document.createElement('div');
        rankHdr.style.cssText = 'padding:12px 14px 4px;display:flex;align-items:center;gap:6px;';
        const rankTitle = document.createElement('span');
        rankTitle.style.cssText = 'font-size:12px;color:var(--accent);font-weight:700;';
        rankTitle.textContent = `🏆 픽코3 — ${rank}순위 추천`;
        rankHdr.appendChild(rankTitle);
        // ★ 오리지널/리핏/블로그검증 뱃지 복구!
        if (item.original) {
          const b = document.createElement('span');
          b.style.cssText = 'font-size:10px;padding:2px 7px;border-radius:10px;background:#ffebee;color:#c62828;font-weight:500;';
          b.textContent = '🔴 오리지널';
          rankHdr.appendChild(b);
        } else if (item.direct_blog_verified) {
          const b = document.createElement('span');
          b.style.cssText = 'font-size:10px;padding:2px 7px;border-radius:10px;background:#e3f2fd;color:#1565c0;font-weight:500;';
          b.textContent = '🔵 리핏';
          rankHdr.appendChild(b);
        } else if (item.from_review) {
          const b = document.createElement('span');
          b.style.cssText = 'font-size:10px;padding:2px 7px;border-radius:10px;background:#fff3e0;color:#e65100;font-weight:500;';
          b.textContent = '📝 블로그 검증';
          rankHdr.appendChild(b);
        }
        bubble.appendChild(rankHdr);
        const cardTop = document.createElement('div');
        cardTop.style.cssText = 'display:flex;gap:14px;padding:14px;align-items:flex-end;border-bottom:0.5px solid var(--color-border-tertiary);';
        const thumbWrap = document.createElement('div');
        thumbWrap.style.cssText = 'width:144px;height:144px;border-radius:8px;background:var(--color-background-secondary);flex-shrink:0;position:relative;display:flex;align-items:center;justify-content:center;overflow:hidden;border:0.5px solid var(--color-border-tertiary);';
        thumbWrap.textContent = '🛍️';
        if (item.image_url) {
          const img = document.createElement('img');
          img.src = item.image_url; img.loading = 'lazy';
          img.style.cssText = 'width:100%;height:100%;object-fit:cover;position:absolute;top:0;left:0;';
          img.onerror = () => img.style.display = 'none';
          thumbWrap.appendChild(img);
        }
        cardTop.appendChild(thumbWrap);
        const info = document.createElement('div'); info.style.cssText = 'flex:1;min-width:0;';
        const nameEl = document.createElement('div');
        nameEl.style.cssText = 'font-size:15px;font-weight:500;line-height:1.4;color:var(--color-text-primary);margin-bottom:4px;';
        const nameText = item.name || '';
        if (nameText) {
          await new Promise(resolve => {
            let ci = 0;
            const ct = setInterval(() => {
              nameEl.textContent += nameText[ci++];
              if (ci >= nameText.length) { clearInterval(ct); resolve(); }
            }, 25);
          });
        }
        const priceEl = document.createElement('div');
        priceEl.style.cssText = 'font-size:14px;color:#8a6f5e;font-weight:500;';
        priceEl.textContent = item.price || '';
        info.appendChild(nameEl); info.appendChild(priceEl);
        cardTop.appendChild(info);
        bubble.appendChild(cardTop);
        const placeholder = document.createElement('div');
        placeholder.style.cssText = 'padding:6px 14px 16px;color:#aaa;font-size:13px;';
        placeholder.textContent = '후기 읽는 중...';

        // ★ features 즉시 렌더링 (헤더와 같이 옴!)
        const headerFeatures = item.features || [];
        if (headerFeatures.length > 0) {
          const fSec = document.createElement('div');
          fSec.style.cssText = 'padding:12px 14px;background:var(--color-background-primary);border-top:0.5px solid var(--color-border-tertiary);';
          const fTitle = document.createElement('div');
          fTitle.style.cssText = 'font-size:13px;font-weight:500;color:var(--color-text-secondary);margin-bottom:8px;';
          fTitle.textContent = '이 제품의 특징';
          fSec.appendChild(fTitle);
          headerFeatures.forEach(f => {
            const row = document.createElement('div');
            row.style.cssText = 'font-size:12px;color:var(--color-text-primary);padding:3px 0;line-height:1.6;';
            row.textContent = `• ${f}`;
            fSec.appendChild(row);
          });
          bubble.appendChild(fSec);
        }

        bubble.appendChild(placeholder);
        mi.appendChild(av); mi.appendChild(bubble);
        wrap.appendChild(mi); chat.appendChild(wrap);
        cardShells[rank] = { wrap, bubble, placeholder };
        smartScroll();
        continue;
      }

      // ── CARD_HANDLERS: 등록된 섹션 자동 처리 ──
      if (CARD_HANDLERS[type] && shell) {
        await CARD_HANDLERS[type](item, shell);
        continue;
      }

      // ── card: 상세페이지 버튼 + 더보기 버튼 ──
      if (type === 'card') {
        if (!shell) { currentRank++; break; }
        if (pkTxt) pkTxt.textContent = rank < 3 ? `${rank+1}순위 카드 생성 중...` : '완료!';
        const detailWrap = document.createElement('div');
        detailWrap.setAttribute('data-detail-wrap', '1');
        detailWrap.style.cssText = 'padding:14px;';
        const detailBtn = document.createElement('a');
        detailBtn.href = item.data?.product_url || '#';
        detailBtn.target = '_blank';
        detailBtn.style.cssText = 'display:block;width:100%;text-align:center;padding:12px 0;background:#c2b099;border-radius:20px;font-size:13px;font-weight:500;color:white;text-decoration:none;cursor:pointer;box-sizing:border-box;';
        detailBtn.textContent = '상세페이지 보러가기';
        detailWrap.appendChild(detailBtn);
        shell.bubble.appendChild(detailWrap);

        // ── 비교해드려요 ──
        const _allProds = (item.data?.all_products || []);
        _appendCompareSection(shell.bubble, item.data?.name || '', _allProds);
        const moreWrap = document.createElement('div');
        moreWrap.setAttribute('data-more-wrap', '1');
        moreWrap.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;padding:12px;border-top:1px solid var(--border);opacity:0;';
        const GRADES = ['저가', '중가', '고가', '최고가'];
        GRADES.forEach(grade => {
          const btn = document.createElement('button');
          const isCur = grade === globalGrade;
          btn.style.cssText = `flex:1;min-width:80px;padding:9px 12px;border-radius:20px;font-size:12px;font-weight:500;cursor:pointer;border:1px solid var(--border);background:${isCur?'var(--user-bubble)':'var(--surface)'};color:${isCur?'white':'var(--text)'};`;
          btn.textContent = isCur ? `${grade} 더보기` : `${grade}로 보기`;
          btn.onclick = () => {
            btn.disabled = true; btn.textContent = '불러오는 중...';
            fetch('/more_recommendations', {
              method:'POST', headers:{'Content-Type':'application/json'},
              body: JSON.stringify({grade, cache_key: globalMoreCacheKey})
            }).then(r => r.json()).then(data => {
              if (data.error || !data.products?.length) { btn.textContent = '더 이상 없어요'; return; }
              renderMoreProducts(data.products, grade);
              btn.textContent = isCur ? `${grade} 더보기` : `${grade}로 보기`;
              btn.disabled = false;
              if (data.remaining === 0) { btn.textContent = '✓ 다 봤어요'; btn.disabled = true; }
            }).catch(() => { btn.textContent = '오류'; btn.disabled = false; });
          };
          moreWrap.appendChild(btn);
        });
        shell.bubble.appendChild(moreWrap);
        setTimeout(() => {
          moreWrap.style.transition = 'opacity 0.4s ease';
          moreWrap.style.opacity = '1';
        }, 500);
        currentRank++;
        smartScroll();

        // ★ 3순위 완성 시 총평 렌더링
        if (currentRank === 4 && window._pendingCritiques) {
          _renderCritiques();
        }

        break;
      }
    }

    isProcessing = false;
    if (Object.values(rankEvents).some(q => q.length > 0)) {
      setTimeout(() => processRankEvents(), 50);
    }
  };

  try {
    const res = await fetch('/recommend_stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session: session })
    });

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let item;
        try { item = JSON.parse(line.slice(6)); } catch(e) { continue; }

        // 토큰 → 로딩 메시지
        if (item.type === 'token') {
          if (pkTxt) pkTxt.textContent = `${item.rank}순위 카드 생성 중...`;
        }

        // ★ 픽코 총평 비평 - done 이후 렌더링을 위해 저장
        if (item.type === 'critique' && item.text) {
          window._pendingCritique = item.text;
        }

        // ★ 필드별 이벤트 → rank별 큐에 자동 분류!
        // token/done/error 제외한 모든 type → 새 필드 추가해도 자동 처리!
        if (item.rank && !['token','done','error'].includes(item.type)) {
          const r = item.rank;
          if (item.grade) globalGrade = item.grade;
          if (item.more_cache_key) globalMoreCacheKey = item.more_cache_key;
          if (item.match_keywords) globalMatchKeywords = item.match_keywords;
          if (rankEvents[r]) {
            rankEvents[r].push(item);
            processRankEvents();
          }
        }

        // 완료
        if (item.type === 'done') {
          if (loader._phase1Timer) clearInterval(loader._phase1Timer);
          const sl = document.getElementById('pk-lbl');
          const sb = document.getElementById('pk-bar');
          if (sl) sl.classList.add('done');
          if (sb) { sb.style.width = '100%'; sb.classList.add('done'); }
          setTimeout(() => loader.remove(), 200);
          if (globalGrade) session.grade = globalGrade;
          if (globalMoreCacheKey) session.more_cache_key = globalMoreCacheKey;
          // ★ 맥락 대화용 session 업데이트
          if (item.session_update) {
            if (item.session_update.last_products) session.last_products = item.session_update.last_products;
            if (item.session_update.context_key) session.context_key = item.session_update.context_key;
            if (item.session_update.user_context) session.user_context = item.session_update.user_context;
          }

          // ★ done 받으면 무조건 더보기 버튼 활성화! (1순위만 나와도 OK)
          setTimeout(() => {
            chat.querySelectorAll('[data-more-wrap]').forEach(el => {
              el.style.transition = 'opacity 0.4s ease';
              el.style.opacity = '1';
            });
            if (pkTxt) pkTxt.textContent = '완료!';
          }, 200);

          // ★ 총평: 각 카드마다 하나씩
          const critiques = item.critiques || [];
          if (critiques.length > 0) {
            window._pendingCritiques = critiques;
            if (currentRank > 3) _renderCritiques();
          }

          smartScroll();
        }

        // 오류
        if (item.type === 'error') {
          if (loader._phase1Timer) clearInterval(loader._phase1Timer);
          loader.remove();
          addAiMsg('추천 중 오류가 발생했어요. 다시 시도해주세요.');
        }
      }
    }
  } catch(e) {
    if (loader._phase1Timer) clearInterval(loader._phase1Timer);
    loader.remove();
    addAiMsg('연결 오류가 발생했어요. 다시 시도해주세요.');
  }
}
