/**
 * Fisheye Studio — Interactive Live WebGL 2 Demo for landonwarnecke.com
 * Demonstrates real-time continuous ray unprojection, physical lenses, and aberrations.
 */

(function () {
  const canvas = document.getElementById('demoCanvas');
  if (!canvas) return;

  const gl = canvas.getContext('webgl2', {
    alpha: false,
    antialias: false,
    preserveDrawingBuffer: false,
    powerPreference: 'high-performance'
  });

  if (!gl) {
    console.warn('WebGL 2 not supported in this browser.');
    return;
  }

  const vsSource = `#version 300 es
  in vec2 position;
  void main() {
    gl_Position = vec4(position, 0.0, 1.0);
  }`;

  const fsSource = `#version 300 es
  precision highp float;
  out vec4 fragColor;

  uniform vec2 u_resolution;
  uniform float u_time;
  uniform vec2 u_mouse;
  uniform int u_mode; // 0: Equisolid, 1: Stereographic, 2: Equidistant, 3: Orthographic
  uniform float u_fov; // degrees
  uniform float u_radialChroma;
  uniform float u_vignette;
  uniform bool u_ssaa;
  uniform vec3 u_skyA, u_skyB, u_groundA, u_groundB, u_tintA, u_tintB, u_void;

  const float PI = 3.141592653589793;

  vec3 unprojectRay(vec2 p, float fovDeg, int mode) {
    float thetaMax = radians(fovDeg) * 0.5;
    float rad = length(p);
    if (rad < 1e-7) return vec3(0.0, 0.0, 1.0);
    vec2 d = p / rad;

    float focal = 1.0;
    float th = 0.0;

    if (mode == 0) { // Equisolid
      focal = 1.0 / (2.0 * sin(thetaMax * 0.5));
      float val = clamp(rad / (2.0 * focal), -1.0, 1.0);
      th = 2.0 * asin(val);
    } else if (mode == 1) { // Stereographic
      focal = 1.0 / (2.0 * tan(thetaMax * 0.5));
      th = 2.0 * atan(rad / (2.0 * focal));
    } else if (mode == 2) { // Equidistant
      focal = 1.0 / thetaMax;
      th = rad / focal;
    } else if (mode == 3) { // Orthographic
      focal = 1.0 / sin(thetaMax);
      float val = clamp(rad / focal, -1.0, 1.0);
      th = asin(val);
    }

    if (th > thetaMax + 0.001) return vec3(0.0);
    return vec3(sin(th) * d.x, sin(th) * d.y, cos(th));
  }

  vec3 traceScene(vec3 rayDir, vec2 mouseRot) {
    if (length(rayDir) < 0.1) return u_void;

    // Orbit camera matrix
    float pitch = mouseRot.y * 1.5;
    float yaw = mouseRot.x * 2.5 + u_time * 0.15;
    mat3 rotY = mat3(cos(yaw), 0.0, sin(yaw), 0.0, 1.0, 0.0, -sin(yaw), 0.0, cos(yaw));
    mat3 rotX = mat3(1.0, 0.0, 0.0, 0.0, cos(pitch), -sin(pitch), 0.0, sin(pitch), cos(pitch));
    vec3 rd = rotY * rotX * rayDir;

    // Atmospheric ground and sky
    vec3 sky = mix(u_skyA, u_skyB, rd.y * 0.5 + 0.5);
    vec3 col = sky;

    // Ground plane with perspective grid
    if (rd.y < -0.01) {
      float t = -2.5 / rd.y;
      vec3 p = rd * t;
      float grid = step(0.95, fract(p.x * 0.4)) + step(0.95, fract(p.z * 0.4));
      vec3 ground = mix(u_groundA, u_groundB, min(1.0, grid) * 0.6);
      ground *= exp(-t * 0.04);
      col = mix(sky, ground, smoothstep(-0.01, -0.05, rd.y));
    }

    // 13-Sphere Thomson Polyhedron Layout (matching KeyShot Perspective Studio)
    vec3 lightDir = normalize(vec3(-0.6, 0.9, 0.8));
    float closestT = 1000.0;
    
    for (int i = 0; i < 13; i++) {
      float fi = float(i);
      float a = fi * 2.39996;
      float z = 1.0 - 2.0 * (fi + 0.5) / 13.0;
      vec3 center = vec3(sqrt(1.0 - z * z) * cos(a), sqrt(1.0 - z * z) * sin(a), z) * 4.8;
      float radius = 0.85 + 0.15 * sin(fi * 1.8 + u_time * 0.5);

      float b = dot(rd, center);
      float disc = b * b - dot(center, center) + radius * radius;
      if (disc > 0.0) {
        float hitT = b - sqrt(disc);
        if (hitT > 0.0 && hitT < closestT) {
          closestT = hitT;
          vec3 n = normalize(rd * hitT - center);
          vec3 tint = mix(u_tintA, u_tintB, 0.5 + 0.5 * sin(fi * 1.7));
          float diff = max(0.0, dot(n, lightDir));
          float spec = pow(max(0.0, dot(reflect(-lightDir, n), -rd)), 40.0);
          float rim = pow(1.0 - max(0.0, dot(n, -rd)), 3.0);
          col = tint * (0.2 + 0.75 * diff) + vec3(1.0, 0.97, 0.95) * spec * 0.85 + rim * 0.15;
        }
      }
    }
    return col;
  }

  vec3 renderSample(vec2 screenCoord, vec2 mouseRot) {
    vec2 p = (screenCoord - u_resolution * 0.5) / min(u_resolution.x, u_resolution.y) * 2.0;
    float rho = length(p);

    // Full-frame radial chromatic aberration
    float disp = u_radialChroma * 0.008 * (rho * rho);
    vec3 dir = unprojectRay(p, u_fov, u_mode);
    if (length(dir) < 0.1) return u_void;

    vec3 col = traceScene(dir, mouseRot);

    if (u_radialChroma > 0.001) {
      vec3 dirR = unprojectRay(p * (1.0 - disp), u_fov, u_mode);
      vec3 dirB = unprojectRay(p * (1.0 + disp), u_fov, u_mode);
      if (length(dirR) > 0.1 && length(dirB) > 0.1) {
        col.r = traceScene(dirR, mouseRot).r;
        col.b = traceScene(dirB, mouseRot).b;
      }
    }

    // Optical Vignetting (cos^n falloff)
    if (u_vignette > 0.001) {
      float vig = pow(clamp(cos(rho * 1.15), 0.0, 1.0), u_vignette * 2.5);
      col *= vig;
    }

    // Antialiased rim mask
    float rimMask = smoothstep(1.0, 0.992, rho);
    col *= rimMask;
    return col;
  }

  void main() {
    vec3 finalColor = vec3(0.0);
    if (u_ssaa) {
      // 4-Sample Rotated Grid Super-Sampling (RGSS)
      vec2 o0 = vec2(-0.375, -0.125);
      vec2 o1 = vec2(-0.125,  0.375);
      vec2 o2 = vec2( 0.125, -0.375);
      vec2 o3 = vec2( 0.375,  0.125);
      finalColor += renderSample(gl_FragCoord.xy + o0, u_mouse);
      finalColor += renderSample(gl_FragCoord.xy + o1, u_mouse);
      finalColor += renderSample(gl_FragCoord.xy + o2, u_mouse);
      finalColor += renderSample(gl_FragCoord.xy + o3, u_mouse);
      finalColor *= 0.25;
    } else {
      finalColor = renderSample(gl_FragCoord.xy, u_mouse);
    }
    fragColor = vec4(finalColor, 1.0);
  }`;

  function createShader(gl, type, source) {
    const s = gl.createShader(type);
    gl.shaderSource(s, source);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      console.error(gl.getShaderInfoLog(s));
      gl.deleteShader(s);
      return null;
    }
    return s;
  }

  const vs = createShader(gl, gl.VERTEX_SHADER, vsSource);
  const fs = createShader(gl, gl.FRAGMENT_SHADER, fsSource);
  const program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);

  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.error('Program link failed:', gl.getProgramInfoLog(program));
    return;
  }
  gl.useProgram(program);

  // Screen quad
  const quadBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, quadBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
    -1, -1,  1, -1, -1,  1,
    -1,  1,  1, -1,  1,  1
  ]), gl.STATIC_DRAW);

  const aPos = gl.getAttribLocation(program, 'position');
  gl.enableVertexAttribArray(aPos);
  gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

  // Uniform locations
  const uRes = gl.getUniformLocation(program, 'u_resolution');
  const uTime = gl.getUniformLocation(program, 'u_time');
  const uMouse = gl.getUniformLocation(program, 'u_mouse');
  const uMode = gl.getUniformLocation(program, 'u_mode');
  const uFov = gl.getUniformLocation(program, 'u_fov');
  const uChroma = gl.getUniformLocation(program, 'u_radialChroma');
  const uVignette = gl.getUniformLocation(program, 'u_vignette');
  const uSSAA = gl.getUniformLocation(program, 'u_ssaa');
  // Palette from theme.css (re-read when the system light/dark setting changes)
  const themeNames = { u_skyA: '--lw-scene-sky-a', u_skyB: '--lw-scene-sky-b', u_groundA: '--lw-scene-ground-a', u_groundB: '--lw-scene-ground-b', u_tintA: '--lw-scene-tint-a', u_tintB: '--lw-scene-tint-b', u_void: '--lw-scene-void' };
  const themeLocs = {}; Object.keys(themeNames).forEach((k) => { themeLocs[k] = gl.getUniformLocation(program, k); });
  function hexVec(v, fallback) {
    const m = /^#?([0-9a-f]{6})$/i.exec((v || '').trim());
    if (!m) return fallback;
    const n = parseInt(m[1], 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  }
  let themeVals = {};
  function readTheme() {
    const cs = getComputedStyle(document.documentElement);
    Object.keys(themeNames).forEach((k) => { themeVals[k] = hexVec(cs.getPropertyValue(themeNames[k]), [0.5, 0.5, 0.5]); });
  }
  readTheme();
  if (window.matchMedia) matchMedia('(prefers-color-scheme: dark)').addEventListener('change', readTheme);
  function applyTheme() { Object.keys(themeLocs).forEach((k) => { if (themeLocs[k]) gl.uniform3fv(themeLocs[k], themeVals[k]); }); }

  // UI State
  let mode = 0; // Equisolid
  let fov = 190.0;
  let chroma = 0.20;
  let vignette = 0.25;
  let ssaa = true;

  let mouseX = 0.0;
  let mouseY = 0.0;
  let isDragging = false;
  let lastX = 0;
  let lastY = 0;

  // Bind UI Controls
  const modeSelect = document.getElementById('demoLensMode');
  const fovSlider = document.getElementById('demoFov');
  const fovVal = document.getElementById('demoFovVal');
  const chromaSlider = document.getElementById('demoChroma');
  const chromaVal = document.getElementById('demoChromaVal');
  const vigSlider = document.getElementById('demoVig');
  const vigVal = document.getElementById('demoVigVal');
  const ssaaCheck = document.getElementById('demoSsaa');
  const formulaLabel = document.getElementById('demoFormula');

  const formulas = [
    'r = 2f · sin(θ / 2) — Area Preserving',
    'r = 2f · tan(θ / 2) — Conformal / Circle Preserving',
    'r = f · θ — Linear Angular Distance',
    'r = f · sin(θ) — Planar Hemispherical'
  ];

  if (modeSelect) {
    modeSelect.addEventListener('change', () => {
      mode = parseInt(modeSelect.value, 10);
      if (formulaLabel) formulaLabel.textContent = formulas[mode];
    });
  }

  if (fovSlider && fovVal) {
    fovSlider.addEventListener('input', () => {
      fov = parseFloat(fovSlider.value);
      fovVal.textContent = fov.toFixed(0) + '°';
    });
  }

  if (chromaSlider && chromaVal) {
    chromaSlider.addEventListener('input', () => {
      chroma = parseFloat(chromaSlider.value);
      chromaVal.textContent = Math.round(chroma * 100) + '%';
    });
  }

  if (vigSlider && vigVal) {
    vigSlider.addEventListener('input', () => {
      vignette = parseFloat(vigSlider.value);
      vigVal.textContent = Math.round(vignette * 100) + '%';
    });
  }

  if (ssaaCheck) {
    ssaaCheck.addEventListener('change', () => {
      ssaa = ssaaCheck.checked;
    });
  }

  // Pointer Interaction
  canvas.addEventListener('pointerdown', (e) => {
    isDragging = true;
    lastX = e.clientX;
    lastY = e.clientY;
    canvas.setPointerCapture(e.pointerId);
  });

  window.addEventListener('pointermove', (e) => {
    if (!isDragging) return;
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    lastX = e.clientX;
    lastY = e.clientY;
    mouseX += dx * 0.005;
    mouseY = Math.max(-1.0, Math.min(1.0, mouseY + dy * 0.005));
  });

  window.addEventListener('pointerup', () => {
    isDragging = false;
  });

  // Render Loop
  let startTime = performance.now();

  function resize() {
    const dpr = Math.min(2.0, window.devicePixelRatio || 1.0);
    const w = Math.round(canvas.clientWidth * dpr);
    const h = Math.round(canvas.clientHeight * dpr);
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
      gl.viewport(0, 0, w, h);
    }
  }

  function frame(time) {
    resize();
    const elapsed = (time - startTime) * 0.001;

    gl.uniform2f(uRes, canvas.width, canvas.height);
    gl.uniform1f(uTime, elapsed);
    applyTheme();
    gl.uniform2f(uMouse, mouseX, mouseY);
    gl.uniform1i(uMode, mode);
    gl.uniform1f(uFov, fov);
    gl.uniform1f(uChroma, chroma);
    gl.uniform1f(uVignette, vignette);
    gl.uniform1i(uSSAA, ssaa ? 1 : 0);

    gl.drawArrays(gl.TRIANGLES, 0, 6);
    requestAnimationFrame(frame);
  }

  requestAnimationFrame(frame);
})();
