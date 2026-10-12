import { api } from "../api.js";
import { cameraZoom, viewBBox } from "./camera.js";
import { createWeatherView } from "./weather-canvas.js";

const ESRI_IMAGERY =
  "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer";
const ESRI_LABELS =
  "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer";
const ESRI_ROADS =
  "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer";
const OSM_TILES = "https://tile.openstreetmap.org/";
const PLANE_CIVIL = "/vendor/leaflet/images/plane_w.png";
const PLANE_MILITARY = "/vendor/leaflet/images/plane_r.png";
const SATELLITE_ICON = "/vendor/leaflet/images/satellite_negate.png";
const SATELLITE_SIZE = 20;
const PLANE_SIZE_BASE = 20;

const COLORS = {
  city: "#f0a202",
  town: "#e8edf7",
  airport: "#6cb6ff",
  military: "#ff6b6b",
  power: "#c084fc",
  port: "#22d3ee",
  place: "#f0a202",
  earthquake: "#ff8a3d",
  event: "#fb7185",
  flight: "#3dd68c",
  camera: "#6be8ff",
  satelliteMilitary: "#f97316",
  satelliteRecon: "#38bdf8",
};

const EVENT_COLORS = {
  drought: "#d97706",
  dustHaze: "#a8a29e",
  earthquakes: "#fb923c",
  floods: "#38bdf8",
  landslides: "#92400e",
  manmade: "#f472b6",
  seaLakeIce: "#7dd3fc",
  severeStorms: "#a78bfa",
  snow: "#e2e8f0",
  tempExtremes: "#facc15",
  volcanoes: "#f97316",
  waterColor: "#22d3ee",
  wildfires: "#ef4444",
};

const KIND_LABELS = {
  town: "населённый пункт",
  airport: "аэропорт",
  military: "военная база / аэродром",
  port: "порт",
  power: "электростанция",
  earthquake: "землетрясение",
  event: "событие NASA",
  camera: "онлайн-камера",
};

const timers = {};

export async function attachLayers(viewer, root) {
  viewer.scene.globe.show = true;
  const imagery = await addArcGisLayer(viewer, ESRI_IMAGERY, { credit: "Esri World Imagery" });
  const streets = addOsmLayer(viewer, { show: false });
  const roads = await addArcGisLayer(viewer, ESRI_ROADS, { credit: "Esri Transportation", alpha: 0.75 });
  const labels = await addArcGisLayer(viewer, ESRI_LABELS, { credit: "Esri Boundaries & Places" });
  const rain = {
    layer: addTiles(viewer, "https://tilecache.rainviewer.com/v2/radar/0/256/{z}/{x}/{y}/2/1_1.png", {
      credit: "RainViewer",
      maximumLevel: 7,
      alpha: 0.78,
      show: false,
    }),
    show: false,
  };
  const clouds = { layer: null, show: false };

  const quakes = addSource(viewer, "quakes");
  const events = addSource(viewer, "events");
  const flights = addSource(viewer, "flights");
  const places = addSource(viewer, "places");
  const storms = addSource(viewer, "storms", false);
  const cameras = addSource(viewer, "cameras");
  const satMilitary = addSource(viewer, "satellites-military");
  const satRecon = addSource(viewer, "satellites-recon");

  const overlays = {
    labels,
    roads,
    places,
    quakes,
    events,
    flights,
    cameras,
    satMilitary,
    satRecon,
    rain,
    clouds,
    storms,
    wind: { show: false },
  };

  attachLayerControl(root, { imagery, streets }, overlays);
  attachPicking(viewer, root);

  bindLiveLayer(viewer, quakes, "quakes", () => api.geo.earthquakes(), 600000);
  bindSatelliteLayers(viewer, satMilitary, satRecon);
  bindLiveLayer(viewer, events, "events", () => api.geo.events(), 600000);
  bindBBoxLayer(viewer, flights, "flights", (bbox) => api.geo.flights(bbox), 600000, 5, 250);
  bindBBoxLayer(viewer, cameras, "cameras", (bbox) => api.geo.cameras(bbox), 180000, 0, 400);
  bindBBoxLayer(viewer, places, "places", (bbox) => api.geo.places(bbox), 600000, 4);
  bindRadarLayer(viewer, rain, clouds);
  bindWeatherField(viewer, overlays);
}

function addProviderLayer(viewer, provider, options = {}) {
  const Cesium = window.Cesium;
  const layer = new Cesium.ImageryLayer(provider);
  layer.alpha = options.alpha ?? 1;
  layer.show = options.show ?? true;
  if (options.index == null) {
    viewer.imageryLayers.add(layer);
  } else {
    viewer.imageryLayers.add(layer, options.index);
  }
  return layer;
}

async function addArcGisLayer(viewer, url, options = {}) {
  const Cesium = window.Cesium;
  try {
    if (!Cesium.ArcGisMapServerImageryProvider?.fromUrl) {
      throw new Error("no ArcGIS provider");
    }
    const provider = await Cesium.ArcGisMapServerImageryProvider.fromUrl(url, {
      enablePickFeatures: false,
    });
    return addProviderLayer(viewer, provider, options);
  } catch (error) {
    console.warn("ArcGIS imagery unavailable", url, error);
    if (url === ESRI_IMAGERY) {
      return addOsmLayer(viewer, options);
    }
    return { show: false };
  }
}

function addOsmLayer(viewer, options = {}) {
  const Cesium = window.Cesium;
  const provider = new Cesium.OpenStreetMapImageryProvider({
    url: OSM_TILES,
    credit: options.credit || "© OpenStreetMap",
  });
  return addProviderLayer(viewer, provider, options);
}

function addTiles(viewer, url, options = {}) {
  const Cesium = window.Cesium;
  return addProviderLayer(
    viewer,
    new Cesium.UrlTemplateImageryProvider({
      enablePickFeatures: false,
      url,
      maximumLevel: options.maximumLevel ?? 17,
      credit: options.credit || "",
    }),
    options,
  );
}

function addSource(viewer, name, show = true) {
  const source = new window.Cesium.CustomDataSource(name);
  source.show = show;
  viewer.dataSources.add(source);
  return source;
}

function attachLayerControl(root, bases, overlays) {
  let panel = document.getElementById("globeLayers");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "globeLayers";
    panel.className = "globe-layers";
    root.appendChild(panel);
  }

  const overlayItems = [
    ["labels", "Города и границы"],
    ["roads", "Дороги"],
    ["places", "Объекты OSM"],
    ["quakes", "Землетрясения"],
    ["events", "События NASA"],
    ["flights", "Самолёты"],
    ["cameras", "Камеры"],
    ["satMilitary", "Спутники: военные"],
    ["satRecon", "Спутники: гражданские"],
    ["rain", "Осадки"],
    ["clouds", "Облачность"],
    ["storms", "Грозы"],
    ["wind", "Ветер"],
  ];

  panel.innerHTML = `
    <label><input type="radio" name="globe-base" value="imagery" checked> Спутник</label>
    <label><input type="radio" name="globe-base" value="streets"> Схема</label>
    <div class="globe-layers-sep"></div>
    ${overlayItems
      .map(
        ([key, label]) =>
          `<label><input type="checkbox" data-overlay="${key}" ${overlayOn(overlays[key]) ? "checked" : ""}> ${label}</label>`,
      )
      .join("")}
  `;

  panel.querySelectorAll('input[name="globe-base"]').forEach((input) => {
    input.addEventListener("change", () => {
      if (!input.checked) {
        return;
      }
      const satellite = input.value === "imagery";
      bases.imagery.show = satellite;
      bases.streets.show = !satellite;
    });
  });

  panel.querySelectorAll("input[data-overlay]").forEach((input) => {
    input.addEventListener("change", () => {
      const key = input.dataset.overlay;
      setOverlayShow(overlays[key], input.checked);
      overlays._onChange?.(key, input.checked);
    });
  });
}

function overlayOn(overlay) {
  if (!overlay) {
    return false;
  }
  if (overlay.layer) {
    return overlay.layer.show;
  }
  return overlay.show !== false;
}

function setOverlayShow(overlay, show) {
  if (!overlay) {
    return;
  }
  overlay.show = show;
  if (overlay.layer) {
    overlay.layer.show = show;
  }
}

function bindLiveLayer(viewer, source, key, loader, intervalMs) {
  const refresh = async () => {
    if (!source.show) {
      return;
    }
    try {
      const data = await loader();
      renderItems(source, data.items || [], cameraZoom(viewer));
    } catch {
      /* слой остаётся прежним */
    }
  };

  source.onShow = () => {
    refresh();
    timers[key] = window.setInterval(refresh, intervalMs);
  };
  source.onHide = () => {
    if (timers[key]) {
      window.clearInterval(timers[key]);
    }
  };
  refresh();
  timers[key] = window.setInterval(refresh, intervalMs);
}

function bindSatelliteLayers(viewer, military, recon) {
  let warming = 0;
  const refresh = async () => {
    if (!military.show && !recon.show) {
      return;
    }
    try {
      const data = await api.geo.satellites();
      if (data.reason === "warming") {
        if (warming < 8) {
          warming += 1;
          window.setTimeout(refresh, 2000);
        }
        return;
      }
      warming = 0;
      const items = data.items || [];
      if (military.show) {
        renderSatellites(viewer, military, items.filter((item) => item.group === "military"));
      }
      if (recon.show) {
        renderSatellites(viewer, recon, items.filter((item) => item.group === "recon"));
      }
    } catch {
      /* слой остаётся прежним */
    }
  };
  const arm = () => {
    refresh();
    if (!timers.satellites) {
      timers.satellites = window.setInterval(refresh, 15000);
    }
  };
  const disarm = () => {
    if (military.show || recon.show) {
      return;
    }
    if (timers.satellites) {
      window.clearInterval(timers.satellites);
      delete timers.satellites;
    }
  };
  military.onShow = arm;
  recon.onShow = arm;
  military.onHide = () => {
    military.entities.removeAll();
    disarm();
  };
  recon.onHide = () => {
    recon.entities.removeAll();
    disarm();
  };
  arm();
}

function bindBBoxLayer(viewer, source, key, loader, intervalMs, minZoom, debounceMs = 750) {
  let debounce = 0;
  let requestId = 0;
  let inflight = false;
  let pending = null;
  let retry = 0;
  let lastOk = 0;
  const debug = key === "cameras";
  const refresh = async (reason = "unknown") => {
    if (inflight) {
      pending = reason === "interval" ? pending || reason : reason;
      if (debug) {
        console.log(`[${key}] queue ${reason}`);
      }
      return;
    }
    const zoom = cameraZoom(viewer);
    if (!source.show || zoom < minZoom) {
      if (debug) {
        console.log(`[${key}] skip ${reason}`, { zoom, minZoom, layerOn: source.show });
      }
      if (zoom < minZoom) {
        source.entities.removeAll();
      }
      return;
    }
    if (reason === "interval" && Date.now() - lastOk < 8000) {
      if (debug) {
        console.log(`[${key}] skip interval, just loaded`);
      }
      return;
    }
    const bbox = viewBBox(viewer);
    const id = ++requestId;
    if (debug) {
      console.log(`[${key}] request ${reason}`, { id, zoom, bbox });
    }
    inflight = true;
    try {
      const data = await loader(bbox);
      if (id !== requestId) {
        return;
      }
      if (data.reason && !(data.items || []).length) {
        if (debug) {
          console.log(`[${key}] empty ${reason}`, { id, source: data.source, reason: data.reason });
        }
        if (reason !== "retry" && retry < 2) {
          pending = pending || "retry";
        }
        return;
      }
      retry = 0;
      const items = data.items || [];
      renderItems(source, items, zoom);
      lastOk = Date.now();
      if (debug) {
        console.log(`[${key}] loaded ${reason}`, {
          id,
          count: items.length,
          source: data.source,
          markers: source.entities.values.length,
          cities: countBy(items, "city"),
        });
      }
    } catch (error) {
      if (debug) {
        console.warn(`[${key}] error ${reason}`, error);
      }
    } finally {
      inflight = false;
      if (pending) {
        const next = pending;
        pending = null;
        if (next === "retry") {
          retry += 1;
          window.setTimeout(() => refresh("retry"), 1200);
        } else {
          refresh(next);
        }
      }
    }
  };
  const schedule = (reason) => {
    window.clearTimeout(debounce);
    debounce = window.setTimeout(() => refresh(reason), debounceMs);
  };

  viewer.camera.moveEnd.addEventListener(() => schedule("moveend"));
  if (viewer.scene.morphComplete) {
    viewer.scene.morphComplete.addEventListener(() => schedule("morph"));
  }
  source.onShow = () => {
    refresh("overlayadd");
    timers[key] = window.setInterval(() => refresh("interval"), intervalMs);
  };
  source.onHide = () => {
    if (timers[key]) {
      window.clearInterval(timers[key]);
    }
    if (debug) {
      console.log(`[${key}] layer off`);
    }
  };
  refresh("init");
  timers[key] = window.setInterval(() => refresh("interval"), intervalMs);
}

function countBy(items, field) {
  const counts = {};
  for (const item of items) {
    const label = item[field] || item.source || "?";
    counts[label] = (counts[label] || 0) + 1;
  }
  return counts;
}

function bindRadarLayer(viewer, rain, clouds) {
  const radarOn = () => rain.show !== false || clouds.show !== false;
  const refresh = async () => {
    if (!radarOn()) {
      return;
    }
    try {
      const data = await api.geo.weatherRadar();
      if (data.rain_url) {
        rain.layer = replaceOverlay(viewer, rain.layer, data.rain_url, {
          credit: "RainViewer",
          maximumLevel: 7,
          alpha: 0.78,
          show: rain.show !== false,
        });
      }
      if (data.clouds_url) {
        clouds.layer = replaceOverlay(viewer, clouds.layer, data.clouds_url, {
          credit: "RainViewer",
          maximumLevel: 7,
          alpha: 0.42,
          show: clouds.show !== false,
        });
      }
    } catch (error) {
      console.warn("weather radar", error);
    }
  };
  const startRadar = () => {
    refresh();
    if (!timers.rain) {
      timers.rain = window.setInterval(refresh, 180000);
    }
  };
  const stopRadar = () => {
    if (radarOn()) {
      return;
    }
    if (timers.rain) {
      window.clearInterval(timers.rain);
      delete timers.rain;
    }
  };

  rain.onShow = startRadar;
  clouds.onShow = startRadar;
  rain.onHide = stopRadar;
  clouds.onHide = stopRadar;
  if (radarOn()) {
    startRadar();
  }
}

function replaceOverlay(viewer, layer, url, options) {
  const index = layer ? viewer.imageryLayers.indexOf(layer) : undefined;
  if (layer) {
    viewer.imageryLayers.remove(layer, true);
  }
  return addTiles(viewer, url, {
    ...options,
    index: index != null && index >= 0 ? index : undefined,
  });
}

function bindWeatherField(viewer, overlays) {
  let debounce = 0;
  let requestId = 0;
  let inflight = false;
  let pending = false;
  let lastBBox = null;
  const fieldKeys = ["clouds", "storms", "wind"];
  const weatherKeys = ["clouds", "storms", "wind", "rain"];
  const view = createWeatherView(viewer);
  const anyOn = () => fieldKeys.some((key) => overlayOn(overlays[key]));
  const smallMove = (bbox) => {
    if (!lastBBox || lastBBox.zoom !== bbox.zoom) {
      return false;
    }
    const spanLat = Number(lastBBox.north) - Number(lastBBox.south);
    const spanLon = Number(lastBBox.east) - Number(lastBBox.west);
    return (
      Math.abs(Number(bbox.south) - Number(lastBBox.south)) < spanLat * 0.2 &&
      Math.abs(Number(bbox.west) - Number(lastBBox.west)) < spanLon * 0.2
    );
  };
  const syncEnabled = () => {
    view.setLayers({
      clouds: overlayOn(overlays.clouds),
      rain: overlayOn(overlays.rain),
      wind: overlayOn(overlays.wind),
    });
  };
  const refresh = async () => {
    if (!anyOn()) {
      view.setData([]);
      overlays.storms.entities.removeAll();
      return;
    }
    if (inflight) {
      pending = true;
      return;
    }
    const bbox = viewBBox(viewer);
    if (smallMove(bbox)) {
      return;
    }
    const id = ++requestId;
    inflight = true;
    try {
      const data = await api.geo.weather(bbox);
      if (id !== requestId) {
        return;
      }
      const items = data.items || [];
      if (!items.length && data.reason) {
        return;
      }
      view.setData(items, data.grid);
      lastBBox = bbox;
      syncEnabled();
      renderStorms(overlays.storms, items);
    } catch (error) {
      console.warn("weather field", error);
    } finally {
      inflight = false;
      if (pending) {
        pending = false;
        window.setTimeout(refresh, 1500);
      }
    }
  };
  const schedule = () => {
    window.clearTimeout(debounce);
    debounce = window.setTimeout(refresh, 400);
  };
  const syncTimer = () => {
    if (timers.weather) {
      window.clearInterval(timers.weather);
      delete timers.weather;
    }
    if (anyOn()) {
      refresh();
      timers.weather = window.setInterval(refresh, 600000);
    }
  };

  viewer.camera.moveEnd.addEventListener(() => {
    if (anyOn()) {
      schedule();
    }
  });
  if (viewer.scene.morphComplete) {
    viewer.scene.morphComplete.addEventListener(() => {
      if (anyOn()) {
        schedule();
      }
    });
  }

  overlays._onChange = (key) => {
    if (weatherKeys.includes(key)) {
      syncEnabled();
      syncTimer();
    }
    const overlay = overlays[key];
    if (overlay?.onShow && overlayOn(overlay)) {
      overlay.onShow();
    }
    if (overlay?.onHide && !overlayOn(overlay)) {
      overlay.onHide();
    }
  };

  syncEnabled();
  syncTimer();
}

function renderStorms(source, items) {
  source.entities.removeAll();
  const Cesium = window.Cesium;
  const image = boltIcon();
  for (const item of items) {
    if (!item.storm) {
      continue;
    }
    source.entities.add({
      name: stormLabel(item.weather_code),
      description: weatherPopup(item, "Гроза"),
      position: Cesium.Cartesian3.fromDegrees(item.lon, item.lat, 4000),
      billboard: {
        image,
        width: 22,
        height: 28,
        disableDepthTestDistance: 40000,
      },
    });
  }
}

function boltIcon() {
  const canvas = document.createElement("canvas");
  canvas.width = 44;
  canvas.height = 56;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#ff4d4d";
  ctx.shadowColor = "#ff2a2a";
  ctx.shadowBlur = 12;
  ctx.font = "40px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("↯", 22, 28);
  return canvas;
}

function stormLabel(code) {
  if (code === 96) {
    return "гроза с градом";
  }
  if (code === 99) {
    return "сильная гроза с градом";
  }
  return "гроза";
}

function weatherPopup(item, title) {
  const rows = Object.entries({
    Явление: title === "Гроза" ? stormLabel(item.weather_code) : title,
    Облачность: item.cloud_cover != null ? `${item.cloud_cover}%` : "",
    Осадки: item.precipitation != null ? `${item.precipitation} мм` : "",
    Ветер: item.wind_speed != null ? `${Number(item.wind_speed).toFixed(1)} м/с` : "",
    Направление: item.wind_direction != null ? `${item.wind_direction}°` : "",
  })
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([label, value]) => `<div><span class="muted">${label}:</span> ${escapeHtml(value)}</div>`)
    .join("");
  return `<strong>${escapeHtml(title)}</strong>${rows}<div class="muted">Open-Meteo</div>`;
}

function planeSize(zoom) {
  return Math.max(6, Math.min(32, Math.round(PLANE_SIZE_BASE * 1.2 ** (zoom - 7))));
}

function renderItems(source, items, zoom) {
  source.entities.removeAll();
  for (const item of items) {
    if (item.kind === "city") {
      continue;
    }
    if (item.kind === "flight") {
      source.entities.add(planeEntity(item, zoom));
    } else if (item.kind === "camera") {
      source.entities.add(cameraEntity(item, zoom));
    } else {
      source.entities.add(pointEntity(item));
    }
  }
}

let CAMERA_ICON = null;

function cameraIcon() {
  if (CAMERA_ICON) {
    return CAMERA_ICON;
  }
  const canvas = document.createElement("canvas");
  canvas.width = 44;
  canvas.height = 36;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "rgba(6, 18, 24, 0.82)";
  ctx.strokeStyle = COLORS.camera;
  ctx.lineWidth = 2.2;
  ctx.beginPath();
  if (typeof ctx.roundRect === "function") {
    ctx.roundRect(4, 8, 26, 20, 4);
  } else {
    ctx.rect(4, 8, 26, 20);
  }
  ctx.fill();
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(30, 14);
  ctx.lineTo(40, 10);
  ctx.lineTo(40, 26);
  ctx.lineTo(30, 22);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = COLORS.camera;
  ctx.beginPath();
  ctx.arc(17, 18, 4, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = "rgba(107, 232, 255, 0.35)";
  ctx.lineWidth = 4;
  ctx.beginPath();
  ctx.arc(17, 18, 7, 0, Math.PI * 2);
  ctx.stroke();
  CAMERA_ICON = canvas;
  return canvas;
}

function cameraEntity(item, zoom) {
  const Cesium = window.Cesium;
  const size = Math.max(16, Math.min(32, Math.round(30 - Number(zoom || 0) * 1.1)));
  return {
    name: item.name,
    description: popupHtml(item),
    position: Cesium.Cartesian3.fromDegrees(item.lon, item.lat, 40),
    billboard: {
      image: cameraIcon(),
      width: size,
      height: Math.round(size * 0.82),
      verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
      scaleByDistance: new Cesium.NearFarScalar(4.0e5, 1.0, 1.8e7, 2.4),
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    },
  };
}

function renderSatellites(viewer, source, items) {
  source.entities.removeAll();
  for (const item of items) {
    source.entities.add(satelliteEntity(item));
    if (Number.isFinite(Number(item.heading))) {
      source.entities.add(satelliteArrowEntity(viewer, item));
    }
  }
}

function satelliteScale() {
  return new window.Cesium.NearFarScalar(1.5e6, 1.0, 4.2e7, 0.55);
}

function satellitePlacement(item) {
  const Cesium = window.Cesium;
  const altKm = Number(item.altitude);
  const meters = Number.isFinite(altKm) ? altKm * 1000 : 400000;
  const css = item.group === "military" ? COLORS.satelliteMilitary : COLORS.satelliteRecon;
  return {
    position: Cesium.Cartesian3.fromDegrees(item.lon, item.lat, meters),
    color: Cesium.Color.fromCssColorString(css),
  };
}

let satelliteArrowImage = null;

function satelliteArrowCanvas() {
  if (satelliteArrowImage) {
    return satelliteArrowImage;
  }
  const icon = SATELLITE_SIZE;
  const span = Math.ceil(icon * 3);
  const canvas = document.createElement("canvas");
  canvas.width = span;
  canvas.height = span;
  const ctx = canvas.getContext("2d");
  const cx = span / 2;
  const cy = span / 2;
  const tip = cy - icon * 1.28;
  const head = Math.max(4, icon * 0.42);
  const headW = head * 0.62;
  const base = cy - icon * 0.62;
  const shaftEnd = tip + head * 0.7;

  const shaft = (color, width) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(cx, base);
    ctx.lineTo(cx, shaftEnd);
    ctx.stroke();
  };
  const headPath = (y, h, w) => {
    ctx.beginPath();
    ctx.moveTo(cx, y);
    ctx.lineTo(cx - w, y + h);
    ctx.lineTo(cx + w, y + h);
    ctx.closePath();
  };

  shaft("#000", Math.max(2.6, icon * 0.2));
  shaft("#fff", Math.max(1.4, icon * 0.1));
  headPath(tip - 0.8, head + 1.6, headW + 1.1);
  ctx.fillStyle = "#000";
  ctx.fill();
  headPath(tip, head, headW);
  ctx.fillStyle = "#fff";
  ctx.fill();

  satelliteArrowImage = canvas;
  return canvas;
}

function satelliteEntity(item) {
  const { position, color } = satellitePlacement(item);
  return {
    name: item.name,
    description: satellitePopup(item),
    position,
    billboard: {
      image: SATELLITE_ICON,
      color,
      width: SATELLITE_SIZE,
      height: SATELLITE_SIZE,
      scaleByDistance: satelliteScale(),
    },
  };
}

function offsetByHeading(position, headingDeg, meters) {
  const Cesium = window.Cesium;
  const heading = Cesium.Math.toRadians(headingDeg);
  const frame = Cesium.Transforms.eastNorthUpToFixedFrame(position);
  const east = Math.sin(heading) * meters;
  const north = Math.cos(heading) * meters;
  return Cesium.Matrix4.multiplyByPoint(frame, new Cesium.Cartesian3(east, north, 0), new Cesium.Cartesian3());
}

function courseScreenRotation(viewer, origin, headingDeg) {
  const Cesium = window.Cesium;
  const ahead = offsetByHeading(origin, headingDeg, 1000);
  const start = Cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene, origin);
  const end = Cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene, ahead);
  if (!start || !end) {
    return null;
  }
  return -Math.atan2(end.x - start.x, -(end.y - start.y));
}

function satelliteArrowEntity(viewer, item) {
  const Cesium = window.Cesium;
  const { position, color } = satellitePlacement(item);
  const span = Math.ceil(SATELLITE_SIZE * 3);
  const heading = Number(item.heading);
  let rotation = 0;
  return {
    name: item.name,
    description: satellitePopup(item),
    position,
    billboard: {
      image: satelliteArrowCanvas(),
      color,
      width: span,
      height: span,
      rotation: new Cesium.CallbackProperty(() => {
        const next = courseScreenRotation(viewer, position, heading);
        if (next != null) {
          rotation = next;
        }
        return rotation;
      }, false),
      scaleByDistance: satelliteScale(),
      eyeOffset: new Cesium.Cartesian3(0, 0, -20),
    },
  };
}

function satellitePopup(item) {
  const alt = Number(item.altitude);
  const speed = Number(item.speed);
  const heading = Number(item.heading);
  const rows = [
    ["Группа", item.group === "military" ? "военный" : "гражданский"],
    ["NORAD", item.norad],
    ["Высота", Number.isFinite(alt) ? `${Math.round(alt)} км` : ""],
    ["Скорость", Number.isFinite(speed) ? `${(speed / 1000).toFixed(2)} км/с` : ""],
    ["Курс", Number.isFinite(heading) ? `${Math.round(heading)}°` : ""],
  ]
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([label, value]) => `<div><span class="muted">${label}:</span> ${escapeHtml(value)}</div>`)
    .join("");
  return `<strong>${escapeHtml(item.name)}</strong>${rows}<div class="muted">CelesTrak</div>`;
}

function pointEntity(item) {
  const Cesium = window.Cesium;
  const color =
    item.kind === "event"
      ? EVENT_COLORS[item.category_id] || COLORS.event
      : COLORS[item.kind] || "#f0a202";
  return {
    name: item.name,
    description: popupHtml(item),
    position: Cesium.Cartesian3.fromDegrees(item.lon, item.lat, 1200),
    point: {
      pixelSize: radiusFor(item) * 1.6,
      color: Cesium.Color.fromCssColorString(color),
      outlineColor: Cesium.Color.BLACK.withAlpha(0.55),
      outlineWidth: 1,
      disableDepthTestDistance: 25000,
    },
  };
}

function planeEntity(item, zoom) {
  const Cesium = window.Cesium;
  const heading = Number(item.heading) || 0;
  const size = planeSize(zoom);
  const src = item.military ? PLANE_MILITARY : PLANE_CIVIL;
  const alt = Number(item.altitude);
  const meters = Number.isFinite(alt) && alt > 0 ? (alt > 20000 ? alt * 0.3048 : alt) : 9000;
  const position = Cesium.Cartesian3.fromDegrees(item.lon, item.lat, meters);
  const normal = Cesium.Ellipsoid.WGS84.geodeticSurfaceNormal(position);
  return {
    name: item.name,
    description: popupHtml(item),
    position,
    billboard: {
      image: src,
      width: size,
      height: size,
      alignedAxis: normal,
      rotation: Cesium.Math.toRadians(-heading),
      disableDepthTestDistance: 20000,
    },
  };
}

function radiusFor(item) {
  if (item.kind === "earthquake") {
    return Math.max(4, Math.min(14, Number(item.magnitude || 3) * 2));
  }
  if (item.kind === "city") {
    return 6;
  }
  if (item.kind === "flight") {
    return 4;
  }
  return 5;
}

function popupHtml(item) {
  const rows = Object.entries({
    Тип: kindLabel(item),
    Курс: item.heading,
    Категория: item.category,
    Магнитуда: item.magnitude,
    Высота: item.altitude,
    Страна: item.country,
    Город: item.city,
    Источник: item.source,
  })
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([label, value]) => `<div><span class="muted">${label}:</span> ${escapeHtml(value)}</div>`)
    .join("");
  return `${popupTitle(item)}${rows}${cameraFrameHtml(item)}`;
}

function cameraFrameHtml(item) {
  if (item.kind !== "camera" || !item.id) {
    return "";
  }
  const src = api.geo.cameraFrame(item.id);
  return `<img class="camera-frame" alt="${escapeHtml(item.name)}" data-src="${escapeHtml(src)}" src="${escapeHtml(src)}">`;
}

function popupTitle(item) {
  const name = escapeHtml(item.name);
  const ident = item.kind === "flight" ? flightAwareIdent(item.name) : "";
  if (!ident) {
    return `<strong>${name}</strong>`;
  }
  return `<strong><a href="https://www.flightaware.com/live/flight/${ident}" target="_blank" rel="noopener noreferrer">${name}</a></strong>`;
}

function flightAwareIdent(name) {
  const ident = String(name || "").replace(/\s+/g, "").toUpperCase();
  return /^[A-Z0-9]{2,12}$/.test(ident) ? ident : "";
}

function kindLabel(item) {
  if (item.kind === "flight") {
    return item.military ? "военный борт" : "гражданский борт";
  }
  return KIND_LABELS[item.kind] || item.kind;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function attachPicking(viewer, root) {
  const Cesium = window.Cesium;
  const popup = document.createElement("div");
  popup.className = "globe-popup";
  popup.hidden = true;
  root.appendChild(popup);
  const tooltip = document.createElement("div");
  tooltip.className = "globe-tooltip";
  tooltip.hidden = true;
  root.appendChild(tooltip);
  let frameTimer = 0;

  const stopFrame = () => {
    if (frameTimer) {
      window.clearInterval(frameTimer);
      frameTimer = 0;
    }
  };

  const bindCameraFrame = () => {
    stopFrame();
    const img = popup.querySelector(".camera-frame");
    if (!img) {
      return;
    }
    const src = img.dataset.src || img.getAttribute("src");
    if (!src) {
      return;
    }
    const bump = () => {
      const next = `${src}${src.includes("?") ? "&" : "?"}t=${Date.now()}`;
      img.src = next;
    };
    bump();
    frameTimer = window.setInterval(bump, 8000);
  };

  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  handler.setInputAction((click) => {
    const picked = viewer.scene.pick(click.position);
    const entity = picked && picked.id;
    const html = entityHtml(entity);
    if (!html) {
      stopFrame();
      popup.hidden = true;
      return;
    }
    popup.innerHTML = `<button type="button" class="globe-popup-close" aria-label="Закрыть">×</button>${html}`;
    popup.hidden = false;
    positionOverlay(popup, root, viewer, click.position);
    popup.querySelector(".globe-popup-close").onclick = () => {
      stopFrame();
      popup.hidden = true;
    };
    bindCameraFrame();
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

  handler.setInputAction((move) => {
    const picked = viewer.scene.pick(move.endPosition);
    const name = picked && picked.id && picked.id.name;
    if (name) {
      tooltip.textContent = name;
      tooltip.hidden = false;
      positionOverlay(tooltip, root, viewer, move.endPosition);
      viewer.scene.canvas.style.cursor = "pointer";
    } else {
      tooltip.hidden = true;
      viewer.scene.canvas.style.cursor = "";
    }
  }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
}

function entityHtml(entity) {
  if (!entity || entity.description == null) {
    return "";
  }
  return typeof entity.description.getValue === "function" ? entity.description.getValue() : entity.description;
}

function positionOverlay(el, root, viewer, windowPos) {
  const rootBox = root.getBoundingClientRect();
  const canvasBox = viewer.scene.canvas.getBoundingClientRect();
  const x = canvasBox.left - rootBox.left + windowPos.x + 12;
  const y = canvasBox.top - rootBox.top + windowPos.y + 12;
  el.style.left = `${Math.min(x, rootBox.width - el.offsetWidth - 8)}px`;
  el.style.top = `${Math.min(y, rootBox.height - el.offsetHeight - 8)}px`;
}
