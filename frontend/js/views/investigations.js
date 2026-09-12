export function renderInvestigations(root, { items, entities, onCreate }) {
  const options = entities
    .map((entity) => `<option value="${entity.id}">${escapeHtml(entity.name)}</option>`)
    .join("");

  root.innerHTML = `
    <section class="panel">
      <h2>Новое расследование</h2>
      <form id="investigation-form">
        <input name="title" placeholder="Название" required />
        <textarea name="description" placeholder="Гипотеза / контекст"></textarea>
        <select name="entity_ids" multiple>
          ${options}
        </select>
        <button type="submit">Создать</button>
      </form>
    </section>
    <section class="list">
      ${items.length ? items.map(renderItem).join("") : `<p class="empty">Расследований пока нет</p>`}
    </section>
  `;

  root.querySelector("#investigation-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    const entityIds = [...event.target.entity_ids.selectedOptions].map((option) => option.value);
    await onCreate({
      title: form.get("title"),
      description: form.get("description"),
      status: "open",
      entity_ids: entityIds,
    });
  });
}

function renderItem(item) {
  const linked = item.entities?.length
    ? item.entities.map((entity) => escapeHtml(entity.name)).join(", ")
    : "Сущности не привязаны";

  return `
    <article class="card">
      <div class="row">
        <div>
          <h3>${escapeHtml(item.title)}</h3>
          <p class="muted">${escapeHtml(item.description || "Без описания")}</p>
          <p class="muted">${linked}</p>
        </div>
        <span class="tag">${escapeHtml(item.status)}</span>
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
