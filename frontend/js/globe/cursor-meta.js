import { api } from "../api.js";
import { cameraZoom, pickLatLng } from "./camera.js";

const ESRI_META =
  "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/4/query";

export function attachCursorMeta(viewer, root) {
  let chip = document.getElementById("cursorMeta");
  if (!chip) {
    chip = document.createElement("div");
    chip.id = "cursorMeta";
    chip.className = "cursor-meta";
    root.appendChild(chip);
  }
  const shotEl = ensureChipLine(chip, "cursor-meta-shot", "снимок…");
  const heightEl = ensureChipLine(chip, "cursor-meta-height", "");
  heightEl.hidden = true;

  let metaTimer = 0;
  let heightTimer = 0;
  let requestId = 0;
  let heightRequest = 0;
  let lastKey = "";
  let heightKey = "";
  const Cesium = window.Cesium;

  const applyHeight = (meters) => {
    const line = formatElevation(meters);
    if (!line) {
      return;
    }
    heightEl.hidden = false;
    heightEl.textContent = line;
  };

  const moveChip = (event) => {
    const bounds = root.getBoundingClientRect();
    chip.style.left = `${event.clientX - bounds.left + 14}px`;
    chip.style.top = `${event.clientY - bounds.top + 16}px`;
    chip.hidden = false;
  };

  const loadMeta = async (latlng) => {
    const zoom = Math.round(cameraZoom(viewer));
    const key = `${latlng.lat.toFixed(3)}:${latlng.lon.toFixed(3)}:${zoom}`;
    if (key === lastKey) {
      return;
    }
    lastKey = key;
    const id = ++requestId;
    try {
      const imagery = await fetchImageryMeta(latlng.lat, latlng.lon, zoom);
      if (id !== requestId) {
        return;
      }
      shotEl.textContent = formatMeta(imagery);
    } catch {
      if (id === requestId) {
        shotEl.textContent = "нет метаданных";
      }
    }
  };

  const loadHeight = async (latlng) => {
    const key = `${latlng.lat.toFixed(4)}:${latlng.lon.toFixed(4)}`;
    if (key === heightKey) {
      return;
    }
    heightKey = key;
    const id = ++heightRequest;
    const meters = await sampleHeight(viewer, latlng.lat, latlng.lon);
    if (id !== heightRequest) {
      return;
    }
    if (meters == null) {
      heightKey = "";
      return;
    }
    applyHeight(meters);
  };

  const canvas = viewer.scene.canvas;
  canvas.addEventListener("mousemove", (event) => {
    const bounds = canvas.getBoundingClientRect();
    const windowPos = new Cesium.Cartesian2(event.clientX - bounds.left, event.clientY - bounds.top);
    const latlng = pickLatLng(viewer, windowPos, true);
    moveChip(event);
    if (!latlng) {
      lastKey = "";
      heightKey = "";
      shotEl.textContent = "космос";
      heightEl.hidden = true;
      return;
    }
    applyHeight(loadedHeight(viewer, latlng.lat, latlng.lon));
    window.clearTimeout(metaTimer);
    window.clearTimeout(heightTimer);
    metaTimer = window.setTimeout(() => loadMeta(latlng), 140);
    heightTimer = window.setTimeout(() => loadHeight(latlng), 80);
  });
  canvas.addEventListener("mouseleave", () => {
    chip.hidden = true;
  });
}

function ensureChipLine(chip, className, text) {
  let line = chip.querySelector(`.${className}`);
  if (!line) {
    line = document.createElement("div");
    line.className = className;
    chip.append(line);
  }
  line.textContent = text;
  return line;
}

function reliefProvider(viewer) {
  const Cesium = window.Cesium;
  const provider = viewer.terrainProvider;
  if (!provider || provider instanceof Cesium.EllipsoidTerrainProvider) {
    return null;
  }
  return provider;
}

function loadedHeight(viewer, lat, lon) {
  const Cesium = window.Cesium;
  if (!reliefProvider(viewer) || !viewer.scene?.globe?.getHeight) {
    return null;
  }
  const height = viewer.scene.globe.getHeight(Cesium.Cartographic.fromDegrees(lon, lat));
  return Number.isFinite(height) ? height : null;
}

async function sampleHeight(viewer, lat, lon) {
  const Cesium = window.Cesium;
  const provider = reliefProvider(viewer);
  if (!provider || !Cesium.sampleTerrain) {
    return null;
  }
  const level = Math.max(0, Math.min(12, Math.round(cameraZoom(viewer))));
  try {
    const [sampled] = await Cesium.sampleTerrain(provider, level, [Cesium.Cartographic.fromDegrees(lon, lat)]);
    return Number.isFinite(sampled?.height) ? sampled.height : null;
  } catch {
    return null;
  }
}

async function fetchImageryMeta(lat, lon, zoom) {
  try {
    const url = new URL(ESRI_META);
    url.search = new URLSearchParams({
      geometry: `${lon},${lat}`,
      geometryType: "esriGeometryPoint",
      inSR: "4326",
      spatialRel: "esriSpatialRelIntersects",
      outFields: "SRC_DATE,SRC_RES,SRC_DESC,NICE_NAME,NICE_DESC,MinMapLevel,MaxMapLevel",
      returnGeometry: "false",
      f: "json",
    }).toString();
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error("esri");
    }
    return pickRecord(await response.json(), zoom);
  } catch {
    return api.geo.imagery({
      lat: String(lat),
      lon: String(lon),
      zoom: String(zoom),
    });
  }
}

function pickRecord(raw, zoom) {
  const records = (raw.features || []).map((feature) => feature.attributes || {});
  const matching = records.filter((item) => {
    const min = item.MinMapLevel;
    const max = item.MaxMapLevel;
    return min == null || max == null || (min <= zoom && zoom <= max);
  });
  const pool = matching.length ? matching : records;
  if (!pool.length) {
    return { date: null, source: null, name: null, resolution_m: null };
  }
  const chosen = pool.reduce((best, item) => {
    const res = item.SRC_RES == null ? 9999 : item.SRC_RES;
    const bestRes = best.SRC_RES == null ? 9999 : best.SRC_RES;
    return res < bestRes ? item : best;
  });
  return {
    date: formatSrcDate(chosen.SRC_DATE),
    source: chosen.NICE_DESC || chosen.SRC_DESC || chosen.NICE_NAME,
    name: chosen.NICE_NAME,
    resolution_m: chosen.SRC_RES,
  };
}

function formatSrcDate(value) {
  if (value == null || value === "" || value === 99999 || value === "99999") {
    return null;
  }
  const text = String(value);
  if (/^\d{8}$/.test(text)) {
    return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`;
  }
  return text;
}

function formatElevation(meters) {
  if (!Number.isFinite(meters)) {
    return "";
  }
  return `высота ${Math.round(meters).toLocaleString("ru-RU")} м`;
}

function formatMeta(data) {
  const date = data.date || "нет даты";
  const source = data.source || data.name || "неизвестный источник";
  if (data.resolution_m == null) {
    return `${date} · ${source}`;
  }
  const res = Number(data.resolution_m) >= 1 ? Number(data.resolution_m).toFixed(0) : Number(data.resolution_m).toFixed(2);
  return `${date} · ${source} · ${res} м`;
}
