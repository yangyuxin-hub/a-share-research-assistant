"""
ChatGPT OAuth 2.0 PKCE 认证模块。

复用 openai/codex 官方 CLI 的认证参数：
  CLIENT_ID     = "app_EMoamEEZ73f0CkXaXp7hrann"
  AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
  TOKEN_URL     = "https://auth.openai.com/oauth/token"
  REDIRECT_URI  = "http://localhost:1455/auth/callback"

完整流程：
1. 生成 PKCE code_verifier + code_challenge (S256)
2. 打开浏览器跳转授权页
3. 本地 HTTP server 监听 localhost:1455 等待回调
4. 用授权码换取 access_token / refresh_token
5. 持久化到 token_path；自动刷新过期 token
"""

import base64
import hashlib
import json
import logging
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Event, Thread
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

logger = logging.getLogger(__name__)

# ── OAuth 常量（来自 openai/codex 官方 CLI）────────────────────────────────
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
REDIRECT_URI = "http://localhost:1455/auth/callback"
SCOPE = "openid profile email offline_access"
CALLBACK_PORT = 1455

# 提前 5 分钟刷新，避免在请求中途过期
_REFRESH_MARGIN = 300


# ── PKCE ────────────────────────────────────────────────────────────────────

def _generate_pkce() -> tuple[str, str]:
    """返回 (code_verifier, code_challenge_S256)"""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _build_auth_url(code_challenge: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


# ── Token 操作 ───────────────────────────────────────────────────────────────

def _exchange_code(code: str, verifier: str) -> dict:
    """用授权码换取 access_token + refresh_token。"""
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": int(time.time()) + int(data["expires_in"]),
    }


def _do_refresh(refresh_tok: str) -> dict:
    """用 refresh_token 换新 access_token。"""
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_tok,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": int(time.time()) + int(data["expires_in"]),
    }


def _extract_account_id(access_token: str) -> str:
    """从 JWT payload 中提取 chatgpt_account_id。"""
    try:
        parts = access_token.split(".")
        if len(parts) != 3:
            return ""
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        # JWT claim 路径：https://api.openai.com/auth.account_id
        return payload.get("https://api.openai.com/auth", {}).get("account_id", "")
    except Exception:
        return ""


# ── 持久化 ───────────────────────────────────────────────────────────────────

def load_tokens(path: str) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_tokens(path: str, tokens: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(tokens, indent=2, ensure_ascii=False), encoding="utf-8")


# ── OAuth 浏览器流程 ──────────────────────────────────────────────────────────

def _run_oauth_flow(token_path: str) -> dict:
    """
    完整的浏览器 OAuth PKCE 流程。
    打开浏览器 → 等待回调 → 换取 token → 保存 → 返回带 account_id 的 token dict。
    """
    verifier, challenge = _generate_pkce()
    state = secrets.token_hex(16)
    auth_url = _build_auth_url(challenge, state)

    code_event = Event()
    received: dict = {}

    class _CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            qs = parse_qs(urlparse(self.path).query)
            if qs.get("state", [""])[0] == state and qs.get("code"):
                received["code"] = qs["code"][0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h2>Authorization successful! "
                    b"You can close this tab.</h2></body></html>"
                )
                code_event.set()
            else:
                self.send_response(400)
                self.end_headers()

        def log_message(self, fmt, *args):  # 静音访问日志
            pass

    server = HTTPServer(("localhost", CALLBACK_PORT), _CallbackHandler)
    Thread(target=server.handle_request, daemon=True).start()

    print(f"\n正在打开浏览器进行 ChatGPT 授权...")
    print(f"如果浏览器未自动打开，请手动访问：\n{auth_url}\n")
    webbrowser.open(auth_url)

    if not code_event.wait(timeout=120):
        server.server_close()
        raise TimeoutError("OAuth 授权等待超时（120 秒），请重试。")

    server.server_close()

    tokens = _exchange_code(received["code"], verifier)
    tokens["account_id"] = _extract_account_id(tokens["access_token"])
    save_tokens(token_path, tokens)
    print("授权成功，token 已保存。\n")
    return tokens


# ── 公开入口 ─────────────────────────────────────────────────────────────────

def ensure_valid_token(token_path: str) -> dict:
    """
    返回有效的 token 信息 dict：
        {
          "access_token": "...",
          "refresh_token": "...",
          "expires_at": 1234567890,
          "account_id": "..."
        }

    - token 不存在 → 触发浏览器授权流程
    - token 即将过期 → 自动刷新
    - 刷新失败 → 重新走授权流程
    """
    tokens = load_tokens(token_path)

    if tokens and tokens.get("expires_at", 0) > time.time() + _REFRESH_MARGIN:
        # 还有效，补全 account_id（首次写入可能没有）
        if not tokens.get("account_id"):
            tokens["account_id"] = _extract_account_id(tokens["access_token"])
        return tokens

    if tokens and tokens.get("refresh_token"):
        try:
            logger.info("ChatGPT token 即将过期，正在刷新...")
            refreshed = _do_refresh(tokens["refresh_token"])
            refreshed["account_id"] = _extract_account_id(refreshed["access_token"])
            save_tokens(token_path, refreshed)
            logger.info("token 刷新成功。")
            return refreshed
        except Exception as e:
            logger.warning(f"token 刷新失败（{e}），将重新授权。")

    return _run_oauth_flow(token_path)
