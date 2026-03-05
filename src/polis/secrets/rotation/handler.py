"""Secrets Manager rotation Lambda: refreshes GitHub App and OAuth tokens.

Implements the 4-step rotation protocol:
  createSecret  — generate new token, store as AWSPENDING
  setSecret     — no-op (token is already usable)
  testSecret    — verify the new token works
  finishSecret  — promote AWSPENDING to AWSCURRENT

Dispatches by secret `type` field:
  - "github_app": Generate JWT from app_id + private_key, create installation access token
  - "oauth":      Standard refresh_token flow

Note: JWT RS256 signing is implemented inline (no PyJWT dependency) so this can
be deployed as a single-file Lambda without layers.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
import urllib.parse
import urllib.request

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sm = boto3.client("secretsmanager")


def handler(event, context):
    secret_id = event["SecretId"]
    step = event["Step"]
    token = event["ClientRequestToken"]

    logger.info("Rotation step=%s secret=%s token=%s", step, secret_id, token)

    if step == "createSecret":
        _create_secret(secret_id, token)
    elif step == "setSecret":
        pass  # No-op — tokens are immediately usable
    elif step == "testSecret":
        _test_secret(secret_id, token)
    elif step == "finishSecret":
        _finish_secret(secret_id, token)
    else:
        raise ValueError(f"Unknown rotation step: {step}")


def _create_secret(secret_id: str, token: str):
    """Generate a new access token and store as AWSPENDING."""
    try:
        sm.get_secret_value(SecretId=secret_id, VersionId=token, VersionStage="AWSPENDING")
        logger.info("AWSPENDING already exists for %s, skipping", secret_id)
        return
    except sm.exceptions.ResourceNotFoundException:
        pass

    current = json.loads(
        sm.get_secret_value(SecretId=secret_id, VersionStage="AWSCURRENT")["SecretString"]
    )

    secret_type = current.get("type", "oauth")
    if secret_type == "github_app":
        new_token = _refresh_github_app(current)
    elif secret_type == "oauth":
        new_token = _refresh_oauth(current)
    else:
        raise ValueError(f"Unknown secret type: {secret_type}")

    new_secret = {**current, "access_token": new_token}
    sm.put_secret_value(
        SecretId=secret_id,
        SecretString=json.dumps(new_secret),
        VersionStages=["AWSPENDING"],
        ClientRequestToken=token,
    )
    logger.info("Stored new token as AWSPENDING for %s", secret_id)


def _test_secret(secret_id: str, token: str):
    """Verify the pending secret works."""
    pending = json.loads(
        sm.get_secret_value(SecretId=secret_id, VersionId=token, VersionStage="AWSPENDING")[
            "SecretString"
        ]
    )

    secret_type = pending.get("type", "oauth")
    access_token = pending["access_token"]

    if secret_type == "github_app":
        _test_github_token(access_token)
    elif secret_type == "oauth":
        test_url = pending.get("test_url")
        if test_url:
            _test_oauth_token(access_token, test_url)

    logger.info("Test passed for %s", secret_id)


def _finish_secret(secret_id: str, token: str):
    """Promote AWSPENDING to AWSCURRENT."""
    meta = sm.describe_secret(SecretId=secret_id)
    versions = meta.get("VersionIdsToStages", {})

    current_version = None
    for vid, stages in versions.items():
        if "AWSCURRENT" in stages and vid != token:
            current_version = vid
            break

    if current_version:
        sm.update_secret_version_stage(
            SecretId=secret_id,
            VersionStage="AWSCURRENT",
            MoveToVersionId=token,
            RemoveFromVersionId=current_version,
        )
    sm.update_secret_version_stage(
        SecretId=secret_id,
        VersionStage="AWSPENDING",
        RemoveFromVersionId=token,
    )
    logger.info("Promoted AWSPENDING to AWSCURRENT for %s", secret_id)


# --- JWT RS256 (inline, no PyJWT dependency) ---


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _pkcs1v15_sign_sha256(private_key_pem: str, message: bytes) -> bytes:
    """PKCS#1 v1.5 RSA-SHA256 signature using only stdlib."""
    pem = private_key_pem.strip()
    lines = [ln for ln in pem.splitlines() if not ln.startswith("-----")]
    der = base64.b64decode("".join(lines))

    def _read_tag_len(data, offset):
        tag = data[offset]
        offset += 1
        length = data[offset]
        offset += 1
        if length & 0x80:
            num_bytes = length & 0x7F
            length = int.from_bytes(data[offset : offset + num_bytes], "big")
            offset += num_bytes
        return tag, length, offset

    def _read_integer(data, offset):
        tag, length, offset = _read_tag_len(data, offset)
        assert tag == 0x02, f"Expected INTEGER tag, got {tag:#x}"
        value = int.from_bytes(data[offset : offset + length], "big")
        return value, offset + length

    def _skip_element(data, offset):
        _, length, offset = _read_tag_len(data, offset)
        return offset + length

    tag, _, offset = _read_tag_len(der, 0)
    assert tag == 0x30

    pos = offset
    first_tag = der[pos]
    if first_tag == 0x02:
        version, next_pos = _read_integer(der, pos)
        if version == 0 and der[next_pos] == 0x30:
            next_pos = _skip_element(der, next_pos)
            tag, length, next_pos = _read_tag_len(der, next_pos)
            assert tag == 0x04
            der = der[next_pos : next_pos + length]
            tag, _, offset = _read_tag_len(der, 0)
            assert tag == 0x30

    _version, offset = _read_integer(der, offset)
    n, offset = _read_integer(der, offset)
    _e, offset = _read_integer(der, offset)
    d, offset = _read_integer(der, offset)

    digest = hashlib.sha256(message).digest()
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + digest
    k = (n.bit_length() + 7) // 8
    pad_len = k - len(digest_info) - 3
    assert pad_len >= 8
    em = b"\x00\x01" + b"\xff" * pad_len + b"\x00" + digest_info

    m_int = int.from_bytes(em, "big")
    s_int = pow(m_int, d, n)
    return s_int.to_bytes(k, "big")


def _jwt_rs256(payload: dict, private_key_pem: str) -> str:
    """Create a signed JWT (RS256) using only stdlib."""
    header = {"alg": "RS256", "typ": "JWT"}
    segments = _b64url(json.dumps(header).encode()) + "." + _b64url(json.dumps(payload).encode())
    signature = _pkcs1v15_sign_sha256(private_key_pem, segments.encode())
    return segments + "." + _b64url(signature)


# --- GitHub App token refresh ---


def _refresh_github_app(secret: dict) -> str:
    """Generate a new GitHub App installation access token."""
    app_id = secret["app_id"]
    private_key = secret["private_key"]
    installation_id = secret["installation_id"]

    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": str(app_id)}
    jwt = _jwt_rs256(payload, private_key)

    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "cogent-rotation-lambda",
        },
    )
    resp = urllib.request.urlopen(req)
    data = json.loads(resp.read())
    logger.info("Generated GitHub token for app=%s install=%s", app_id, installation_id)
    return data["token"]


def _test_github_token(token: str):
    req = urllib.request.Request(
        "https://api.github.com/installation/repositories?per_page=1",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "cogent-rotation-lambda",
        },
    )
    resp = urllib.request.urlopen(req)
    if resp.status != 200:
        raise RuntimeError(f"GitHub token test failed: HTTP {resp.status}")


# --- OAuth token refresh ---


def _refresh_oauth(secret: dict) -> str:
    data = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": secret["refresh_token"],
            "client_id": secret["client_id"],
            "client_secret": secret["client_secret"],
        }
    ).encode()

    req = urllib.request.Request(
        secret["token_url"],
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp = urllib.request.urlopen(req)
    tokens = json.loads(resp.read())

    if "error" in tokens:
        raise RuntimeError(f"OAuth refresh failed: {tokens['error']}")
    return tokens["access_token"]


def _test_oauth_token(token: str, test_url: str):
    req = urllib.request.Request(test_url, headers={"Authorization": f"Bearer {token}"})
    resp = urllib.request.urlopen(req)
    if resp.status != 200:
        raise RuntimeError(f"OAuth token test failed: HTTP {resp.status}")
