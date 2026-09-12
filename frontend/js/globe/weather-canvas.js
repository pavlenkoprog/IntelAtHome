import { cameraZoom, pickLatLng } from "./camera.js";

export function createWeatherView(viewer) {
  const canvas = document.createElement("canvas");
  canvas.className = "weather-canvas";
  const parent = viewer.canvas.parentElement || viewer.container;
  parent.appendChild(canvas);
  const ctx = canvas.getContext("2d", { alpha: true });

  let field = [];
  let grid = null;
  let layers = { clouds: false, rain: false, wind: false };
  let dirty = true;
  let lastView = "";
  let cloudLayer = null;
  let cloudKey = "";
  let cloudBusy = false;

  const Cesium = window.Cesium;
  let project = () => null;

  const syncBox = () => {
    const width = viewer.canvas.clientWidth;
    const height = viewer.canvas.clientHeight;
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
  };

  const bindProject = () => {
    const occluder = new Cesium.EllipsoidalOccluder(viewer.scene.globe.ellipsoid, viewer.camera.positionWC);
    project = (lat, lon) => {
      const cartesian = Cesium.Cartesian3.fromDegrees(lon, lat);
      if (!occluder.isPointVisible(cartesian)) {
        return null;
      }
      return Cesium.SceneTransforms.worldToWindowCoordinates
        ? Cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene, cartesian)
        : Cesium.SceneTransforms.wgs84ToWindowCoordinates(viewer.scene, cartesian);
    };
  };

  const removeCloudLayer = () => {
    if (!cloudLayer) {
      return;
    }
    viewer.imageryLayers.remove(cloudLayer, true);
    cloudLayer = null;
    cloudKey = "";
  };

  const rectangleFromGrid = (meta) => {
    let west = Number(meta.west);
    let east = Number(meta.east);
    const south = Number(meta.south);
    const north = Number(meta.north);
    if (!Number.isFinite(west) || !Number.isFinite(east) || !Number.isFinite(south) || !Number.isFinite(north)) {
      return null;
    }
    if (east <= west) {
      east = west + Number(meta.cols || 1) * Number(meta.dlon || 1);
    }
    if (east - west >= 359) {
      return Cesium.Rectangle.MAX_VALUE;
    }
    return Cesium.Rectangle.fromDegrees(west, south, Math.min(east, west + 359.9), north);
  };

  const rasterClouds = (meta) => {
    const cols = Number(meta.cols) || 0;
    const rows = Number(meta.rows) || 0;
    if (cols < 1 || rows < 1) {
      return null;
    }
    const raster = document.createElement("canvas");
    raster.width = cols;
    raster.height = rows;
    const rasterCtx = raster.getContext("2d", { alpha: true });
    const image = rasterCtx.createImageData(cols, rows);
    const pixels = image.data;
    for (const cell of field) {
      const cover = Number(cell.cloud_cover) || 0;
      const t = Math.max(0, (cover - 2) / 98);
      if (t <= 0) {
        continue;
      }
      const row = Number.isFinite(Number(cell.row)) ? Number(cell.row) : 0;
      const col = Number.isFinite(Number(cell.col)) ? Number(cell.col) : 0;
      if (row < 0 || col < 0 || row >= rows || col >= cols) {
        continue;
      }
      const idx = ((rows - 1 - row) * cols + col) * 4;
      pixels[idx] = 236;
      pixels[idx + 1] = 244;
      pixels[idx + 2] = 255;
      pixels[idx + 3] = Math.round(Math.min(0.88, 0.22 + t * 0.72) * 255);
    }
    rasterCtx.putImageData(image, 0, 0);
    const scale = Math.max(8, Math.min(24, Math.round(256 / Math.max(cols, rows))));
    const out = document.createElement("canvas");
    out.width = cols * scale;
    out.height = rows * scale;
    const outCtx = out.getContext("2d");
    outCtx.imageSmoothingEnabled = true;
    outCtx.filter = "blur(1.2px)";
    outCtx.drawImage(raster, 0, 0, out.width, out.height);
    return out;
  };

  const syncCloudLayer = async () => {
    if (!layers.clouds || !field.length) {
      removeCloudLayer();
      return;
    }
    const meta = grid && grid.rows && grid.cols ? grid : inferGrid();
    if (!meta) {
      return;
    }
    const key = `${meta.west}:${meta.south}:${meta.east}:${meta.north}:${meta.cols}x${meta.rows}:${field.length}`;
    if (key === cloudKey && cloudLayer) {
      cloudLayer.show = true;
      return;
    }
    if (cloudBusy) {
      return;
    }
    cloudBusy = true;
    const rectangle = rectangleFromGrid(meta);
    const image = rasterClouds(meta);
    if (!rectangle || !image) {
      cloudBusy = false;
      return;
    }
    try {
      const url = image.toDataURL("image/png");
      const provider = Cesium.SingleTileImageryProvider.fromUrl
        ? await Cesium.SingleTileImageryProvider.fromUrl(url, { rectangle })
        : new Cesium.SingleTileImageryProvider({
            url,
            rectangle,
            tileWidth: image.width,
            tileHeight: image.height,
          });
      removeCloudLayer();
      cloudLayer = new Cesium.ImageryLayer(provider);
      cloudLayer.alpha = 0.82;
      viewer.imageryLayers.add(cloudLayer);
      cloudKey = key;
    } catch (error) {
      console.warn("cloud imagery", error);
    } finally {
      cloudBusy = false;
    }
  };

  const inferGrid = () => {
    if (!field.length) {
      return null;
    }
    if (grid && grid.rows && grid.cols) {
      return grid;
    }
    const souths = [...new Set(field.map((cell) => Number(cell.south)))].sort((a, b) => a - b);
    const wests = [...new Set(field.map((cell) => Number(cell.west)))].sort((a, b) => a - b);
    if (!souths.length || !wests.length) {
      return null;
    }
    return {
      rows: souths.length,
      cols: wests.length,
      south: souths[0],
      west: wests[0],
      north: souths[souths.length - 1] + (souths.length > 1 ? souths[1] - souths[0] : 2),
      east: wests[wests.length - 1] + (wests.length > 1 ? wests[1] - wests[0] : 2),
      dlat: souths.length > 1 ? souths[1] - souths[0] : 2,
      dlon: wests.length > 1 ? wests[1] - wests[0] : 2,
    };
  };

  const drawCloudFallback = () => {
    if (cloudLayer) {
      return;
    }
    ctx.save();
    ctx.filter = "blur(8px)";
    for (const cell of field) {
      const cover = Number(cell.cloud_cover) || 0;
      const t = Math.max(0, (cover - 2) / 98);
      if (t <= 0) {
        continue;
      }
      const center = project(cell.lat, cell.lon);
      if (!center) {
        continue;
      }
      const corner = project(cell.north, cell.east) || project(cell.south, cell.west);
      const radius = corner ? Math.max(18, Math.hypot(corner.x - center.x, corner.y - center.y) * 0.9) : 28;
      ctx.fillStyle = `rgba(236, 244, 255, ${Math.min(0.72, 0.2 + t * 0.6)})`;
      ctx.beginPath();
      ctx.arc(center.x, center.y, radius, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  };

  const rainColor = (mm) => {
    if (mm >= 4) {
      return [239, 68, 68];
    }
    if (mm >= 1.5) {
      return [250, 204, 21];
    }
    if (mm >= 0.4) {
      return [74, 222, 128];
    }
    return [56, 189, 248];
  };

  const drawRain = () => {
    for (const cell of field) {
      const mm = Number(cell.precipitation) || 0;
      if (mm <= 0) {
        continue;
      }
      const center = project(cell.lat, cell.lon);
      if (!center) {
        continue;
      }
      const corner = project(cell.north, cell.east);
      const radius = corner ? Math.max(22, Math.hypot(corner.x - center.x, corner.y - center.y) * 0.85) : 26;
      const [r, g, b] = rainColor(mm);
      const alpha = Math.min(0.55, 0.18 + mm * 0.12);
      const gradient = ctx.createRadialGradient(center.x, center.y, radius * 0.1, center.x, center.y, radius);
      gradient.addColorStop(0, `rgba(${r},${g},${b},${alpha})`);
      gradient.addColorStop(1, `rgba(${r},${g},${b},0)`);
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.arc(center.x, center.y, radius, 0, Math.PI * 2);
      ctx.fill();
    }
  };

  const windAt = (lat, lon) => {
    if (!field.length) {
      return null;
    }
    const nearest = [];
    for (const cell of field) {
      const dlat = cell.lat - lat;
      const dlon = (cell.lon - lon) * Math.cos((lat * Math.PI) / 180);
      const d = dlat * dlat + dlon * dlon;
      if (nearest.length < 4) {
        nearest.push({ cell, d });
        nearest.sort((a, b) => a.d - b.d);
        continue;
      }
      if (d < nearest[3].d) {
        nearest[3] = { cell, d };
        nearest.sort((a, b) => a.d - b.d);
      }
    }
    let east = 0;
    let north = 0;
    let speedSum = 0;
    let weightSum = 0;
    for (const { cell, d } of nearest) {
      const weight = 1 / Math.max(d, 1e-8);
      const speed = Number(cell.wind_speed) || 0;
      const toRad = (((Number(cell.wind_direction) || 0) + 180) * Math.PI) / 180;
      east += Math.sin(toRad) * speed * weight;
      north += Math.cos(toRad) * speed * weight;
      speedSum += speed * weight;
      weightSum += weight;
    }
    return {
      speed: speedSum / weightSum,
      toRad: Math.atan2(east, north),
    };
  };

  const drawWind = () => {
    if (!field.length) {
      return;
    }
    const gap = Math.max(22, 36 - cameraZoom(viewer));
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "rgba(220, 236, 255, 0.42)";
    ctx.lineWidth = 1.15;
    for (let y = gap / 2; y < canvas.height; y += gap) {
      for (let x = gap / 2; x < canvas.width; x += gap) {
        const latlng = pickLatLng(viewer, new Cesium.Cartesian2(x, y));
        if (!latlng) {
          continue;
        }
        const wind = windAt(latlng.lat, latlng.lon);
        if (!wind) {
          continue;
        }
        const len = 10 + Math.min(14, wind.speed * 1.1);
        const tipX = x + Math.sin(wind.toRad) * (len / 2);
        const tipY = y - Math.cos(wind.toRad) * (len / 2);
        const tailX = x - Math.sin(wind.toRad) * (len / 2);
        const tailY = y + Math.cos(wind.toRad) * (len / 2);
        const head = 4;
        const left = wind.toRad + Math.PI * 0.78;
        const right = wind.toRad - Math.PI * 0.78;
        ctx.beginPath();
        ctx.moveTo(tailX, tailY);
        ctx.lineTo(tipX, tipY);
        ctx.moveTo(tipX, tipY);
        ctx.lineTo(tipX + Math.sin(left) * head, tipY - Math.cos(left) * head);
        ctx.moveTo(tipX, tipY);
        ctx.lineTo(tipX + Math.sin(right) * head, tipY - Math.cos(right) * head);
        ctx.stroke();
      }
    }
    ctx.restore();
  };

  const draw = () => {
    syncBox();
    bindProject();
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (layers.clouds) {
      void syncCloudLayer();
      drawCloudFallback();
    } else {
      removeCloudLayer();
    }
    if (layers.rain) {
      drawRain();
    }
    if (layers.wind) {
      drawWind();
    }
  };

  const viewKey = () => {
    const camera = viewer.camera;
    return `${camera.positionWC.x | 0}:${camera.positionWC.y | 0}:${camera.positionWC.z | 0}:${camera.heading.toFixed(3)}:${camera.pitch.toFixed(3)}:${canvas.width}x${canvas.height}`;
  };

  viewer.scene.postRender.addEventListener(() => {
    const key = viewKey();
    if (!dirty && key === lastView) {
      return;
    }
    lastView = key;
    dirty = false;
    draw();
  });

  return {
    setData(items, nextGrid) {
      field = items || [];
      grid = nextGrid || null;
      cloudKey = "";
      dirty = true;
    },
    setLayers(next) {
      layers = { ...layers, ...next };
      dirty = true;
    },
    destroy() {
      removeCloudLayer();
      canvas.remove();
    },
  };
}
