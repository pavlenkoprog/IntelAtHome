export function renderDashboard(root, { health, investigations, entities, datasets }) {
  root.innerHTML = `
    <div class="grid">
      <article class="card">
        <h3>Расследования</h3>
        <p>${investigations.length}</p>
      </article>
      <article class="card">
        <h3>Сущности</h3>
        <p>${entities.length}</p>
      </article>
      <article class="card">
        <h3>Датасеты</h3>
        <p>${datasets.length}</p>
      </article>
      <article class="card">
        <h3>API</h3>
        <p>${health ? `${health.app} ${health.version}` : "недоступен"}</p>
      </article>
    </div>
  `;
}
