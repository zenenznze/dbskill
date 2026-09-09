#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_PATH="$ROOT_DIR/skills/dbs-reset/scripts/codex_rate_limit_reset.py"

python3 - "$SCRIPT_PATH" <<'PY'
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

script_path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("dbs_reset", script_path)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

usage = {
    "rate_limit": {
        "primary_window": {"used_percent": 42, "reset_at": "2030-01-02T00:00:00Z"},
        "secondary_window": {"used_percent": 75, "reset_at": "2030-01-08T00:00:00Z"},
    },
    "rate_limit_reset_credits": {"available_count": 7, "applicable_available_count": 2},
}
credits = {
    "available_count": 7,
    "credits": [
        {
            "id": "fixture-credit-later-abcdef12",
            "status": "available",
            "reset_type": "codex_rate_limits",
            "expires_at": "2030-01-03T00:00:00Z",
        },
        {
            "id": "fixture-credit-earlier-12345678",
            "status": "available",
            "reset_type": "codex_rate_limits",
            "expires_at": "2030-01-02T00:00:00Z",
        },
    ],
}

auth = module.Auth("dummy-bearer", "dummy-account")
with patch.object(module, "request_json", side_effect=[usage, credits]):
    result = module.build_check(auth, module.display_zone("UTC"), 1)

assert result["available_count"] == 7, result
assert result["detail_count"] == 2, result
assert result["credits"][0]["expires_at"] == "2030-01-02 00:00:00 UTC", result
assert result["usage"]["applicable_available_count"] == 2, result
rendered = json.dumps(result, ensure_ascii=False)
assert "dummy-bearer" not in rendered
assert "dummy-account" not in rendered
assert "fixture-credit-earlier-12345678" not in rendered
assert "12345678" not in rendered

with tempfile.TemporaryDirectory() as directory:
    auth_path = Path(directory) / "auth.json"
    auth_path.write_text(
        json.dumps({"tokens": {"access_token": "dummy-access", "account_id": "dummy-account"}}),
        encoding="utf-8",
    )
    loaded = module.load_auth(auth_path)
    assert loaded.bearer == "dummy-access"
    assert loaded.account == "dummy-account"

assert module.SUCCESS_CODES == {"reset", "already_redeemed"}
print("dbs-reset script unit checks passed")
PY
