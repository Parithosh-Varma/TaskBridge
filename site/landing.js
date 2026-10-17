/* landing.js — dispatch-board relay animation + scroll reveal (index.html only). */
(function(){
  var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* scroll reveal */
  var rvs = [].slice.call(document.querySelectorAll('.rv'));
  if (reduce || !('IntersectionObserver' in window)) {
    rvs.forEach(function(el){ el.classList.add('in'); });
  } else {
    var io = new IntersectionObserver(function(entries){
      entries.forEach(function(e){
        if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
      });
    }, { threshold: .12, rootMargin: '0px 0px -6% 0px' });
    rvs.forEach(function(el){ io.observe(el); });
  }

  /* relay board: one task's round trip, on loop */
  var board = document.querySelector('.board');
  if (!board) return;
  var packet   = board.querySelector('.packet.main');
  var ret      = board.querySelector('.packet.ret');
  var log      = board.querySelector('.board-log');
  var stations = [].slice.call(board.querySelectorAll('.station'));
  var POS = ['16.66%', '50%', '83.33%'];
  var steps = [
    { pos:0, cls:'st-pending', txt:'t-3f2a · pending',   st:0, line:'▸ submit_task → t-3f2a · priority 5' },
    { pos:1, cls:'st-pending', txt:'t-3f2a · queued',    st:1, line:'▸ queued in tasks.db · survives restarts', lc:'warn' },
    { pos:2, cls:'st-run',     txt:'t-3f2a · running',   st:2, line:'◷ worktree br/t-3f2a · opencode run · streaming', lc:'run' },
    { pos:2, cls:'st-done',    txt:'t-3f2a · completed', st:2, line:'✓ completed · 14 files · tests green', lc:'ok' }
  ];
  var RET_LINE = '↩ get_task_result → summary + diff';

  function setChip(s){
    packet.className = 'packet main ' + s.cls;
    packet.textContent = s.txt;
    packet.style.left = POS[s.pos];
    stations.forEach(function(el, i){ el.classList.toggle('on', i === s.st); });
  }
  function addLine(t, cls){
    var d = document.createElement('div');
    d.className = 'ln' + (cls ? ' ' + cls : '');
    d.textContent = t;
    log.appendChild(d);
    while (log.children.length > 5) log.removeChild(log.firstChild);
  }

  if (reduce) {
    setChip(steps[3]);
    steps.forEach(function(s){ addLine(s.line, s.lc); });
    ret.style.left = POS[0];
    ret.style.opacity = '1';
    addLine(RET_LINE, 'ok');
    return;
  }

  var sleep = function(ms){ return new Promise(function(r){ setTimeout(r, ms); }); };
  (async function loop(){
    for (;;) {
      log.innerHTML = '';
      ret.style.transition = 'none';
      ret.style.opacity = '0';
      ret.style.left = POS[2];
      packet.style.transition = 'none';
      setChip(steps[0]);
      await sleep(80);
      packet.style.transition = '';
      ret.style.transition = '';
      addLine(steps[0].line);
      await sleep(1250);
      setChip(steps[1]); addLine(steps[1].line, steps[1].lc);
      await sleep(1500);
      setChip(steps[2]); addLine(steps[2].line, steps[2].lc);
      await sleep(2000);
      setChip(steps[3]); addLine(steps[3].line, steps[3].lc);
      await sleep(700);
      ret.style.opacity = '1';
      ret.style.left = POS[0];
      await sleep(850);
      addLine(RET_LINE, 'ok');
      await sleep(2600);
    }
  })();
})();
