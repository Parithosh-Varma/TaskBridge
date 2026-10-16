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
  var INK = "248,239,220";

  var reduced = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var mobile = window.innerWidth < 640;
  var CELL_W = mobile ? 16 : 12;
  var CELL_H = mobile ? 25 : 19;
  var DPR_CAP = mobile ? 1.5 : 2;

  var W = 0, H = 0, DPR = 1, cols = 0, rows = 0, aspect = 1;
  var sprites = new Map();
  var fontPx = 0;
  var gradKey = -1, bgGrad = null;

  // Scroll-synced palette stops: [sp, topRGB, bottomRGB].
  var STOPS = [
    [0.00, [198, 63, 12], [233, 119, 26]],
    [0.30, [148, 50, 13], [184, 82, 15]],
    [0.55, [70, 25, 11], [104, 41, 13]],
    [0.78, [21, 10, 17], [36, 15, 23]],
    [1.00, [10, 5, 4], [22, 10, 6]]
  ];
  var PHASES = ["EYE", "RINGS", "ROWS", "FLOW", "EMBER"];
  var ACT_T = [6.0, 20.0, 34.0, 48.0, 62.0]; // static timestamps per act (reduced motion)

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

  function sprite(idx, alvl) {
    var key = idx * 8 + alvl;
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
    var alpha = 0.14 + 0.86 * (alvl / 7);
    g.fillStyle = "rgba(" + INK + "," + alpha.toFixed(3) + ")";
    g.fillText(RAMP[idx], CELL_W / 2, CELL_H / 2 + 1);
    sprites.set(key, c);
    return c;
  }

  /* Designed darkness field. px is aspect-corrected, py is not; units ~ vh/2. */
  function field(px, py, t, sp) {
    var wEye = 1 - ss(0.10, 0.20, sp);
    var wRings = ss(0.13, 0.23, sp) * (1 - ss(0.33, 0.43, sp));
    var wRows = ss(0.37, 0.47, sp) * (1 - ss(0.62, 0.72, sp));
    var wFlow = ss(0.64, 0.74, sp) * (1 - ss(0.86, 0.94, sp));
    var wEmber = ss(0.88, 0.96, sp);
    var dark = 0, d, i;

    if (wEye > 0.01) {
      var a = 0.46 * Math.min(1, Math.max(0.30, aspect / 1.78));
      var cy = -0.17 + 0.004 * Math.sin(t * 0.5);
      var u = px / a;
      var inX = Math.abs(u) < 1.04 ? 1 : 0;
      var uu = u < -1.3 ? -1.3 : u > 1.3 ? 1.3 : u;
      var curve = cy + 0.20 * uu * uu;
      var band = (1 - ss(0.008, 0.036, Math.abs(py - curve))) * inX;
      var lash = 0, lxs = [-0.55, -0.18, 0.18, 0.55];
      for (i = 0; i < 4; i++) {
        var lx = lxs[i] * a;
        var ly = cy + 0.20 * lxs[i] * lxs[i] + 0.007;
        d = sdSeg(px, py, lx, ly, lx + lxs[i] * 0.05, ly + 0.075);
        var seg = 1 - ss(0.005, 0.016, d);
        if (seg > lash) lash = seg;
      }
      var above = curve - py, below = py - curve, shade = 0;
      if (above > 0) shade = Math.exp(-above * 7.0) * 0.38 * inX;
      else if (below > 0) shade = Math.exp(-below * 9.0) * 0.18 * inX;
      var eye = band;
      if (lash > eye) eye = lash;
      if (shade > eye) eye = shade;
      dark += wEye * eye;
    }

    if (wRings > 0.01) {
      var rx = px, ry = py - 0.03;
      var r = Math.sqrt(rx * rx + ry * ry);
      var v = (r * 4.6 - t * 0.22) % 1; if (v < 0) v += 1;
      var ring = (1 - ss(0.02, 0.13, Math.abs(v - 0.5))) * Math.exp(-r * 1.7);
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
      var chev = (1 - ss(0.03, 0.15, Math.abs(f - 0.5))) * 0.9 * Math.exp(-Math.abs(py - yc) * 1.6);
      var mdx = px - 0.44 * Math.min(1, aspect * 0.62), mdy = py + 0.24;
      var mr = Math.sqrt(mdx * mdx + mdy * mdy);
      var crater = 0.72 + 0.28 * Math.sin(px * 95.0) * Math.sin(py * 87.0);
      var disc = (1 - ss(0.143, 0.159, mr)) * crater;
      dark += wFlow * (chev > disc ? chev : disc);
    }
    var starAmp = wFlow > wEmber ? wFlow : wEmber;
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

    if (wEmber > 0.01) {
      var er = Math.sqrt(px * px + (py + 0.02) * (py + 0.02));
      var ering = 1 - ss(0.006, 0.045, Math.abs(er - 0.21));
      var seal = (1 - ss(0.008, 0.05, er)) * 0.85;
      dark += wEmber * (ering > seal ? ering : seal);
    }

    dark += 0.10 * (0.5 + 0.5 * Math.sin(px * 47 + t * 0.8) * Math.sin(py * 53 - t * 0.7));
    return clamp01(0.05 + dark * 0.92);
  }

  function phaseOf(sp, t) {
    var w = [
      1 - ss(0.10, 0.20, sp),
      ss(0.13, 0.23, sp) * (1 - ss(0.33, 0.43, sp)),
      ss(0.37, 0.47, sp) * (1 - ss(0.62, 0.72, sp)),
      ss(0.64, 0.74, sp) * (1 - ss(0.86, 0.94, sp)),
      ss(0.88, 0.96, sp)
    ];
    var bi = 0;
    for (var i = 1; i < 5; i++) if (w[i] > w[bi]) bi = i;
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
        idx = Math.min(LEVELS, (Math.pow(L, 0.8) * (LEVELS + 1)) | 0);
        if (idx === 0) continue;
        al = (L * 8) | 0; if (al > 7) al = 7;
        ctx.drawImage(sprite(idx, al), cI * CELL_W, y, CELL_W, CELL_H);
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
    var ids = ["top", "orchestrate", "coordinate", "execute", "return"];
    if (e.key >= "0" && e.key <= "4") {
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
