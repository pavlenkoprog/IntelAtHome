export const LOOKS = [
  { id: "normal", key: "1", label: "NORMAL" },
  { id: "crt", key: "2", label: "CRT" },
  { id: "noir", key: "3", label: "NOIR" },
];

const NOIR_FS = `
uniform sampler2D colorTexture;
uniform float intensity;
uniform float contrastAmt;
uniform float grainAmt;
uniform float vignetteAmt;
in vec2 v_textureCoordinates;

void main() {
  vec2 uv = v_textureCoordinates;
  vec4 color = texture(colorTexture, uv);
  float luma = dot(color.rgb, vec3(0.299, 0.587, 0.114));
  vec3 desaturated = mix(color.rgb, vec3(luma), intensity);
  float contrast = 1.0 + contrastAmt * intensity;
  vec3 contrasted = clamp((desaturated - 0.5) * contrast + 0.5, 0.0, 1.0);
  float grain = fract(sin(dot(uv * vec2(1245.0, 973.0), vec2(12.9898, 78.233))) * 43758.5453);
  contrasted += (grain - 0.5) * 0.1 * grainAmt * intensity;
  vec2 vigUV = uv * (1.0 - uv);
  float vig = pow(vigUV.x * vigUV.y * 16.0, 0.28 + 0.45 * vignetteAmt * intensity);
  vec3 sepia = vec3(
    dot(contrasted, vec3(0.393, 0.769, 0.189)),
    dot(contrasted, vec3(0.349, 0.686, 0.168)),
    dot(contrasted, vec3(0.272, 0.534, 0.131))
  );
  vec3 tinted = mix(contrasted, sepia, 0.18 * intensity);
  out_FragColor = vec4(mix(color.rgb, tinted * vig, intensity), color.a);
}
`;

const CRT_FS = `
uniform sampler2D colorTexture;
uniform float intensity;
in vec2 v_textureCoordinates;

void main() {
  vec4 color = texture(colorTexture, v_textureCoordinates);
  vec3 rgb = color.rgb;
  float luma = dot(rgb, vec3(0.299, 0.587, 0.114));
  vec3 graded = mix(vec3(luma), rgb, 0.85);
  graded *= vec3(1.08, 1.01, 0.92);
  graded = (graded - 0.5) * 1.25 + 0.5;
  graded *= 1.05;
  out_FragColor = vec4(mix(color.rgb, clamp(graded, 0.0, 1.0), intensity), color.a);
}
`;

let current = "crt";
let bound = false;
let stages = null;

export function attachLooks(root, hud, viewer) {
  ensureStages(viewer);
  renderBar(root);
  applyLook("crt", root, hud);

  if (bound) {
    return;
  }
  bound = true;
  window.addEventListener("keydown", (event) => {
    if (event.target.closest("input, textarea, select")) {
      return;
    }
    const look = LOOKS.find((item) => item.key === event.key);
    if (!look || document.getElementById("globeRoot")?.hidden) {
      return;
    }
    applyLook(look.id, root, document.getElementById("globeHud"));
  });
}

function ensureStages(viewer) {
  if (stages || !viewer || !window.Cesium) {
    return;
  }
  const Cesium = window.Cesium;
  stages = {
    noir: viewer.scene.postProcessStages.add(
      new Cesium.PostProcessStage({
        name: "look_noir",
        fragmentShader: NOIR_FS,
        uniforms: { intensity: 0, contrastAmt: 1.45, grainAmt: 0.62, vignetteAmt: 0.78 },
      }),
    ),
    crt: viewer.scene.postProcessStages.add(
      new Cesium.PostProcessStage({
        name: "look_crt",
        fragmentShader: CRT_FS,
        uniforms: { intensity: 0 },
      }),
    ),
  };
  stages.noir.enabled = false;
  stages.crt.enabled = false;
}

function renderBar(root) {
  let bar = document.getElementById("lookBar");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "lookBar";
    bar.className = "look-bar";
    root.appendChild(bar);
  }
  bar.innerHTML = LOOKS.map(
    (look) =>
      `<button type="button" data-look="${look.id}" class="${look.id === current ? "is-active" : ""}">${look.key} ${look.label}</button>`,
  ).join("");
  bar.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      applyLook(button.dataset.look, root, document.getElementById("globeHud"));
    });
  });
}

function applyLook(id, root, hud) {
  current = id;
  LOOKS.forEach((look) => root.classList.toggle(`look-${look.id}`, look.id === id));
  const active = LOOKS.find((look) => look.id === id);
  document.querySelectorAll("#lookBar button").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.look === id);
  });
  if (stages) {
    stages.noir.enabled = id === "noir";
    stages.noir.uniforms.intensity = id === "noir" ? 1 : 0;
    stages.crt.enabled = id === "crt";
    stages.crt.uniforms.intensity = id === "crt" ? 1 : 0;
  }
  if (hud && active) {
    hud.textContent = `Сенсор: ${active.label} · клавиши 1–3`;
  }
}
