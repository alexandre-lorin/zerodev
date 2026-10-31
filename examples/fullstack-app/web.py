"""Vérifie que DATABASE_URL et REDIS_URL pointent vers des services qui répondent réellement."""
import os
import socket
import time
from urllib.parse import urlparse


def check(var):
    url = os.environ.get(var)
    if not url:
        return f"{var} : <absent>"
    u = urlparse(url)
    try:
        with socket.create_connection((u.hostname, u.port), timeout=2):
            return f"{var} : connexion OK ({u.hostname}:{u.port})"
    except OSError as e:
        return f"{var} : {url} → ÉCHEC ({e})"


print(check("DATABASE_URL"), flush=True)
print(check("REDIS_URL"), flush=True)
while True:
    time.sleep(1)
