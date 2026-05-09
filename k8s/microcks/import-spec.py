#!/usr/bin/env python3
"""Import api/openapi.yaml into Microcks via REST API.

Env vars expected (injected from the workflow):
  MICROCKS_KEYCLOAK_URL  - token endpoint base URL
  MICROCKS_URL           - Microcks base URL
  MICROCKS_CLIENT_ID
  MICROCKS_CLIENT_SECRET
  MICROCKS_USERNAME
  MICROCKS_PASSWORD
  SPEC_FILE              - path to the OpenAPI YAML file to import
"""
import os, sys, urllib.request, urllib.parse, json

KEYCLOAK = os.environ["MICROCKS_KEYCLOAK_URL"].rstrip("/")
MICROCKS  = os.environ["MICROCKS_URL"].rstrip("/")
CLIENT_ID = os.environ["MICROCKS_CLIENT_ID"]
SECRET    = os.environ["MICROCKS_CLIENT_SECRET"]
USER      = os.environ["MICROCKS_USERNAME"]
PASSWD    = os.environ["MICROCKS_PASSWORD"]
SPEC_FILE = os.environ.get("SPEC_FILE", "/data/openapi.yaml")

with open(SPEC_FILE, "rb") as f:
    spec_bytes = f.read()

# 1 — get token
payload = urllib.parse.urlencode({
    "grant_type": "password",
    "client_id": CLIENT_ID,
    "client_secret": SECRET,
    "username": USER,
    "password": PASSWD,
}).encode()
req = urllib.request.Request(
    KEYCLOAK + "/protocol/openid-connect/token",
    data=payload, method="POST",
    headers={"Content-Type": "application/x-www-form-urlencoded"},
)
with urllib.request.urlopen(req, timeout=15) as r:
    token = json.loads(r.read())["access_token"]

# 2 — import spec (multipart/form-data)
boundary = b"----MicrocksImport1234"
body = (
    b"--" + boundary + b"\r\n"
    b'Content-Disposition: form-data; name="file"; filename="openapi.yaml"\r\n'
    b"Content-Type: application/yaml\r\n\r\n"
    + spec_bytes
    + b"\r\n--" + boundary + b"--\r\n"
)
req2 = urllib.request.Request(
    MICROCKS + "/api/artifact/import?mainArtifact=true",
    data=body, method="POST",
    headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "multipart/form-data; boundary=" + boundary.decode(),
    },
)
try:
    with urllib.request.urlopen(req2, timeout=30) as r:
        result = json.loads(r.read())
        names = [s.get("name") + ":" + s.get("version", "") for s in result] if isinstance(result, list) else [str(result)]
        print("Microcks import OK:", ", ".join(names))
except urllib.error.HTTPError as e:
    print("Microcks import error:", e.code, e.read().decode()[:300], file=sys.stderr)
    sys.exit(1)
