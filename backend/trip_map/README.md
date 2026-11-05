# trip_map

Модуль отображения плана поездки на карте: города, отели, переезды. Часть общего FastAPI-бэкенда.

## Подключение к хосту

```python
import trip_map

app.include_router(trip_map.router)   # API: /trip-map/api/trip
trip_map.mount_static(app)            # UI:  /trip-map/ui/
```

Источник плана подменяется через зависимости FastAPI (например, агентный модуль отдаёт план из своего хранилища):

```python
app.dependency_overrides[trip_map.get_source] = lambda: MySource()   # объект с методом load() -> trip_map.schema.Trip
```

По умолчанию план читается из файла (`TRIP_MAP_FILE`, по умолчанию `examples/trip.json`).

## Формат плана

Граф: `places` + `nodes` + `sequence`, данные выбранных вариантов лежат в верхнеуровневом `offers` и подставляются по `selected_offer_ref`. Схема: [schema.py](schema.py), примеры: [examples/](examples/).

- `places`: любое место (город, аэропорт, район) в любой стране. `lat`/`lon` необязательны: без них координаты ищет геокодер по `name`. `parent` вкладывает место в другое.
- `nodes[*].type`: любая строка. Узел с `place` рисуется меткой, с `from`/`to` линией. Переезд внутри города (`from == to` или вложенные места) только в списке.
- `nodes[*].mode`: как совершается переезд. `drive` / `walk` / `bike` строятся по реальным дорогам, всё остальное (`flight`, `rail`, поле не задано) рисуется прямой линией (дугой по большому кругу). Шаг с дорожным режимом внутри города (аэропорт → центр) тоже рисуется.
- Пока `selected_offer_ref` равен `null`, шаг показывается как «вариант не выбран».

## Карта и язык подписей

По умолчанию: **MapLibre GL + векторные тайлы OpenFreeMap**. Бесплатно, без ключа и регистрации. Подписи берутся из `name:<язык>` тайлов (по умолчанию `ru`), а где русского названия нет, показывается латиница и только потом местное название. Язык для одного просмотра задаётся `/trip-map/ui/?lang=en`.

| Переменная | Назначение |
|---|---|
| `TRIP_MAP_PROVIDER` | `maplibre` (по умолчанию), `google` или `leaflet` (растровый OSM, подписи на местном языке) |
| `TRIP_MAP_LANGUAGE` | язык подписей: `ru`, `en`, `pt-BR`, ... |
| `TRIP_MAP_STYLE_URL` | стиль MapLibre, по умолчанию `https://tiles.openfreemap.org/styles/liberty`. Подойдёт любой стиль на схеме OpenMapTiles (свой сервер, MapTiler и т. п.) |
| `GOOGLE_MAPS_API_KEY`, `GOOGLE_MAPS_MAP_ID` | только для `google`. Ключ уходит в браузер, ограничьте его по HTTP referrer. `GOOGLE_MAPS_MAP_ID` по умолчанию `DEMO_MAP_ID` |

Если выбранная карта не загрузилась (нет WebGL, недоступен сервис тайлов, ключ Google отклонён), фронт переключается на Leaflet + OSM и пишет об этом. Все карты лежат за общим интерфейсом в [static/map-adapters.js](static/map-adapters.js), новый поставщик добавляется одним адаптером.

Публичный OpenFreeMap бесплатный и без гарантий. Для продакшена можно поднять свои тайлы и указать их стиль в `TRIP_MAP_STYLE_URL`.

## Маршруты по дорогам

Геометрию строит бэкенд (`GET /trip-map/api/route`) через OSRM-совместимый API и кэширует в файле: повторные просмотры не ходят во внешний сервис. По умолчанию используются публичные серверы FOSSGIS (`routing.openstreetmap.de`, профили car / foot / bike). Они бесплатные, но без гарантий и для лёгкой нагрузки; для продакшена поднимите свой OSRM и укажите его в `TRIP_MAP_ROUTING_URL` (шаблон, `{profile}` заменяется на `car` / `foot` / `bike`; свой сервер обычно обслуживает один профиль, тогда `{profile}` не нужен). Если маршрут не получен, фронт рисует прямую линию. Железнодорожные маршруты (Синкансэн) так не строятся: для них нужны данные расписаний.

| Переменная | Назначение |
|---|---|
| `TRIP_MAP_ROUTING_URL` | базовый URL OSRM, по умолчанию `https://routing.openstreetmap.de/routed-{profile}` |
| `TRIP_MAP_DATA_DIR` | каталог кэшей геокодера и маршрутов, по умолчанию `data/trip_map` |

## API


- `GET /trip-map/api/trip`: нормализованный план (`places` с координатами, `steps` с подставленным оффером).
- `GET /trip-map/api/route?from_lat&from_lon&to_lat&to_lon&mode=drive|walk|bike`: дорожный маршрут `{points, distance_m, duration_s}`, 404 если маршрута нет.
- `GET /trip-map/api/config`: настройки карты для фронта (провайдер, стиль, язык, ключ Google).
- `PUT /trip-map/api/trip`: заменить план (только если источник умеет `save`).

## Тесты

```bash
cd backend && pip install -r requirements-dev.txt && pytest
```
