import base64
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("cws", ROOT / ".github" / "actions" / "chrome-web-store" / "cws.py")
cws = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cws)

NAME = "publishers/pub-1/items/item-1"


@pytest.fixture(scope="module")
def key(tmp_path_factory):
    folder = tmp_path_factory.mktemp("key")
    private = folder / "key.pem"
    subprocess.run(["openssl", "genrsa", "-out", str(private), "2048"], check=True, capture_output=True)
    public = folder / "public.pem"
    subprocess.run(["openssl", "rsa", "-in", str(private), "-pubout", "-out", str(public)],
                   check=True, capture_output=True)
    return {
        "client_email": "cws@example.iam.gserviceaccount.com",
        "private_key": private.read_text(),
        "token_uri": "https://oauth2.example.com/token",
        "public_path": str(public),
    }


def decode(part):
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


class FakeHttp:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers=None, body=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "body": body})
        return self.responses.pop(0)


def test_assertion_is_a_signed_jwt_for_the_chrome_web_store_scope(key, tmp_path):
    assertion = cws.assertion(key, now=1_000)
    header, claims, signature = assertion.split(".")
    assert decode(header) == {"alg": "RS256", "typ": "JWT"}
    assert decode(claims) == {
        "iss": "cws@example.iam.gserviceaccount.com",
        "scope": "https://www.googleapis.com/auth/chromewebstore",
        "aud": "https://oauth2.example.com/token",
        "iat": 1_000,
        "exp": 4_600,
    }
    signed = tmp_path / "signed"
    signed.write_text(f"{header}.{claims}")
    sig = tmp_path / "sig"
    sig.write_bytes(base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)))
    result = subprocess.run(
        ["openssl", "dgst", "-sha256", "-verify", key["public_path"], "-signature", str(sig), str(signed)],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_assertion_defaults_the_token_uri(key):
    without = {k: v for k, v in key.items() if k != "token_uri"}
    claims = decode(cws.assertion(without, now=0).split(".")[1])
    assert claims["aud"] == "https://oauth2.googleapis.com/token"


def test_assertion_rejects_a_key_without_a_private_key():
    with pytest.raises(cws.StoreError, match="client_email and private_key"):
        cws.assertion({"client_email": "a@b"}, now=0)


def test_access_token_exchanges_the_jwt(key):
    http = FakeHttp((200, {"access_token": "tok", "expires_in": 3599}))
    assert cws.access_token(key, http, now=0) == "tok"
    call = http.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://oauth2.example.com/token"
    assert call["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert b"grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer" in call["body"]
    assert b"assertion=" in call["body"]


def test_access_token_reports_the_oauth_error(key):
    http = FakeHttp((400, {"error": "invalid_grant", "error_description": "Invalid JWT Signature."}))
    with pytest.raises(cws.StoreError, match="invalid_grant: Invalid JWT Signature."):
        cws.access_token(key, http, now=0)


def test_upload_posts_the_zip(tmp_path):
    package = tmp_path / "distribution.zip"
    package.write_bytes(b"zip bytes")
    http = FakeHttp((200, {"name": NAME, "uploadState": "SUCCEEDED", "crxVersion": "2.0.4"}))
    assert cws.upload("tok", NAME, package, http) == "2.0.4"
    call = http.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://chromewebstore.googleapis.com/upload/v2/publishers/pub-1/items/item-1:upload"
    assert call["headers"]["Authorization"] == "Bearer tok"
    assert call["body"] == b"zip bytes"


def test_upload_fails_on_a_failed_state(tmp_path):
    package = tmp_path / "distribution.zip"
    package.write_bytes(b"zip")
    http = FakeHttp((200, {"uploadState": "FAILED"}))
    with pytest.raises(cws.StoreError, match="Upload failed: uploadState is FAILED"):
        cws.upload("tok", NAME, package, http)


def test_upload_reports_the_api_error(tmp_path):
    package = tmp_path / "distribution.zip"
    package.write_bytes(b"zip")
    http = FakeHttp((400, {"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                     "message": "The version must be greater than the published one."}}))
    with pytest.raises(cws.StoreError,
                       match="Upload failed: HTTP 400 INVALID_ARGUMENT: The version must be greater"):
        cws.upload("tok", NAME, package, http)


def test_upload_fails_when_the_zip_is_missing(tmp_path):
    with pytest.raises(cws.StoreError, match="No package at"):
        cws.upload("tok", NAME, tmp_path / "missing.zip", FakeHttp())


def test_upload_polls_fetch_status_while_in_progress(tmp_path):
    package = tmp_path / "distribution.zip"
    package.write_bytes(b"zip")
    http = FakeHttp(
        (200, {"uploadState": "IN_PROGRESS"}),
        (200, {"lastAsyncUploadState": "IN_PROGRESS"}),
        (200, {"lastAsyncUploadState": "SUCCEEDED",
               "submittedItemRevisionStatus": {"distributionChannels": [{"crxVersion": "1.3.1"}]}}),
    )
    waits = []
    assert cws.upload("tok", NAME, package, http, sleep=waits.append, interval=5) == "1.3.1"
    assert waits == [5, 5]
    assert http.calls[1]["method"] == "GET"
    assert http.calls[1]["url"] == "https://chromewebstore.googleapis.com/v2/publishers/pub-1/items/item-1:fetchStatus"


def test_upload_gives_up_after_the_last_poll(tmp_path):
    package = tmp_path / "distribution.zip"
    package.write_bytes(b"zip")
    http = FakeHttp((200, {"uploadState": "IN_PROGRESS"}), *[(200, {"lastAsyncUploadState": "IN_PROGRESS"})] * 3)
    with pytest.raises(cws.StoreError, match="still IN_PROGRESS after 3 checks"):
        cws.upload("tok", NAME, package, http, sleep=lambda s: None, polls=3)


def test_upload_fails_when_polling_reports_failure(tmp_path):
    package = tmp_path / "distribution.zip"
    package.write_bytes(b"zip")
    http = FakeHttp((200, {"uploadState": "IN_PROGRESS"}), (200, {"lastAsyncUploadState": "FAILED"}))
    with pytest.raises(cws.StoreError, match="Upload failed: uploadState is FAILED"):
        cws.upload("tok", NAME, package, http, sleep=lambda s: None)


@pytest.mark.parametrize("choice, publish_type", [("default", "DEFAULT_PUBLISH"), ("staged", "STAGED_PUBLISH")])
def test_publish_sends_the_publish_type(choice, publish_type):
    http = FakeHttp((200, {"name": NAME, "state": "PENDING_REVIEW"}))
    assert cws.publish("tok", NAME, choice, http) == ("PENDING_REVIEW", [])
    call = http.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://chromewebstore.googleapis.com/v2/publishers/pub-1/items/item-1:publish"
    assert call["headers"]["Authorization"] == "Bearer tok"
    assert call["headers"]["Content-Type"] == "application/json"
    assert json.loads(call["body"]) == {"publishType": publish_type}


def test_publish_rejects_an_unknown_publish_type():
    with pytest.raises(cws.StoreError, match="publish_type must be default or staged, not soon"):
        cws.publish("tok", NAME, "soon", FakeHttp())


@pytest.mark.parametrize("state", ["PENDING_REVIEW", "STAGED", "PUBLISHED", "PUBLISHED_TO_TESTERS"])
def test_publish_accepts_good_states(state):
    assert cws.publish("tok", NAME, "default", FakeHttp((200, {"state": state})))[0] == state


@pytest.mark.parametrize("state", ["REJECTED", "CANCELLED", "ITEM_STATE_UNSPECIFIED", None])
def test_publish_fails_on_bad_states(state):
    body = {"state": state} if state else {}
    with pytest.raises(cws.StoreError, match="Publish failed: state is"):
        cws.publish("tok", NAME, "default", FakeHttp((200, body)))


def test_publish_returns_warnings():
    http = FakeHttp((200, {"state": "PENDING_REVIEW",
                           "warningInfo": {"warnings": [{"reason": "R", "description": "Check this."}]}}))
    assert cws.publish("tok", NAME, "default", http) == ("PENDING_REVIEW", ["R: Check this."])


def test_publish_reports_the_api_error():
    http = FakeHttp((403, {"error": {"code": 403, "status": "PERMISSION_DENIED", "message": "No access."}}))
    with pytest.raises(cws.StoreError, match="Publish failed: HTTP 403 PERMISSION_DENIED: No access."):
        cws.publish("tok", NAME, "default", http)


def test_main_uploads_then_publishes(key, tmp_path, monkeypatch, capsys):
    package = tmp_path / "distribution.zip"
    package.write_bytes(b"zip")
    http = FakeHttp(
        (200, {"access_token": "tok"}),
        (200, {"uploadState": "SUCCEEDED", "crxVersion": "2.0.4"}),
        (200, {"state": "PENDING_REVIEW", "warningInfo": {"warnings": [{"reason": "R", "description": "D"}]}}),
    )
    monkeypatch.setenv("SERVICE_ACCOUNT_KEY", json.dumps(key))
    code = cws.main(["--publisher-id", "pub-1", "--item-id", "item-1", "--zip", str(package)], http=http)
    assert code == 0
    out = capsys.readouterr().out
    assert "Uploaded version 2.0.4" in out
    assert "::warning::R: D" in out
    assert "Submitted for publishing: PENDING_REVIEW" in out
    assert [c["url"].rsplit(":", 1)[-1] for c in http.calls[1:]] == ["upload", "publish"]


@pytest.mark.parametrize("args, env, message", [
    (["--item-id", "item-1"], "{}", "publisher_id is empty"),
    (["--publisher-id", "pub-1"], "{}", "item_id is empty"),
    (["--publisher-id", "pub-1", "--item-id", "item-1"], "", "service_account_key is empty"),
    (["--publisher-id", "pub-1", "--item-id", "item-1"], "not json", "service_account_key is not valid JSON"),
])
def test_main_fails_clearly_on_missing_settings(args, env, message, monkeypatch, capsys):
    monkeypatch.setenv("SERVICE_ACCOUNT_KEY", env)
    assert cws.main(args, http=FakeHttp()) == 1
    assert f"::error::{message}" in capsys.readouterr().out


def test_main_reports_a_failure_as_an_error(key, tmp_path, monkeypatch, capsys):
    package = tmp_path / "distribution.zip"
    package.write_bytes(b"zip")
    http = FakeHttp((200, {"access_token": "tok"}), (200, {"uploadState": "FAILED"}))
    monkeypatch.setenv("SERVICE_ACCOUNT_KEY", json.dumps(key))
    assert cws.main(["--publisher-id", "pub-1", "--item-id", "item-1", "--zip", str(package)], http=http) == 1
    assert "::error::Upload failed: uploadState is FAILED" in capsys.readouterr().out


def test_main_checks_the_publish_type_before_uploading(monkeypatch, capsys):
    monkeypatch.setenv("SERVICE_ACCOUNT_KEY", "{}")
    http = FakeHttp()
    args = ["--publisher-id", "pub-1", "--item-id", "item-1", "--publish-type", "soon"]
    assert cws.main(args, http=http) == 1
    assert http.calls == []
    assert "::error::publish_type must be default or staged, not soon" in capsys.readouterr().out
