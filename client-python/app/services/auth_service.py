from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.core.config import get_server_base_url


class LoginError(Exception):
    pass


def _post_request(path: str, payload: dict) -> dict:
    base_url = get_server_base_url()
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8")
    except urllib.error.URLError as error:
        raise LoginError(f"无法连接服务器：{error.reason}") from error

    try:
        data = json.loads(body)
    except json.JSONDecodeError as error:
        raise LoginError("服务器返回了无法识别的数据") from error

    if data.get("code") != 0:
        raise LoginError(data.get("message", "登录失败"))
    return data.get("data", {})


def login(username: str, password: str) -> dict:
    return _post_request(
        "/api/auth/login",
        {"username": username, "password": password},
    )


def register(
    username: str,
    nickname: str,
    phone: str,
    email: str,
    password: str,
) -> dict:
    return _post_request(
        "/api/auth/register",
        {
            "username": username,
            "nickname": nickname,
            "phone": phone,
            "email": email,
            "password": password,
        },
    )


def get_profile(username: str) -> dict:
    return _post_request(
        "/api/auth/profile",
        {"username": username},
    )


def update_profile(
    username: str,
    nickname: str,
    phone: str,
    email: str,
) -> dict:
    return _post_request(
        "/api/auth/profile/update",
        {
            "username": username,
            "nickname": nickname,
            "phone": phone,
            "email": email,
        },
    )
