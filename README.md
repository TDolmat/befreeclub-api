# API

**Endpoint:** `GET /subscribers`

**W przeglądarce:**
```
https://api.befreeclub.pro/subscribers?key=TWOJ_KLUCZ
```

**curl:**
```bash
curl "https://api.befreeclub.pro/subscribers?key=TWOJ_KLUCZ"
```

| Parametr | Opis |
|----------|------|
| `key` | Klucz API (wymagany) |
| `cache` | `true` (domyślne) lub `false` wymusza świeże dane |

**Response:**
```json
{
  "emails": ["user1@example.com", "user2@example.com"],
  "cached": true
}
```

---

# Lokalnie

```bash
pip install -r requirements.txt
python generate_key.py
# Dodaj CIRCLE_ADMIN_API_V1 do .env
python app.py
curl "http://localhost:5050/subscribers?key=TWOJ_KLUCZ"
```

# VPS

```bash
git clone <repo> && cd befreeclub-api
python3 generate_key.py
nano .env  # dodaj CIRCLE_ADMIN_API_V1
```

Zmień porty w `docker-compose.yml`:
```yaml
ports:
  - "80:80"
  - "443:443"
```

```bash
docker compose up -d --build
```

Gotowe - Caddy automatycznie pobierze SSL dla api.befreeclub.pro.
