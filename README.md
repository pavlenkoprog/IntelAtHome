# PalantirAtHome

Локальная платформа для расследований: датасеты, сущности и рабочие кейсы.

Стек: **FastAPI** на бэкенде, **vanilla JavaScript** на фронтенде, SQLite для старта.

## Архитектура

```
backend/app
  api/v1/routes   HTTP-слой
  schemas         контракты запросов и ответов
  services        бизнес-логика
  models          SQLAlchemy-модели
  db              сессии и инициализация БД

frontend
  js/api.js       клиент API
  js/views        экраны
  js/app.js       маршрутизация
```

API живёт на `/api/v1`, UI раздаётся самим FastAPI с корня.

## Запуск

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Откройте http://127.0.0.1:8000 — UI (глобус по умолчанию), http://127.0.0.1:8000/docs — Swagger.

Если порт 8000 занят:

```powershell
uvicorn app.main:app --reload --port 8001
```

Главный экран — спутниковая карта (Esri) с подписями городов, границами и дорогами. Справа включаются слои: OSM-объекты, землетрясения USGS, события NASA EONET, пуски, самолёты.

Через Docker:

```powershell
docker compose up
```

## Домены

- **Datasets** — источники данных
- **Entities** — люди, организации, места, события, документы
- **Investigations** — расследования и привязка сущностей
