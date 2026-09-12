import { api } from "./api.js";
import { renderDashboard } from "./views/dashboard.js";
import { renderDatasets } from "./views/datasets.js";
import { renderEntities } from "./views/entities.js";
import { renderInvestigations } from "./views/investigations.js";

const titles = {
  dashboard: "Обзор",
  investigations: "Расследования",
  entities: "Сущности",
  datasets: "Датасеты",
};

const root = document.getElementById("app");
const titleNode = document.getElementById("page-title");
const statusNode = document.getElementById("api-status");

function currentRoute() {
  return window.location.hash.replace("#/", "") || "dashboard";
}

function setActiveNav(route) {
  document.querySelectorAll(".nav a").forEach((link) => {
    link.classList.toggle("active", link.dataset.route === route);
  });
}

async function render() {
  const route = currentRoute();
  titleNode.textContent = titles[route] || "Обзор";
  setActiveNav(titles[route] ? route : "dashboard");
  root.innerHTML = `<p class="muted">Загрузка…</p>`;

  try {
    const [health, investigations, entities, datasets] = await Promise.all([
      api.health(),
      api.investigations.list(),
      api.entities.list(),
      api.datasets.list(),
    ]);

    statusNode.textContent = "API online";
    statusNode.className = "status ok";

    if (route === "datasets") {
      renderDatasets(root, {
        items: datasets,
        onCreate: async (payload) => {
          await api.datasets.create(payload);
          await render();
        },
      });
      return;
    }

    if (route === "entities") {
      renderEntities(root, {
        items: entities,
        datasets,
        onCreate: async (payload) => {
          await api.entities.create(payload);
          await render();
        },
      });
      return;
    }

    if (route === "investigations") {
      renderInvestigations(root, {
        items: investigations,
        entities,
        onCreate: async (payload) => {
          await api.investigations.create(payload);
          await render();
        },
      });
      return;
    }

    renderDashboard(root, { health, investigations, entities, datasets });
  } catch (error) {
    statusNode.textContent = "API offline";
    statusNode.className = "status err";
    root.innerHTML = `<p class="empty">${error.message}</p>`;
  }
}

window.addEventListener("hashchange", render);
render();
