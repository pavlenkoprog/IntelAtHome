import { api } from "../api.js";

const ESRI_IMAGERY =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const ESRI_LABELS =
  "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}";
const ESRI_ROADS =
  "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}";
const OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const PLANE_CIVIL = "/vendor/leaflet/images/plane_w.png";
const PLANE_MILITARY = "/vendor/leaflet/images/plane_r.png";
const PLANE_SIZE = 24;

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
  launch: "#a3e635",
  flight: "#3dd68c",
};

const timers = {};

export function attachLayers(map) {
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
  const launches = window.L.layerGroup();
  const flights = window.L.layerGroup();
  const places = window.L.layerGroup();

  imagery.addTo(map);
  roads.addTo(map);
  labels.addTo(map);
  quakes.addTo(map);
  events.addTo(map);
  places.addTo(map);
  flights.addTo(map);

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
        Пуски: launches,
        Самолёты: flights,
      },
      { collapsed: false, position: "topright" },
    )
    .addTo(map);

  bindLiveLayer(map, quakes, "quakes", () => api.geo.earthquakes(), 180000);
  bindLiveLayer(map, events, "events", () => api.geo.events(), 180000);
  bindLiveLayer(map, launches, "launches", () => api.geo.launches(), 300000);
  bindBBoxLayer(map, flights, "flights", (bbox) => api.geo.flights(bbox), 20000, 4);
  bindBBoxLayer(map, places, "places", (bbox) => api.geo.places(bbox), 180000, 4);
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
      renderItems(layer, data.items || []);
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

function bindBBoxLayer(map, layer, key, loader, intervalMs, minZoom) {
  let debounce = 0;
  let requestId = 0;
  const refresh = async () => {
    if (!map.hasLayer(layer) || map.getZoom() < minZoom) {
      if (map.getZoom() < minZoom) {
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
      zoom: String(Math.round(map.getZoom())),
    };
    const id = ++requestId;
    try {
      const data = await loader(bbox);
      if (id !== requestId) {
        return;
      }
      if (data.reason && !(data.items || []).length) {
        return;
      }
      renderItems(layer, data.items || []);
    } catch {
      /* слой остаётся прежним */
    }
  };
  const schedule = () => {
    window.clearTimeout(debounce);
    debounce = window.setTimeout(refresh, 750);
  };

  map.on("moveend", schedule);
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

function renderItems(layer, items) {
  layer.clearLayers();
  for (const item of items) {
    if (item.kind === "city") {
      continue;
    }
    const marker =
      item.kind === "flight" ? planeMarker(item) : circleMarker(item);
    marker.bindPopup(popupHtml(item));
    marker.bindTooltip(item.name, { direction: "top", opacity: 0.9 });
    marker.addTo(layer);
  }
}

function circleMarker(item) {
  return window.L.circleMarker([item.lat, item.lon], {
    radius: radiusFor(item),
    color: COLORS[item.kind] || "#f0a202",
    weight: 1,
    fillOpacity: 0.85,
  });
}

function planeMarker(item) {
  const heading = Number(item.heading) || 0;
  const src = item.military ? PLANE_MILITARY : PLANE_CIVIL;
  const icon = window.L.divIcon({
    className: "plane-marker",
    iconSize: [PLANE_SIZE, PLANE_SIZE],
    iconAnchor: [PLANE_SIZE / 2, PLANE_SIZE / 2],
    html: `<img src="${src}" alt="" style="transform:rotate(${heading}deg)">`,
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
    Тип: item.kind === "flight" ? (item.military ? "военный" : "гражданский") : item.kind,
    Курс: item.heading,
    Категория: item.category,
    Магнитуда: item.magnitude,
    Высота: item.altitude,
    Страна: item.country,
    Когда: item.when,
    Площадка: item.pad,
  })
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([label, value]) => `<div><span class="muted">${label}:</span> ${escapeHtml(value)}</div>`)
    .join("");
  return `<strong>${escapeHtml(item.name)}</strong>${rows}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
