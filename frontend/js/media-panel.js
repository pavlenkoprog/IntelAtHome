import { api } from "./api.js";
import { flyToLatLon, setMediaPins } from "./globe/viewer.js";

const IMAGE_EXT = /\.(jpe?g|png|webp|gif|tiff?|heic|heif|avif)$/i;
const VIDEO_EXT = /\.(mp4|mov|m4v|webm|mkv|avi|3gp|3g2)$/i;

let items = [];
let activeId = "";
let busy = false;

export function initMediaPanel() {
  const input = document.getElementById("mediaFile");
  const drop = document.getElementById("mediaDrop");
  const list = document.getElementById("mediaList");
  if (!input || !drop || !list || drop.dataset.ready === "1") {
    return;
  }
  drop.dataset.ready = "1";

  input.addEventListener("change", () => {
    const files = [...input.files];
    input.value = "";
    ingest(files);
  });
  drop.addEventListener("dragover", (event) => {
    event.preventDefault();
    drop.classList.add("is-drag");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("is-drag"));
  drop.addEventListener("drop", (event) => {
    event.preventDefault();
    drop.classList.remove("is-drag");
    ingest([...(event.dataTransfer?.files || [])]);
  });

  refresh();
}

async function refresh() {
  try {
    items = await api.media.list();
    render();
  } catch (error) {
    setStatus(errorText(error), true);
  }
}

async function ingest(files) {
  const accepted = files.filter(isMedia);
  if (!accepted.length || busy) {
    return;
  }
  busy = true;
  try {
    for (const file of accepted) {
      setStatus(`Читаем «${file.name}»…`, false);
      const preview = await makePreview(file);
      const form = new FormData();
      form.append("file", file, file.name);
      if (preview) {
        form.append("preview", preview, "preview.jpg");
      }
      const created = await api.media.upload(form);
      activeId = created.id;
      await refresh();
      if (created.latitude == null || created.longitude == null) {
        setStatus(`В «${created.filename}» нет геоданных`, false);
      } else {
        setStatus("", false);
        flyToLatLon(created.latitude, created.longitude);
      }
    }
  } catch (error) {
    setStatus(errorText(error), true);
  } finally {
    busy = false;
  }
}

async function removeItem(id) {
  try {
    await api.media.remove(id);
    if (activeId === id) {
      activeId = "";
    }
    await refresh();
  } catch (error) {
    setStatus(errorText(error), true);
  }
}

function render() {
  const list = document.getElementById("mediaList");
  if (!list) {
    return;
  }
  list.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "media-empty";
    empty.textContent = "Пока нет файлов";
    list.append(empty);
  } else {
    for (const item of items) {
      list.append(renderCard(item));
    }
  }
  setMediaPins(items, activeId);
}

function renderCard(item) {
  const card = document.createElement("article");
  card.className = "media-card";
  card.tabIndex = 0;
  if (item.id === activeId) {
    card.classList.add("is-active");
  }

  const image = document.createElement("img");
  image.alt = "";
  image.src = api.media.previewUrl(item.id);

  const body = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = item.filename;
  title.title = item.filename;
  const meta = document.createElement("span");
  meta.textContent = locationText(item);
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "media-remove";
  remove.textContent = "Удалить";
  remove.addEventListener("click", (event) => {
    event.stopPropagation();
    removeItem(item.id);
  });

  body.append(title, meta, remove);
  card.append(image, body);
  card.addEventListener("click", () => select(item));
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      select(item);
    }
  });
  return card;
}

function select(item) {
  activeId = item.id;
  render();
  if (item.latitude != null && item.longitude != null) {
    flyToLatLon(item.latitude, item.longitude);
  }
}

function locationText(item) {
  if (item.latitude == null || item.longitude == null) {
    return "В метаданных нет координат";
  }
  const latitude = `${Math.abs(item.latitude).toFixed(5)}° ${item.latitude >= 0 ? "с.ш." : "ю.ш."}`;
  const longitude = `${Math.abs(item.longitude).toFixed(5)}° ${item.longitude >= 0 ? "в.д." : "з.д."}`;
  const extra = [];
  if (item.altitude != null) {
    extra.push(`${item.altitude} м`);
  }
  if (item.taken_at) {
    extra.push(item.taken_at.replace("T", " "));
  }
  const coords = `${latitude}, ${longitude}`;
  return extra.length ? `${coords} · ${extra.join(" · ")}` : coords;
}

function isMedia(file) {
  return file.type.startsWith("image/") || file.type.startsWith("video/") || IMAGE_EXT.test(file.name) || VIDEO_EXT.test(file.name);
}

function errorText(error) {
  if (error?.message === "Failed to fetch") {
    return "API offline";
  }
  return error?.message || "Не удалось прочитать файл";
}

function setStatus(text, isError) {
  const node = document.getElementById("mediaStatus");
  if (!node) {
    return;
  }
  node.textContent = text;
  node.classList.toggle("is-err", Boolean(isError) && Boolean(text));
}

function makePreview(file) {
  if (file.type.startsWith("video/") || VIDEO_EXT.test(file.name)) {
    return previewVideo(file);
  }
  return previewImage(file);
}

function previewImage(file) {
  return new Promise((resolve) => {
    const image = new Image();
    const url = URL.createObjectURL(file);
    image.onload = () => {
      canvasBlob(image).then((blob) => {
        URL.revokeObjectURL(url);
        resolve(blob);
      });
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      resolve(null);
    };
    image.src = url;
  });
}

function previewVideo(file) {
  return new Promise((resolve) => {
    const video = document.createElement("video");
    const url = URL.createObjectURL(file);
    let settled = false;
    const finish = (blob) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      URL.revokeObjectURL(url);
      video.removeAttribute("src");
      video.load();
      resolve(blob || null);
    };
    const timer = window.setTimeout(() => finish(null), 8000);
    video.muted = true;
    video.playsInline = true;
    video.preload = "auto";
    video.onerror = () => finish(null);
    video.onloadeddata = () => {
      const duration = Number.isFinite(video.duration) ? video.duration : 0;
      const target = duration > 0 ? Math.min(0.25, duration / 2) : 0;
      const capture = () => canvasBlob(video).then(finish);
      if (target > 0) {
        video.onseeked = capture;
        try {
          video.currentTime = target;
        } catch {
          capture();
        }
        return;
      }
      capture();
    };
    video.src = url;
  });
}

function canvasBlob(source) {
  const width = source.videoWidth || source.naturalWidth || 0;
  const height = source.videoHeight || source.naturalHeight || 0;
  if (!width || !height) {
    return Promise.resolve(null);
  }
  const scale = Math.min(1, 360 / Math.max(width, height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  const context = canvas.getContext("2d");
  if (!context) {
    return Promise.resolve(null);
  }
  context.drawImage(source, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve) => {
    canvas.toBlob((blob) => resolve(blob), "image/jpeg", 0.72);
  });
}
