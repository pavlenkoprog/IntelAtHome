export const LOOKS = [
  { id: "normal", key: "1", label: "NORMAL" },
  { id: "crt", key: "2", label: "CRT" },
  { id: "noir", key: "3", label: "NOIR" },
];

let current = "normal";
let bound = false;

export function attachLooks(root, hud, map) {
  if (map) {
    mountScanlines(map, root);
  }
  renderBar(root);
  applyLook("normal", root, hud);

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
    applyLook(look.id, root, hud);
  });
}

function mountScanlines(map, root) {
  const pane = map.getPane("fxPane") || map.createPane("fxPane");
  pane.style.zIndex = 215;
  pane.style.pointerEvents = "none";
  for (const name of [".look-scanlines", ".look-grain"]) {
    const node = root.querySelector(name);
    if (node && node.parentElement !== pane) {
      pane.appendChild(node);
    }
  }
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
  if (hud && active) {
    hud.textContent = `Сенсор: ${active.label} · клавиши 1–3`;
  }
}
