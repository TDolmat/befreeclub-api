#!/usr/bin/env python3
import secrets
import os

key = secrets.token_urlsafe(32)
print(f"Generated API Key: {key}")

env_path = ".env"
lines = []

if os.path.exists(env_path):
    with open(env_path, "r") as f:
        lines = f.readlines()

found = False
for i, line in enumerate(lines):
    if line.startswith("API_KEY="):
        lines[i] = f"API_KEY={key}\n"
        found = True
        break

if not found:
    lines.append(f"API_KEY={key}\n")

with open(env_path, "w") as f:
    f.writelines(lines)

print(f"API Key saved to {env_path}")

