#!/usr/bin/env python3
"""Read Codex usage and banked reset credits without exposing auth material.

The ``check`` command is read-only. The ``consume`` command is the only path
that can call the upstream mutation endpoint, and it requires ``--confirm``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

USAGE_ENDPOINT = "https://chatgpt.com/backend-api/wham/usage"
CREDITS_ENDPOINT = "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits"
CONSUME_ENDPOINT = f"{CREDITS_ENDPOINT}/consume"
DEFAULT_TZ = "Asia/Shanghai"
SUCCESS_CODES = {"reset", "already_redeemed"}


class ResetError(Exception):
    """A user-safe error that must not contain secrets or raw responses."""

    def __init__(self, code: str, message: str, *, status: int | None = None, retry_after: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retry_after = retry_after


class Auth:
    def __init__(self, bearer: str, account: str):
        self.bearer = bearer
        self.account = account


def auth_path(cli_path: str | None) -> Path:
    if cli_path:
        return Path(cli_path).expanduser()
    root = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
    return Path(root).expanduser() / "auth.json"


def first_string(data: Any, paths: tuple[tuple[str, ...], ...]) -> str | None:
    for path in paths:
        value = data
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def load_auth(path: Path) -> Auth:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ResetError("missing_auth", f"Codex auth file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ResetError("invalid_auth_shape", "Codex auth file is not valid JSON.") from exc
    except OSError as exc:
        raise ResetError("auth_unreadable", f"Codex auth file cannot be read: {exc}") from exc

    if not isinstance(data, dict):
        raise ResetError("invalid_auth_shape", "Codex auth file did not contain a JSON object.")

    bearer = first_string(data, (("tokens", "access_token"), ("tokens", "accessToken"), ("access_token",), ("accessToken",)))
    account = first_string(
        data,
        (
            ("tokens", "account_id"),
            ("tokens", "accountId"),
            ("account_id",),
            ("accountId",),
            ("account", "id"),
        ),
    )
    if not bearer:
        raise ResetError("missing_access_token", "Codex auth has no access token.")
    if not account:
        raise ResetError("missing_account_id", "Codex auth has no account ID.")
    return Auth(bearer, account)


def headers(auth: Auth) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {auth.bearer}",
        "ChatGPT-Account-ID": auth.account,
        "Content-Type": "application/json",
        "Origin": "https://chatgpt.com",
        "Originator": "Codex Desktop",
        "OAI-Product-Sku": "CODEX",
        "User-Agent": "dbs-reset-readonly/1.0",
    }


def request_json(
    auth: Auth,
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    encoded = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=encoded, headers=headers(auth), method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        retry_after = exc.headers.get("Retry-After")
        raise ResetError(
            "http_error",
            f"Endpoint returned HTTP {exc.code}.",
            status=exc.code,
            retry_after=retry_after,
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", "network error")
        raise ResetError("network_error", f"Could not reach endpoint: {reason}") from exc
    except TimeoutError as exc:
        raise ResetError("timeout", "Endpoint request timed out.") from exc

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResetError("invalid_json", "Endpoint response was not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ResetError("invalid_json", "Endpoint response did not contain a JSON object.")
    return parsed


def pick(data: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in data:
            return data[name]
    return None


def parse_time(value: Any) -> dt.datetime | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        return dt.datetime.fromtimestamp(seconds, tz=dt.timezone.utc)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.isdigit():
            seconds = float(text) / 1000 if len(text) > 10 else float(text)
            return dt.datetime.fromtimestamp(seconds, tz=dt.timezone.utc)
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = dt.datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed.astimezone(dt.timezone.utc)
    return None


def display_zone(name: str) -> dt.tzinfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ResetError("invalid_timezone", f"Unknown timezone: {name}") from exc


def format_time(value: Any, zone: dt.tzinfo) -> str | None:
    parsed = parse_time(value)
    return parsed.astimezone(zone).strftime("%Y-%m-%d %H:%M:%S %Z") if parsed else None


def suffix(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value[-8:]
    return None


def normalize_credit(credit: Any, zone: dt.tzinfo) -> dict[str, Any] | None:
    if not isinstance(credit, dict):
        return None
    return {
        "status": pick(credit, "status", "state") or "unknown",
        "reset_type": pick(credit, "reset_type", "resetType") or "unknown",
        "granted_at": format_time(pick(credit, "granted_at", "grantedAt"), zone),
        "expires_at": format_time(pick(credit, "expires_at", "expiresAt"), zone),
    }


def usage_summary(data: dict[str, Any], zone: dt.tzinfo) -> dict[str, Any]:
    rate = data.get("rate_limit")
    if not isinstance(rate, dict):
        return {}
    result: dict[str, Any] = {}
    for label, names in (("primary_window", ("primary_window", "primaryWindow")), ("secondary_window", ("secondary_window", "secondaryWindow"))):
        window = pick(rate, *names)
        if isinstance(window, dict):
            result[label] = {
                "used_percent": pick(window, "used_percent", "usedPercent"),
                "reset_at": format_time(pick(window, "reset_at", "resetAt"), zone),
            }
    credits = data.get("rate_limit_reset_credits")
    if isinstance(credits, dict):
        result["available_count"] = pick(credits, "available_count", "availableCount")
        applicable = pick(credits, "applicable_available_count", "applicableAvailableCount")
        if applicable is not None:
            result["applicable_available_count"] = applicable
    return result


def build_check(auth: Auth, zone: dt.tzinfo, timeout: float) -> dict[str, Any]:
    usage = request_json(auth, USAGE_ENDPOINT, timeout=timeout)
    details = request_json(auth, CREDITS_ENDPOINT, timeout=timeout)
    raw_credits = details.get("credits")
    if not isinstance(raw_credits, list):
        raw_credits = []
    credits = [item for item in (normalize_credit(item, zone) for item in raw_credits) if item]
    credits.sort(key=lambda item: (item["expires_at"] is None, item["expires_at"] or ""))
    available_count = pick(details, "available_count", "availableCount")
    if not isinstance(available_count, int) or isinstance(available_count, bool):
        raise ResetError("invalid_json", "Reset credit response has no valid available_count.")
    return {
        "ok": True,
        "queried_at": dt.datetime.now(dt.timezone.utc).astimezone(zone).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "usage": usage_summary(usage, zone),
        "available_count": available_count,
        "detail_count": len(credits),
        "credits": credits,
    }


def available_credit_ids(details: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    raw = details.get("credits")
    if not isinstance(raw, list):
        return []
    result: list[tuple[str, dict[str, Any]]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        status = str(pick(item, "status", "state") or "").lower()
        credit_id = pick(item, "id")
        if status == "available" and isinstance(credit_id, str) and credit_id:
            result.append((credit_id, item))
    result.sort(key=lambda pair: (parse_time(pick(pair[1], "expires_at", "expiresAt")) is None, parse_time(pick(pair[1], "expires_at", "expiresAt")) or dt.datetime.max.replace(tzinfo=dt.timezone.utc), pair[0]))
    return result


def print_error(error: ResetError) -> int:
    print(f"错误 [{error.code}]：{error.message}", file=sys.stderr)
    if error.status in (401, 403):
        print("请重新登录本机官方 Codex；这不是“没有 reset credit”的证据。", file=sys.stderr)
    if error.retry_after:
        print(f"Retry-After：{error.retry_after}", file=sys.stderr)
    return 1


def human_check(result: dict[str, Any]) -> None:
    print(f"Codex reset 次数（available_count）：{result['available_count']}")
    usage = result.get("usage") or {}
    for label, title in (("primary_window", "5 小时窗口"), ("secondary_window", "weekly 窗口")):
        window = usage.get(label)
        if window:
            print(f"{title}：已使用 {window.get('used_percent', 'unknown')}%，窗口重置 {window.get('reset_at') or 'unknown'}")
    applicable = usage.get("applicable_available_count")
    if applicable is not None:
        print(f"当前窗口适用的 reset：{applicable}")
    if result["detail_count"] != result["available_count"]:
        print(f"详情行数：{result['detail_count']}（数量仍以 available_count 为准）")
    for index, credit in enumerate(result["credits"], 1):
        print(
            f"第 {index} 条详情：status={credit['status']}，type={credit['reset_type']}，"
            f"到期={credit['expires_at'] or 'unknown'}"
        )


def run_check(args: argparse.Namespace) -> int:
    try:
        auth = load_auth(auth_path(args.auth_file))
        zone = display_zone(args.timezone)
        result = build_check(auth, zone, args.timeout)
    except ResetError as error:
        return print_error(error)
    if args.human:
        human_check(result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_consume(args: argparse.Namespace) -> int:
    if not args.confirm and not args.dry_run:
        print("拒绝执行：consume 必须同时提供 --confirm；测试请使用 check 或 --dry-run。", file=sys.stderr)
        return 2
    try:
        auth = load_auth(auth_path(args.auth_file))
        zone = display_zone(args.timezone)
        check = build_check(auth, zone, args.timeout)
        available_count = check["available_count"]
        details = request_json(auth, CREDITS_ENDPOINT, timeout=args.timeout)
        candidates = available_credit_ids(details)
        if args.index < 1 or args.index > len(candidates):
            raise ResetError("credit_not_found", f"没有第 {args.index} 张可用详情；available_count={available_count}，可见详情={len(candidates)}。")
        credit_id, raw_credit = candidates[args.index - 1]
        key = args.idempotency_key or str(uuid.uuid4())
        preview = {
            "selected_index": args.index,
            "available_count": available_count,
            "expires_at": format_time(pick(raw_credit, "expires_at", "expiresAt"), zone),
            "idempotency_key": key,
        }
        if args.dry_run:
            print(json.dumps({"ok": True, "dry_run": True, **preview}, ensure_ascii=False, indent=2))
            return 0
        response = request_json(
            auth,
            CONSUME_ENDPOINT,
            method="POST",
            body={"redeem_request_id": key, "credit_id": credit_id},
            timeout=args.timeout,
        )
        code = pick(response, "code")
        result: dict[str, Any] = {
            "ok": code in SUCCESS_CODES,
            "code": code or "unknown",
            "windows_reset": pick(response, "windows_reset", "windowsReset"),
            "idempotency_key": key,
        }
        if code in SUCCESS_CODES:
            result["post_check"] = build_check(auth, zone, args.timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    except ResetError as error:
        return print_error(error)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Query Codex usage/reset credits; consume only with explicit confirmation.")
    parser.add_argument("--auth-file", help="Codex auth.json path; default follows CODEX_HOME or ~/.codex")
    parser.add_argument("--timezone", default=os.environ.get("DBS_RESET_TIMEZONE", DEFAULT_TZ))
    parser.add_argument("--timeout", type=float, default=20.0)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="read-only usage and reset-credit query")
    check.add_argument("--human", action="store_true", help="print a concise human-readable report")
    check.set_defaults(handler=run_check)

    consume = subparsers.add_parser("consume", help="consume one upstream reset credit")
    consume.add_argument("--index", type=int, default=1, help="1-based index among available credits sorted by expiry")
    consume.add_argument("--idempotency-key", help="reuse this key when retrying the same request")
    consume.add_argument("--confirm", action="store_true", help="explicitly authorize the upstream mutation")
    consume.add_argument("--dry-run", action="store_true", help="select and display a credit without calling POST")
    consume.set_defaults(handler=run_consume)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
