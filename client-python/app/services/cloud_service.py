from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from app.core.config import get_server_base_url


class CloudApiError(Exception):
    pass


def _base() -> str:
    return get_server_base_url()


def _json_request(path: str, payload: dict | None = None) -> dict:
    base = _base()
    if payload is None:
        request = urllib.request.Request(f"{base}{path}", method="GET")
    else:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{base}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            text = response.read().decode("utf-8")
    except urllib.error.URLError as error:
        raise CloudApiError(f"无法连接服务器：{error.reason}") from error
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise CloudApiError("服务器返回了无法识别的数据") from error
    if data.get("code") != 0:
        raise CloudApiError(data.get("message", "请求失败"))
    return data.get("data", {})


def list_cloud_models(owner: str) -> list[dict]:
    path = f"/api/cloud/models?owner={urllib.parse.quote(owner)}"
    data = _json_request(path)
    return data if isinstance(data, list) else []


def upload_cloud_model(owner: str, kind: str, name: str, file_path: str | Path) -> dict:
    base = _base()
    path = Path(file_path).resolve()
    boundary = uuid.uuid4().hex
    filename = path.name

    fields = {"owner": owner, "kind": kind, "name": name}
    body = bytearray()
    for key, value in fields.items():
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")
    body += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    body += path.read_bytes()
    body += f"\r\n--{boundary}--\r\n".encode("utf-8")

    request = urllib.request.Request(
        f"{base}/api/cloud/models",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            text = response.read().decode("utf-8")
    except urllib.error.URLError as error:
        raise CloudApiError(f"上传失败：{error.reason}") from error
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise CloudApiError("服务器返回了无法识别的数据") from error
    if data.get("code") != 0:
        raise CloudApiError(data.get("message", "上传失败"))
    return data.get("data", {})


def download_cloud_model(model_id: int, owner: str) -> bytes:
    base = _base()
    path = f"/api/cloud/models/{model_id}/download?owner={urllib.parse.quote(owner)}"
    try:
        with urllib.request.urlopen(f"{base}{path}", timeout=120) as response:
            return response.read()
    except urllib.error.URLError as error:
        raise CloudApiError(f"下载失败：{error.reason}") from error


def delete_cloud_model(model_id: int, owner: str) -> dict:
    return _json_request("/api/cloud/models/delete", {"id": model_id, "owner": owner})


def list_cloud_presets(owner: str, kind: str) -> list[dict]:
    path = f"/api/cloud/presets?owner={urllib.parse.quote(owner)}&kind={urllib.parse.quote(kind)}"
    data = _json_request(path)
    return data if isinstance(data, list) else []


def upload_cloud_preset(owner: str, kind: str, name: str, content: str) -> dict:
    return _json_request(
        "/api/cloud/presets",
        {"owner": owner, "kind": kind, "name": name, "content": content},
    )


def delete_cloud_preset(preset_id: int, owner: str) -> dict:
    return _json_request("/api/cloud/presets/delete", {"id": preset_id, "owner": owner})
