import { attachCursorMeta } from "./cursor-meta.js";
import { attachLooks } from "./filters.js";
import { attachLayers } from "./layers.js";

let map = null;

export async function showGlobe() {
  const root = document.getElementById("globeRoot");
  const container = document.getElementById("cesiumContainer");
  const hud = document.getElementById("globeHud");
  if (!root || !container) {
    throw new Error("Нет контейнера карты");
  }

  root.hidden = false;
  await loadLeaflet();

  if (!window.L) {
    setHud(hud, "Leaflet не загрузился");
    throw new Error("Leaflet не загрузился");
  }

  if (!map) {
    map = window.L.map(container, {
      worldCopyJump: true,
      minZoom: 2,
      zoomControl: true,
    }).setView([30, 20], 3);
    attachLayers(map);
    attachLooks(root, hud);
    attachCursorMeta(map, root);
  }

  requestAnimationFrame(() => map.invalidateSize());
  setTimeout(() => map.invalidateSize(), 100);
}

export function hideGlobe() {
  const root = document.getElementById("globeRoot");
  if (root) {
    root.hidden = true;
  }
}

function setHud(hud, text) {
  if (hud) {
    hud.textContent = text;
  }
}

function loadLeaflet() {
  if (window.L) {
    return Promise.resolve();
  }

  loadCss("/vendor/leaflet/leaflet.css");
  return loadScript("/vendor/leaflet/leaflet.js");
}

function loadCss(href) {
  if (document.querySelector(`link[href="${href}"]`)) {
    return;
  }
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  document.head.appendChild(link);
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error(`Не загрузился ${src}`)));
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Не загрузился ${src}`));
    document.head.appendChild(script);
  });
}
