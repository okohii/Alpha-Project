"use strict";

/**
 * ALPHA Astral Core — Hélice Dupla Cyber-Astral.
 *
 * Entidade abstrata com duas espirais entrelaçadas (DNA), pontes de energia,
 * arcos orbitais, nucleo luminoso e particulas. Fundo escuro (#05060c),
 * paleta predominantemente vermelha com highlights brancos.
 *
 * Reage aos estados do avatar: idle/listening/thinking/planning/executing/
 * verifying/speaking/success/error.
 */
window.AstralCore = (function () {
  "use strict";

  const HELIX_R = 0.56;
  const HELIX_H = 3.4;
  const HELIX_TURNS = 1.6;
  const STRAND_W = 0.09;
  const N_SAMPLES = 110;
  const BRIDGE_EVERY = 0.085;
  const BRIDGE_W = 0.028;
  const ARC_COUNT = 3;
  const N_PARTICLES = 450;
  const TAU = Math.PI * 2;

  const ENERGY = {
    idle: 0.18, listening: 0.5, thinking: 0.7,
    planning: 0.62, executing: 0.85, verifying: 0.72,
    speaking: 1.0, success: 0.9, error: 0.4,
  };

  /* ── math 4x4 ───────────────────────────────────────────────────────── */

  function mat4() { const m = new Float32Array(16); m[0] = m[5] = m[10] = m[15] = 1; return m; }

  function mult(o, a, b) {
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
      let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
      o[c * 4 + r] = s;
    } return o;
  }

  function perspective(o, fy, asp, n, f) {
    const t = 1 / Math.tan(fy / 2); o.fill(0);
    o[0] = t / asp; o[5] = t; o[10] = (f + n) / (n - f); o[11] = -1; o[14] = 2 * f * n / (n - f);
    return o;
  }

  function lookAt(o, eye, ctr, up) {
    let zx = eye[0] - ctr[0], zy = eye[1] - ctr[1], zz = eye[2] - ctr[2];
    let l = Math.hypot(zx, zy, zz) || 1; zx /= l; zy /= l; zz /= l;
    let xx = up[1] * zz - up[2] * zy, xy = up[2] * zx - up[0] * zz, xz = up[0] * zy - up[1] * zx;
    l = Math.hypot(xx, xy, xz) || 1; xx /= l; xy /= l; xz /= l;
    const yx = zy * xz - zz * xy, yy = zz * xx - zx * xz, yz = zx * xy - zy * xx;
    o[0] = xx; o[1] = yx; o[2] = zx; o[3] = 0; o[4] = xy; o[5] = yy; o[6] = zy; o[7] = 0;
    o[8] = xz; o[9] = yz; o[10] = zz; o[11] = 0;
    o[12] = -(xx * eye[0] + xy * eye[1] + xz * eye[2]);
    o[13] = -(yx * eye[0] + yy * eye[1] + yz * eye[2]);
    o[14] = -(zx * eye[0] + zy * eye[1] + zz * eye[2]); o[15] = 1;
    return o;
  }

  function rotX(a) { const m = mat4(), c = Math.cos(a), s = Math.sin(a); m[5] = c; m[6] = s; m[9] = -s; m[10] = c; return m; }
  function rotY(a) { const m = mat4(), c = Math.cos(a), s = Math.sin(a); m[0] = c; m[2] = -s; m[8] = s; m[10] = c; return m; }

  /* ── GLSL ────────────────────────────────────────────────────────────── */

  const HELIX_VS = `
    attribute vec3 aPos;
    attribute float aType;
    uniform mat4 uPM, uVM;
    varying vec3 vW;
    varying float vT;
    void main(){
      vW = aPos; vT = aType;
      gl_Position = uPM * uVM * vec4(aPos, 1.0);
    }
  `;
  const HELIX_FS = `
    precision highp float;
    varying vec3 vW; varying float vT;
    uniform float uTime, uEnergy;
    void main(){
      float hN = clamp(vW.y / 1.6 + 0.5, 0.0, 1.0);
      float fade = sin(hN * 3.14159);
      float ang = atan(vW.x, vW.z);
      float pulse = 0.78 + 0.22 * sin(ang * 3.2 - uTime * 2.2);
      vec3 sC = mix(vec3(0.94, 0.10, 0.15), vec3(1.0, 0.6, 0.35), fade * pulse);
      vec3 bC = mix(vec3(0.96, 0.18, 0.16), vec3(1.0, 0.82, 0.55), pulse * (0.5 + 0.5 * uEnergy));
      vec3 col = vT > 0.5 ? bC : sC;
      float alpha = (0.42 + 0.5 * uEnergy) * fade * pulse;
      if (vT > 0.5) alpha *= (0.6 + 0.5 * uEnergy);
      if (alpha <= 0.02) discard;
      gl_FragColor = vec4(col, alpha);
    }
  `;

  const ARC_VS = `
    attribute vec3 aPos;
    attribute float aParam;
    uniform mat4 uPM, uVM;
    varying vec3 vW;
    varying float vParam;
    void main(){
      vW = aPos; vParam = aParam;
      gl_Position = uPM * uVM * vec4(aPos, 1.0);
    }
  `;
  const ARC_FS = `
    precision highp float;
    varying vec3 vW; varying float vParam;
    uniform float uTime, uEnergy;
    void main(){
      float pulse = 0.5 + 0.5 * sin(vParam * 6.28 - uTime * 2.5);
      vec3 col = mix(vec3(1.0, 0.15, 0.18), vec3(1.0, 0.72, 0.45), pulse);
      float a = (0.4 + 0.6 * uEnergy) * (0.6 + 0.4 * pulse);
      if (a <= 0.02) discard;
      gl_FragColor = vec4(col, a);
    }
  `;

  const PART_VS = `
    attribute vec3 aP; // strand(0/1), t, speed
    attribute float aSc;
    uniform mat4 uPM, uVM;
    uniform float uTime, uEnergy, uAmp;
    varying vec3 vCol;
    void main(){
      float strand = aP.x;
      float t = fract(aP.y + uTime * aP.z * 0.015);
      float ang = t * 6.28318 * ${HELIX_TURNS.toFixed(2)} + uTime * aP.z + strand * 3.14159;
      float R = ${HELIX_R.toFixed(2)} + 0.02 * sin(ang * 3.0);
      vec3 pos = vec3(R * cos(ang), (t - 0.5) * ${HELIX_H.toFixed(2)}, R * sin(ang));
      float sc = aSc * (0.08 + 0.06 * uEnergy);
      pos += vec3(sin(uTime * 0.7 + aP.y * 13.0) * sc, sin(uTime * 0.5 + aP.y * 9.0) * sc * 0.4, cos(uTime * 0.6 + aP.y * 11.0) * sc);
      float hN = clamp(pos.y / 1.6 + 0.5, 0.0, 1.0);
      float fade = sin(hN * 3.14159);
      vCol = mix(vec3(0.95, 0.15, 0.14), vec3(1.0, 0.6, 0.35), fade);
      float sz = (3.4 + uEnergy * 2.2 + uAmp * 1.2) * (0.45 + 0.55 * fade);
      gl_PointSize = min(sz, 22.0);
      gl_Position = uPM * uVM * vec4(pos, 1.0);
    }
  `;
  const PART_FS = `
    precision highp float;
    varying vec3 vCol;
    uniform float uEnergy;
    void main(){
      float d = length(gl_PointCoord - 0.5) * 2.0;
      float a = smoothstep(1.0, 0.0, d); a = a * a;
      if (a < 0.01) discard;
      gl_FragColor = vec4(vCol, a * (0.55 + 0.45 * uEnergy));
    }
  `;

  const HALO_VS = `
    attribute vec3 aPos;
    uniform mat4 uPM, uVM;
    uniform vec3 uCenter;
    uniform float uSize;
    varying vec2 vUV;
    void main(){
      vec4 v = uVM * vec4(uCenter, 1.0);
      vec3 R = vec3(uVM[0][0], uVM[1][0], uVM[2][0]);
      vec3 U = vec3(uVM[0][1], uVM[1][1], uVM[2][1]);
      vec3 p = v.xyz + (R * aPos.x + U * aPos.y) * uSize;
      vUV = aPos.xy + 0.5;
      gl_Position = uPM * vec4(p, 1.0);
    }
  `;
  const HALO_FS = `
    precision highp float;
    varying vec2 vUV;
    uniform float uEnergy, uAmp, uIntensity;
    void main(){
      float d = length(vUV - 0.5) * 2.0;
      float a = pow(max(1.0 - d, 0.0), 2.4);
      if (a < 0.01) discard;
      vec3 col = mix(vec3(0.95, 0.1, 0.13), vec3(1.0, 0.55, 0.32), d * 1.1);
      gl_FragColor = vec4(col, a * uIntensity * (0.45 + 0.55 * uEnergy + 0.5 * uAmp));
    }
  `;

  /* ── GL bootstrap ────────────────────────────────────────────────────── */

  function compile(gl, t, s) {
    const sh = gl.createShader(t); gl.shaderSource(sh, s); gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error("shader: " + gl.getShaderInfoLog(sh));
    return sh;
  }
  function link(gl, vs, fs) {
    const p = gl.createProgram(); gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, vs));
    gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error("link: " + gl.getProgramInfoLog(p));
    return p;
  }

  /* ── AstralCore ──────────────────────────────────────────────────────── */

  class AstralCore {
constructor(canvas) {
      const gl = canvas.getContext("webgl", { alpha: true, antialias: true, premultipliedAlpha: false, depth: true, powerPreference: "high-performance" })
        || canvas.getContext("experimental-webgl", { alpha: true });
      if (!gl) throw new Error("WebGL unavailable");
      this._gl = gl; this._canvas = canvas;
      this.state = "idle"; this._energy = 0.18; this._extAmp = 0; this._impulse = 0; this._lastT = 0; this._disposed = false;

      this._p = {
        helix: link(gl, HELIX_VS, HELIX_FS),
        arc: link(gl, ARC_VS, ARC_FS),
        part: link(gl, PART_VS, PART_FS),
        halo: link(gl, HALO_VS, HALO_FS),
      };

      // locations POR PROGRAMA — evitar colisão entre helix.aPos e halo.aPos
      this._L = {};
      const A = (pg, n) => {
        const m = (this._L[pg] = this._L[pg] || {});
        m[n] = gl.getAttribLocation(pg, n);
      };
      const U = (pg, n) => {
        const m = (this._L[pg] = this._L[pg] || {});
        m[n] = gl.getUniformLocation(pg, n);
      };

      const hp = this._p.helix, ap = this._p.arc, pp = this._p.part, kp = this._p.halo;
      A(hp, "aPos"); A(hp, "aType"); U(hp, "uPM"); U(hp, "uVM"); U(hp, "uTime"); U(hp, "uEnergy");
      A(ap, "aPos"); A(ap, "aParam"); U(ap, "uPM"); U(ap, "uVM"); U(ap, "uTime"); U(ap, "uEnergy");
      A(pp, "aP"); A(pp, "aSc"); U(pp, "uPM"); U(pp, "uVM"); U(pp, "uTime"); U(pp, "uEnergy"); U(pp, "uAmp");
      A(kp, "aPos"); U(kp, "uPM"); U(kp, "uVM"); U(kp, "uCenter"); U(kp, "uSize"); U(kp, "uEnergy"); U(kp, "uAmp"); U(kp, "uIntensity");

      this._helixBuf = gl.createBuffer();
      this._arcBuf = gl.createBuffer();
      this._buildParticles();
      this._buildQuad();
      this.resize();
      window.addEventListener("resize", () => this.resize());
      this._raf = requestAnimationFrame((t) => this._loop(t));
    }

    _buildParticles() {
      const gl = this._gl;
      const data = new Float32Array(N_PARTICLES * 4);
      for (let i = 0; i < N_PARTICLES; i++) {
        data[i * 4] = Math.random() < 0.5 ? 0 : 1;
        data[i * 4 + 1] = Math.random();
        data[i * 4 + 2] = 0.2 + Math.random() * 0.8;
        data[i * 4 + 3] = 0.5 + Math.random() * 1.5;
      }
      this._partBuf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, this._partBuf);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    }

    _buildQuad() {
      const gl = this._gl;
      this._quadBuf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, this._quadBuf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-0.5, -0.5, 0, 0.5, -0.5, 0, -0.5, 0.5, 0, 0.5, 0.5, 0]), gl.STATIC_DRAW);
    }

    resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = this._canvas.clientWidth || window.innerWidth;
      const h = this._canvas.clientHeight || window.innerHeight;
      this._canvas.width = Math.max(1, Math.floor(w * dpr));
      this._canvas.height = Math.max(1, Math.floor(h * dpr));
      this._gl.viewport(0, 0, this._canvas.width, this._canvas.height);
      this._asp = this._canvas.width / this._canvas.height;
    }

    setState(s) {
      if (s in ENERGY) {
        if (this.state === "success" && s !== "success") this._impulse = 1;
        if (s === "error") this._impulse = 0.5;
        this.state = s;
      }
    }

    setAmplitude(v) { this._extAmp = Math.max(0, Math.min(1, v)); }
    dispose() { this._disposed = true; cancelAnimationFrame(this._raf); }

    /* ── loop ──────────────────────────────────────────────────────────── */

    _loop(ts) {
      if (this._disposed) return;
      const dt = this._lastT ? Math.min((ts - this._lastT) / 1000, 0.1) : 0.016;
      this._lastT = ts;
      const t = ts * 0.001;
      const gl = this._gl;

      const target = ENERGY[this.state] || 0.2;
      this._energy += (target - this._energy) * (1 - Math.exp(-dt * 2.8));
      this._impulse = Math.max(0, this._impulse - dt * 2.2);
      const e = this._energy;
      const amp = this._extAmp * 0.4 + this._impulse * 0.6;
      const speaking = this.state === "speaking";

      const pmat = mat4();
      perspective(pmat, 0.62, Math.max(0.2, this._asp), 0.05, 50);
      const sw = Math.sin(t * 0.25);
      const eye = [
        0.35 * Math.sin(t * 0.18 + 1) * (0.5 + e),
        1.3 + 0.3 * Math.sin(t * 0.35) * (0.4 + e),
        4.3 + 0.25 * sw * (0.3 + e),
      ];
      const vmat = mat4();
      lookAt(vmat, eye, [0, 0, 0], [0, 1, 0]);

      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST);
      gl.enable(gl.BLEND);

      const spin = t * 0.35 + e * 0.08;

      // 1. aura externa
      this._drawHalo(pmat, vmat, [0, 0, 0], 4.8, 0.22 + 0.4 * e + amp * 0.25, amp);
      this._drawHalo(pmat, vmat, [0, 0, 0], 2.2, 0.7 + 0.5 * e + amp * 0.35, amp);

      // 2. nucleo luminoso
      const nucleusPulse = 1 + 0.12 * e + (speaking ? 0.35 * Math.abs(Math.sin(t * 7.5)) : 0.05 * Math.sin(t * 2));
      this._drawHalo(pmat, vmat, [0, 0, 0], 0.8 * nucleusPulse, 1.1 + 0.6 * e, amp);

      // 3. helice
      this._drawHelix(pmat, vmat, spin, t, e);

      // 4. arcos orbitais
      this._drawArcs(pmat, vmat, spin, t, e);

      // 5. particulas
      this._drawParticles(pmat, vmat, t, e, amp, spin);

      // 6. flash
      if (this._impulse > 0.02) {
        this._drawHalo(pmat, vmat, [0, 0, 0], 3.5 + this._impulse * 2, this._impulse * 0.85, amp);
      }
    }

    /* ── draw helpers ───────────────────────────────────────────────────── */

    _drawHalo(pm, vm, c, size, intensity, amp) {
      const gl = this._gl, L = this._L[this._p.halo];
      gl.useProgram(this._p.halo);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
      gl.disable(gl.DEPTH_TEST);
      gl.depthMask(false);
      gl.bindBuffer(gl.ARRAY_BUFFER, this._quadBuf);
      gl.enableVertexAttribArray(L.aPos);
      gl.vertexAttribPointer(L.aPos, 3, gl.FLOAT, false, 0, 0);
      gl.uniformMatrix4fv(L.uPM, false, pm);
      gl.uniformMatrix4fv(L.uVM, false, vm);
      gl.uniform3fv(L.uCenter, c);
      gl.uniform1f(L.uSize, size);
      gl.uniform1f(L.uEnergy, this._energy);
      gl.uniform1f(L.uAmp, amp);
      gl.uniform1f(L.uIntensity, intensity);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      gl.depthMask(true);
      gl.enable(gl.DEPTH_TEST);
    }

    _buildHelixData(spin, t, e) {
      const verts = []; // x,y,z,type  (type: 0=strand, 1=bridge)
      const k = HELIX_H / TAU / HELIX_TURNS; // dy/dθ

      for (let strand = 0; strand < 2; strand++) {
        for (let i = 0; i <= N_SAMPLES; i++) {
          const tf = i / N_SAMPLES;
          const theta = tf * TAU * HELIX_TURNS + spin + strand * Math.PI;
          const sway = Math.sin(tf * 3 + t * 0.2) * 0.04 * (0.3 + e);
          const cx = HELIX_R * Math.cos(theta) + sway;
          const cz = HELIX_R * Math.sin(theta);
          const cy = (tf - 0.5) * HELIX_H;

          const wFrac = Math.sin(tf * Math.PI);
          const w = STRAND_W * wFrac * (0.85 + 0.3 * e);

          const perpX = Math.cos(theta);
          const perpZ = Math.sin(theta);
          verts.push(cx + perpX * w, cy, cz + perpZ * w, 0);
          verts.push(cx - perpX * w, cy, cz - perpZ * w, 0);
        }
      }

      // energy bridges (quad strip de 4 vértices por ponte)
      const nBridges = Math.floor(1 / BRIDGE_EVERY);
      for (let b = 1; b < nBridges; b++) {
        const tf = b * BRIDGE_EVERY;
        const theta1 = tf * TAU * HELIX_TURNS + spin;
        const theta2 = theta1 + Math.PI;
        const y = (tf - 0.5) * HELIX_H;
        const wB = BRIDGE_W * (0.6 + 0.4 * Math.sin(t * 3 + b * 2));
        const dx = Math.cos(theta1) * HELIX_R, dz = Math.sin(theta1) * HELIX_R;
        const dx2 = Math.cos(theta2) * HELIX_R, dz2 = Math.sin(theta2) * HELIX_R;
        const nx = -(dz2 - dz), nz = (dx2 - dx);
        const len = Math.hypot(nx, nz) || 1;
        nx /= len; nz /= len;
        verts.push(dx + nx * wB, y, dz + nz * wB, 1);
        verts.push(dx2 + nx * wB, y, dz2 + nz * wB, 1);
        verts.push(dx - nx * wB, y, dz - nz * wB, 1);
        verts.push(dx2 - nx * wB, y, dz2 - nz * wB, 1);
      }

      return new Float32Array(verts);
    }

    _drawHelix(pm, vm, spin, t, e) {
      const gl = this._gl, L = this._L[this._p.helix];
      gl.useProgram(this._p.helix);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
      gl.depthMask(false);

      const data = this._buildHelixData(spin, t, e);
      const perStrand = (N_SAMPLES + 1) * 2;
      const bridgeStart = perStrand * 2;
      const nBridges = Math.floor(1 / BRIDGE_EVERY) - 1;

      gl.bindBuffer(gl.ARRAY_BUFFER, this._helixBuf);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_DRAW);
      gl.enableVertexAttribArray(L.aPos);
      gl.vertexAttribPointer(L.aPos, 3, gl.FLOAT, false, 16, 0);
      gl.enableVertexAttribArray(L.aType);
      gl.vertexAttribPointer(L.aType, 1, gl.FLOAT, false, 16, 12);

      gl.uniformMatrix4fv(L.uPM, false, pm);
      gl.uniformMatrix4fv(L.uVM, false, vm);
      gl.uniform1f(L.uTime, t);
      gl.uniform1f(L.uEnergy, e);

      // fita da hélice 1 e 2 (strips separados, sem triângulo de junção)
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, perStrand);
      gl.drawArrays(gl.TRIANGLE_STRIP, perStrand, perStrand);

      // pontes de energia (quad strip por ponte)
      for (let b = 0; b < nBridges; b++) {
        gl.drawArrays(gl.TRIANGLE_STRIP, bridgeStart + b * 4, 4);
      }

      gl.depthMask(true);
    }

    _buildArcData(spin, t, e) {
      const verts = [];
      const arcParams = [
        { r: 0.85, rZ: 0.75, hAmp: 1.3, turns: 0.8, speed: 0.35, phase: 0 },
        { r: 1.05, rZ: 0.9, hAmp: 1.0, turns: 1.1, speed: -0.28, phase: 2.1 },
        { r: 0.7, rZ: 0.65, hAmp: 1.5, turns: 0.6, speed: 0.42, phase: 4.2 },
      ];
      const arcSegs = 70;

      for (let a = 0; a < ARC_COUNT && a < arcParams.length; a++) {
        const ap = arcParams[a];
        const w = 0.045 * (0.8 + 0.5 * e);
        for (let i = 0; i <= arcSegs; i++) {
          const tf = i / arcSegs;
          const angle = tf * TAU * ap.turns + spin * ap.speed + ap.phase;
          const x = ap.r * Math.cos(angle);
          const z = ap.rZ * Math.sin(angle);
          const y = Math.sin(tf * Math.PI) * ap.hAmp + Math.sin(angle * 2 + t * 1.5) * 0.08 * e;
          const tangX = -ap.r * Math.sin(angle) * ap.turns;
          const tangZ = ap.rZ * Math.cos(angle) * ap.turns;
          const tangY = Math.cos(tf * Math.PI) * ap.hAmp;
          const len = Math.hypot(tangX, tangY, tangZ) || 1;
          const nx = -tangZ / len, ny = tangX / len, nz = 0;
          verts.push(x + nx * w, y + ny * w * 0.3, z + nz * w, tf);
          verts.push(x - nx * w, y - ny * w * 0.3, z - nz * w, tf);
        }
      }
      return new Float32Array(verts);
    }

    _drawArcs(pm, vm, spin, t, e) {
      const gl = this._gl, L = this._L[this._p.arc];
      gl.useProgram(this._p.arc);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
      gl.depthMask(false);

      const data = this._buildArcData(spin, t, e);
      gl.bindBuffer(gl.ARRAY_BUFFER, this._arcBuf);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_DRAW);
      gl.enableVertexAttribArray(L.aPos);
      gl.vertexAttribPointer(L.aPos, 3, gl.FLOAT, false, 16, 0);
      gl.enableVertexAttribArray(L.aParam);
      gl.vertexAttribPointer(L.aParam, 1, gl.FLOAT, false, 16, 12);

      gl.uniformMatrix4fv(L.uPM, false, pm);
      gl.uniformMatrix4fv(L.uVM, false, vm);
      gl.uniform1f(L.uTime, t);
      gl.uniform1f(L.uEnergy, e);

      const arcSegs = 70;
      const arcVertsPer = (arcSegs + 1) * 2;
      for (let a = 0; a < ARC_COUNT; a++) {
        gl.drawArrays(gl.TRIANGLE_STRIP, a * arcVertsPer, arcVertsPer);
      }

      gl.depthMask(true);
    }

    _drawParticles(pm, vm, t, e, amp, spin) {
      const gl = this._gl, L = this._L[this._p.part];
      gl.useProgram(this._p.part);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
      gl.depthMask(false);

      gl.bindBuffer(gl.ARRAY_BUFFER, this._partBuf);
      gl.enableVertexAttribArray(L.aP);
      gl.vertexAttribPointer(L.aP, 3, gl.FLOAT, false, 16, 0);
      gl.enableVertexAttribArray(L.aSc);
      gl.vertexAttribPointer(L.aSc, 1, gl.FLOAT, false, 16, 12);

      gl.uniformMatrix4fv(L.uPM, false, pm);
      gl.uniformMatrix4fv(L.uVM, false, vm);
      gl.uniform1f(L.uTime, t);
      gl.uniform1f(L.uEnergy, e);
      gl.uniform1f(L.uAmp, amp);

      gl.drawArrays(gl.POINTS, 0, N_PARTICLES);
      gl.depthMask(true);
    }
  }

  return AstralCore;
})();