import os
import re
import json
import sqlite3
import hashlib
import mimetypes
import threading
import unicodedata
import requests
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, send_from_directory, abort
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()

app = Flask(__name__)

DATA_DIR = os.environ.get("DATA_DIR", ".")
AVATARS_DIR = os.path.join(DATA_DIR, "avatars")
STATIC_INITIALS_DIR = os.environ.get("STATIC_INITIALS_DIR", "/app/initials")
DATABASE = os.path.join(DATA_DIR, "data.db")
CIRCLE_TOKEN = os.getenv("CIRCLE_ADMIN_API_V1")
API_KEY = os.getenv("API_KEY")
CACHE_MINUTES = int(os.getenv("CACHE_MINUTES", 30))
FALLBACK_MIN_INTERVAL_MINUTES = int(os.getenv("FALLBACK_MIN_INTERVAL_MINUTES", 60))
DAILY_REFRESH_HOUR_UTC = int(os.getenv("DAILY_REFRESH_HOUR_UTC", 4))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://api.befreeclub.pro").rstrip("/")

os.makedirs(AVATARS_DIR, exist_ok=True)

_fetch_lock = threading.Lock()


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            id INTEGER PRIMARY KEY,
            last_fetch TEXT,
            emails TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS members_cache (
            id INTEGER PRIMARY KEY,
            last_fetch TEXT,
            members_json TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS members (
            email TEXT PRIMARY KEY,
            name TEXT,
            first_name TEXT,
            last_name TEXT,
            avatar_url TEXT,
            avatar_filename TEXT,
            headline TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fetch_log (
            key TEXT PRIMARY KEY,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()


def hash_email(email):
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:16]


_POLISH_MAP = str.maketrans({
    "Ł": "L", "ł": "l", "Đ": "D", "đ": "d", "Ø": "O", "ø": "o",
    "Æ": "AE", "æ": "ae", "Œ": "OE", "œ": "oe", "ß": "ss",
})


def asciify(s):
    if not s:
        return ""
    s = s.translate(_POLISH_MAP)
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _letters_only(s):
    return re.sub(r"[^A-Z]", "", asciify(s or "").upper())


def compute_initials(first_name, last_name, email):
    """Return 1-2 uppercase ASCII letters. Prefers 2."""
    first = _letters_only(first_name)
    last = _letters_only(last_name)

    if first and last:
        return first[0] + last[0]
    if first:
        return first[:2]  # 2 chars if possible, else 1

    # Fallback: email local part
    local = (email or "").split("@")[0]
    cleaned = _letters_only(local)
    if cleaned:
        return cleaned[:2]
    return "X"  # extreme fallback; should never happen (email is primary key)


def ext_from_content_type(content_type):
    if not content_type:
        return None
    ct = content_type.split(";")[0].strip().lower()
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
    }
    return mapping.get(ct) or mimetypes.guess_extension(ct)


def ext_from_url(url):
    if not url:
        return None
    path = url.split("?")[0].split("#")[0]
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"):
        return ".jpg" if ext == ".jpeg" else ext
    return None


def download_avatar(email, url):
    """Download avatar and save to AVATARS_DIR. Return filename or None."""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=15, stream=True)
        if resp.status_code != 200:
            return None
        ext = ext_from_content_type(resp.headers.get("Content-Type")) or ext_from_url(url) or ".jpg"
        filename = f"{hash_email(email)}{ext}"
        filepath = os.path.join(AVATARS_DIR, filename)

        # Remove any previous files with different extensions for this email
        prefix = hash_email(email)
        for existing in os.listdir(AVATARS_DIR):
            if existing.startswith(prefix + ".") and existing != filename:
                try:
                    os.remove(os.path.join(AVATARS_DIR, existing))
                except OSError:
                    pass

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return filename
    except Exception as e:
        app.logger.warning(f"Avatar download failed for {email}: {e}")
        return None


def bfc_avatar_url(filename):
    if not filename:
        return None
    return f"{PUBLIC_BASE_URL}/avatars/{filename}"


def initials_url(letters):
    return f"{PUBLIC_BASE_URL}/avatars/initials/{letters}.png"


def avatar_url_for_member(first_name, last_name, email, avatar_filename):
    """Return public avatar URL: real avatar file if present, else pre-generated initials PNG."""
    if avatar_filename:
        return bfc_avatar_url(avatar_filename)
    letters = compute_initials(first_name, last_name, email)
    return initials_url(letters)


def upsert_member(member):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute("""
        INSERT INTO members (email, name, first_name, last_name, avatar_url, avatar_filename, headline, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
            name = excluded.name,
            first_name = excluded.first_name,
            last_name = excluded.last_name,
            avatar_url = excluded.avatar_url,
            avatar_filename = COALESCE(excluded.avatar_filename, members.avatar_filename),
            headline = excluded.headline,
            updated_at = excluded.updated_at
    """, (
        member["email"],
        member.get("name"),
        member.get("first_name"),
        member.get("last_name"),
        member.get("avatar_url"),
        member.get("avatar_filename"),
        member.get("headline"),
        now,
    ))
    conn.commit()
    conn.close()


def get_member_by_email(email):
    conn = get_db()
    row = conn.execute("SELECT * FROM members WHERE email = ? COLLATE NOCASE", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None


def set_fetch_timestamp(key):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute("""
        INSERT INTO fetch_log (key, timestamp)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET timestamp = excluded.timestamp
    """, (key, now))
    conn.commit()
    conn.close()


def get_fetch_timestamp(key):
    conn = get_db()
    row = conn.execute("SELECT timestamp FROM fetch_log WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["timestamp"] if row else None


def minutes_since(ts_str):
    if not ts_str:
        return float("inf")
    ts = datetime.fromisoformat(ts_str)
    return (datetime.now(timezone.utc) - ts).total_seconds() / 60


def save_cache(emails):
    now = datetime.now(timezone.utc).isoformat()
    emails_str = ",".join(emails)
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO cache (id, last_fetch, emails)
        VALUES (1, ?, ?)
    """, (now, emails_str))
    conn.commit()
    conn.close()


def save_members_cache(members):
    now = datetime.now(timezone.utc).isoformat()
    members_str = json.dumps(members)
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO members_cache (id, last_fetch, members_json)
        VALUES (1, ?, ?)
    """, (now, members_str))
    conn.commit()
    conn.close()


def get_cached_data():
    conn = get_db()
    row = conn.execute("SELECT * FROM cache WHERE id = 1").fetchone()
    conn.close()
    return row


def get_cached_members():
    conn = get_db()
    row = conn.execute("SELECT * FROM members_cache WHERE id = 1").fetchone()
    conn.close()
    return row


def is_cache_valid(last_fetch_str):
    if not last_fetch_str:
        return False
    return minutes_since(last_fetch_str) < CACHE_MINUTES


def fetch_circle_active_members():
    """Fetch raw active members from Circle. Returns list of dicts with Circle fields."""
    headers = {
        "Authorization": f"Bearer {CIRCLE_TOKEN}",
        "Content-Type": "application/json",
    }
    url = "https://app.circle.so/api/v1/community_members"
    members = []

    for page in range(1, 1000):
        params = {"sort": "latest", "per_page": 100, "page": page}
        response = requests.get(url, headers=headers, params=params, timeout=30)
        data = response.json()
        if len(data) == 0:
            break
        for m in data:
            if m.get("active"):
                members.append(m)
    return members


def sync_members_from_circle():
    """Full sync: fetch from Circle, download avatars, upsert into DB, update legacy caches.
    Returns the normalized list of members (with BFC avatar URLs)."""
    with _fetch_lock:
        raw_members = fetch_circle_active_members()

        normalized = []
        emails = []
        for rm in raw_members:
            email = rm.get("email")
            if not email:
                continue
            circle_avatar = rm.get("avatar_url")

            existing = get_member_by_email(email)
            avatar_filename = existing["avatar_filename"] if existing else None

            # Re-download if URL changed or no local file yet
            needs_download = (
                circle_avatar
                and (not existing or existing.get("avatar_url") != circle_avatar or not avatar_filename
                     or not os.path.exists(os.path.join(AVATARS_DIR, avatar_filename)))
            )
            if needs_download:
                new_filename = download_avatar(email, circle_avatar)
                if new_filename:
                    avatar_filename = new_filename

            member_record = {
                "email": email,
                "name": rm.get("name"),
                "first_name": rm.get("first_name"),
                "last_name": rm.get("last_name"),
                "avatar_url": circle_avatar,
                "avatar_filename": avatar_filename,
                "headline": rm.get("headline"),
            }
            upsert_member(member_record)

            normalized.append({
                "email": email,
                "name": rm.get("name"),
                "first_name": rm.get("first_name"),
                "last_name": rm.get("last_name"),
                "avatar_url": avatar_url_for_member(
                    rm.get("first_name"), rm.get("last_name"), email, avatar_filename
                ),
                "headline": rm.get("headline"),
            })
            emails.append(email)

        save_cache(emails)
        save_members_cache(normalized)
        set_fetch_timestamp("last_full_fetch")

        return normalized


def member_row_to_public(row):
    if not row:
        return None
    return {
        "email": row["email"],
        "name": row["name"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "avatar_url": avatar_url_for_member(
            row["first_name"], row["last_name"], row["email"], row["avatar_filename"]
        ),
        "headline": row["headline"],
    }


def can_fallback_fetch():
    last = get_fetch_timestamp("last_full_fetch")
    return minutes_since(last) >= FALLBACK_MIN_INTERVAL_MINUTES


def require_api_key():
    # Preferred: Authorization: Bearer <key>
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        if auth_header[7:].strip() == API_KEY:
            return None

    # Alternative: X-API-Key header
    x_key = request.headers.get("X-API-Key")
    if x_key and x_key == API_KEY:
        return None

    # Legacy: ?key=... query param (backwards compat)
    q_key = request.args.get("key")
    if q_key and q_key == API_KEY:
        return None

    return jsonify({"error": "Invalid or missing API key"}), 401


@app.route("/subscribers", methods=["GET"])
def subscribers():
    auth_error = require_api_key()
    if auth_error:
        return auth_error

    use_cache = request.args.get("cache", "true").lower() != "false"

    if use_cache:
        cached = get_cached_data()
        if cached and is_cache_valid(cached["last_fetch"]):
            emails = cached["emails"].split(",") if cached["emails"] else []
            return jsonify({"emails": emails, "cached": True})

    sync_members_from_circle()
    cached = get_cached_data()
    emails = cached["emails"].split(",") if cached and cached["emails"] else []
    return jsonify({"emails": emails, "cached": False})


@app.route("/members", methods=["GET"])
def members():
    auth_error = require_api_key()
    if auth_error:
        return auth_error

    use_cache = request.args.get("cache", "true").lower() != "false"

    if use_cache:
        cached = get_cached_members()
        if cached and is_cache_valid(cached["last_fetch"]):
            members_data = json.loads(cached["members_json"]) if cached["members_json"] else []
            return jsonify({"members": members_data, "cached": True})

    members_data = sync_members_from_circle()
    return jsonify({"members": members_data, "cached": False})


@app.route("/members/<email>", methods=["GET"])
def member_by_email(email):
    auth_error = require_api_key()
    if auth_error:
        return auth_error

    use_cache = request.args.get("cache", "true").lower() != "false"

    if use_cache:
        row = get_member_by_email(email)
        if row:
            return jsonify({"member": member_row_to_public(row), "source": "cache"})

    # Either cache=false, or not in cache — try to refresh from Circle (rate-limited)
    if not can_fallback_fetch():
        row = get_member_by_email(email)  # stale fallback
        if row:
            return jsonify({"member": member_row_to_public(row), "source": "cache_stale"})
        return jsonify({
            "error": "Not found",
            "member": None,
            "source": "cache",
            "hint": "Cache does not contain this email and Circle refresh is rate-limited.",
        }), 404

    sync_members_from_circle()
    row = get_member_by_email(email)
    if row:
        return jsonify({"member": member_row_to_public(row), "source": "circle"})

    return jsonify({"error": "Not found", "member": None, "source": "circle"}), 404


@app.route("/subscription/<email>", methods=["GET"])
def subscription(email):
    auth_error = require_api_key()
    if auth_error:
        return auth_error

    use_cache = request.args.get("cache", "true").lower() != "false"

    if use_cache:
        row = get_member_by_email(email)
        if row:
            return jsonify({"email": email, "has_subscription": True, "source": "cache"})

    if not can_fallback_fetch():
        row = get_member_by_email(email)
        return jsonify({
            "email": email,
            "has_subscription": bool(row),
            "source": "cache_stale" if row else "cache",
        })

    sync_members_from_circle()
    row = get_member_by_email(email)
    return jsonify({
        "email": email,
        "has_subscription": bool(row),
        "source": "circle",
    })


_INITIALS_RE = re.compile(r"^[A-Z]{1,2}$")


@app.route("/avatars/initials/<letters>.png", methods=["GET"])
def serve_initials(letters):
    if not _INITIALS_RE.match(letters):
        abort(404)
    filepath = os.path.join(STATIC_INITIALS_DIR, f"{letters}.png")
    if not os.path.exists(filepath):
        abort(404)
    response = send_from_directory(STATIC_INITIALS_DIR, f"{letters}.png", max_age=31536000)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@app.route("/avatars/<filename>", methods=["GET"])
def serve_avatar(filename):
    # Prevent path traversal; allow only simple filenames
    if "/" in filename or ".." in filename or filename.startswith("."):
        abort(404)
    filepath = os.path.join(AVATARS_DIR, filename)
    if not os.path.exists(filepath) or not os.path.isfile(filepath):
        abort(404)
    return send_from_directory(AVATARS_DIR, filename, max_age=86400)


@app.route("/health", methods=["GET"])
def health():
    last_full = get_fetch_timestamp("last_full_fetch")
    return jsonify({
        "status": "ok",
        "last_full_fetch": last_full,
        "minutes_since_full_fetch": minutes_since(last_full) if last_full else None,
    })


def scheduled_daily_refresh():
    """Runs daily; refreshes only if last fetch was long enough ago (idempotent across workers)."""
    last = get_fetch_timestamp("last_full_fetch")
    if minutes_since(last) < 20 * 60:  # 20h guard prevents double-runs across workers
        app.logger.info("Skipping scheduled refresh — last fetch too recent")
        return
    try:
        app.logger.info("Running scheduled daily refresh")
        sync_members_from_circle()
    except Exception as e:
        app.logger.error(f"Scheduled refresh failed: {e}")


def start_scheduler():
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        scheduled_daily_refresh,
        "cron",
        hour=DAILY_REFRESH_HOUR_UTC,
        minute=0,
        id="daily_refresh",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler


init_db()

# Start scheduler only when app is actually serving (not e.g. during imports for tests)
if os.getenv("ENABLE_SCHEDULER", "true").lower() == "true":
    start_scheduler()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
