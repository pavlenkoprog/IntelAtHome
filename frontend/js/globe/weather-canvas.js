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

  const drawClouds = () => {
    ctx.save();
    ctx.filter = "blur(6px)";
    for (const cell of field) {
      const cover = Number(cell.cloud_cover) || 0;
      const t = Math.max(0, (cover - 5) / 95);
      if (t <= 0) {
        continue;
      }
      const pts = [
        project(cell.south, cell.west),
        project(cell.south, cell.east),
        project(cell.north, cell.east),
        project(cell.north, cell.west),
      ];
      if (pts.some((pt) => !pt)) {
        continue;
      }
      ctx.fillStyle = `rgba(236, 244, 255, ${(0.16 + t * 0.7) * t})`;
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      ctx.lineTo(pts[1].x, pts[1].y);
      ctx.lineTo(pts[2].x, pts[2].y);
      ctx.lineTo(pts[3].x, pts[3].y);
      ctx.closePath();
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
      const corner = project(cell.north, cell.east);
      if (!center || !corner) {
        continue;
      }
      const radius = Math.max(22, Math.hypot(corner.x - center.x, corner.y - center.y) * 0.85);
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
      drawClouds();
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
      dirty = true;
    },
    setLayers(next) {
      layers = { ...layers, ...next };
      dirty = true;
    },
    destroy() {
      canvas.remove();
    },
  };
}
