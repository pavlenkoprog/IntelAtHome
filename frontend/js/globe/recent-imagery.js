import { pickLatLng } from "./camera.js";

const CMR_ENDPOINT = "https://cmr.earthdata.nasa.gov/search/granules.umm_json";
const WVS_ENDPOINT = "https://wvs.earthdata.nasa.gov/api/v1/snapshot";
const WAYBACK_CONFIG = "https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json";
const WAYBACK_ZOOM = 15;
const WAYBACK_LEVEL = 19;
const CATALOG_DAYS = 30;
const SIDE_KM = 10;
const HALF_KM = SIDE_KM / 2;
const KM_PER_DEG = 111.32;
const SNAPSHOT_PX = 400;
const FLY_ABOVE_M = 25_000;
const FRAME_ID = "shot-frame";

const PRODUCTS = {
  S30: {
    label: "Sentinel-2",
    collection: "C2021957295-LPCLOUD",
    layer: "HLS_S30_Nadir_BRDF_Adjusted_Reflectance",
  },
  L30: {
    label: "Landsat 8/9",
    collection: "C2021957657-LPCLOUD",
    layer: "HLS_L30_Nadir_BRDF_Adjusted_Reflectance",
  },
};

const MONTHS = "янв фев мар апр май июн июл авг сен окт ноя дек".split(" ");

export function attachRecentImagery(viewer, root) {
  const Cesium = window.Cesium;
  const panel = buildPanel(root);
  let patch = null;
  let searchAbort = null;
  let imageAbort = null;
  let requestId = 0;
  let activeKey = "";

  const clearPatch = () => {
    if (!patch) {
      return;
    }
    if (patch.layer) {
      viewer.imageryLayers.remove(patch.layer, true);
    }
    if (patch.frame) {
      viewer.entities.remove(patch.frame);
    }
    if (patch.objectUrl) {
      URL.revokeObjectURL(patch.objectUrl);
    }
    patch = null;
  };

  const closePanel = () => {
    requestId += 1;
    searchAbort?.abort();
    imageAbort?.abort();
    clearPatch();
    activeKey = "";
    panel.root.hidden = true;
  };

  panel.close.addEventListener("click", closePanel);

  viewer.scene.canvas.addEventListener("contextmenu", (event) => {
    event.preventDefault();
  });

  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  handler.setInputAction((click) => {
    const picked = viewer.scene.pick(click.position);
    const entity = picked && picked.id;
    if (entity && entity.id !== FRAME_ID) {
      return;
    }
    const latlng = pickLatLng(viewer, click.position, true);
    if (!latlng) {
      return;
    }
    void openAt(latlng.lat, latlng.lon);
  }, Cesium.ScreenSpaceEventType.RIGHT_CLICK);

  async function openAt(lat, lon) {
    const box = boxAround(lat, lon);
    const id = ++requestId;
    searchAbort?.abort();
    imageAbort?.abort();
    clearPatch();
    activeKey = "";
    panel.root.hidden = false;
    panel.where.textContent = formatCoord(lat, lon);
    panel.list.replaceChildren();
    if (!box) {
      panel.status.textContent = "У полюса или линии дат квадрат 10×10 км не собирается";
      return;
    }
    panel.status.textContent = "Ищем снимки за 30 суток…";
    const controller = new AbortController();
    searchAbort = controller;
    const waybackPromise = searchWayback(lat, lon, controller.signal);
    let shots = [];
    let shotsFailed = false;
    try {
      shots = await searchShots(lat, lon, controller.signal);
    } catch (error) {
      if (id !== requestId || error?.name === "AbortError") {
        waybackPromise.catch(() => {});
        return;
      }
      shotsFailed = true;
    }
    if (id !== requestId) {
      return;
    }
    renderShots(shots, box, id);
    panel.status.textContent = listingStatus(shots.length, null);
    let versions = [];
    let waybackFailed = false;
    try {
      versions = await waybackPromise;
    } catch (error) {
      if (id !== requestId || error?.name === "AbortError") {
        return;
      }
      waybackFailed = true;
    }
    if (id !== requestId) {
      return;
    }
    appendWayback(versions, box, id);
    if (shotsFailed && waybackFailed) {
      panel.status.textContent = "Каталоги недоступны";
      return;
    }
    panel.status.textContent = listingStatus(shots.length, waybackFailed ? 0 : versions.length);
  }

  function renderShots(shots, box, id) {
    panel.list.replaceChildren();
    for (const shot of shots) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "shot-row";
      button.dataset.key = shot.key;
      if (shot.key === activeKey) {
        button.classList.add("is-active");
      }
      const date = document.createElement("span");
      date.textContent = formatDay(shot.day);
      const meta = document.createElement("small");
      meta.textContent = shotLabel(shot);
      button.append(date, meta);
      button.addEventListener("click", () => {
        if (id !== requestId) {
          return;
        }
        void choose(shot, box, id);
      });
      panel.list.append(button);
    }
  }

  function appendWayback(versions, box, id) {
    if (!versions.length) {
      return;
    }
    const label = document.createElement("div");
    label.className = "shot-panel-sep";
    label.textContent = "Wayback";
    panel.list.append(label);
    for (const shot of versions) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "shot-row";
      button.dataset.key = shot.key;
      const date = document.createElement("span");
      date.textContent = formatDay(shot.day);
      const meta = document.createElement("small");
      meta.textContent = "Wayback";
      button.append(date, meta);
      button.addEventListener("click", () => {
        if (id !== requestId) {
          return;
        }
        void choose(shot, box, id);
      });
      panel.list.append(button);
    }
  }

  async function choose(shot, box, id) {
    imageAbort?.abort();
    clearPatch();
    const controller = new AbortController();
    imageAbort = controller;
    activeKey = shot.key;
    for (const button of panel.list.querySelectorAll(".shot-row")) {
      button.classList.toggle("is-active", button.dataset.key === shot.key);
    }
    panel.status.textContent = "Кладём квадрат 10×10 км…";
    try {
      const next = await loadPatch(viewer, shot, box, controller.signal);
      if (id !== requestId || controller.signal.aborted || !next) {
        next?.release();
        return;
      }
      patch = next;
      panel.status.textContent = `${formatDay(shot.day)} · ${shot.product === "wayback" ? "Wayback" : PRODUCTS[shot.product].label} · ${SIDE_KM}×${SIDE_KM} км`;
      const height = viewer.camera.positionCartographic?.height;
      if (height > FLY_ABOVE_M) {
        viewer.camera.flyTo({
          destination: window.Cesium.Rectangle.fromDegrees(box.west, box.south, box.east, box.north),
          duration: 1.1,
        });
      }
    } catch (error) {
      if (id !== requestId || error?.name === "AbortError") {
        return;
      }
      activeKey = "";
      for (const button of panel.list.querySelectorAll(".shot-row")) {
        button.classList.remove("is-active");
      }
      panel.status.textContent = "Снимок на эту дату не открылся";
    }
  }
}

function buildPanel(root) {
  const panel = document.createElement("aside");
  panel.className = "shot-panel";
  panel.hidden = true;
  panel.innerHTML = `
    <div class="shot-panel-head">
      <div>
        <strong>Снимки</strong>
        <div class="shot-panel-where"></div>
      </div>
      <button type="button" class="shot-panel-close" aria-label="Закрыть">×</button>
    </div>
    <div class="shot-panel-status"></div>
    <div class="shot-panel-list"></div>
    <div class="shot-panel-credit">NASA GIBS · HLS · Esri Wayback</div>
  `;
  root.appendChild(panel);
  return {
    root: panel,
    where: panel.querySelector(".shot-panel-where"),
    status: panel.querySelector(".shot-panel-status"),
    list: panel.querySelector(".shot-panel-list"),
    close: panel.querySelector(".shot-panel-close"),
  };
}

async function searchShots(lat, lon, signal) {
  const end = new Date();
  const start = new Date(end.getTime() - (CATALOG_DAYS - 1) * 86_400_000);
  const startIso = `${start.toISOString().slice(0, 10)}T00:00:00Z`;
  const endIso = end.toISOString();
  const products = Object.keys(PRODUCTS);
  const settled = await Promise.allSettled(
    products.map((product) => fetchGranules(product, lat, lon, startIso, endIso, signal)),
  );
  const granules = [];
  let failed = 0;
  settled.forEach((result) => {
    if (result.status === "fulfilled") {
      granules.push(...result.value);
    } else if (result.reason?.name !== "AbortError") {
      failed += 1;
    } else {
      throw result.reason;
    }
  });
  if (failed === products.length) {
    throw new Error("cmr");
  }
  return groupShots(granules);
}

async function fetchGranules(product, lat, lon, startIso, endIso, signal) {
  const params = new URLSearchParams({
    collection_concept_id: PRODUCTS[product].collection,
    point: `${lon.toFixed(5)},${lat.toFixed(5)}`,
    temporal: `${startIso},${endIso}`,
    sort_key: "-start_date",
    page_size: "100",
  });
  const response = await fetch(`${CMR_ENDPOINT}?${params}`, { signal });
  if (!response.ok) {
    throw new Error(`CMR ${response.status}`);
  }
  return parseGranules(await response.json(), product);
}

function parseGranules(json, product) {
  const granules = [];
  for (const item of json?.items || []) {
    const start = item?.umm?.TemporalExtent?.RangeDateTime?.BeginningDateTime;
    if (typeof start !== "string" || !Number.isFinite(Date.parse(start))) {
      continue;
    }
    const raw = (item.umm.AdditionalAttributes || []).find((attr) => attr?.Name === "CLOUD_COVERAGE")?.Values?.[0];
    const cloud = Number(raw);
    granules.push({
      product,
      day: start.slice(0, 10),
      cloud: Number.isFinite(cloud) ? cloud : null,
    });
  }
  return granules;
}

function groupShots(granules) {
  const byKey = new Map();
  for (const granule of granules) {
    const key = `${granule.product}:${granule.day}`;
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, { key, product: granule.product, day: granule.day, cloud: granule.cloud });
      continue;
    }
    if (granule.cloud != null && (existing.cloud == null || granule.cloud < existing.cloud)) {
      existing.cloud = granule.cloud;
    }
  }
  return [...byKey.values()].sort((a, b) => {
    if (a.day !== b.day) {
      return a.day < b.day ? 1 : -1;
    }
    return a.product === b.product ? 0 : a.product === "S30" ? -1 : 1;
  });
}

function boxAround(lat, lon) {
  const cos = Math.cos((lat * Math.PI) / 180);
  if (!(cos > 0.05)) {
    return null;
  }
  const halfLat = HALF_KM / KM_PER_DEG;
  const halfLon = HALF_KM / (KM_PER_DEG * cos);
  const south = lat - halfLat;
  const north = lat + halfLat;
  const west = lon - halfLon;
  const east = lon + halfLon;
  if (south < -85 || north > 85 || west < -180 || east > 180) {
    return null;
  }
  return { west, south, east, north };
}

function snapshotUrl(shot, box) {
  const params = new URLSearchParams({
    REQUEST: "GetSnapshot",
    LAYERS: PRODUCTS[shot.product].layer,
    CRS: "EPSG:4326",
    TIME: shot.day,
    BBOX: [box.south, box.west, box.north, box.east].map((value) => value.toFixed(6)).join(","),
    WIDTH: String(SNAPSHOT_PX),
    HEIGHT: String(SNAPSHOT_PX),
    FORMAT: "image/png",
  });
  return `${WVS_ENDPOINT}?${params}`;
}

async function loadPatch(viewer, shot, box, signal) {
  if (shot.product === "wayback") {
    return loadWaybackPatch(viewer, shot, box, signal);
  }
  const Cesium = window.Cesium;
  const url = snapshotUrl(shot, box);
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`snapshot ${response.status}`);
  }
  const present = String(response.headers.get("Data-Present") ?? "true").toLowerCase();
  if (present === "false") {
    throw new Error("empty");
  }
  const blob = await response.blob();
  signal.throwIfAborted();
  const objectUrl = URL.createObjectURL(blob);
  const rectangle = Cesium.Rectangle.fromDegrees(box.west, box.south, box.east, box.north);
  let layer = null;
  try {
    const provider = await Cesium.SingleTileImageryProvider.fromUrl(objectUrl, {
      rectangle,
      credit: "NASA GIBS",
    });
    signal.throwIfAborted();
    layer = new Cesium.ImageryLayer(provider);
    viewer.imageryLayers.add(layer, Math.min(1, viewer.imageryLayers.length));
    const frame = addFrame(viewer, box);
    const created = { layer, frame, objectUrl };
    created.release = () => {
      viewer.imageryLayers.remove(layer, true);
      viewer.entities.remove(frame);
      URL.revokeObjectURL(objectUrl);
    };
    return created;
  } catch (error) {
    if (layer) {
      viewer.imageryLayers.remove(layer, true);
    }
    URL.revokeObjectURL(objectUrl);
    throw error;
  }
}

let waybackCatalog = null;
const waybackVersions = new Map();

async function searchWayback(lat, lon, signal) {
  const tile = tileXY(lat, lon, WAYBACK_ZOOM);
  const cacheKey = `${tile.z}/${tile.x}/${tile.y}`;
  const cached = waybackVersions.get(cacheKey);
  if (cached) {
    return cached;
  }
  const catalog = await loadWaybackCatalog();
  signal.throwIfAborted();
  const sizes = await mapPool(catalog, 8, (item) => tileBytes(waybackTileUrl(item.url, tile), signal), signal);
  signal.throwIfAborted();
  const versions = [];
  let previous = null;
  catalog.forEach((item, index) => {
    const bytes = sizes[index];
    if (bytes == null || bytes === previous) {
      return;
    }
    previous = bytes;
    versions.push({
      key: `WB:${item.releaseNum}`,
      product: "wayback",
      day: item.day,
      tileUrl: item.url,
    });
  });
  if (!versions.length && catalog.length) {
    throw new Error("wayback tiles");
  }
  waybackVersions.set(cacheKey, versions);
  return versions;
}

async function loadWaybackCatalog() {
  if (waybackCatalog) {
    return waybackCatalog;
  }
  const response = await fetch(WAYBACK_CONFIG);
  if (!response.ok) {
    throw new Error(`wayback ${response.status}`);
  }
  const json = await response.json();
  const items = [];
  for (const [key, value] of Object.entries(json)) {
    if (!/^\d+$/.test(key) || typeof value?.itemURL !== "string") {
      continue;
    }
    const day = String(value.itemTitle || "").match(/\d{4}-\d{2}-\d{2}/)?.[0];
    if (!day) {
      continue;
    }
    items.push({ releaseNum: Number(key), day, url: value.itemURL });
  }
  items.sort((a, b) => (a.day < b.day ? 1 : a.day > b.day ? -1 : b.releaseNum - a.releaseNum));
  waybackCatalog = items;
  return waybackCatalog;
}

function waybackTileUrl(template, tile) {
  return template
    .replaceAll("{level}", String(tile.z))
    .replaceAll("{row}", String(tile.y))
    .replaceAll("{col}", String(tile.x));
}

function tileXY(lat, lon, zoom) {
  const scale = 2 ** zoom;
  const latitude = (lat * Math.PI) / 180;
  return {
    z: zoom,
    x: Math.floor(((lon + 180) / 360) * scale),
    y: Math.floor(((1 - Math.log(Math.tan(latitude) + 1 / Math.cos(latitude)) / Math.PI) / 2) * scale),
  };
}

async function tileBytes(url, signal) {
  try {
    const response = await fetch(url, { signal });
    if (!response.ok) {
      return null;
    }
    const blob = await response.blob();
    return blob.size > 0 ? blob.size : null;
  } catch (error) {
    if (error?.name === "AbortError") {
      throw error;
    }
    return null;
  }
}

async function mapPool(items, limit, worker, signal) {
  const results = new Array(items.length);
  let cursor = 0;
  const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) {
      signal.throwIfAborted();
      const index = cursor;
      cursor += 1;
      results[index] = await worker(items[index], index);
    }
  });
  await Promise.all(runners);
  return results;
}

async function loadWaybackPatch(viewer, shot, box, signal) {
  signal.throwIfAborted();
  const Cesium = window.Cesium;
  const rectangle = Cesium.Rectangle.fromDegrees(box.west, box.south, box.east, box.north);
  const provider = new Cesium.UrlTemplateImageryProvider({
    url: shot.tileUrl.replaceAll("{level}", "{z}").replaceAll("{row}", "{y}").replaceAll("{col}", "{x}"),
    rectangle,
    maximumLevel: WAYBACK_LEVEL,
    credit: "Esri Wayback",
    enablePickFeatures: false,
  });
  const layer = new Cesium.ImageryLayer(provider);
  viewer.imageryLayers.add(layer, Math.min(1, viewer.imageryLayers.length));
  const frame = addFrame(viewer, box);
  return {
    layer,
    frame,
    objectUrl: null,
    release() {
      viewer.imageryLayers.remove(layer, true);
      viewer.entities.remove(frame);
    },
  };
}

function addFrame(viewer, box) {
  const Cesium = window.Cesium;
  const existing = viewer.entities.getById(FRAME_ID);
  if (existing) {
    viewer.entities.remove(existing);
  }
  return viewer.entities.add({
    id: FRAME_ID,
    polyline: {
      positions: Cesium.Cartesian3.fromDegreesArray([
        box.west, box.south,
        box.east, box.south,
        box.east, box.north,
        box.west, box.north,
        box.west, box.south,
      ]),
      width: 2,
      material: Cesium.Color.fromCssColorString("#f0a202"),
      clampToGround: true,
    },
  });
}

function shotLabel(shot) {
  if (shot.product === "wayback") {
    return "Wayback";
  }
  return `${PRODUCTS[shot.product].label} · ${cloudLabel(shot.cloud)}`;
}

function listingStatus(hlsCount, waybackCount) {
  const parts = [];
  if (hlsCount > 0) {
    parts.push(`${hlsCount} за 30 суток`);
  }
  if (waybackCount == null) {
    parts.push("версии Wayback…");
  } else if (waybackCount > 0) {
    parts.push(versionsLabel(waybackCount));
  }
  if (!parts.length) {
    return "Снимков на эту точку нет";
  }
  return `${parts.join(" · ")} · квадрат ${SIDE_KM}×${SIDE_KM} км`;
}

function versionsLabel(count) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) {
    return `${count} версия Wayback`;
  }
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return `${count} версии Wayback`;
  }
  return `${count} версий Wayback`;
}

function formatCoord(lat, lon) {
  const ns = lat >= 0 ? "с.ш." : "ю.ш.";
  const ew = lon >= 0 ? "в.д." : "з.д.";
  return `${Math.abs(lat).toFixed(3)}° ${ns}, ${Math.abs(lon).toFixed(3)}° ${ew}`;
}

function formatDay(day) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!match) {
    return day;
  }
  return `${Number(match[3])} ${MONTHS[Number(match[2]) - 1]} ${match[1]}`;
}

function cloudLabel(cloud) {
  if (cloud == null) {
    return "облачность неизвестна";
  }
  return `${Math.round(cloud)}% облаков`;
}
