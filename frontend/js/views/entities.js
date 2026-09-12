export function renderEntities(root, { items, datasets, onCreate }) {
  const options = datasets
    .map((dataset) => `<option value="${dataset.id}">${escapeHtml(dataset.name)}</option>`)
    .join("");

  root.innerHTML = `
    <section class="panel">
      <h2>Новая сущность</h2>
      <form id="entity-form">
        <input name="name" placeholder="Имя" required />
        <select name="entity_type">
          <option value="person">person</option>
          <option value="organization">organization</option>
          <option value="location">location</option>
          <option value="event">event</option>
          <option value="document">document</option>
        </select>
        <select name="dataset_id">
          <option value="">Без датасета</option>
          ${options}
        </select>
        <textarea name="description" placeholder="Описание"></textarea>
        <button type="submit">Создать</button>
      </form>
    </section>
    <section class="list">
      ${items.length ? items.map(renderItem).join("") : `<p class="empty">Сущностей пока нет</p>`}
    </section>
  `;

  root.querySelector("#entity-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    await onCreate({
      name: form.get("name"),
      entity_type: form.get("entity_type"),
      dataset_id: form.get("dataset_id") || null,
      description: form.get("description"),
      properties: {},
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
        <span class="tag">${escapeHtml(item.entity_type)}</span>
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
