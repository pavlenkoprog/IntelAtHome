import { api } from "../api.js";

const ESRI_META =
  "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/4/query";

export function attachCursorMeta(map, root) {
  let chip = document.getElementById("cursorMeta");
  if (!chip) {
    chip = document.createElement("div");
    chip.id = "cursorMeta";
    chip.className = "cursor-meta";
    chip.textContent = "снимок…";
    root.appendChild(chip);
  }

  let timer = 0;
  let requestId = 0;
  let lastKey = "";

  const moveChip = (event) => {
    const bounds = root.getBoundingClientRect();
    chip.style.left = `${event.clientX - bounds.left + 14}px`;
    chip.style.top = `${event.clientY - bounds.top + 16}px`;
    chip.hidden = false;
  };

  const loadMeta = async (latlng) => {
    const zoom = Math.round(map.getZoom());
    const key = `${latlng.lat.toFixed(3)}:${latlng.lng.toFixed(3)}:${zoom}`;
    if (key === lastKey) {
      return;
    }
    lastKey = key;
    const id = ++requestId;
    try {
      const data = await fetchImageryMeta(latlng.lat, latlng.lng, zoom);
      if (id !== requestId) {
        return;
      }
      chip.textContent = formatMeta(data);
    } catch {
      if (id === requestId) {
        chip.textContent = "нет метаданных";
      }
    }
  };

  map.on("mousemove", (event) => {
    moveChip(event.originalEvent);
    window.clearTimeout(timer);
    timer = window.setTimeout(() => loadMeta(event.latlng), 140);
  });
  map.on("mouseout", () => {
    chip.hidden = true;
  });
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

function formatMeta(data) {
  const date = data.date || "нет даты";
  const source = data.source || data.name || "неизвестный источник";
  if (data.resolution_m == null) {
    return `${date} · ${source}`;
  }
  const res = Number(data.resolution_m) >= 1 ? Number(data.resolution_m).toFixed(0) : Number(data.resolution_m).toFixed(2);
  return `${date} · ${source} · ${res} м`;
}
