import { globeHomeView } from "./camera.js";
import { attachCursorMeta } from "./cursor-meta.js";
import { attachLooks } from "./filters.js";
import { attachLayers } from "./layers.js";

const CESIUM_VERSION = "1.124.0";
const CESIUM_CDNS = [
  `https://cdn.jsdelivr.net/npm/cesium@${CESIUM_VERSION}/Build/Cesium/`,
  `https://cdnjs.cloudflare.com/ajax/libs/cesium/${CESIUM_VERSION}/`,
];

let viewer = null;

export async function showGlobe() {
  const root = document.getElementById("globeRoot");
  const container = document.getElementById("cesiumContainer");
  const hud = document.getElementById("globeHud");
  if (!root || !container) {
    throw new Error("Нет контейнера глобуса");
  }

  root.hidden = false;
  await loadCesium();

  if (!window.Cesium) {
    setHud(hud, "Cesium не загрузился");
    throw new Error("Cesium не загрузился");
  }

  if (!viewer) {
    setHud(hud, "Загрузка глобуса…");
    viewer = createViewer(container);
    await attachLayers(viewer, root);
    attachLooks(root, hud, viewer);
    attachCursorMeta(viewer, root);
  } else {
    viewer.useDefaultRenderLoop = true;
  }

  requestAnimationFrame(() => viewer.resize());
  window.setTimeout(() => viewer.resize(), 120);
}

export function hideGlobe() {
  const root = document.getElementById("globeRoot");
  if (root) {
    root.hidden = true;
  }
  if (viewer) {
    viewer.useDefaultRenderLoop = false;
  }
}

function createViewer(container) {
  const Cesium = window.Cesium;

  const viewer = new Cesium.Viewer(container, {
    animation: false,
    baseLayerPicker: false,
    fullscreenButton: false,
    vrButton: false,
    geocoder: false,
    homeButton: true,
    infoBox: false,
    sceneModePicker: true,
    selectionIndicator: false,
    timeline: false,
    navigationHelpButton: false,
    navigationInstructionsInitiallyVisible: false,
    shouldAnimate: false,
    baseLayer: false,
    skyBox: false,
    terrainProvider: new Cesium.EllipsoidTerrainProvider(),
  });

  viewer.scene.globe.show = true;
  viewer.scene.backgroundColor = Cesium.Color.fromCssColorString("#0b1a28");
  viewer.scene.globe.baseColor = Cesium.Color.fromBytes(12, 62, 110);
  viewer.scene.globe.enableLighting = false;
  viewer.scene.globe.showGroundAtmosphere = true;
  viewer.scene.globe.depthTestAgainstTerrain = false;
  viewer.scene.fog.enabled = false;
  viewer.scene.skyAtmosphere.show = true;
  viewer.scene.skyAtmosphere.atmosphereLightIntensity = 18;
  viewer.scene.skyAtmosphere.saturationShift = -0.12;
  viewer.scene.skyAtmosphere.brightnessShift = -0.08;
  if (viewer.scene.moon) {
    viewer.scene.moon.show = false;
  }
  if (viewer.scene.sun) {
    viewer.scene.sun.show = true;
  }

  const controller = viewer.scene.screenSpaceCameraController;
  controller.minimumZoomDistance = 200;
  controller.maximumZoomDistance = 4.6e7;
  controller.enableCollisionDetection = true;

  viewer.camera.setView(globeHomeView());
  loadRelief(viewer);

  viewer.homeButton.viewModel.command.beforeExecute.addEventListener((event) => {
    event.cancel = true;
    viewer.camera.flyTo({ ...globeHomeView(), duration: 1.6 });
  });

  return viewer;
}

const RELIEF_URL = "https://terrain.reearth.land/cesium-mesh/ellipsoid";

function loadRelief(viewer) {
  const Cesium = window.Cesium;
  if (!Cesium.CesiumTerrainProvider?.fromUrl || !Cesium.Terrain || !viewer.scene.setTerrain) {
    return;
  }

  // «ellipsoid» здесь — высоты над эллипсоидом WGS84 (Mapterhorn + EGM2008), не плоский шар.
  const terrain = new Cesium.Terrain(
    Cesium.CesiumTerrainProvider.fromUrl(RELIEF_URL, {
      requestVertexNormals: true,
      requestWaterMask: true,
    }),
  );
  viewer.scene.setTerrain(terrain);
  terrain.readyEvent.addEventListener(() => {
    if (viewer.isDestroyed()) {
      return;
    }
    viewer.scene.globe.depthTestAgainstTerrain = true;
  });
  terrain.errorEvent.addEventListener((error) => {
    console.warn("relief unavailable", error);
  });
}

function setHud(hud, text) {
  if (hud) {
    hud.textContent = text;
  }
}

async function loadCesium() {
  if (window.Cesium) {
    return;
  }
  let lastError;
  for (const base of CESIUM_CDNS) {
    try {
      window.CESIUM_BASE_URL = base;
      loadCss(`${base}Widgets/widgets.css`);
      await loadScript(`${base}Cesium.js`);
      if (window.Cesium) {
        return;
      }
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("Cesium не загрузился");
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
      if (window.Cesium) {
        resolve();
        return;
      }
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
