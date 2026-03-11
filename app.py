import os
import json
import sqlite3
import requests
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

DATA_DIR = os.environ.get("DATA_DIR", ".")
DATABASE = os.path.join(DATA_DIR, "data.db")
CIRCLE_TOKEN = os.getenv("CIRCLE_ADMIN_API_V1")
API_KEY = os.getenv("API_KEY")
CACHE_MINUTES = int(os.getenv("CACHE_MINUTES", 30))


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


def is_cache_valid(last_fetch_str):
    if not last_fetch_str:
        return False
    last_fetch = datetime.fromisoformat(last_fetch_str)
    now = datetime.now(timezone.utc)
    diff = (now - last_fetch).total_seconds() / 60
    return diff < CACHE_MINUTES


def fetch_active_subscribers():
    headers = {
        "Authorization": f"Bearer {CIRCLE_TOKEN}",
        "Content-Type": "application/json"
    }
    url = "https://app.circle.so/api/v1/community_members"
    emails = []

    for page in range(1, 1000):
        params = {"sort": "latest", "per_page": 100, "page": page}
        response = requests.get(url, headers=headers, params=params)
        data = response.json()

        if len(data) == 0:
            break

        for member in data:
            if member.get("active"):
                emails.append(member["email"])

    return emails


def fetch_active_members():
    headers = {
        "Authorization": f"Bearer {CIRCLE_TOKEN}",
        "Content-Type": "application/json"
    }
    url = "https://app.circle.so/api/v1/community_members"
    members = []

    for page in range(1, 1000):
        params = {"sort": "latest", "per_page": 100, "page": page}
        response = requests.get(url, headers=headers, params=params)
        data = response.json()

        if len(data) == 0:
            break

        for member in data:
            if member.get("active"):
                members.append({
                    "email": member.get("email"),
                    "name": member.get("name"),
                    "first_name": member.get("first_name"),
                    "last_name": member.get("last_name"),
                    "avatar_url": member.get("avatar_url"),
                    "headline": member.get("headline"),
                })

    return members


@app.route("/subscribers", methods=["GET"])
def subscribers():
    api_key = request.args.get("key")

    if not api_key or api_key != API_KEY:
        return jsonify({"error": "Invalid API key"}), 401

    use_cache = request.args.get("cache", "true").lower() != "false"

    if use_cache:
        cached = get_cached_data()
        if cached and is_cache_valid(cached["last_fetch"]):
            emails = cached["emails"].split(",") if cached["emails"] else []
            return jsonify({"emails": emails, "cached": True})

    emails = fetch_active_subscribers()
    save_cache(emails)

    return jsonify({"emails": emails, "cached": False})


@app.route("/members", methods=["GET"])
def members():
    api_key = request.args.get("key")

    if not api_key or api_key != API_KEY:
        return jsonify({"error": "Invalid API key"}), 401

    use_cache = request.args.get("cache", "true").lower() != "false"

    if use_cache:
        cached = get_cached_members()
        if cached and is_cache_valid(cached["last_fetch"]):
            members_data = json.loads(cached["members_json"]) if cached["members_json"] else []
            return jsonify({"members": members_data, "cached": True})

    members_data = fetch_active_members()
    save_members_cache(members_data)

    return jsonify({"members": members_data, "cached": False})


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
