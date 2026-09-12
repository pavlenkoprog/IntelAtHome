export function createWeatherView(map) {
  const canvas = document.createElement("canvas");
  canvas.className = "weather-canvas";
  const pane = map.getPane("weatherOverlayPane") || map.getPanes().overlayPane;
  pane.appendChild(canvas);
  const ctx = canvas.getContext("2d", { alpha: true });

  let field = [];
  let layers = { clouds: false, rain: false, wind: false };
  let particles = [];
  let raf = 0;
  let last = 0;

  const syncBox = () => {
    const size = map.getSize();
    if (canvas.width !== size.x || canvas.height !== size.y) {
      canvas.width = size.x;
      canvas.height = size.y;
    }
    const topLeft = map.containerPointToLayerPoint([0, 0]);
    window.L.DomUtil.setPosition(canvas, topLeft);
  };

  const sample = (lat, lon) => {
    if (!field.length) {
      return null;
    }
    let best = field[0];
    let bestD = Infinity;
    for (const cell of field) {
      const dlat = cell.lat - lat;
      const dlon = (cell.lon - lon) * Math.cos((lat * Math.PI) / 180);
      const d = dlat * dlat + dlon * dlon;
      if (d < bestD) {
        bestD = d;
        best = cell;
      }
    }
    return best;
  };

  const spawn = () => {
    const bounds = map.getBounds().pad(0.08);
    return {
      lat: bounds.getSouth() + Math.random() * (bounds.getNorth() - bounds.getSouth()),
      lon: bounds.getWest() + Math.random() * (bounds.getEast() - bounds.getWest()),
      age: Math.random(),
    };
  };

  const ensureParticles = () => {
    const need = layers.wind ? Math.round(Math.min(900, 280 + map.getZoom() * 40)) : 0;
    while (particles.length < need) {
      particles.push(spawn());
    }
    if (particles.length > need) {
      particles.length = need;
    }
  };

  const drawClouds = () => {
    for (const cell of field) {
      const cover = Number(cell.cloud_cover) || 0;
      if (cover < 12) {
        continue;
      }
      const center = map.latLngToContainerPoint([cell.lat, cell.lon]);
      const corner = map.latLngToContainerPoint([cell.north, cell.east]);
      const radius = Math.max(28, Math.hypot(corner.x - center.x, corner.y - center.y) * 0.95);
      const alpha = 0.12 + (cover / 100) * 0.42;
      const gradient = ctx.createRadialGradient(center.x, center.y, radius * 0.12, center.x, center.y, radius);
      gradient.addColorStop(0, `rgba(255,255,255,${alpha})`);
      gradient.addColorStop(0.45, `rgba(214,226,240,${alpha * 0.7})`);
      gradient.addColorStop(1, "rgba(214,226,240,0)");
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.arc(center.x, center.y, radius, 0, Math.PI * 2);
      ctx.fill();
    }
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
      const center = map.latLngToContainerPoint([cell.lat, cell.lon]);
      const corner = map.latLngToContainerPoint([cell.north, cell.east]);
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

  const stepWind = (dt) => {
    const bounds = map.getBounds().pad(0.12);
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    for (const particle of particles) {
      const cell = sample(particle.lat, particle.lon);
      const speed = Number(cell?.wind_speed) || 0.4;
      const from = Number(cell?.wind_direction) || 0;
      const toRad = ((from + 180) * Math.PI) / 180;
      const meters = Math.max(0.6, speed) * (dt / 1000) * 32;
      particle.lat += (Math.cos(toRad) * meters) / 111320;
      particle.lon += (Math.sin(toRad) * meters) / (111320 * Math.max(0.2, Math.cos((particle.lat * Math.PI) / 180)));
      particle.age += dt / 4200;
      if (particle.age > 1 || !bounds.contains([particle.lat, particle.lon])) {
        const fresh = spawn();
        particle.lat = fresh.lat;
        particle.lon = fresh.lon;
        particle.age = 0;
        continue;
      }
      const point = map.latLngToContainerPoint([particle.lat, particle.lon]);
      const fade = particle.age < 0.15 ? particle.age / 0.15 : particle.age > 0.8 ? (1 - particle.age) / 0.2 : 1;
      const tone = speed >= 12 ? "255,140,120" : speed >= 6 ? "210,230,255" : "180,220,255";
      const len = 4 + Math.min(16, speed * 1.1);
      ctx.strokeStyle = `rgba(${tone},${0.18 + fade * 0.28})`;
      ctx.lineWidth = speed >= 10 ? 1.6 : 1.1;
      ctx.beginPath();
      ctx.moveTo(point.x, point.y);
      ctx.lineTo(point.x - Math.sin(toRad) * len, point.y + Math.cos(toRad) * len);
      ctx.stroke();
    }
    ctx.restore();
  };

  const frame = (time) => {
    raf = window.requestAnimationFrame(frame);
    const dt = Math.min(48, time - last || 16);
    last = time;
    if (!layers.clouds && !layers.rain && !layers.wind) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      return;
    }
    syncBox();
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (layers.clouds) {
      drawClouds();
    }
    if (layers.rain) {
      drawRain();
    }
    if (layers.wind) {
      ensureParticles();
      stepWind(dt);
    } else {
      particles = [];
    }
  };

  const start = () => {
    if (!raf) {
      last = performance.now();
      raf = window.requestAnimationFrame(frame);
    }
  };

  map.on("move resize", syncBox);
  start();

  return {
    setData(items) {
      field = items || [];
      particles = [];
      ensureParticles();
    },
    setLayers(next) {
      layers = { ...layers, ...next };
      if (!layers.wind) {
        particles = [];
      }
      start();
    },
    destroy() {
      window.cancelAnimationFrame(raf);
      map.off("move resize", syncBox);
      canvas.remove();
    },
  };
}
