/* ASCII scroll-composition engine.
   Scroll phase cross-fades four designed SDF forms (eye -> rings -> ledger ->
   current -> ember seal) while the background gradient lerps through matching
   color stops. No per-frame allocation: fixed scratch vars, sprite cache. */
(function () {
  "use strict";
  var canvas = document.getElementById("field");
  var ctx = canvas.getContext("2d");
  var RAMP = " .:-=+*xX#%@";
  var LEVELS = RAMP.length - 1;
  var INK = "255,250,243"; // reference cream
  var GOLD = "244,211,58"; // reference gold for densest cells

  var reduced = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var mobile = window.innerWidth < 640;
  var CELL_W = mobile ? 13 : 10;
  var CELL_H = mobile ? 21 : 16;
  var DPR_CAP = mobile ? 1.5 : 2;

  var W = 0, H = 0, DPR = 1, cols = 0, rows = 0, aspect = 1;
  var sprites = new Map();
  var fontPx = 0;
  var gradKey = -1, bgGrad = null;

  // Scroll-synced palette stops: [sp, topRGB, bottomRGB].
  // Sampled from the reference: tangerine day -> violet dusk -> indigo night,
  // with an ember seam for the phoenix and near-black for the finale.
  var STOPS = [
    [0.00, [224, 80, 45], [244, 150, 58]],
    [0.28, [176, 62, 44], [208, 104, 52]],
    [0.48, [84, 30, 66], [110, 44, 80]],
    [0.68, [30, 16, 60], [44, 24, 84]],
    [0.84, [40, 14, 26], [66, 22, 34]],
    [1.00, [10, 5, 8], [22, 10, 12]]
  ];
  var PHASES = ["EYE", "RINGS", "ROWS", "FLOW", "RISE", "CLAUDE"];
  var ACT_T = [6.0, 20.0, 34.0, 48.0, 55.0, 62.0]; // static timestamps per act (reduced motion)

  var mx = 0.5, my = 0.42, emx = 0.5, emy = 0.42;
  var inView = true, tabVisible = !document.hidden, rafId = 0, t0 = 0;
  var heroIn = document.getElementById("heroIn");
  var phaseEl = document.getElementById("phase");
  var statEl = document.getElementById("stat");
  var lastStat = 0, lastPhase = "";
  var revs = Array.prototype.slice.call(document.querySelectorAll(".rev"));
  var yr = document.getElementById("yr");
  if (yr) yr.textContent = new Date().getFullYear();

  function makeFont(px) {
    return "600 " + px + 'px "Space Mono",ui-monospace,Menlo,Consolas,monospace';
  }
  function ss(a, b, x) {
    var v = (x - a) / (b - a);
    v = v < 0 ? 0 : v > 1 ? 1 : v;
    return v * v * (3 - 2 * v);
  }
  function clamp01(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
  function sdSeg(px, py, ax, ay, bx, by) {
    var vx = bx - ax, vy = by - ay;
    var wx = px - ax, wy = py - ay;
    var denom = vx * vx + vy * vy;
    var k = denom > 0 ? (wx * vx + wy * vy) / denom : 0;
    k = k < 0 ? 0 : k > 1 ? 1 : k;
    var dx = wx - vx * k, dy = wy - vy * k;
    return Math.sqrt(dx * dx + dy * dy);
  }

  function resize() {
    DPR = Math.min(window.devicePixelRatio || 1, DPR_CAP);
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = Math.round(W * DPR);
    canvas.height = Math.round(H * DPR);
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    aspect = W / H;
    cols = Math.max(1, Math.ceil(W / CELL_W));
    rows = Math.max(1, Math.ceil(H / CELL_H));
    fontPx = Math.round(CELL_H * 0.78);
    sprites.clear();
    gradKey = -1;
  }

  function palette(sp) {
    var i = 0;
    while (i < STOPS.length - 2 && sp > STOPS[i + 1][0]) i++;
    var a = STOPS[i], b = STOPS[i + 1];
    var k = (sp - a[0]) / (b[0] - a[0]);
    k = k < 0 ? 0 : k > 1 ? 1 : k;
    var top = [0, 1, 2].map(function (j) { return Math.round(a[1][j] + (b[1][j] - a[1][j]) * k); });
    var bot = [0, 1, 2].map(function (j) { return Math.round(a[2][j] + (b[2][j] - a[2][j]) * k); });
    return [top, bot];
  }

  function paintBg(sp) {
    var key = Math.round(sp * 48);
    if (key !== gradKey) {
      var pal = palette(sp);
      bgGrad = ctx.createLinearGradient(0, 0, 0, H);
      bgGrad.addColorStop(0, "rgb(" + pal[0][0] + "," + pal[0][1] + "," + pal[0][2] + ")");
      bgGrad.addColorStop(1, "rgb(" + pal[1][0] + "," + pal[1][1] + "," + pal[1][2] + ")");
      gradKey = key;
    }
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, W, H);
  }

  function sprite(idx, alvl, tone) {
    var key = idx * 8 + alvl + (tone ? 96 : 0);
    var s = sprites.get(key);
    if (s) return s;
    var c = document.createElement("canvas");
    c.width = Math.ceil(CELL_W * DPR);
    c.height = Math.ceil(CELL_H * DPR);
    var g = c.getContext("2d");
    g.setTransform(DPR, 0, 0, DPR, 0, 0);
    g.font = makeFont(fontPx);
    g.textAlign = "center";
    g.textBaseline = "middle";
    var alpha = 0.30 + 0.70 * (alvl / 7);
    g.fillStyle = tone ? "rgba(" + GOLD + "," + alpha.toFixed(3) + ")"
                       : "rgba(" + INK + "," + alpha.toFixed(3) + ")";
    g.fillText(RAMP[idx], CELL_W / 2, CELL_H / 2 + 1);
    sprites.set(key, c);
    return c;
  }

  /* Designed darkness field. px is aspect-corrected, py is not; units ~ vh/2. */
  function field(px, py, t, sp) {
    var wEye = 1 - ss(0.10, 0.18, sp);
    var wRings = ss(0.13, 0.21, sp) * (1 - ss(0.30, 0.37, sp));
    var wRows = ss(0.31, 0.39, sp) * (1 - ss(0.49, 0.57, sp));
    var wFlow = ss(0.49, 0.57, sp) * (1 - ss(0.63, 0.71, sp));
    var wPhx = ss(0.65, 0.72, sp) * (1 - ss(0.82, 0.88, sp));
    var wEmber = ss(0.86, 0.93, sp);
    var dark = 0, d, i;

    if (wEye > 0.01) {
      var a = 0.58 * Math.min(1, Math.max(0.32, aspect / 1.78));
      var cy = -0.28 + 0.004 * Math.sin(t * 0.5);
      var u = px / a;
      var inX = Math.abs(u) < 1.04 ? 1 : 0;
      var uu = u < -1.3 ? -1.3 : u > 1.3 ? 1.3 : u;
      var curve = cy + 0.20 * uu * uu;
      var band = (1 - ss(0.010, 0.050, Math.abs(py - curve))) * inX;
      var lash = 0, lxs = [-0.60, -0.30, 0.0, 0.30, 0.60];
      for (i = 0; i < 5; i++) {
        var lx = lxs[i] * a;
        var ly = cy + 0.20 * lxs[i] * lxs[i] + 0.007;
        d = sdSeg(px, py, lx, ly, lx + lxs[i] * 0.05, ly + 0.09);
        var seg = 1 - ss(0.005, 0.016, d);
        if (seg > lash) lash = seg;
      }
      var above = curve - py, below = py - curve, shade = 0;
      if (above > 0) shade = Math.exp(-above * 7.0) * 0.35 * inX;
      else if (below > 0) shade = Math.exp(-below * 9.0) * 0.15 * inX;
      var eye = band;
      if (lash > eye) eye = lash;
      if (shade > eye) eye = shade;
      // Flanking cloud banks low left/right: frame the wordmark in clear space.
      var bxx = 0.66 * Math.min(1, Math.max(0.35, aspect / 1.5));
      var bdx = Math.abs(px) - bxx, bdy = py - 0.44 - 0.01 * Math.sin(t * 0.4);
      var bank = 0.42 * Math.exp(-((bdx * bdx) / 0.040 + (bdy * bdy) / 0.017));
      if (bank > eye) eye = bank;
      dark += wEye * eye;
    }

    if (wRings > 0.01) {
      var rx = px, ry = py - 0.03;
      var r = Math.sqrt(rx * rx + ry * ry);
      var v = (r * 5.0 - t * 0.22) % 1; if (v < 0) v += 1;
      var ring = (1 - ss(0.03, 0.18, Math.abs(v - 0.5))) * Math.exp(-r * 1.5);
      var dot = 1 - ss(0.008, 0.045, r);
      var rings = ring > dot ? ring : dot;
      dark += wRings * rings;
    }

    if (wRows > 0.01) {
      var N = aspect < 0.8 ? 5 : 7;
      var hw = Math.max(0.20, 0.54 * aspect / 1.78);
      var rh = 0.60 / N;
      var active = Math.floor(t * 0.55) % N;
      var rows = 0;
      for (i = 0; i < N; i++) {
        var yi = -0.30 + (i + 0.5) * rh + 0.004 * Math.sin(t * 0.7 + i * 1.7);
        var dx = Math.abs(px) - hw, dy = Math.abs(py - yi) - rh * 0.30;
        var qx = dx > 0 ? dx : 0, qy = dy > 0 ? dy : 0;
        d = Math.sqrt(qx * qx + qy * qy) + Math.min(dx > dy ? dx : dy, 0);
        var bar = 1 - ss(-0.004, 0.012, d);
        var isA = (i === active) ? 1 : 0;
        var ddx = px - (-hw + 0.07), ddy = py - yi;
        var sdot = (1 - ss(0.008, 0.026, Math.sqrt(ddx * ddx + ddy * ddy))) * (isA ? 1 : 0.35);
        var cell = bar * (isA ? 0.95 : 0.72);
        if (sdot > cell) cell = sdot;
        if (cell > rows) rows = cell;
      }
      dark += wRows * rows;
    }

    var star = 0;
    if (wFlow > 0.01) {
      var yc = 0.04;
      var sv = px - 0.42 * Math.abs(py - yc);
      var f = (sv * 2.4 - t * 0.32) % 1; if (f < 0) f += 1;
      var chev = (1 - ss(0.03, 0.15, Math.abs(f - 0.5))) * Math.exp(-Math.abs(py - yc) * 1.3);
      var mdx = px - 0.44 * Math.min(1, aspect * 0.62), mdy = py + 0.24;
      var mr = Math.sqrt(mdx * mdx + mdy * mdy);
      var crater = 0.72 + 0.28 * Math.sin(px * 95.0) * Math.sin(py * 87.0);
      var disc = (1 - ss(0.143, 0.159, mr)) * crater;
      dark += wFlow * (chev > disc ? chev : disc);
    }
    var starAmp = wFlow > wPhx ? wFlow : wPhx;
    if (wEmber > starAmp) starAmp = wEmber;
    if (starAmp > 0.01) {
      var gx = Math.floor(px * 230), gy = Math.floor(py * 230);
      var h = Math.sin(gx * 12.9898 + gy * 78.233) * 43758.5;
      h = h - Math.floor(h);
      if (h > 0.986) {
        var tw = 0.55 + 0.45 * Math.sin(t * 2.2 + h * 40.0);
        star = ((h - 0.986) / 0.014) * 0.95 * tw;
      }
      dark += starAmp * star;
    }

    if (wPhx > 0.01 && typeof PHOENIX !== "undefined") {
      // Sampled user artwork: nearest-neighbor density lookup with a slow
      // drift so the print feels alive. ' '=0, '+'=0.5, '='=0.9.
      var k = Math.min(0.96 * aspect / 1.818, 0.86);
      var ox = 0.010 * Math.sin(t * 0.30), oy = 0.008 * Math.cos(t * 0.23);
      var ax = (px - ox) / k, ay = (py - 0.02 - oy) / k;
      var col = Math.floor((ax / 1.818 + 0.5) * PHOENIX.w);
      var prow = Math.floor((ay + 0.5) * PHOENIX.h);
      var pd = 0;
      if (col >= 0 && col < PHOENIX.w && prow >= 0 && prow < PHOENIX.h) {
        var ch = PHOENIX.rows[prow].charCodeAt(col);
        pd = ch === 61 ? 0.9 : ch === 43 ? 0.5 : 0;
      }
      dark += wPhx * pd;
    }

    if (wEmber > 0.01) {
      // Claude starburst, upper-right like a rising sun: 12 narrow tapered
      // rays, deep valleys, slow rotation, dense core.
      var sx = px - 0.40 * Math.min(1, aspect * 0.62), sy = py + 0.24;
      var er = Math.sqrt(sx * sx + sy * sy);
      var ang = Math.atan2(sy, sx) + t * 0.05;
      var rays = Math.pow(Math.abs(Math.cos(6 * ang)), 1.6);
      var rStar = 0.20 * (0.30 + 0.70 * rays);
      var star = 1 - ss(-0.004, 0.006, er - rStar);
      dark += wEmber * star;
    }

    dark += 0.05 * (0.5 + 0.5 * Math.sin(px * 47 + t * 0.8) * Math.sin(py * 53 - t * 0.7));
    return clamp01(0.015 + dark * 0.98);
  }

  function phaseOf(sp, t) {
    var w = [
      1 - ss(0.10, 0.18, sp),
      ss(0.13, 0.21, sp) * (1 - ss(0.30, 0.37, sp)),
      ss(0.31, 0.39, sp) * (1 - ss(0.49, 0.57, sp)),
      ss(0.49, 0.57, sp) * (1 - ss(0.63, 0.71, sp)),
      ss(0.65, 0.72, sp) * (1 - ss(0.82, 0.88, sp)),
      ss(0.86, 0.93, sp)
    ];
    var bi = 0;
    for (var i = 1; i < 6; i++) if (w[i] > w[bi]) bi = i;
    return bi;
  }

  function scrollP() {
    var maxS = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
    var sp = window.scrollY / maxS;
    return sp < 0 ? 0 : sp > 1 ? 1 : sp;
  }

  function renderCells(t, sp) {
    var r, cI, nx, ny, L, idx, al;
    for (r = 0; r < rows; r++) {
      ny = (r + 0.5) / rows;
      var y = r * CELL_H;
      for (cI = 0; cI < cols; cI++) {
        nx = (cI + 0.5) / cols;
        var px = (nx - (emx - 0.5) * 0.04 - 0.5) * aspect;
        var py = (ny - (emy - 0.5) * 0.04 - sp * 0.05 - 0.5);
        L = field(px, py, t, sp);
        idx = Math.min(LEVELS, (Math.pow(L, 0.65) * (LEVELS + 1)) | 0);
        if (idx === 0) continue;
        al = (L * 8) | 0; if (al > 7) al = 7;
        ctx.drawImage(sprite(idx, al, idx >= 9 ? 1 : 0), cI * CELL_W, y, CELL_W, CELL_H);
      }
    }
  }

  function chrome(sp, t, now) {
    var p0 = window.scrollY / Math.max(1, window.innerHeight);
    if (p0 > 1) p0 = 1;
    if (heroIn) {
      heroIn.style.transform = "translate3d(0," + (-70 * p0).toFixed(1) + "px,0) scale(" + (1 - 0.08 * p0).toFixed(3) + ")";
      heroIn.style.opacity = (1 - 0.9 * p0).toFixed(2);
    }
    if (now - lastStat > 250) {
      lastStat = now;
      var bi = phaseOf(sp, t);
      if (PHASES[bi] !== lastPhase) {
        lastPhase = PHASES[bi];
        if (phaseEl) phaseEl.textContent = lastPhase.toLowerCase();
      }
      if (statEl) statEl.textContent = lastPhase + " · " + String(Math.round(sp * 100)).padStart(3, "0") + "%";
    }
  }

  function frame(now) {
    if (!inView || !tabVisible) { rafId = 0; return; }
    if (t0 === 0) t0 = now;
    var t = (now - t0) / 1000;
    emx += (mx - emx) * 0.06;
    emy += (my - emy) * 0.06;
    var sp = scrollP();
    paintBg(sp);
    renderCells(t, sp);
    chrome(sp, t, now);
    rafId = requestAnimationFrame(frame);
  }

  function start() {
    if (rafId || !inView || !tabVisible) return;
    t0 = 0;
    rafId = requestAnimationFrame(frame);
  }

  function renderStatic(sp) {
    var bi = phaseOf(sp, 0);
    emx = 0.5; emy = 0.42;
    paintBg(sp);
    renderCells(ACT_T[bi], sp);
    chrome(sp, ACT_T[bi], Date.now());
  }

  window.addEventListener("mousemove", function (e) {
    mx = e.clientX / W; my = e.clientY / H;
  }, { passive: true });
  window.addEventListener("touchmove", function (e) {
    if (e.touches.length) {
      mx = e.touches[0].clientX / W; my = e.touches[0].clientY / H;
    }
  }, { passive: true });

  if ("ResizeObserver" in window) {
    new ResizeObserver(function () { resize(); if (reduced) renderStatic(scrollP()); }).observe(document.body);
  }
  window.addEventListener("resize", function () { resize(); if (reduced) renderStatic(scrollP()); });
  var scrollT = 0;
  window.addEventListener("scroll", function () {
    if (!reduced) return;
    var now = Date.now();
    if (now - scrollT > 120) { scrollT = now; renderStatic(scrollP()); }
  }, { passive: true });
  document.addEventListener("visibilitychange", function () {
    if (reduced) return;
    tabVisible = !document.hidden;
    if (tabVisible) start();
  });
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) {
      if (reduced) return;
      inView = entries[0].isIntersecting;
      if (inView) start();
    }).observe(canvas);
    if (!reduced) {
      var io2 = new IntersectionObserver(function (entries) {
        for (var i = 0; i < entries.length; i++) {
          if (entries[i].isIntersecting) {
            entries[i].target.classList.add("in");
            io2.unobserve(entries[i].target);
          }
        }
      }, { threshold: 0.25 });
      for (var k = 0; k < revs.length; k++) io2.observe(revs[k]);
    } else {
      for (var j = 0; j < revs.length; j++) revs[j].classList.add("in");
    }
  } else {
    for (var m = 0; m < revs.length; m++) revs[m].classList.add("in");
  }
  document.addEventListener("keydown", function (e) {
    var ids = ["top", "orchestrate", "coordinate", "execute", "rise", "return"];
    if (e.key >= "0" && e.key <= "5") {
      var el = document.getElementById(ids[+e.key]);
      if (el) el.scrollIntoView({ behavior: reduced ? "auto" : "smooth" });
    }
  });
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(function () {
      sprites.clear();
      if (reduced) renderStatic(scrollP());
    });
  }

  resize();
  if (reduced) renderStatic(0);
  else start();
})();
