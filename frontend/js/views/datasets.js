export function renderDatasets(root, { items, onCreate }) {
  root.innerHTML = `
    <section class="panel">
      <h2>Новый датасет</h2>
      <form id="dataset-form">
        <input name="name" placeholder="Название" required />
        <input name="source_type" placeholder="Источник (csv, api, manual)" value="manual" />
        <textarea name="description" placeholder="Описание"></textarea>
        <button type="submit">Создать</button>
      </form>
    </section>
    <section class="list">
      ${items.length ? items.map(renderItem).join("") : `<p class="empty">Датасетов пока нет</p>`}
    </section>
  `;

  root.querySelector("#dataset-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    await onCreate({
      name: form.get("name"),
      source_type: form.get("source_type"),
      description: form.get("description"),
    });
  });
}

function renderItem(item) {
  return `
    <article class="card">
      <div class="row">
        <div>
          <h3>${escapeHtml(item.name)}</h3>
          <p class="muted">${escapeHtml(item.description || "Без описания")}</p>
        </div>
        <span class="tag">${escapeHtml(item.source_type)}</span>
      </div>
    </article>
  `;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
