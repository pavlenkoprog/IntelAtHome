export function createWeatherView(map) {
  const canvas = document.createElement("canvas");
  canvas.className = "weather-canvas";
  const pane = map.getPane("weatherOverlayPane") || map.getPanes().overlayPane;
  pane.appendChild(canvas);
  const ctx = canvas.getContext("2d", { alpha: true });

  let field = [];
  let grid = null;
  let layers = { clouds: false, rain: false, wind: false };
  const raster = document.createElement("canvas");
  const rasterCtx = raster.getContext("2d", { alpha: true });

  const syncBox = () => {
    const size = map.getSize();
    if (canvas.width !== size.x || canvas.height !== size.y) {
      canvas.width = size.x;
      canvas.height = size.y;
    }
    const topLeft = map.containerPointToLayerPoint([0, 0]);
    window.L.DomUtil.setPosition(canvas, topLeft);
  };

  const gridMeta = () => {
    if (grid && grid.rows && grid.cols && grid.dlat && grid.dlon) {
      return grid;
    }
    if (!field.length) {
      return null;
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
      dlat: souths.length > 1 ? souths[1] - souths[0] : Number(field[0].north) - Number(field[0].south),
      dlon: wests.length > 1 ? wests[1] - wests[0] : Number(field[0].east) - Number(field[0].west),
    };
  };

  const drawClouds = () => {
    const meta = gridMeta();
    if (!meta || !field.length) {
      return;
    }
    const { rows, cols, south, west, dlat, dlon } = meta;
    if (raster.width !== cols || raster.height !== rows) {
      raster.width = cols;
      raster.height = rows;
    }
    const image = rasterCtx.createImageData(cols, rows);
    const pixels = image.data;
    for (let i = 0; i < field.length; i += 1) {
      const cell = field[i];
      const row = Number.isFinite(Number(cell.row)) ? Number(cell.row) : Math.floor(i / cols);
      const col = Number.isFinite(Number(cell.col)) ? Number(cell.col) : i % cols;
      if (row < 0 || col < 0 || row >= rows || col >= cols) {
        continue;
      }
      const cover = Number(cell.cloud_cover) || 0;
      const t = Math.max(0, (cover - 5) / 95);
      if (t <= 0) {
        continue;
      }
      const idx = ((rows - 1 - row) * cols + col) * 4;
      pixels[idx] = 236;
      pixels[idx + 1] = 244;
      pixels[idx + 2] = 255;
      pixels[idx + 3] = Math.round((0.16 + t * 0.7) * t * 255);
    }
    rasterCtx.putImageData(image, 0, 0);
    const sw = map.latLngToContainerPoint([south, west]);
    const ne = map.latLngToContainerPoint([south + rows * dlat, west + cols * dlon]);
    const x = Math.min(sw.x, ne.x);
    const y = Math.min(sw.y, ne.y);
    const width = Math.abs(ne.x - sw.x);
    const height = Math.abs(ne.y - sw.y);
    if (width < 2 || height < 2) {
      return;
    }
    ctx.save();
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.filter = "blur(6px)";
    ctx.drawImage(raster, x, y, width, height);
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
    const size = map.getSize();
    const gap = Math.max(22, 36 - map.getZoom());
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "rgba(220, 236, 255, 0.42)";
    ctx.lineWidth = 1.15;
    for (let y = gap / 2; y < size.y; y += gap) {
      for (let x = gap / 2; x < size.x; x += gap) {
        const latlng = map.containerPointToLatLng([x, y]);
        const wind = windAt(latlng.lat, latlng.lng);
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

  map.on("move resize zoom", draw);

  return {
    setData(items, nextGrid) {
      field = items || [];
      grid = nextGrid || null;
      draw();
    },
    setLayers(next) {
      layers = { ...layers, ...next };
      draw();
    },
    destroy() {
      map.off("move resize zoom", draw);
      canvas.remove();
    },
  };
}
