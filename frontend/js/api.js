const API_BASE = "/api/v1";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
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
    launches: () => request("/geo/launches"),
    flights: (bbox) => request(`/geo/flights?${new URLSearchParams(bbox)}`),
    places: (bbox) => request(`/geo/places?${new URLSearchParams(bbox)}`),
    imagery: (params) => request(`/geo/imagery?${new URLSearchParams(params)}`),
    weatherRadar: () => request("/geo/weather/radar"),
    weather: (bbox) => request(`/geo/weather?${new URLSearchParams(bbox)}`),
  },
};
