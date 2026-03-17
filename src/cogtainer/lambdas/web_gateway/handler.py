from __future__ import annotations

import json
import logging
import os
import time
from uuid import uuid4

import boto3

from cogos.db.models.channel_message import ChannelMessage
from cogos.db.repository import Repository
from cogos.files.store import FileStore
from cogos.io.web.serving import content_type_for_path, lookup_static_file

logger = logging.getLogger(__name__)

_jwks_cache: dict[str, tuple[float, dict]] = {}
_JWKS_TTL = 300


def _content_type_for(path: str) -> str:
    return content_type_for_path(path)


def _is_api_request(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _resolve_static_path(path: str) -> str:
    if path in ("/", ""):
        return "web/index.html"
    return "web/" + path.lstrip("/")


def _validate_cf_jwt(token: str, team_domain: str) -> bool:
    if os.environ.get("SKIP_JWT_VALIDATION"):
        return True
    try:
        import jwt
        import requests

        certs_url = f"https://{team_domain}.cloudflareaccess.com/cdn-cgi/access/certs"
        now = time.monotonic()
        cached = _jwks_cache.get(team_domain)
        if cached and (now - cached[0]) < _JWKS_TTL:
            jwks = cached[1]
        else:
            resp = requests.get(certs_url, timeout=5)
            resp.raise_for_status()
            jwks = resp.json()
            _jwks_cache[team_domain] = (now, jwks)

        header = jwt.get_unverified_header(token)
        kid = header.get("kid")

        for key_data in jwks.get("keys", []):
            if key_data.get("kid") == kid:
                public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
                jwt.decode(
                    token,
                    public_key,
                    algorithms=["RS256"],
                    audience=f"https://{team_domain}.cloudflareaccess.com",
                )
                return True
        return False
    except Exception:
        logger.exception("JWT validation failed")
        return False


def _make_response(
    status: int,
    body: str,
    content_type: str = "text/plain",
    headers: dict | None = None,
    is_base64: bool = False,
) -> dict:
    h = {"content-type": content_type, "cache-control": "no-store"}
    if headers:
        h.update(headers)
    resp = {"statusCode": status, "headers": h, "body": body}
    if is_base64:
        resp["isBase64Encoded"] = True
    return resp


def handler(event: dict, context=None) -> dict:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/")
    query_params = event.get("queryStringParameters") or {}
    headers = event.get("headers") or {}
    body = event.get("body")

    if not os.environ.get("SKIP_JWT_VALIDATION"):
        token = headers.get("cf-access-jwt-assertion", "")
        team_domain = os.environ.get("CF_TEAM_DOMAIN", "softmax")
        if not token or not _validate_cf_jwt(token, team_domain):
            return _make_response(403, "forbidden")

    repo = Repository.create()

    if _is_api_request(path):
        return _handle_api_request(repo, method, path, query_params, headers, body)
    return _handle_static_request(repo, path)


def _handle_static_request(repo: Repository, path: str) -> dict:
    store = FileStore(repo)
    web_file = lookup_static_file(store, path)
    if web_file is None:
        return _make_response(404, "not found")
    if web_file.is_base64:
        return _make_response(200, web_file.content, content_type=web_file.content_type, is_base64=True)
    return _make_response(200, web_file.content, content_type=web_file.content_type)


def _handle_api_request(
    repo: Repository,
    method: str,
    path: str,
    query_params: dict,
    headers: dict,
    body: str | None,
) -> dict:
    request_id = str(uuid4())

    channel = repo.get_channel_by_name("io:web:request")
    if not channel:
        return _make_response(503, "web request channel not configured")

    handlers = repo.match_handlers_by_channel(channel.id)
    if not handlers:
        return _make_response(503, "no handler for web requests")

    target_handler = handlers[0]
    process = repo.get_process(target_handler.process)
    if not process:
        return _make_response(503, "handler process not found")

    filtered_headers = {k: v for k, v in headers.items() if not k.startswith("cf-")}

    msg = ChannelMessage(
        channel=channel.id,
        payload={
            "request_id": request_id,
            "method": method,
            "path": path,
            "query": query_params,
            "headers": filtered_headers,
            "body": body,
        },
    )
    repo.append_channel_message(msg)

    executor_fn = os.environ.get("EXECUTOR_FUNCTION_NAME", "")
    lambda_client = boto3.client("lambda")

    try:
        response = lambda_client.invoke(
            FunctionName=executor_fn,
            InvocationType="RequestResponse",
            Payload=json.dumps(
                {
                    "process_id": str(process.id),
                    "web_request_id": request_id,
                    "web_request": {
                        "method": method,
                        "path": path,
                        "query": query_params,
                        "headers": filtered_headers,
                        "body": body,
                    },
                }
            ),
        )

        resp_payload = json.loads(response["Payload"].read())
        web_response = resp_payload.get("web_response")

        if not web_response:
            return _make_response(204, "")

        return _make_response(
            web_response.get("status", 200),
            web_response.get("body", ""),
            content_type=web_response.get("headers", {}).get("content-type", "application/json"),
            headers=web_response.get("headers"),
        )
    except Exception:
        logger.exception("Executor invocation failed")
        return _make_response(502, "executor error")
