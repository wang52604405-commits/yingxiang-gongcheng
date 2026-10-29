(function () {
  "use strict";
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = window.matchMedia("(pointer: fine)").matches;
  const SCENE_KEY = "yx-bg-scene";
  const SCENES = ["ocean", "water", "build", "muni", "power"];

  function normalizeScene(s) {
    s = (s || "").toLowerCase().replace(/^prof-/, "");
    if (s === "river") s = "water";
    if (s === "bridge" || s === "overpass") s = "muni";
    if (s === "tower" || s === "pylon") s = "power";
    if (s === "skyline" || s === "building") s = "build";
    return SCENES.indexOf(s) >= 0 ? s : "ocean";
  }

  function readStoredScene() {
    try {
      const fromHash = (location.hash || "").replace(/^#/, "");
      if (fromHash.indexOf("prof-") === 0) return normalizeScene(fromHash);
      const q = new URLSearchParams(location.search).get("scene");
      if (q) return normalizeScene(q);
      return normalizeScene(sessionStorage.getItem(SCENE_KEY) || "ocean");
    } catch (e) {
      return "ocean";
    }
  }

  function persistScene(scene) {
    scene = normalizeScene(scene);
    try { sessionStorage.setItem(SCENE_KEY, scene); } catch (e) {}
    document.body.setAttribute("data-scene", scene);
    document.querySelectorAll(".prof-card[data-scene]").forEach((el) => {
      el.classList.toggle("is-scene-active", el.getAttribute("data-scene") === scene);
    });
    document.querySelectorAll(".prof-deep[data-scene]").forEach((el) => {
      el.classList.toggle("is-scene-active", el.getAttribute("data-scene") === scene);
    });
    if (window.__yxSetScene) window.__yxSetScene(scene);
    return scene;
  }

  /* ========== Unified pointer (one rAF, transform only) ========== */
  const ptr = {
    x: window.innerWidth / 2,
    y: window.innerHeight / 2,
    sx: window.innerWidth / 2,
    sy: window.innerHeight / 2,
    rx: window.innerWidth / 2,
    ry: window.innerHeight / 2,
    down: false,
    hover: false
  };

  const dot = document.getElementById("cDot");
  const ring = document.getElementById("cRing");
  const useCursor = fine && !reduce && dot && ring;

  if (useCursor) {
    dot.hidden = false;
    ring.hidden = false;
    window.addEventListener("pointermove", (e) => {
      ptr.x = e.clientX;
      ptr.y = e.clientY;
    }, { passive: true });
    window.addEventListener("pointerdown", () => {
      ptr.down = true;
      document.body.classList.add("is-press");
    });
    window.addEventListener("pointerup", () => {
      ptr.down = false;
      document.body.classList.remove("is-press");
    });
    document.querySelectorAll("a, button, .prof-card, .device, .cta, .util-card, .stat-pill").forEach((el) => {
      el.addEventListener("pointerenter", () => {
        ptr.hover = true;
        document.body.classList.add("is-hover");
      });
      el.addEventListener("pointerleave", () => {
        ptr.hover = false;
        document.body.classList.remove("is-hover");
      });
    });
  }

  /* ========== Multi-scene particle canvas ========== */
  const canvas = document.getElementById("aurora");
  let canvasApi = null;

  if (canvas && canvas.getContext) {
    const ctx = canvas.getContext("2d", { alpha: true, desynchronized: true }) || canvas.getContext("2d");
    let W = 0, H = 0, dpr = 1;
    let scene = readStoredScene();
    let particles = [];
    let structures = [];
    let arcs = [];
    let shafts = [];
    let ripples = [];
    let running = true;
    let lastT = performance.now();

    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = window.innerWidth;
      H = window.innerHeight;
      canvas.width = Math.floor(W * dpr);
      canvas.height = Math.floor(H * dpr);
      canvas.style.width = W + "px";
      canvas.style.height = H + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      rebuild();
    }

    function particleBudget() {
      const area = W * H;
      return Math.max(90, Math.min(200, Math.floor(area / 7500)));
    }

    function rebuild() {
      let n = particleBudget();
      if (scene === "ocean") n = Math.floor(n * 1.35);
      else n = Math.floor(n * 1.55);
      particles = [];
      structures = [];
      arcs = [];
      shafts = [];
      ripples = [];
      if (scene === "ocean") initOcean(n);
      else if (scene === "water") initRiver(n);
      else if (scene === "build") initBuild(n);
      else if (scene === "muni") initBridge(n);
      else if (scene === "power") initPower(n);
    }

    function initOcean(n) {
      for (let i = 0; i < n; i++) {
        const layer = Math.random();
        particles.push({
          x: Math.random() * W,
          y: Math.random() * H,
          vx: (Math.random() - 0.5) * 0.4,
          vy: (Math.random() - 0.5) * 0.28,
          r: (1.15 - layer * 0.55) * (1.1 + Math.random() * 2.4),
          a: 0.32 + Math.random() * 0.55,
          phase: Math.random() * Math.PI * 2,
          amp: 16 + (1 - layer) * 26,
          layer,
          bobSp: 0.5 + Math.random() * 0.95
        });
      }
      for (let i = 0; i < 11; i++) {
        shafts.push({
          x: W * (0.04 + i * 0.09) + (Math.random() - 0.5) * 36,
          w: 48 + Math.random() * 100,
          a: 0.09 + Math.random() * 0.16,
          drift: (Math.random() - 0.5) * 0.32,
          sway: Math.random() * Math.PI * 2
        });
      }
      for (let i = 0; i < 34; i++) {
        structures.push({
          type: "bubble",
          x: Math.random() * W,
          y: Math.random() * H,
          r: 2.5 + Math.random() * 11,
          sp: 24 + Math.random() * 60,
          wob: Math.random() * Math.PI * 2,
          a: 0.22 + Math.random() * 0.45
        });
      }
      // kelp / soft fronds for depth
      for (let i = 0; i < 7; i++) {
        structures.push({
          type: "kelp",
          x: W * (0.08 + i * 0.13),
          base: H * (0.72 + Math.random() * 0.2),
          h: 90 + Math.random() * 140,
          phase: Math.random() * Math.PI * 2,
          segs: 5 + Math.floor(Math.random() * 3)
        });
      }
    }

    function initRiver(n) {
      structures.push({
        type: "sluice",
        gateX: W * 0.38,
        gateW: Math.min(260, W * 0.26),
        topY: H * 0.14,
        waterTop: H * 0.4,
        waterBot: H * 0.84
      });
      // bank trees silhouettes
      for (let i = 0; i < 8; i++) {
        structures.push({
          type: "bankTree",
          x: (i / 7) * W,
          y: H * 0.38 - (i % 2) * 12,
          s: 0.7 + Math.random() * 0.5
        });
      }
      for (let i = 0; i < n; i++) {
        const band = 0.44 + Math.random() * 0.34;
        particles.push({
          x: Math.random() * W,
          y: H * band,
          vx: 2.2 + Math.random() * 3.4,
          vy: (Math.random() - 0.5) * 0.3,
          r: Math.random() * 2.8 + 0.7,
          a: 0.5 + Math.random() * 0.45,
          phase: Math.random() * Math.PI * 2,
          band
        });
      }
    }

    function initBuild(n) {
      const towers = 7 + Math.floor(W / 200);
      for (let t = 0; t < towers; t++) {
        const bx = ((t + 0.5) / towers) * W + (Math.random() - 0.5) * 18;
        const floors = 9 + Math.floor(Math.random() * 12);
        const fw = 38 + Math.random() * 52;
        const depth = 10 + Math.random() * 16;
        structures.push({
          type: "tower",
          bx, fw, floors, depth,
          rise: Math.random() * 0.25,
          style: t % 3,
          hasCrane: t % 3 === 1
        });
      }
      for (let i = 0; i < n * 0.9; i++) {
        particles.push({
          x: Math.random() * W,
          y: Math.random() * H,
          vx: (Math.random() - 0.5) * 0.3,
          vy: -0.3 - Math.random() * 0.65,
          r: Math.random() * 1.9 + 0.4,
          a: 0.35 + Math.random() * 0.5,
          phase: Math.random() * Math.PI * 2
        });
      }
    }

    function initBridge(n) {
      const deckY = H * 0.5;
      const pillars = [];
      const spans = 5;
      for (let i = 0; i <= spans; i++) {
        pillars.push((i / spans) * W * 0.92 + W * 0.04);
      }
      structures.push({
        type: "bridge",
        deckY,
        pillars,
        cables: pillars.slice(0, -1).map((x, i) => ({
          x1: x,
          x3: pillars[i + 1]
        }))
      });
      // street lamps
      for (let i = 0; i < pillars.length; i++) {
        structures.push({ type: "lamp", x: pillars[i] - 22, y: deckY - 6 });
        structures.push({ type: "lamp", x: pillars[i] + 22, y: deckY - 6 });
      }
      for (let i = 0; i < n; i++) {
        const onDeck = Math.random() < 0.62;
        particles.push({
          x: Math.random() * W,
          y: onDeck ? deckY : H * 0.12 + Math.random() * H * 0.78,
          vx: onDeck ? 2.4 + Math.random() * 3.2 : (Math.random() - 0.5) * 0.45,
          vy: onDeck ? 0 : (Math.random() - 0.5) * 0.3,
          r: Math.random() * 2.1 + 0.5,
          a: 0.4 + Math.random() * 0.5,
          phase: Math.random() * Math.PI * 2,
          onDeck,
          car: onDeck && Math.random() < 0.35
        });
      }
    }

    function initPower(n) {
      const pylons = 4 + Math.floor(W / 320);
      for (let i = 0; i < pylons; i++) {
        const x = ((i + 0.5) / pylons) * W;
        const top = H * (0.12 + Math.random() * 0.06);
        structures.push({
          type: "pylon",
          x,
          top,
          base: H * 0.9,
          arms: [top + 22, top + 58, top + 98, top + 138]
        });
      }
      for (let i = 0; i < structures.length - 1; i++) {
        const a = structures[i], b = structures[i + 1];
        if (a.type !== "pylon" || b.type !== "pylon") continue;
        a.arms.forEach((ay, idx) => {
          arcs.push({
            x1: a.x, y1: ay,
            x2: b.x, y2: b.arms[idx] || b.arms[b.arms.length - 1],
            phase: Math.random() * Math.PI * 2
          });
        });
      }
      // substation block
      structures.push({
        type: "substation",
        x: W * 0.5 - 60,
        y: H * 0.78,
        w: 120,
        h: 48
      });
      for (let i = 0; i < n; i++) {
        particles.push({
          x: Math.random() * W,
          y: Math.random() * H,
          vx: (Math.random() - 0.5) * 0.5,
          vy: (Math.random() - 0.5) * 0.5,
          r: Math.random() * 2.1 + 0.4,
          a: 0.4 + Math.random() * 0.5,
          phase: Math.random() * Math.PI * 2
        });
      }
    }

    function wash(t) {
      const washes = {
        ocean: ["rgba(14,165,164,0.24)", "rgba(8,145,178,0.17)", "rgba(56,189,248,0.11)"],
        water: ["rgba(14,165,233,0.28)", "rgba(56,189,248,0.2)", "rgba(125,211,252,0.11)"],
        build: ["rgba(103,232,249,0.24)", "rgba(45,212,191,0.15)", "rgba(165,243,252,0.09)"],
        muni: ["rgba(45,212,191,0.26)", "rgba(20,184,166,0.16)", "rgba(94,234,212,0.1)"],
        power: ["rgba(34,211,238,0.28)", "rgba(6,182,212,0.17)", "rgba(165,243,252,0.11)"]
      };
      const c = washes[scene] || washes.ocean;
      const g1 = ctx.createRadialGradient(
        W * (0.28 + Math.sin(t * 0.32) * 0.1), H * 0.06, 0,
        W * 0.3, H * 0.12, W * 0.7
      );
      g1.addColorStop(0, c[0]); g1.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g1; ctx.fillRect(0, 0, W, H);
      const g2 = ctx.createRadialGradient(
        W * (0.76 + Math.cos(t * 0.45) * 0.07), H * 0.72, 0,
        W * 0.72, H * 0.6, W * 0.52
      );
      g2.addColorStop(0, c[1]); g2.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g2; ctx.fillRect(0, 0, W, H);
      const g3 = ctx.createRadialGradient(
        ptr.sx, ptr.sy, 0,
        ptr.sx, ptr.sy, W * 0.28
      );
      g3.addColorStop(0, c[2]); g3.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g3; ctx.fillRect(0, 0, W, H);
    }

    function softDot(x, y, r, color) {
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
    }

    /* Soft attraction toward smoothed pointer (Vercel Ship-style gravity) */
    function stepParticle(p) {
      const dx = ptr.sx - p.x;
      const dy = ptr.sy - p.y;
      const dist = Math.hypot(dx, dy) || 1;
      if (dist < 240) {
        const f = (1 - dist / 240) * 0.042;
        p.vx += (dx / dist) * f;
        p.vy += (dy / dist) * f;
      }
      // mild swirl near cursor
      if (dist < 140) {
        p.vx += (-dy / dist) * 0.012;
        p.vy += (dx / dist) * 0.012;
      }
      p.vx *= 0.988;
      p.vy *= 0.988;
      p.x += p.vx;
      p.y += p.vy;
      if (p.x < -14) p.x = W + 14;
      if (p.x > W + 14) p.x = -14;
      if (p.y < -14) p.y = H + 14;
      if (p.y > H + 14) p.y = -14;
    }

    function linkParticles(strength, rgb, limCap, distMax) {
      const lim = Math.min(particles.length, limCap || 60);
      const maxD = distMax || 105;
      for (let i = 0; i < lim; i++) {
        const p = particles[i];
        for (let j = i + 1; j < lim; j++) {
          const q = particles[j];
          const d = Math.hypot(p.x - q.x, p.y - q.y);
          if (d < maxD) {
            ctx.beginPath();
            ctx.moveTo(p.x, p.y);
            ctx.lineTo(q.x, q.y);
            ctx.strokeStyle = "rgba(" + rgb + "," + (strength * (1 - d / maxD)) + ")";
            ctx.lineWidth = 0.55;
            ctx.stroke();
          }
        }
      }
    }

    function drawOcean(t, dt) {
      shafts.forEach((s) => {
        s.sway += dt * 0.38;
        s.x += s.drift * dt * 26 + Math.sin(s.sway) * 0.18;
        if (s.x < -120) s.x = W + 70;
        if (s.x > W + 120) s.x = -70;
        const topW = s.w * 0.32;
        const botW = s.w + 56;
        const g = ctx.createLinearGradient(s.x, 0, s.x, H);
        g.addColorStop(0, "rgba(186,230,253," + (s.a * 1.2) + ")");
        g.addColorStop(0.32, "rgba(94,234,212," + (s.a * 0.9) + ")");
        g.addColorStop(0.72, "rgba(14,165,164," + (s.a * 0.32) + ")");
        g.addColorStop(1, "rgba(2,22,31,0)");
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.moveTo(s.x - topW * 0.15, 0);
        ctx.lineTo(s.x + topW, 0);
        ctx.lineTo(s.x + botW, H);
        ctx.lineTo(s.x - botW * 0.4, H);
        ctx.closePath();
        ctx.fill();
      });

      // caustic bands
      for (let i = 0; i < 5; i++) {
        const y0 = H * (0.12 + i * 0.18) + Math.sin(t * 0.65 + i * 1.2) * 20;
        ctx.beginPath();
        ctx.moveTo(0, y0);
        for (let x = 0; x <= W; x += 20) {
          const y = y0 + Math.sin(x * 0.014 + t * 1.15 + i) * (11 + i * 2.5)
            + Math.sin(x * 0.0045 + t * 0.35) * 9;
          ctx.lineTo(x, y);
        }
        ctx.strokeStyle = "rgba(165,243,252," + (0.075 + i * 0.014) + ")";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      // kelp
      structures.forEach((k) => {
        if (k.type !== "kelp") return;
        ctx.beginPath();
        ctx.moveTo(k.x, k.base);
        for (let s = 1; s <= k.segs; s++) {
          const tt = s / k.segs;
          const sway = Math.sin(t * 0.9 + k.phase + tt * 2.2) * (18 * tt);
          ctx.lineTo(k.x + sway, k.base - k.h * tt);
        }
        ctx.strokeStyle = "rgba(45,212,191,0.28)";
        ctx.lineWidth = 2.2;
        ctx.stroke();
        // leaf tips
        for (let s = 2; s <= k.segs; s += 2) {
          const tt = s / k.segs;
          const sway = Math.sin(t * 0.9 + k.phase + tt * 2.2) * (18 * tt);
          const y = k.base - k.h * tt;
          ctx.beginPath();
          ctx.ellipse(k.x + sway + 10, y, 14, 5, -0.4, 0, Math.PI * 2);
          ctx.fillStyle = "rgba(20,184,166,0.12)";
          ctx.fill();
        }
      });

      particles.forEach((p) => {
        const bob = Math.sin(t * p.bobSp + p.phase) * p.amp;
        const driftX = Math.sin(t * 0.32 + p.phase) * (5 + (1 - p.layer) * 9);
        p.vx += Math.sin(t * 1.3 + p.phase) * 0.007;
        p.vy += Math.cos(t * 1.05 + p.phase) * 0.005;
        stepParticle(p);
        const px = p.x + driftX;
        const py = p.y + bob;
        softDot(px, py, p.r, "rgba(186,230,253," + p.a + ")");
        if (p.layer < 0.4) softDot(px, py, p.r * 2.6, "rgba(94,234,212," + (p.a * 0.2) + ")");
      });
      linkParticles(0.1, "94,234,212", 58, 98);

      if (Math.random() < 0.025 && ripples.length < 7) {
        ripples.push({
          x: Math.random() * W, y: H * (0.22 + Math.random() * 0.48),
          r: 5, max: 85 + Math.random() * 110, life: 0
        });
      }
      for (let i = ripples.length - 1; i >= 0; i--) {
        const r = ripples[i];
        r.r += dt * 34;
        const fade = Math.max(0, 1 - r.r / r.max);
        ctx.beginPath();
        ctx.ellipse(r.x, r.y, r.r, r.r * 0.32, 0, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(165,243,252," + (0.42 * fade) + ")";
        ctx.lineWidth = 1.6;
        ctx.stroke();
        if (r.r > r.max) ripples.splice(i, 1);
      }

      structures.forEach((b) => {
        if (b.type !== "bubble") return;
        b.wob += dt * 2.1;
        b.y -= b.sp * dt;
        b.x += Math.sin(b.wob) * 0.65;
        if (b.y < -24) { b.y = H + 24; b.x = Math.random() * W; }
        ctx.beginPath();
        ctx.arc(b.x, b.y, b.r, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(186,230,253," + b.a + ")";
        ctx.lineWidth = 1.35;
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(b.x - b.r * 0.32, b.y - b.r * 0.32, Math.max(1.2, b.r * 0.3), 0, Math.PI * 2);
        ctx.fillStyle = "rgba(255,255,255," + (b.a * 0.55) + ")";
        ctx.fill();
      });
    }

    function drawRiver(t, dt) {
      const sluice = structures.find((s) => s.type === "sluice");
      const wt = sluice ? sluice.waterTop : H * 0.4;
      const wb = sluice ? sluice.waterBot : H * 0.84;

      // sky wash
      const sky = ctx.createLinearGradient(0, 0, 0, wt);
      sky.addColorStop(0, "rgba(8,47,73,0.35)");
      sky.addColorStop(1, "rgba(14,165,233,0.05)");
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, W, wt);

      // banks with hatch
      ctx.fillStyle = "rgba(15,118,110,0.18)";
      ctx.beginPath();
      ctx.moveTo(0, 0); ctx.lineTo(W, 0); ctx.lineTo(W, wt - 48); ctx.lineTo(0, wt - 28);
      ctx.closePath(); ctx.fill();
      ctx.beginPath();
      ctx.moveTo(0, wb + 8); ctx.lineTo(W, wb + 22); ctx.lineTo(W, H); ctx.lineTo(0, H);
      ctx.closePath(); ctx.fill();

      structures.forEach((tr) => {
        if (tr.type !== "bankTree") return;
        const s = tr.s;
        ctx.strokeStyle = "rgba(94,234,212,0.35)";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(tr.x, tr.y);
        ctx.lineTo(tr.x, tr.y - 28 * s);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(tr.x, tr.y - 28 * s);
        ctx.lineTo(tr.x - 12 * s, tr.y - 10 * s);
        ctx.moveTo(tr.x, tr.y - 22 * s);
        ctx.lineTo(tr.x + 14 * s, tr.y - 8 * s);
        ctx.stroke();
      });

      const wg = ctx.createLinearGradient(0, wt, 0, wb);
      wg.addColorStop(0, "rgba(14,165,233,0.12)");
      wg.addColorStop(0.45, "rgba(56,189,248,0.22)");
      wg.addColorStop(1, "rgba(8,145,178,0.14)");
      ctx.fillStyle = wg;
      ctx.fillRect(0, wt, W, wb - wt);

      for (let row = 0; row < 6; row++) {
        const baseY = wt + (wb - wt) * (0.12 + row * 0.14);
        ctx.beginPath();
        for (let x = 0; x <= W; x += 14) {
          const y = baseY + Math.sin(x * 0.022 + t * 3 + row) * 11
            + Math.sin(x * 0.007 + t * 1.3) * 7;
          if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = "rgba(186,230,253," + (0.3 + row * 0.05) + ")";
        ctx.lineWidth = 1.7;
        ctx.stroke();
      }

      if (sluice) {
        const gx = sluice.gateX, gw = sluice.gateW, ty = sluice.topY;
        // concrete towers with bevel
        [[gx, ty], [gx + gw, ty]].forEach(([px]) => {
          const g = ctx.createLinearGradient(px - 14, 0, px + 14, 0);
          g.addColorStop(0, "rgba(8,145,178,0.25)");
          g.addColorStop(0.5, "rgba(56,189,248,0.45)");
          g.addColorStop(1, "rgba(8,145,178,0.25)");
          ctx.fillStyle = g;
          ctx.fillRect(px - 14, ty, 28, wb - ty);
          ctx.strokeStyle = "rgba(186,230,253,0.9)";
          ctx.lineWidth = 2;
          ctx.strokeRect(px - 14, ty, 28, wb - ty);
          // rivets
          for (let ry = ty + 20; ry < wb - 10; ry += 28) {
            softDot(px - 6, ry, 1.6, "rgba(165,243,252,0.7)");
            softDot(px + 6, ry, 1.6, "rgba(165,243,252,0.7)");
          }
        });
        // top gantry
        ctx.fillStyle = "rgba(94,234,212,0.4)";
        ctx.fillRect(gx - 14, ty, gw + 28, 16);
        ctx.strokeStyle = "rgba(186,230,253,0.95)";
        ctx.strokeRect(gx - 14, ty, gw + 28, 16);
        // hoist wheels
        softDot(gx + gw * 0.25, ty + 8, 5, "rgba(165,243,252,0.85)");
        softDot(gx + gw * 0.75, ty + 8, 5, "rgba(165,243,252,0.85)");
        // gate leaf
        const lift = 24 + Math.sin(t * 0.75) * 22;
        ctx.fillStyle = "rgba(14,116,144,0.35)";
        ctx.fillRect(gx + 6, ty + 22 + lift, gw - 12, Math.max(20, wb - ty - 40 - lift));
        ctx.strokeStyle = "rgba(125,211,252,0.8)";
        ctx.lineWidth = 2;
        for (let i = 0; i < 8; i++) {
          const by = ty + 30 + lift + i * 14;
          if (by > wb - 12) break;
          ctx.beginPath();
          ctx.moveTo(gx + 10, by);
          ctx.lineTo(gx + gw - 10, by);
          ctx.stroke();
        }
        // spray under gate
        for (let i = 0; i < 12; i++) {
          const sx = gx + 20 + (i / 11) * (gw - 40);
          const sy = wb - 30 - Math.abs(Math.sin(t * 4 + i)) * 18;
          softDot(sx, sy, 2 + Math.random(), "rgba(186,230,253,0.45)");
        }
      }

      particles.forEach((p) => {
        p.y = H * p.band + Math.sin(t * 2.9 + p.phase + p.x * 0.012) * 16;
        p.x += p.vx * dt * 78;
        // gentle attract while flowing
        const dx = ptr.sx - p.x, dy = ptr.sy - p.y;
        const d = Math.hypot(dx, dy) || 1;
        if (d < 180) p.y += (dy / d) * 0.35;
        if (p.x > W + 20) p.x = -20;
        softDot(p.x, p.y, p.r, "rgba(186,230,253," + p.a + ")");
        ctx.beginPath();
        ctx.moveTo(p.x, p.y);
        ctx.lineTo(p.x - p.vx * 18, p.y);
        ctx.strokeStyle = "rgba(56,189,248," + (p.a * 0.5) + ")";
        ctx.lineWidth = 1.4;
        ctx.stroke();
      });
    }

    function drawBuild(t, dt) {
      ctx.strokeStyle = "rgba(94,234,212,0.35)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(0, H * 0.9);
      ctx.lineTo(W, H * 0.9);
      ctx.stroke();

      // perspective grid floor
      for (let i = 0; i < 12; i++) {
        const x = (i / 11) * W;
        ctx.beginPath();
        ctx.moveTo(W * 0.5, H * 0.55);
        ctx.lineTo(x, H * 0.9);
        ctx.strokeStyle = "rgba(103,232,249,0.08)";
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      structures.forEach((s, si) => {
        if (s.type !== "tower") return;
        s.rise = Math.min(1, s.rise + dt * 0.22);
        const showF = Math.max(1, Math.floor(s.floors * s.rise));
        const left = s.bx - s.fw / 2;
        const right = s.bx + s.fw / 2;
        const baseY = H * 0.9;
        const floorH = 15 + (s.style === 2 ? 3 : 0);
        const topY = baseY - showF * floorH;
        const depth = s.depth;

        // side face (isometric hint)
        ctx.fillStyle = "rgba(8,145,178,0.12)";
        ctx.beginPath();
        ctx.moveTo(right, topY);
        ctx.lineTo(right + depth, topY - depth * 0.35);
        ctx.lineTo(right + depth, baseY - depth * 0.35);
        ctx.lineTo(right, baseY);
        ctx.closePath();
        ctx.fill();
        ctx.strokeStyle = "rgba(103,232,249,0.45)";
        ctx.stroke();

        // front face
        const fg = ctx.createLinearGradient(left, 0, right, 0);
        fg.addColorStop(0, "rgba(6,78,92,0.55)");
        fg.addColorStop(0.5, "rgba(14,116,144,0.35)");
        fg.addColorStop(1, "rgba(6,78,92,0.55)");
        ctx.fillStyle = fg;
        ctx.fillRect(left, topY, s.fw, baseY - topY);
        ctx.strokeStyle = "rgba(103,232,249,0.75)";
        ctx.lineWidth = 1.8;
        ctx.strokeRect(left, topY, s.fw, baseY - topY);

        for (let f = 0; f < showF; f++) {
          const fy = baseY - (f + 1) * floorH;
          ctx.beginPath();
          ctx.moveTo(left, fy);
          ctx.lineTo(right, fy);
          ctx.strokeStyle = "rgba(94,234,212,0.35)";
          ctx.lineWidth = 1;
          ctx.stroke();
          const cols = Math.max(3, Math.floor(s.fw / 13));
          for (let c = 0; c < cols; c++) {
            const wx = left + 5 + c * ((s.fw - 10) / cols);
            const lit = 0.2 + 0.8 * (0.5 + 0.5 * Math.sin(t * 2.8 + si + c * 0.8 + f * 0.4));
            ctx.fillStyle = "rgba(165,243,252," + (0.12 + lit * 0.5) + ")";
            ctx.fillRect(wx, fy + 2.5, Math.max(3.5, (s.fw - 10) / cols - 3.5), floorH - 5);
          }
        }

        // roof cap
        ctx.beginPath();
        ctx.moveTo(left - 2, topY);
        ctx.lineTo(s.bx, topY - 10);
        ctx.lineTo(right + 2, topY);
        ctx.strokeStyle = "rgba(186,230,253,0.7)";
        ctx.stroke();
        softDot(s.bx, topY - 10, 2.5, "rgba(186,230,253,0.95)");

        if (s.hasCrane && showF > s.floors * 0.5) {
          const mastX = s.bx + s.fw * 0.15;
          const craneTop = topY - 18;
          const jib = 55 + Math.sin(t * 0.4 + si) * 4;
          ctx.strokeStyle = "rgba(186,230,253,0.8)";
          ctx.lineWidth = 2.2;
          ctx.beginPath();
          ctx.moveTo(mastX, topY);
          ctx.lineTo(mastX, craneTop);
          ctx.lineTo(mastX + jib, craneTop);
          ctx.lineTo(mastX - 18, craneTop);
          ctx.stroke();
          // lattice on mast
          for (let k = 0; k < 4; k++) {
            const my = topY - k * ((topY - craneTop) / 4);
            ctx.beginPath();
            ctx.moveTo(mastX - 4, my);
            ctx.lineTo(mastX + 4, my + 6);
            ctx.strokeStyle = "rgba(94,234,212,0.45)";
            ctx.lineWidth = 1;
            ctx.stroke();
          }
          const hookX = mastX + jib - 8;
          const hookY = craneTop + 30 + Math.sin(t * 2.2 + si) * 14;
          ctx.beginPath();
          ctx.moveTo(hookX, craneTop);
          ctx.lineTo(hookX, hookY);
          ctx.strokeStyle = "rgba(94,234,212,0.65)";
          ctx.stroke();
          softDot(hookX, hookY, 3.5, "rgba(165,243,252,1)");
        }
      });

      particles.forEach((p) => {
        p.vy = -0.4 - Math.abs(Math.sin(t * 1.3 + p.phase)) * 0.55;
        stepParticle(p);
        softDot(p.x, p.y, p.r, "rgba(103,232,249," + (p.a * 0.75) + ")");
      });
    }

    function drawBridge(t, dt) {
      const s = structures.find((x) => x.type === "bridge");
      if (!s) return;
      const { deckY, pillars, cables } = s;
      const ground = H * 0.92;

      // distant hills
      ctx.beginPath();
      ctx.moveTo(0, H * 0.55);
      for (let x = 0; x <= W; x += 40) {
        ctx.lineTo(x, H * 0.55 + Math.sin(x * 0.008) * 28);
      }
      ctx.lineTo(W, ground);
      ctx.lineTo(0, ground);
      ctx.closePath();
      ctx.fillStyle = "rgba(13,148,136,0.1)";
      ctx.fill();

      ctx.strokeStyle = "rgba(45,212,191,0.28)";
      ctx.beginPath();
      ctx.moveTo(0, ground);
      ctx.lineTo(W, ground);
      ctx.stroke();

      pillars.forEach((x) => {
        ctx.beginPath();
        ctx.moveTo(x - 16, deckY);
        ctx.lineTo(x + 16, deckY);
        ctx.lineTo(x + 32, ground);
        ctx.lineTo(x - 32, ground);
        ctx.closePath();
        const pg = ctx.createLinearGradient(x - 32, 0, x + 32, 0);
        pg.addColorStop(0, "rgba(13,148,136,0.2)");
        pg.addColorStop(0.5, "rgba(45,212,191,0.4)");
        pg.addColorStop(1, "rgba(13,148,136,0.2)");
        ctx.fillStyle = pg;
        ctx.fill();
        ctx.strokeStyle = "rgba(94,234,212,0.8)";
        ctx.lineWidth = 2;
        ctx.stroke();
        softDot(x, deckY + 6, 2.2, "rgba(153,246,228,0.9)");
      });

      // dual deck
      ctx.fillStyle = "rgba(15,118,110,0.4)";
      ctx.fillRect(0, deckY - 8, W, 18);
      ctx.strokeStyle = "rgba(45,212,191,0.95)";
      ctx.lineWidth = 2.4;
      ctx.strokeRect(0, deckY - 8, W, 18);
      // guard rails
      ctx.strokeStyle = "rgba(94,234,212,0.55)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(0, deckY - 18);
      ctx.lineTo(W, deckY - 18);
      ctx.moveTo(0, deckY + 14);
      ctx.lineTo(W, deckY + 14);
      ctx.stroke();
      ctx.setLineDash([18, 12]);
      ctx.strokeStyle = "rgba(165,243,252,0.75)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(0, deckY + 1);
      ctx.lineTo(W, deckY + 1);
      ctx.stroke();
      ctx.setLineDash([]);

      pillars.forEach((x, i) => {
        const th = 110 + (i % 2) * 32;
        ctx.strokeStyle = "rgba(94,234,212,0.85)";
        ctx.lineWidth = 2.4;
        ctx.beginPath();
        ctx.moveTo(x - 10, deckY);
        ctx.lineTo(x - 5, deckY - th);
        ctx.lineTo(x + 5, deckY - th);
        ctx.lineTo(x + 10, deckY);
        ctx.stroke();
        // tower cross
        ctx.beginPath();
        ctx.moveTo(x - 8, deckY - th * 0.4);
        ctx.lineTo(x + 8, deckY - th * 0.55);
        ctx.moveTo(x + 8, deckY - th * 0.4);
        ctx.lineTo(x - 8, deckY - th * 0.55);
        ctx.strokeStyle = "rgba(45,212,191,0.5)";
        ctx.lineWidth = 1.2;
        ctx.stroke();
        softDot(x, deckY - th, 3.8, "rgba(153,246,228,1)");
      });

      cables.forEach((c, ci) => {
        const h1 = 110 + (ci % 2) * 32;
        const h2 = 110 + ((ci + 1) % 2) * 32;
        const midY = deckY - Math.max(h1, h2) + 48;
        ctx.beginPath();
        ctx.moveTo(c.x1, deckY - h1);
        ctx.quadraticCurveTo((c.x1 + c.x3) / 2, midY, c.x3, deckY - h2);
        ctx.strokeStyle = "rgba(94,234,212,0.7)";
        ctx.lineWidth = 2.3;
        ctx.stroke();
        for (let k = 1; k < 8; k++) {
          const tt = k / 8;
          const px = c.x1 + (c.x3 - c.x1) * tt;
          const cy = (1 - tt) * (1 - tt) * (deckY - h1)
            + 2 * (1 - tt) * tt * midY
            + tt * tt * (deckY - h2);
          ctx.beginPath();
          ctx.moveTo(px, cy);
          ctx.lineTo(px, deckY - 8);
          ctx.strokeStyle = "rgba(45,212,191,0.32)";
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      });

      structures.forEach((lamp) => {
        if (lamp.type !== "lamp") return;
        ctx.strokeStyle = "rgba(94,234,212,0.5)";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(lamp.x, lamp.y);
        ctx.lineTo(lamp.x, lamp.y - 22);
        ctx.lineTo(lamp.x + 8, lamp.y - 26);
        ctx.stroke();
        softDot(lamp.x + 8, lamp.y - 26, 3, "rgba(153,246,228," + (0.55 + 0.45 * Math.sin(t * 3 + lamp.x)) + ")");
      });

      particles.forEach((p) => {
        if (p.onDeck) {
          p.x += p.vx * dt * 78;
          p.y = deckY + Math.sin(t * 5 + p.phase) * 2.5;
          if (p.x > W + 14) p.x = -14;
          if (p.car) {
            ctx.fillStyle = "rgba(153,246,228," + p.a + ")";
            ctx.fillRect(p.x - 9, p.y - 3, 18, 6);
            softDot(p.x + 8, p.y, 1.5, "rgba(255,255,255,0.8)");
          } else {
            softDot(p.x, p.y, p.r, "rgba(110,231,183," + p.a + ")");
          }
        } else {
          stepParticle(p);
          softDot(p.x, p.y, p.r, "rgba(110,231,183," + (p.a * 0.7) + ")");
        }
      });
    }

    function drawPower(t, dt) {
      ctx.strokeStyle = "rgba(34,211,238,0.25)";
      ctx.beginPath();
      ctx.moveTo(0, H * 0.9);
      ctx.lineTo(W, H * 0.9);
      ctx.stroke();

      structures.forEach((p) => {
        if (p.type === "substation") {
          ctx.fillStyle = "rgba(8,145,178,0.25)";
          ctx.fillRect(p.x, p.y, p.w, p.h);
          ctx.strokeStyle = "rgba(34,211,238,0.7)";
          ctx.lineWidth = 1.8;
          ctx.strokeRect(p.x, p.y, p.w, p.h);
          for (let i = 0; i < 4; i++) {
            ctx.strokeRect(p.x + 8 + i * 28, p.y + 8, 20, p.h - 16);
            softDot(p.x + 18 + i * 28, p.y + 4, 2, "rgba(165,243,252,0.8)");
          }
          return;
        }
        if (p.type !== "pylon") return;

        ctx.strokeStyle = "rgba(34,211,238,0.88)";
        ctx.lineWidth = 2.1;
        ctx.beginPath();
        ctx.moveTo(p.x - 26, p.base);
        ctx.lineTo(p.x - 7, p.top);
        ctx.moveTo(p.x + 26, p.base);
        ctx.lineTo(p.x + 7, p.top);
        ctx.moveTo(p.x - 26, p.base);
        ctx.lineTo(p.x + 26, p.base);
        const steps = 7;
        for (let i = 0; i < steps; i++) {
          const t0 = i / steps, t1 = (i + 1) / steps;
          const y0 = p.base + (p.top - p.base) * t0;
          const y1 = p.base + (p.top - p.base) * t1;
          const w0 = 26 - 19 * t0, w1 = 26 - 19 * t1;
          ctx.moveTo(p.x - w0, y0); ctx.lineTo(p.x + w1, y1);
          ctx.moveTo(p.x + w0, y0); ctx.lineTo(p.x - w1, y1);
          ctx.moveTo(p.x - w0, y0); ctx.lineTo(p.x + w0, y0);
        }
        ctx.stroke();

        p.arms.forEach((ay, ai) => {
          const armW = 40 + ai * 5;
          ctx.strokeStyle = "rgba(103,232,249,0.95)";
          ctx.lineWidth = 2.5;
          ctx.beginPath();
          ctx.moveTo(p.x - armW, ay);
          ctx.lineTo(p.x + armW, ay);
          ctx.stroke();
          // brace triangles
          ctx.beginPath();
          ctx.moveTo(p.x - armW * 0.4, ay);
          ctx.lineTo(p.x, ay - 10);
          ctx.lineTo(p.x + armW * 0.4, ay);
          ctx.strokeStyle = "rgba(34,211,238,0.55)";
          ctx.lineWidth = 1.2;
          ctx.stroke();
          [-1, 1].forEach((side) => {
            const ix = p.x + side * armW;
            // insulator string
            for (let k = 0; k < 4; k++) {
              softDot(ix, ay + 6 + k * 5, 2.2, "rgba(186,230,253," + (0.55 + k * 0.1) + ")");
            }
          });
        });
        softDot(p.x, p.top - 5, 4.5, "rgba(165,243,252,1)");
        // beacon blink
        if (Math.sin(t * 4) > 0.3) {
          softDot(p.x, p.top - 5, 10, "rgba(34,211,238,0.2)");
        }
      });

      arcs.forEach((a) => {
        const pulse = 0.4 + 0.6 * Math.abs(Math.sin(t * 2.6 + a.phase));
        const sag = 24 + Math.sin(t * 1.1 + a.phase) * 7;
        ctx.beginPath();
        ctx.moveTo(a.x1, a.y1);
        ctx.quadraticCurveTo((a.x1 + a.x2) / 2, (a.y1 + a.y2) / 2 + sag, a.x2, a.y2);
        ctx.strokeStyle = "rgba(34,211,238," + (0.72 * pulse) + ")";
        ctx.lineWidth = 2.3;
        ctx.stroke();
        if (Math.sin(t * 10 + a.phase) > 0.8) {
          ctx.beginPath();
          ctx.moveTo(a.x1, a.y1);
          const mx2 = (a.x1 + a.x2) / 2 + (Math.random() - 0.5) * 30;
          const my2 = (a.y1 + a.y2) / 2 + sag + (Math.random() - 0.5) * 24;
          ctx.lineTo(mx2, my2);
          ctx.lineTo(a.x2, a.y2);
          ctx.strokeStyle = "rgba(186,230,253,0.95)";
          ctx.lineWidth = 2.6;
          ctx.shadowColor = "rgba(34,211,238,0.85)";
          ctx.shadowBlur = 14;
          ctx.stroke();
          ctx.shadowBlur = 0;
        }
      });

      particles.forEach((p) => {
        stepParticle(p);
        softDot(p.x, p.y, p.r, "rgba(34,211,238," + p.a + ")");
      });
      linkParticles(0.13, "34,211,238", 55, 102);
    }

    function render(now) {
      if (!running) return;
      const dt = Math.min(0.05, (now - lastT) / 1000) || 0.016;
      lastT = now;
      const t = now * 0.001;
      ctx.clearRect(0, 0, W, H);
      wash(t);
      if (scene === "ocean") drawOcean(t, dt);
      else if (scene === "water") drawRiver(t, dt);
      else if (scene === "build") drawBuild(t, dt);
      else if (scene === "muni") drawBridge(t, dt);
      else if (scene === "power") drawPower(t, dt);
    }

    function setScene(next) {
      next = normalizeScene(next);
      if (next === scene && particles.length) return;
      scene = next;
      rebuild();
    }

    window.__yxSetScene = setScene;
    resize();
    window.addEventListener("resize", resize, { passive: true });
    document.addEventListener("visibilitychange", () => {
      running = document.visibilityState === "visible";
      if (running) lastT = performance.now();
    });

    canvasApi = {
      render,
      running: () => running && !reduce,
      washOnce: () => { wash(0); }
    };

    persistScene(scene);
    if (reduce) {
      canvas.style.opacity = "0.45";
      wash(0);
    }
  } else {
    persistScene(readStoredScene());
  }

  /* Scene switching */
  document.querySelectorAll(".prof-card[data-scene]").forEach((card) => {
    const scene = card.getAttribute("data-scene");
    card.addEventListener("pointerenter", () => { if (!reduce) persistScene(scene); });
    card.addEventListener("click", () => { persistScene(scene); });
  });

  const deepPanels = Array.from(document.querySelectorAll(".prof-deep[data-scene]"));
  if (deepPanels.length) {
    const hash = (location.hash || "").replace(/^#/, "");
    if (hash.indexOf("prof-") === 0) persistScene(normalizeScene(hash));
    if ("IntersectionObserver" in window) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach((en) => {
          if (en.isIntersecting && en.intersectionRatio > 0.45) {
            const s = en.target.getAttribute("data-scene");
            if (s) persistScene(s);
          }
        });
      }, { threshold: [0.45, 0.6] });
      deepPanels.forEach((p) => io.observe(p));
    }
    window.addEventListener("hashchange", () => {
      const h = (location.hash || "").replace(/^#/, "");
      if (h.indexOf("prof-") === 0) persistScene(h);
    });
  }

  /* Tilt state */
  const tiltEls = document.querySelectorAll("[data-lean]");
  const tilts = new Map();
  tiltEls.forEach((el) => {
    tilts.set(el, { rx: 0, ry: 0, tx: 0, ty: 0, active: 0 });
    el.addEventListener("pointermove", (e) => {
      const r = el.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width;
      const py = (e.clientY - r.top) / r.height;
      const depth = parseFloat(el.dataset.depth || "10");
      const st = tilts.get(el);
      st.tx = (py - 0.5) * -depth;
      st.ty = (px - 0.5) * depth;
      st.active = 1;
      const spot = el.querySelector(".card-spot");
      if (spot) {
        spot.style.setProperty("--mx", (px * 100) + "%");
        spot.style.setProperty("--my", (py * 100) + "%");
      }
    }, { passive: true });
    el.addEventListener("pointerleave", () => {
      const st = tilts.get(el);
      st.tx = 0; st.ty = 0; st.active = 0;
    });
  });

  /* Stage parallax targets */
  const stage = document.getElementById("stage");
  let stageSX = 0, stageSY = 0, stageTX = 0, stageTY = 0;
  const desk = stage && stage.querySelector(".device-desk");
  const phone = stage && stage.querySelector(".device-phone");
  if (stage && !reduce) {
    stage.addEventListener("pointermove", (e) => {
      const r = stage.getBoundingClientRect();
      stageTX = ((e.clientX - r.left) / r.width - 0.5) * 2;
      stageTY = ((e.clientY - r.top) / r.height - 0.5) * 2;
    }, { passive: true });
    stage.addEventListener("pointerleave", () => { stageTX = 0; stageTY = 0; });
  } else if (stage && reduce) {
    if (desk) desk.style.transform = "perspective(1200px) rotateX(-3deg) rotateY(6deg)";
    if (phone) phone.style.transform = "perspective(1200px) rotateX(2deg) rotateY(-8deg)";
  }

  /* Magnetic CTAs */
  const magnets = [];
  document.querySelectorAll(".cta[data-magnet]").forEach((btn) => {
    if (reduce || !fine) return;
    const st = { el: btn, cx: 0, cy: 0, tx: 0, ty: 0 };
    magnets.push(st);
    btn.addEventListener("pointermove", (e) => {
      const r = btn.getBoundingClientRect();
      st.tx = (e.clientX - (r.left + r.width / 2)) * 0.32;
      st.ty = (e.clientY - (r.top + r.height / 2)) * 0.32;
    }, { passive: true });
    btn.addEventListener("pointerleave", () => { st.tx = 0; st.ty = 0; });
  });

  /* Carousels */
  function startCarousel(root, slideSel, interval) {
    const slides = Array.from(root.querySelectorAll(slideSel));
    if (slides.length < 2) return;
    let i = 0;
    const dots = root.querySelectorAll(".g-dots span");
    function show(n) {
      slides.forEach((s, idx) => s.classList.toggle("active", idx === n));
      dots.forEach((d, idx) => d.classList.toggle("on", idx === n));
    }
    show(0);
    if (reduce) return;
    let paused = false;
    root.addEventListener("pointerenter", () => { paused = true; });
    root.addEventListener("pointerleave", () => { paused = false; });
    setInterval(() => {
      if (paused) return;
      i = (i + 1) % slides.length;
      show(i);
    }, interval);
  }
  document.querySelectorAll(".gallery").forEach((g) => startCarousel(g, ".g-slide", 3200));

  /* Nav active */
  const path = (location.pathname.split("/").pop() || "index.html").toLowerCase();
  document.querySelectorAll(".nav-links a").forEach((a) => {
    const href = (a.getAttribute("href") || "").split("#")[0].toLowerCase();
    if (href && href === path) a.classList.add("active");
    if (path === "" && href === "index.html") a.classList.add("active");
  });

  /* ========== Single main loop: cursor + tilt + magnet + canvas ========== */
  let spin = 0;
  const t0 = performance.now();

  function mainLoop(now) {
    const t = (now - t0) / 1000;

    if (useCursor) {
      // Fast smooth for tip, slower for ring (Linear-style lag)
      ptr.sx += (ptr.x - ptr.sx) * 0.42;
      ptr.sy += (ptr.y - ptr.sy) * 0.42;
      ptr.rx += (ptr.x - ptr.rx) * 0.14;
      ptr.ry += (ptr.y - ptr.ry) * 0.14;
      dot.style.transform = "translate3d(" + ptr.sx.toFixed(2) + "px," + ptr.sy.toFixed(2) + "px,0) translate(-50%,-50%)";
      ring.style.transform = "translate3d(" + ptr.rx.toFixed(2) + "px," + ptr.ry.toFixed(2) + "px,0) translate(-50%,-50%)";
    } else {
      ptr.sx += (ptr.x - ptr.sx) * 0.25;
      ptr.sy += (ptr.y - ptr.sy) * 0.25;
    }

    if (!reduce) {
      tilts.forEach((st, el) => {
        st.rx += (st.tx - st.rx) * 0.12;
        st.ry += (st.ty - st.ry) * 0.12;
        if (el.classList.contains("device")) return;
        if (el.classList.contains("strip-mock")) {
          const bob = Math.sin(t * 0.5) * 1.6;
          const yaw = Math.sin(t * 0.32) * 2;
          el.style.transform = "perspective(1600px) rotateX(" + (7 + bob + st.rx).toFixed(2)
            + "deg) rotateY(" + (yaw + st.ry).toFixed(2) + "deg) scale(0.985)";
          return;
        }
        const idleX = st.active ? 0 : Math.sin(t * 0.55 + (el._oid || 0)) * 1.1;
        const idleY = st.active ? 0 : Math.cos(t * 0.45 + (el._oid || 0)) * 1.2;
        if (el._oid == null) el._oid = Math.random() * 10;
        el.style.transform = "perspective(1000px) rotateX(" + (st.rx + idleX).toFixed(2)
          + "deg) rotateY(" + (st.ry + idleY).toFixed(2) + "deg) translateZ(" + (st.active ? 10 : 0) + "px)";
      });

      stageSX += (stageTX - stageSX) * 0.08;
      stageSY += (stageTY - stageSY) * 0.08;
      const px = Math.max(-1, Math.min(1, stageSX));
      const py = Math.max(-1, Math.min(1, stageSY));
      if (desk) {
        const st = tilts.get(desk) || { rx: 0, ry: 0 };
        const bobD = Math.sin(t * 0.65) * 5;
        const yawD = Math.sin(t * 0.38) * 2.5;
        desk.style.transform = "perspective(1200px) translate3d(" + (-px * 8).toFixed(1) + "px,"
          + (-py * 5 + bobD).toFixed(1) + "px,0) rotateX(" + (st.rx - 3 + py * 2).toFixed(2)
          + "deg) rotateY(" + (st.ry + 6 + px * 2.5 + yawD).toFixed(2) + "deg)";
      }
      if (phone) {
        const st = tilts.get(phone) || { rx: 0, ry: 0 };
        const bobP = Math.sin(t * 0.8 + 1.2) * 7;
        const yawP = Math.cos(t * 0.42) * 3.5;
        phone.style.transform = "perspective(1200px) translate3d(" + (px * 8).toFixed(1) + "px,"
          + (py * 6 + bobP).toFixed(1) + "px,28px) rotateX(" + (st.rx + 2 - py * 2.5).toFixed(2)
          + "deg) rotateY(" + (st.ry - 8 - px * 3 + yawP).toFixed(2) + "deg)";
      }

      magnets.forEach((m) => {
        m.cx += (m.tx - m.cx) * 0.14;
        m.cy += (m.ty - m.cy) * 0.14;
        m.el.style.transform = "translate3d(" + m.cx.toFixed(2) + "px," + m.cy.toFixed(2) + "px,0)";
      });

      spin = (spin + 0.5) % 360;
      document.querySelectorAll(".prof-card").forEach((c) => {
        if (!c.matches(":hover") && !c.classList.contains("is-scene-active")) {
          c.style.setProperty("--spin", spin + "deg");
        }
      });
    }

    if (canvasApi && canvasApi.running()) canvasApi.render(now);

    requestAnimationFrame(mainLoop);
  }

  if (!fine) {
    window.addEventListener("pointermove", (e) => {
      ptr.x = e.clientX; ptr.y = e.clientY;
    }, { passive: true });
  }


  var navEl = document.querySelector(".nav");
  var toggle = document.querySelector(".nav-toggle");
  if (toggle && navEl) {
    toggle.addEventListener("click", function () {
      var open = navEl.classList.toggle("menu-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "关闭导航" : "打开导航");
    });
    var navLinks = document.querySelector(".nav-links");
    if (navLinks) {
      navLinks.addEventListener("click", function (event) {
        if (event.target.closest("a")) {
          navEl.classList.remove("menu-open");
          toggle.setAttribute("aria-expanded", "false");
          toggle.setAttribute("aria-label", "打开导航");
        }
      });
    }
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        navEl.classList.remove("menu-open");
        toggle.setAttribute("aria-expanded", "false");
        toggle.setAttribute("aria-label", "打开导航");
      }
    });
  }

  requestAnimationFrame(mainLoop);
})();
