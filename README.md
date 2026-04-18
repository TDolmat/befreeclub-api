# BeFreeClub API

Cache dla Circle API z lokalnym storage avatarów i publicznym dostępem do plików.

## Autoryzacja

Klucz API można przekazać na trzy sposoby (w kolejności preferencji):

1. **`Authorization: Bearer <klucz>`** — zalecane
2. **`X-API-Key: <klucz>`** — alternatywa
3. **`?key=<klucz>`** — legacy, backwards compat (klucz leci w URL-u → wycieka do logów/history)

```bash
# Zalecane
curl -H "Authorization: Bearer TWOJ_KLUCZ" https://api.befreeclub.pro/members

# Legacy
curl "https://api.befreeclub.pro/members?key=TWOJ_KLUCZ"
```

```js
fetch("https://api.befreeclub.pro/members", {
  headers: { Authorization: `Bearer ${API_KEY}` }
});
```

```python
requests.get(
    "https://api.befreeclub.pro/members",
    headers={"Authorization": f"Bearer {API_KEY}"},
)
```

## Endpointy

### Wymagające API key

| Method | Path | Opis |
|--------|------|------|
| GET | `/subscribers` | Lista emaili aktywnych subskrybentów |
| GET | `/members` | Lista członków z lokalnymi URL-ami avatarów |
| GET | `/members/<email>` | Pojedynczy członek (fallback do Circle jeśli brak w cache) |
| GET | `/subscription/<email>` | Czy user ma aktywną subskrypcję (`true`/`false`) |
| GET | `/health` | Status API + timestamp ostatniego fetchu |

Parametry query:
- `cache=false` — wymusza odświeżenie z Circle (tylko `/subscribers` i `/members`)

### Publiczne (bez API key)

| Method | Path | Opis |
|--------|------|------|
| GET | `/avatars/<filename>` | Serwuje pliki avatarów (`<sha256(email)[:16]>.jpg/png/...`) |

## Przykłady

```bash
# Lista emaili
curl -H "Authorization: Bearer TWOJ_KLUCZ" https://api.befreeclub.pro/subscribers

# Pojedynczy członek
curl -H "Authorization: Bearer TWOJ_KLUCZ" https://api.befreeclub.pro/members/jan@example.com

# Check subskrypcji
curl -H "Authorization: Bearer TWOJ_KLUCZ" https://api.befreeclub.pro/subscription/jan@example.com

# Avatar (publicznie, bez klucza)
curl https://api.befreeclub.pro/avatars/a1b2c3d4e5f6g7h8.jpg
```

### Response `/members/<email>`

Znaleziony w cache:
```json
{
  "member": {
    "email": "jan@example.com",
    "name": "Jan Kowalski",
    "first_name": "Jan",
    "last_name": "Kowalski",
    "avatar_url": "https://api.befreeclub.pro/avatars/a1b2c3d4e5f6g7h8.jpg",
    "headline": "Developer"
  },
  "source": "cache"
}
```

Nie znaleziony, fallback odświeżył dane z Circle:
```json
{ "member": { ... }, "source": "circle" }
```

Nie znaleziony, fallback rate-limited (mniej niż `FALLBACK_MIN_INTERVAL_MINUTES` od ostatniego fetchu):
```json
{
  "error": "Not found",
  "member": null,
  "source": "cache",
  "hint": "Cache does not contain this email and fallback refresh is rate-limited."
}
```
HTTP 404.

## Cache & refresh

- `CACHE_MINUTES` (default `30`) — TTL cache na `/subscribers` i `/members`
- `FALLBACK_MIN_INTERVAL_MINUTES` (default `60`) — minimalny odstęp między fallback-fetchami gdy user nie znaleziony w cache (anty-DDoS)
- `DAILY_REFRESH_HOUR_UTC` (default `4`) — godzina UTC dla automatycznego daily refresh (APScheduler)
- Avatar jest pobierany lokalnie podczas każdego fetchu z Circle; zmiana URL-a = ponowne pobranie

## Zmienne środowiskowe

```
CIRCLE_ADMIN_API_V1=...      # token Circle
API_KEY=...                  # klucz API do BFC (generuj przez generate_key.py)
CACHE_MINUTES=30
FALLBACK_MIN_INTERVAL_MINUTES=60
DAILY_REFRESH_HOUR_UTC=4
PUBLIC_BASE_URL=https://api.befreeclub.pro
ENABLE_SCHEDULER=true
DATA_DIR=/app/data           # ustawiane przez Dockerfile
```

## Lokalne uruchomienie

```bash
pip install -r requirements.txt
python generate_key.py       # dodaje API_KEY do .env
# Dodaj ręcznie CIRCLE_ADMIN_API_V1 do .env
python app.py
curl "http://localhost:5050/subscribers?key=TWOJ_KLUCZ"
```

## Deploy na VPS

```bash
git pull
docker compose up -d --build
```

Caddy automatycznie pobiera SSL dla `api.befreeclub.pro`.

## Storage

- `./data/data.db` — SQLite
- `./data/avatars/` — pliki avatarów (persystowane przez volume w docker-compose)
