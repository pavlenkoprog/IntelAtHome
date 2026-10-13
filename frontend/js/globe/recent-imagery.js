import { pickLatLng } from "./camera.js";

const CMR_ENDPOINT = "https://cmr.earthdata.nasa.gov/search/granules.umm_json";
const WVS_ENDPOINT = "https://wvs.earthdata.nasa.gov/api/v1/snapshot";
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
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

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
    try {
      const shots = await searchShots(lat, lon, controller.signal);
      if (id !== requestId) {
        return;
      }
      if (!shots.length) {
        panel.status.textContent = "За 30 суток снимка на эту точку нет";
        return;
      }
      panel.status.textContent = `${shots.length} за 30 суток · квадрат ${SIDE_KM}×${SIDE_KM} км`;
      renderShots(shots, box, id);
    } catch (error) {
      if (id !== requestId || error?.name === "AbortError") {
        return;
      }
      panel.status.textContent = "Каталог NASA недоступен";
    }
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
      meta.textContent = `${PRODUCTS[shot.product].label} · ${cloudLabel(shot.cloud)}`;
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
      panel.status.textContent = `${formatDay(shot.day)} · ${PRODUCTS[shot.product].label} · ${SIDE_KM}×${SIDE_KM} км`;
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
    <div class="shot-panel-credit">NASA GIBS · HLS</div>
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
    const existing = viewer.entities.getById(FRAME_ID);
    if (existing) {
      viewer.entities.remove(existing);
    }
    const frame = viewer.entities.add({
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
