import { api } from "./api.js";
import { showGlobe } from "./globe/viewer.js";
import { initMediaPanel } from "./media-panel.js";

const statusNode = document.getElementById("api-status");

async function pingApi() {
  try {
    await api.health();
    statusNode.textContent = "API online";
    statusNode.className = "status ok";
  } catch {
    statusNode.textContent = "API offline";
    statusNode.className = "status err";
  }
}

async function start() {
  try {
    await showGlobe();
  } catch (error) {
    const root = document.getElementById("app");
    const message = document.createElement("p");
    message.className = "empty";
    message.textContent = error.message;
    root.classList.remove("is-hidden");
    root.replaceChildren(message);
  }
  await pingApi();
  initMediaPanel();
}

start();
