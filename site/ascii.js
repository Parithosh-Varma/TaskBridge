/* ASCII halftone engine: procedural luminance field -> character grid on canvas.
   No per-frame allocation: fixed blob table, sprite cache, direct math per cell. */
(function () {
  "use strict";
  var canvas = document.getElementById("field");
  var ctx = canvas.getContext("2d");
  var RAMP = " .:-=+*xX#%@";
  var LEVELS = RAMP.length - 1; // 11
  var INK = "246,233,207"; // cream rgb triplet for rgba() composition

  var reduced = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var mobile = window.innerWidth < 640;
  var CELL_W = mobile ? 16 : 12;
  var CELL_H = mobile ? 25 : 19;
  var DPR_CAP = mobile ? 1.5 : 2;

  var W = 0, H = 0, DPR = 1, cols = 0, rows = 0, aspect = 1;
  var bgGrad = null;
  var sprites = new Map(); // key: idx*8+alphaLvl -> canvas
  var fontPx = 0;

  // Deterministic blobs: a slow "sleeping-form" mass + satellites.
  var NB = 5;
  var BX = new Float64Array(NB), BY = new Float64Array(NB),
      BR = new Float64Array(NB), BA = new Float64Array(NB),
      BS = new Float64Array(NB), BP = new Float64Array(NB);
  var seed = 20261016;
  function rnd() {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 4294967296;
  }
  var basePos = [[0.50, 0.40], [0.30, 0.55], [0.70, 0.55], [0.50, 0.66], [0.50, 0.24]];
  for (var i = 0; i < NB; i++) {
    BX[i] = basePos[i][0]; BY[i] = basePos[i][1];
    BR[i] = 0.16 + rnd() * 0.14;
    BA[i] = 0.55 + rnd() * 0.45;
    BS[i] = 0.10 + rnd() * 0.16;
    BP[i] = rnd() * 6.283;
  }

  var mx = 0.5, my = 0.42, emx = 0.5, emy = 0.42; // eased mouse (normalized)
  var inView = true, tabVisible = !document.hidden, rafId = 0, t0 = 0;

  function makeFont(px) {
    return "600 " + px + 'px "Space Mono",ui-monospace,Menlo,Consolas,monospace';
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
    bgGrad = ctx.createLinearGradient(0, 0, 0, H);
    bgGrad.addColorStop(0, "#B93A0E");
    bgGrad.addColorStop(0.55, "#D1540F");
    bgGrad.addColorStop(1, "#E8761A");
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

  function clamp01(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }

  function field(nx, ny, t, scrollP) {
    // Gentle domain warp so the composition breathes.
    var wx = nx + 0.16 * Math.sin(ny * 4.2 + t * 0.32) + scrollP * 0.08 * Math.sin(ny * 9.0 - t * 0.21);
    var wy = ny + 0.16 * Math.sin(nx * 3.1 - t * 0.27);
    var ax = wx * aspect;
    var f = 0, dx, dy, q;
    for (var i = 0; i < NB; i++) {
      var cx = (BX[i] + 0.07 * Math.sin(t * BS[i] + BP[i])) * aspect;
      var cy = BY[i] + 0.06 * Math.sin(t * BS[i] * 1.3 + BP[i] * 1.7);
      dx = ax - cx; dy = wy - cy;
      q = (dx * dx + dy * dy) / (BR[i] * BR[i] * aspect);
      if (q < 6) f += BA[i] * Math.exp(-q * 2.2);
    }
    // Flowing strata + fine grain over the masses.
    f += 0.20 * Math.sin(wx * 6.0 + t * 0.5) * Math.sin(wy * 5.0 - t * 0.38);
    f += 0.10 * Math.sin((wx + wy) * 11.0 - t * 0.62);
    f += 0.05 * Math.sin(wx * 31.0 + wy * 27.0 + t * 0.9);
    // Soft vignette: composition gathers toward upper-center, fades at edges.
    var vx = (nx - 0.5) * 1.5, vy = (ny - 0.44) * 1.7;
    f *= Math.exp(-(vx * vx + vy * vy) * 0.5);
    // Cursor glow: characters thicken near the pointer.
    var mdx = nx - emx, mdy = (ny - emy) * aspect;
    var md = mdx * mdx + mdy * mdy;
    if (md < 0.09) f += 0.30 * Math.exp(-md * 28);
    // Scroll deepens contrast, revealing more of the composition.
    f *= (1 + 0.35 * scrollP);
    return clamp01(0.12 + f * 0.62);
  }

  function frame(now) {
    if (!inView || !tabVisible) { rafId = 0; return; }
    if (t0 === 0) t0 = now;
    var t = (now - t0) / 1000;
    emx += (mx - emx) * 0.06;
    emy += (my - emy) * 0.06;

    var maxS = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
    var sp = window.scrollY / maxS;
    if (sp < 0) sp = 0; else if (sp > 1) sp = 1;
    var ft = t * (0.55 + 0.9 * sp) + sp * 5.0;

    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, W, H);

    var y, x, nx, ny, L, q, idx, al;
    for (var r = 0; r < rows; r++) {
      ny = (r + 0.5) / rows;
      y = r * CELL_H;
      for (var cI = 0; cI < cols; cI++) {
        nx = (cI + 0.5) / cols;
        // Subtle parallax: sampling drifts against pointer and scroll.
        L = field(nx - (emx - 0.5) * 0.05, ny - (emy - 0.5) * 0.05 - sp * 0.06, ft, sp);
        q = L < 0 ? 0 : L > 1 ? 1 : L;
        idx = Math.min(LEVELS, (Math.pow(q, 0.8) * (LEVELS + 1)) | 0);
        if (idx === 0) continue; // ramp space: leave background bare
        al = (q * 8) | 0; if (al > 7) al = 7;
        x = cI * CELL_W;
        ctx.drawImage(sprite(idx, al), x, y, CELL_W, CELL_H);
      }
    }
    rafId = requestAnimationFrame(frame);
  }

  function start() {
    if (rafId || !inView || !tabVisible) return;
    t0 = 0;
    rafId = requestAnimationFrame(frame);
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
    new ResizeObserver(function () { resize(); if (reduced) renderOnce(); }).observe(document.body);
  }
  window.addEventListener("resize", function () { resize(); if (reduced) renderOnce(); });
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
  }
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(function () { sprites.clear(); if (reduced) renderOnce(); });
  }

  function renderOnce() {
    // Static fallback: one composed frame, cursor centered, mid scroll-phase.
    emx = 0.5; emy = 0.42;
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, W, H);
    var ft = 8.0, sp = 0.25;
    for (var r = 0; r < rows; r++) {
      var ny = (r + 0.5) / rows, y = r * CELL_H;
      for (var cI = 0; cI < cols; cI++) {
        var nx = (cI + 0.5) / cols;
        var L = field(nx, ny, ft, sp);
        var idx = Math.min(LEVELS, (Math.pow(L, 0.8) * (LEVELS + 1)) | 0);
        if (idx === 0) continue;
        var al = (L * 8) | 0; if (al > 7) al = 7;
        ctx.drawImage(sprite(idx, al), cI * CELL_W, y, CELL_W, CELL_H);
      }
    }
  }

  resize();
  if (reduced) renderOnce();
  else start();
})();
