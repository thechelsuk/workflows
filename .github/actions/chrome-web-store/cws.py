import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://chromewebstore.googleapis.com"
SCOPE = "https://www.googleapis.com/auth/chromewebstore"
TOKEN_URI = "https://oauth2.googleapis.com/token"
PUBLISH_TYPES = {"default": "DEFAULT_PUBLISH", "staged": "STAGED_PUBLISH"}
GOOD_STATES = {"PENDING_REVIEW", "STAGED", "PUBLISHED", "PUBLISHED_TO_TESTERS"}


class StoreError(Exception):
    pass


def http_request(method, url, headers=None, body=None):
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {"error": {"message": raw.decode(errors="replace")[:500]}}
    return status, data


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign(private_key, message):
    with tempfile.NamedTemporaryFile("w", delete=False, dir=os.environ.get("RUNNER_TEMP")) as handle:
        os.chmod(handle.name, 0o600)
        handle.write(private_key)
    try:
        result = subprocess.run(["openssl", "dgst", "-sha256", "-sign", handle.name],
                                input=message, capture_output=True)
    finally:
        os.unlink(handle.name)
    if result.returncode != 0:
        raise StoreError(f"Could not sign the token request: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def assertion(key, now=None):
    if not key.get("client_email") or not key.get("private_key"):
        raise StoreError("The service account key needs client_email and private_key")
    now = int(time.time()) if now is None else now
    header = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = b64(json.dumps({
        "iss": key["client_email"],
        "scope": SCOPE,
        "aud": key.get("token_uri") or TOKEN_URI,
        "iat": now,
        "exp": now + 3600,
    }).encode())
    unsigned = f"{header}.{claims}"
    return f"{unsigned}.{b64(sign(key['private_key'], unsigned.encode()))}"


def access_token(key, http, now=None):
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion(key, now),
    }).encode()
    status, data = http("POST", key.get("token_uri") or TOKEN_URI,
                        {"Content-Type": "application/x-www-form-urlencoded"}, body)
    if status != 200 or not data.get("access_token"):
        detail = ": ".join(str(p) for p in (data.get("error"), data.get("error_description")) if p)
        raise StoreError(f"Could not get an access token: HTTP {status} {detail}".rstrip())
    return data["access_token"]


def api_error(action, status, data):
    error = data.get("error") if isinstance(data.get("error"), dict) else {}
    label = " ".join(str(p) for p in (status, error.get("status")) if p)
    return StoreError(f"{action} failed: HTTP {label}: {error.get('message') or json.dumps(data)}")


def fetch_status(token, name, http):
    status, data = http("GET", f"{API}/v2/{name}:fetchStatus", {"Authorization": f"Bearer {token}"})
    if status != 200:
        raise api_error("Status check", status, data)
    return data


def uploaded_version(data):
    channels = (data.get("submittedItemRevisionStatus") or {}).get("distributionChannels") or []
    return channels[0].get("crxVersion", "") if channels else ""


def upload(token, name, package, http, sleep=time.sleep, interval=10, polls=30):
    package = Path(package)
    if not package.is_file():
        raise StoreError(f"No package at {package}")
    status, data = http("POST", f"{API}/upload/v2/{name}:upload",
                        {"Authorization": f"Bearer {token}"}, package.read_bytes())
    if status != 200:
        raise api_error("Upload", status, data)
    state, version = data.get("uploadState"), data.get("crxVersion", "")
    checks = 0
    while state == "IN_PROGRESS":
        if checks == polls:
            raise StoreError(f"Upload failed: still IN_PROGRESS after {polls} checks")
        sleep(interval)
        checks += 1
        data = fetch_status(token, name, http)
        state, version = data.get("lastAsyncUploadState"), uploaded_version(data)
    if state != "SUCCEEDED":
        raise StoreError(f"Upload failed: uploadState is {state}")
    return version


def publish(token, name, choice, http):
    if choice not in PUBLISH_TYPES:
        raise StoreError(f"publish_type must be default or staged, not {choice}")
    status, data = http("POST", f"{API}/v2/{name}:publish",
                        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json.dumps({"publishType": PUBLISH_TYPES[choice]}).encode())
    if status != 200:
        raise api_error("Publish", status, data)
    state = data.get("state")
    if state not in GOOD_STATES:
        raise StoreError(f"Publish failed: state is {state}")
    warnings = [f"{w.get('reason', '')}: {w.get('description', '')}"
                for w in (data.get("warningInfo") or {}).get("warnings", [])]
    return state, warnings


def load_key(raw):
    if not raw.strip():
        raise StoreError("service_account_key is empty")
    try:
        return json.loads(raw)
    except ValueError:
        raise StoreError("service_account_key is not valid JSON") from None


def main(argv=None, http=http_request):
    parser = argparse.ArgumentParser(description="Upload a zip to the Chrome Web Store, then publish it.")
    parser.add_argument("--publisher-id", default="")
    parser.add_argument("--item-id", default="")
    parser.add_argument("--zip", default="distribution.zip")
    parser.add_argument("--publish-type", default="default")
    args = parser.parse_args(argv)
    try:
        if not args.publisher_id:
            raise StoreError("publisher_id is empty")
        if not args.item_id:
            raise StoreError("item_id is empty")
        if args.publish_type not in PUBLISH_TYPES:
            raise StoreError(f"publish_type must be default or staged, not {args.publish_type}")
        key = load_key(os.environ.get("SERVICE_ACCOUNT_KEY", ""))
        name = f"publishers/{args.publisher_id}/items/{args.item_id}"
        token = access_token(key, http)
        version = upload(token, name, args.zip, http)
        print(f"Uploaded version {version} to {name}")
        state, warnings = publish(token, name, args.publish_type, http)
        for warning in warnings:
            print(f"::warning::{warning}")
        print(f"Submitted for publishing: {state}")
    except StoreError as error:
        print(f"::error::{error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
