const API_BASE = "/api/v1";

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 204) {
    return null;
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Request failed: ${response.status}`);
  }
  return data;
}

export const api = {
  health: () => request("/health"),
  datasets: {
    list: () => request("/datasets"),
    create: (payload) => request("/datasets", { method: "POST", body: JSON.stringify(payload) }),
  },
  entities: {
    list: () => request("/entities"),
    create: (payload) => request("/entities", { method: "POST", body: JSON.stringify(payload) }),
  },
  investigations: {
    list: () => request("/investigations"),
    create: (payload) => request("/investigations", { method: "POST", body: JSON.stringify(payload) }),
  },
  geo: {
    earthquakes: () => request("/geo/earthquakes"),
    events: () => request("/geo/events"),
    flights: (bbox) => request(`/geo/flights?${new URLSearchParams(bbox)}`),
    places: (bbox) => request(`/geo/places?${new URLSearchParams(bbox)}`),
    imagery: (params) => request(`/geo/imagery?${new URLSearchParams(params)}`),
    weatherRadar: () => request("/geo/weather/radar"),
    weather: (bbox) => request(`/geo/weather?${new URLSearchParams(bbox)}`),
    cameras: (bbox) => request(`/geo/cameras?${new URLSearchParams(bbox)}`),
    satellites: () => request("/geo/satellites"),
    cameraFrame: (id) => `${API_BASE}/geo/cameras/${encodeURIComponent(id)}/frame`,
  },
  media: {
    list: () => request("/media"),
    upload: (formData) => request("/media", { method: "POST", body: formData }),
    remove: (id) => request(`/media/${encodeURIComponent(id)}`, { method: "DELETE" }),
    previewUrl: (id) => `${API_BASE}/media/${encodeURIComponent(id)}/preview`,
  },
};
