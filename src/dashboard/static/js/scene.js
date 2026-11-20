// AI automation engine — Three.js scene for the Command Center.
// ~19 draw calls: core, shell, glow, 3 rings, instanced nodes, halo points, 8 links, spokes, particles, pulses.
// Pulses only flow while a real backend job is running (state.active); idle = slow ambient drift.
import * as THREE from "../vendor/three.module.min.js";

const STATUS_COLOR = { ok: 0x5eead4, idle: 0x5b6488, warn: 0xfbbf24, err: 0xfb7185, run: 0x3be0ff };

export function webglAvailable() {
  try {
    const c = document.createElement("canvas");
    return !!(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl")));
  } catch { return false; }
}

function glowTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d");
  const r = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  r.addColorStop(0, "rgba(255,255,255,1)");
  r.addColorStop(0.25, "rgba(255,255,255,.45)");
  r.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = r;
  g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export function createScene(host, { nodes, onSelect, tip }) {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  host.prepend(renderer.domElement);
  renderer.domElement.setAttribute("aria-hidden", "true");

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x04060d, 0.035);
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
  const world = new THREE.Group();
  scene.add(world);
  const tex = glowTexture();
  const disposables = [tex];
  const track = (o) => (disposables.push(o), o);

  // ---------------- core
  const coreU = { uTime: { value: 0 }, uEnergy: { value: 1 }, cA: { value: new THREE.Color(0x0b1440) }, cB: { value: new THREE.Color(0x4c7dff) }, cC: { value: new THREE.Color(0x9b7bff) } };
  const core = new THREE.Mesh(track(new THREE.IcosahedronGeometry(1.15, 5)), track(new THREE.ShaderMaterial({
    uniforms: coreU,
    vertexShader: `uniform float uTime; varying vec3 vN; varying vec3 vV; varying float vD;
      float n3(vec3 p){ return sin(p.x*2.1+uTime*.9)*sin(p.y*2.3+uTime*.7)*sin(p.z*1.9+uTime*.8); }
      void main(){ float d=n3(position*1.6)*.085+n3(position*3.4+1.7)*.03; vD=d;
        vec4 mv=modelViewMatrix*vec4(position+normal*d,1.); vN=normalize(normalMatrix*normal); vV=normalize(-mv.xyz); gl_Position=projectionMatrix*mv; }`,
    fragmentShader: `uniform vec3 cA; uniform vec3 cB; uniform vec3 cC; uniform float uEnergy; varying vec3 vN; varying vec3 vV; varying float vD;
      void main(){ float f=pow(1.-max(dot(vN,vV),0.),2.4); vec3 base=mix(cA,cB*.55,smoothstep(-.09,.11,vD));
        vec3 col=base+mix(cB,cC,f)*f*1.7*uEnergy; gl_FragColor=vec4(col,1.); }`,
  })));
  world.add(core);
  const shell = new THREE.LineSegments(track(new THREE.EdgesGeometry(track(new THREE.IcosahedronGeometry(1.62, 1)))),
    track(new THREE.LineBasicMaterial({ color: 0x7aa0ff, transparent: true, opacity: 0.14 })));
  world.add(shell);
  const glow = new THREE.Sprite(track(new THREE.SpriteMaterial({ map: tex, color: 0x4c7dff, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false })));
  glow.scale.setScalar(6.5);
  world.add(glow);

  // ---------------- rings
  const rings = [[2.05, 0x4c7dff, 0.5, [1.2, 0.2, 0]], [2.45, 0x8b5cf6, 0.32, [1.45, -0.5, 0.3]], [2.9, 0x3be0ff, 0.18, [1.0, 0.8, -0.2]]].map(([r, c, o, rot]) => {
    const m = new THREE.Mesh(track(new THREE.TorusGeometry(r, 0.006, 6, 220)),
      track(new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: o, blending: THREE.AdditiveBlending, depthWrite: false })));
    m.rotation.set(...rot);
    world.add(m);
    return m;
  });

  // ---------------- orbital nodes
  const orbit = new THREE.Group();
  orbit.rotation.x = -0.42;
  world.add(orbit);
  const N = nodes.length, R = 4.7;
  const pos = nodes.map((_, i) => {
    const a = (i / N) * Math.PI * 2 - Math.PI / 2;
    return new THREE.Vector3(Math.cos(a) * R, Math.sin(i * 1.7) * 0.35, Math.sin(a) * R);
  });
  const inst = new THREE.InstancedMesh(track(new THREE.SphereGeometry(0.15, 20, 14)), track(new THREE.MeshBasicMaterial({ color: 0xffffff })), N);
  const haloGeo = track(new THREE.BufferGeometry().setFromPoints(pos));
  const haloCol = new Float32Array(N * 3);
  haloGeo.setAttribute("color", new THREE.BufferAttribute(haloCol, 3));
  const halos = new THREE.Points(haloGeo, track(new THREE.PointsMaterial({ map: tex, size: 1.25, vertexColors: true, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending, depthWrite: false })));
  orbit.add(inst, halos);

  // sequential workflow links (curved toward the core)
  const curves = pos.slice(0, -1).map((p, i) => new THREE.QuadraticBezierCurve3(p, p.clone().add(pos[i + 1]).multiplyScalar(0.36), pos[i + 1]));
  const links = curves.map((c) => {
    const l = new THREE.Line(track(new THREE.BufferGeometry().setFromPoints(c.getPoints(40))),
      track(new THREE.LineBasicMaterial({ color: 0x7aa0ff, transparent: true, opacity: 0.35, blending: THREE.AdditiveBlending, depthWrite: false })));
    orbit.add(l);
    return l;
  });
  // spokes to the core (one draw call)
  const spokeArr = [];
  pos.forEach((p) => spokeArr.push(0, 0, 0, p.x, p.y, p.z));
  const spokes = new THREE.LineSegments(track(new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(spokeArr, 3))),
    track(new THREE.LineBasicMaterial({ color: 0x4c7dff, transparent: true, opacity: 0.08, depthWrite: false })));
  orbit.add(spokes);

  // pulses (only visible while a real job runs)
  const P = 18;
  const pulseGeo = track(new THREE.BufferGeometry());
  pulseGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(P * 3), 3));
  const pulses = new THREE.Points(pulseGeo, track(new THREE.PointsMaterial({ map: tex, size: 0.42, color: 0x3be0ff, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false })));
  pulses.visible = false;
  orbit.add(pulses);

  // ambient particles
  const PC = 700, pp = new Float32Array(PC * 3);
  for (let i = 0; i < PC; i++) {
    const r = 6 + Math.random() * 12, t = Math.random() * Math.PI * 2, u = Math.acos(2 * Math.random() - 1);
    pp.set([r * Math.sin(u) * Math.cos(t), r * Math.cos(u) * 0.55, r * Math.sin(u) * Math.sin(t)], i * 3);
  }
  const dust = new THREE.Points(track(new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(pp, 3))),
    track(new THREE.PointsMaterial({ map: tex, size: 0.09, color: 0x8ea8ff, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false })));
  scene.add(dust);

  // ---------------- labels (projected DOM)
  const labelLayer = document.createElement("div");
  labelLayer.style.cssText = "position:absolute;inset:0;pointer-events:none;z-index:1;overflow:hidden";
  const labels = nodes.map((n) => {
    const d = document.createElement("div");
    d.textContent = n.short || n.name;
    d.style.cssText = "position:absolute;left:0;top:0;font:500 10.5px 'JetBrains Mono',monospace;letter-spacing:.06em;color:#a7afcf;white-space:nowrap;transform:translate(-50%,14px);transition:color .2s,opacity .2s;text-shadow:0 1px 8px #000";
    labelLayer.append(d);
    return d;
  });
  host.append(labelLayer);

  // ---------------- state
  let status = nodes.map(() => "idle"), active = -1, hovered = -1, energy = 1, targetEnergy = 1;
  const m4 = new THREE.Matrix4(), col = new THREE.Color(), tmp = new THREE.Vector3();
  const screen = nodes.map(() => ({ x: 0, y: 0, vis: true }));
  let W = 1, H = 1, shift = 0;

  function layout() {
    W = host.clientWidth || 1; H = host.clientHeight || 1;
    renderer.setSize(W, H, false);
    camera.aspect = W / H;
    const wide = camera.aspect > 1.25;
    // Fit the engine into the free side of the hero: copy sits left on wide layouts, on top when narrow.
    const halfH = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * 14.2, halfW = halfH * camera.aspect;
    shift = wide ? halfW * 0.5 : 0;
    // narrow: engine lives in a ~BAND px strip under the copy (see .hero-copy padding-bottom)
    const BAND = 300, px2world = (2 * halfH) / H;
    const fit = wide ? Math.min(1.05, (halfW * 0.47) / 5.4, (halfH * 0.95) / 4.2) : Math.min(1, (halfW * 0.92) / 5.2, (BAND * px2world) / 4.4);
    world.scale.setScalar(fit);
    camera.position.set(0, wide ? 2.4 : 0.6, 14.2);
    camera.lookAt(0, wide ? 0 : 0, 0);
    world.position.set(shift, wide ? -0.2 : -(H / 2 - BAND / 2 - 10) * px2world, 0);
    labels.forEach((l) => (l.style.display = W < 560 ? "none" : ""));
    camera.updateProjectionMatrix();
  }

  function applyColors() {
    nodes.forEach((_, i) => {
      const s = i === active ? "run" : status[i];
      col.setHex(STATUS_COLOR[s] ?? STATUS_COLOR.idle);
      inst.setColorAt(i, col);
      const dim = hovered >= 0 && hovered !== i ? 0.35 : 1;
      haloCol.set([col.r * dim, col.g * dim, col.b * dim], i * 3);
      labels[i].style.color = hovered === i || active === i ? "#eef1ff" : "#8790b4";
    });
    inst.instanceColor.needsUpdate = true;
    haloGeo.attributes.color.needsUpdate = true;
    links.forEach((l, i) => {
      const on = hovered >= 0 ? (i === hovered || i === hovered - 1) : active >= 0 ? (i === active - 1 || i === active) : false;
      l.material.opacity = on ? 0.95 : hovered >= 0 ? 0.12 : 0.32;
      l.material.color.setHex(on ? 0x3be0ff : 0x7aa0ff);
    });
  }
  inst.setColorAt(0, col); // allocate instanceColor
  applyColors();

  // ---------------- interaction (screen-space picking: forgiving on touch)
  const pointer = { x: 0, y: 0, nx: 0, ny: 0, inside: false };
  function pick(px, py) {
    let best = -1, bd = 34;
    screen.forEach((s, i) => { const d = Math.hypot(s.x - px, s.y - py); if (s.vis && d < bd) { bd = d; best = i; } });
    return best;
  }
  function onMove(e) {
    const r = host.getBoundingClientRect();
    pointer.x = e.clientX - r.left; pointer.y = e.clientY - r.top;
    pointer.nx = (pointer.x / r.width) * 2 - 1; pointer.ny = (pointer.y / r.height) * 2 - 1;
    const h = pick(pointer.x, pointer.y);
    if (h !== hovered) { hovered = h; applyColors(); renderTip(); }
    host.style.cursor = h >= 0 ? "pointer" : "";
    if (reduce) frame(0);
  }
  function onLeave() { hovered = -1; applyColors(); renderTip(); host.style.cursor = ""; if (reduce) frame(0); }
  function onClick(e) {
    const r = host.getBoundingClientRect();
    const i = pick(e.clientX - r.left, e.clientY - r.top);
    if (i < 0) return;
    if (reduce || !running) return onSelect(nodes[i]);
    const fly = (flyTo = { i, t0: performance.now() });
    setTimeout(() => { if (flyTo === fly) { flyTo = null; camera.zoom = 1; camera.updateProjectionMatrix(); onSelect(nodes[i]); } }, 900); // rAF may be throttled
  }
  function renderTip() {
    if (!tip) return;
    if (hovered < 0) { tip.style.opacity = "0"; return; }
    const n = nodes[hovered];
    tip.innerHTML = n.tipHTML ? n.tipHTML() : n.name;
    tip.style.opacity = "1";
    tip.style.left = screen[hovered].x + "px";
    tip.style.top = screen[hovered].y + "px";
  }
  host.addEventListener("pointermove", onMove);
  host.addEventListener("pointerleave", onLeave);
  host.addEventListener("click", onClick);
  function onKey(e) { // keyboard: arrow keys cycle nodes, Enter opens
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") { hovered = (Math.max(hovered, 0) + (e.key === "ArrowRight" ? 1 : N - 1)) % N; applyColors(); renderTip(); e.preventDefault(); if (reduce) frame(0); }
    if (e.key === "Enter" && hovered >= 0) onSelect(nodes[hovered]);
  }
  host.addEventListener("keydown", onKey);

  // ---------------- loop
  let raf = 0, running = false, last = performance.now(), t = 0, flyTo = null;
  const lookTarget = new THREE.Vector3();
  function frame(now) {
    const dt = Math.min((now - last) / 1000, 0.05) || 0;
    last = now;
    if (!reduce) t += dt;
    energy += (targetEnergy - energy) * Math.min(dt * 3, 1);
    coreU.uTime.value = t;
    coreU.uEnergy.value = energy;
    core.rotation.y = t * 0.12;
    shell.rotation.y = -t * 0.05; shell.rotation.x = t * 0.03;
    rings.forEach((r, i) => (r.rotation.z = t * (0.08 + i * 0.04) * (i % 2 ? -1 : 1)));
    orbit.rotation.y = t * 0.035;
    dust.rotation.y = t * 0.01;
    glow.material.opacity = 0.45 + 0.12 * Math.sin(t * 1.3) * energy;

    nodes.forEach((_, i) => {
      const s = (i === hovered ? 1.7 : 1) * (i === active ? 1.25 + 0.2 * Math.sin(t * 6) : 1);
      m4.makeScale(s, s, s).setPosition(pos[i]);
      inst.setMatrixAt(i, m4);
    });
    inst.instanceMatrix.needsUpdate = true;

    if (active >= 0 && !reduce) {
      const arr = pulseGeo.attributes.position.array;
      const lanes = [active - 1, active].filter((k) => k >= 0 && k < curves.length);
      for (let k = 0; k < P; k++) {
        const lane = lanes.length ? curves[lanes[k % lanes.length]] : null;
        const u = (t * 0.45 + k / P) % 1;
        if (lane) lane.getPoint(u, tmp); else tmp.copy(pos[active]).multiplyScalar(u);
        if (k % 3 === 2) tmp.copy(pos[active]).multiplyScalar(1 - u); // core → active stage
        arr.set([tmp.x, tmp.y, tmp.z], k * 3);
      }
      pulseGeo.attributes.position.needsUpdate = true;
    }

    // camera: gentle parallax, optional fly-to on click
    const wide = camera.aspect > 1.25;
    const baseY = wide ? 2.4 : 0.6;
    camera.position.x += ((reduce ? 0 : pointer.nx * 0.6) - camera.position.x) * 0.04;
    camera.position.y += ((reduce ? baseY : baseY - pointer.ny * 0.4) - camera.position.y) * 0.04;
    lookTarget.set(shift * 0.15, 0, 0);
    if (flyTo) {
      const k = Math.min((now - flyTo.t0) / 520, 1), e = k * k * (3 - 2 * k);
      orbit.localToWorld(tmp.copy(pos[flyTo.i]));
      lookTarget.lerp(tmp, e * 0.85);
      camera.zoom = 1 + e * 0.9;
      camera.updateProjectionMatrix();
      if (k >= 1) { const n = nodes[flyTo.i]; flyTo = null; camera.zoom = 1; camera.updateProjectionMatrix(); onSelect(n); }
    }
    camera.lookAt(lookTarget);

    renderer.render(scene, camera);

    // project labels / picking targets
    nodes.forEach((_, i) => {
      orbit.localToWorld(tmp.copy(pos[i]));
      tmp.project(camera);
      const s = screen[i];
      s.x = (tmp.x * 0.5 + 0.5) * W; s.y = (-tmp.y * 0.5 + 0.5) * H; s.vis = tmp.z < 1;
      labels[i].style.transform = `translate(${s.x}px, ${s.y}px) translate(-50%, 14px)`;
    });
    if (hovered >= 0 && tip) { tip.style.left = screen[hovered].x + "px"; tip.style.top = screen[hovered].y + "px"; }
    if (running && !reduce) raf = requestAnimationFrame(frame);
  }
  function start() { if (running || reduce) return; running = true; last = performance.now(); raf = requestAnimationFrame(frame); }
  function stop() { running = false; cancelAnimationFrame(raf); }

  // pause when off-screen or tab hidden
  let onScreen = true;
  const io = new IntersectionObserver(([e]) => { onScreen = e.isIntersecting; onScreen && !document.hidden ? start() : stop(); }, { threshold: 0.02 });
  io.observe(host);
  const onVis = () => (document.hidden || !onScreen ? stop() : start());
  document.addEventListener("visibilitychange", onVis);
  const ro = new ResizeObserver(() => { layout(); if (reduce || !running) frame(performance.now()); });
  ro.observe(host);
  layout();
  frame(performance.now());
  start();

  return {
    /** statuses: array of 'ok'|'idle'|'warn'|'err'; activeIndex: node index of the running stage or -1 */
    update(statuses, activeIndex) {
      status = statuses;
      active = activeIndex;
      targetEnergy = active >= 0 ? 1.8 : 1;
      pulses.visible = active >= 0;
      applyColors();
      if (reduce) frame(performance.now());
    },
    destroy() {
      stop();
      io.disconnect(); ro.disconnect();
      document.removeEventListener("visibilitychange", onVis);
      host.removeEventListener("pointermove", onMove);
      host.removeEventListener("pointerleave", onLeave);
      host.removeEventListener("click", onClick);
      host.removeEventListener("keydown", onKey);
      disposables.forEach((d) => d.dispose && d.dispose());
      inst.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
      labelLayer.remove();
    },
  };
}
