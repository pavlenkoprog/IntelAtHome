import { api } from "../api.js";
import { createWeatherView } from "./weather-canvas.js";

const ESRI_IMAGERY =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const ESRI_LABELS =
  "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}";
const ESRI_ROADS =
  "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}";
const OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const PLANE_CIVIL = "/vendor/leaflet/images/plane_w.png";
const PLANE_MILITARY = "/vendor/leaflet/images/plane_r.png";
const PLANE_SIZE_BASE = 12;

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
};

const timers = {};

export function attachLayers(map) {
  map.createPane("weatherPane");
  map.getPane("weatherPane").style.zIndex = 520;
  map.createPane("weatherOverlayPane");
  map.getPane("weatherOverlayPane").style.zIndex = 530;
  map.createPane("weatherMarkerPane");
  map.getPane("weatherMarkerPane").style.zIndex = 640;
  map.createPane("roadsPane");
  map.getPane("roadsPane").style.zIndex = 350;
  map.createPane("labelsPane");
  map.getPane("labelsPane").style.zIndex = 450;

  const imagery = tile(ESRI_IMAGERY, "Esri World Imagery", 17);
  const streets = tile(OSM_TILES, "© OpenStreetMap", 19);
  const roads = tile(ESRI_ROADS, "Esri Transportation", 17, { pane: "roadsPane", opacity: 0.75 });
  const labels = tile(ESRI_LABELS, "Esri Boundaries & Places", 17, { pane: "labelsPane" });

  const quakes = window.L.layerGroup();
  const events = window.L.layerGroup();
  const flights = window.L.layerGroup();
  const places = window.L.layerGroup();
  const rainTiles = tile("https://tilecache.rainviewer.com/v2/radar/0/256/{z}/{x}/{y}/2/1_1.png", "RainViewer", 19, {
    pane: "weatherPane",
    opacity: 0.78,
    maxNativeZoom: 7,
  });
  const rain = window.L.layerGroup([rainTiles]);
  const clouds = window.L.layerGroup();
  const storms = window.L.layerGroup();
  const wind = window.L.layerGroup();

  imagery.addTo(map);
  roads.addTo(map);
  labels.addTo(map);
  quakes.addTo(map);
  events.addTo(map);
  places.addTo(map);
  flights.addTo(map);
  rain.addTo(map);
  clouds.addTo(map);
  storms.addTo(map);
  wind.addTo(map);

  window.L.control
    .layers(
      {
        Спутник: imagery,
        Схема: streets,
      },
      {
        "Города и границы": labels,
        Дороги: roads,
        "Объекты OSM": places,
        Землетрясения: quakes,
        "События NASA": events,
        Самолёты: flights,
        Осадки: rain,
        Облачность: clouds,
        Грозы: storms,
        Ветер: wind,
      },
      { collapsed: false, position: "topright" },
    )
    .addTo(map);

  bindLiveLayer(map, quakes, "quakes", () => api.geo.earthquakes(), 600000);
  bindLiveLayer(map, events, "events", () => api.geo.events(), 600000);
  bindBBoxLayer(map, flights, "flights", (bbox) => api.geo.flights(bbox), 600000, 5, 250);
  bindBBoxLayer(map, places, "places", (bbox) => api.geo.places(bbox), 600000, 4);
  bindRadarLayer(map, rain, rainTiles, clouds);
  bindWeatherField(map, clouds, storms, wind, rain);
}

function tile(url, attribution, maxZoom, extra = {}) {
  return window.L.tileLayer(url, { maxZoom, attribution, ...extra });
}

function bindLiveLayer(map, layer, key, loader, intervalMs) {
  const refresh = async () => {
    if (!map.hasLayer(layer)) {
      return;
    }
    try {
      const data = await loader();
      renderItems(layer, data.items || [], map);
    } catch {
      /* слой остаётся прежним */
    }
  };

  map.on("overlayadd", (event) => {
    if (event.layer === layer) {
      refresh();
      timers[key] = window.setInterval(refresh, intervalMs);
    }
  });
  map.on("overlayremove", (event) => {
    if (event.layer === layer && timers[key]) {
      window.clearInterval(timers[key]);
    }
  });
  refresh();
  timers[key] = window.setInterval(refresh, intervalMs);
}

function bindBBoxLayer(map, layer, key, loader, intervalMs, minZoom, debounceMs = 750) {
  let debounce = 0;
  let requestId = 0;
  let inflight = false;
  let pending = null;
  let retry = 0;
  let lastOk = 0;
  const debug = key === "flights";
  const refresh = async (reason = "unknown") => {
    if (inflight) {
      pending = reason === "interval" ? pending || reason : reason;
      if (debug) {
        console.log(`[flights] queue ${reason}`);
      }
      return;
    }
    const zoom = map.getZoom();
    if (!map.hasLayer(layer) || zoom < minZoom) {
      if (debug) {
        console.log(`[flights] skip ${reason}`, { zoom, minZoom, layerOn: map.hasLayer(layer) });
      }
      if (zoom < minZoom) {
        layer.clearLayers();
      }
      return;
    }
    const bounds = map.getBounds();
    const bbox = {
      south: String(bounds.getSouth()),
      west: String(bounds.getWest()),
      north: String(bounds.getNorth()),
      east: String(bounds.getEast()),
      zoom: String(Math.round(zoom)),
    };
    if (reason === "interval" && Date.now() - lastOk < 8000) {
      if (debug) {
        console.log("[flights] skip interval, just loaded");
      }
      return;
    }
    const id = ++requestId;
    if (debug) {
      console.log(`[flights] request ${reason}`, { id, zoom, bbox });
    }
    inflight = true;
    try {
      const data = await loader(bbox);
      if (data.reason && !(data.items || []).length) {
        if (debug) {
          console.log(`[flights] empty ${reason}`, { id, source: data.source, reason: data.reason });
        }
        if (reason !== "retry" && retry < 2) {
          pending = pending || "retry";
        }
        return;
      }
      retry = 0;
      const items = data.items || [];
      renderItems(layer, items, map);
      lastOk = Date.now();
      if (debug) {
        console.log(`[flights] loaded ${reason}`, {
          id,
          count: items.length,
          source: data.source,
          markers: layer.getLayers().length,
        });
      }
    } catch (error) {
      if (debug) {
        console.warn(`[flights] error ${reason}`, error);
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

  map.on("moveend", () => schedule("moveend"));
  map.on("overlayadd", (event) => {
    if (event.layer === layer) {
      refresh("overlayadd");
      timers[key] = window.setInterval(() => refresh("interval"), intervalMs);
    }
  });
  map.on("overlayremove", (event) => {
    if (event.layer === layer && timers[key]) {
      window.clearInterval(timers[key]);
      if (debug) {
        console.log("[flights] layer off");
      }
    }
  });
  refresh("init");
  timers[key] = window.setInterval(() => refresh("interval"), intervalMs);
}

function bindRadarLayer(map, overlay, tiles, clouds) {
  let cloudTiles = null;
  const refresh = async () => {
    try {
      const data = await api.geo.weatherRadar();
      if (data.rain_url) {
        tiles.setUrl(data.rain_url);
      }
      if (data.clouds_url) {
        if (!cloudTiles) {
          cloudTiles = tile(data.clouds_url, "RainViewer", 19, {
            pane: "weatherPane",
            opacity: 0.42,
            maxNativeZoom: 7,
          });
          cloudTiles.addTo(clouds);
        } else {
          cloudTiles.setUrl(data.clouds_url);
        }
      }
    } catch (error) {
      console.warn("weather radar", error);
    }
  };

  map.on("overlayadd", (event) => {
    if (event.layer === overlay) {
      refresh();
      timers.rain = window.setInterval(refresh, 180000);
    }
  });
  map.on("overlayremove", (event) => {
    if (event.layer === overlay && timers.rain) {
      window.clearInterval(timers.rain);
    }
  });
  refresh();
  if (map.hasLayer(overlay)) {
    timers.rain = window.setInterval(refresh, 180000);
  }
}

function bindWeatherField(map, clouds, storms, wind, rain) {
  let debounce = 0;
  let requestId = 0;
  let inflight = false;
  let pending = false;
  let lastBBox = null;
  const fieldOverlays = [clouds, storms, wind];
  const overlays = [clouds, storms, wind, rain];
  const view = createWeatherView(map);
  const anyOn = () => fieldOverlays.some((layer) => map.hasLayer(layer));
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
      clouds: map.hasLayer(clouds),
      rain: map.hasLayer(rain),
      wind: map.hasLayer(wind),
    });
  };
  const refresh = async () => {
    if (!anyOn()) {
      view.setData([]);
      return;
    }
    if (inflight) {
      pending = true;
      return;
    }
    const bounds = map.getBounds();
    const bbox = {
      south: String(bounds.getSouth()),
      west: String(bounds.getWest()),
      north: String(bounds.getNorth()),
      east: String(bounds.getEast()),
      zoom: String(Math.round(map.getZoom())),
    };
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
      renderStorms(storms, items);
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

  map.on("moveend", () => {
    if (anyOn()) {
      schedule();
    }
  });
  map.on("resize", () => {
    if (anyOn()) {
      schedule();
    }
  });
  map.on("overlayadd", (event) => {
    if (overlays.includes(event.layer)) {
      syncEnabled();
      syncTimer();
    }
  });
  map.on("overlayremove", (event) => {
    if (overlays.includes(event.layer)) {
      syncEnabled();
      syncTimer();
    }
  });
  syncEnabled();
  syncTimer();
}

function renderStorms(layer, items) {
  layer.clearLayers();
  for (const item of items) {
    if (!item.storm) {
      continue;
    }
    const icon = window.L.divIcon({
      className: "storm-marker",
      iconSize: [22, 28],
      iconAnchor: [11, 14],
      html: `<span class="storm-bolt">↯</span>`,
    });
    const marker = window.L.marker([item.lat, item.lon], {
      icon,
      keyboard: false,
      pane: "weatherMarkerPane",
      zIndexOffset: 400,
    });
    marker.bindPopup(weatherPopup(item, "Гроза"));
    marker.bindTooltip(stormLabel(item.weather_code), { direction: "top", opacity: 0.9 });
    marker.addTo(layer);
  }
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
    "Облачность": item.cloud_cover != null ? `${item.cloud_cover}%` : "",
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

function renderItems(layer, items, map) {
  layer.clearLayers();
  const zoom = map ? map.getZoom() : 7;
  for (const item of items) {
    if (item.kind === "city") {
      continue;
    }
    const marker =
      item.kind === "flight" ? planeMarker(item, zoom) : circleMarker(item);
    marker.bindPopup(popupHtml(item));
    marker.bindTooltip(item.name, { direction: "top", opacity: 0.9 });
    marker.addTo(layer);
  }
}

function circleMarker(item) {
  const color =
    item.kind === "event"
      ? EVENT_COLORS[item.category_id] || COLORS.event
      : COLORS[item.kind] || "#f0a202";
  return window.L.circleMarker([item.lat, item.lon], {
    radius: radiusFor(item),
    color,
    weight: 1,
    fillOpacity: 0.85,
  });
}

function planeMarker(item, zoom) {
  const heading = Number(item.heading) || 0;
  const size = planeSize(zoom);
  const src = item.military ? PLANE_MILITARY : PLANE_CIVIL;
  const icon = window.L.divIcon({
    className: "plane-marker",
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    html: `<img src="${src}" alt="" style="width:${size}px;height:${size}px;transform:rotate(${heading}deg)">`,
  });
  return window.L.marker([item.lat, item.lon], { icon, keyboard: false });
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
  })
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([label, value]) => `<div><span class="muted">${label}:</span> ${escapeHtml(value)}</div>`)
    .join("");
  return `${popupTitle(item)}${rows}`;
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
