#!/usr/bin/env bash
set -euo pipefail

IMAGE_URI="${1:?image URI is required}"
AWS_REGION_VALUE="${2:?AWS region is required}"
PARAMETER_PREFIX="${3:-/product-identity/production}"

export AWS_REGION="$AWS_REGION_VALUE"
export AWS_DEFAULT_REGION="$AWS_REGION_VALUE"
export AWS_USE_DUALSTACK_ENDPOINT=true

APP_DIR=/opt/product-identity
RUNTIME_DIR=/etc/product-identity
ENV_FILE="$RUNTIME_DIR/runtime.env"
KEYS_FILE="$RUNTIME_DIR/runtime.keys"
CONTAINER_NAME=product-identity-api

install -d -m 0755 "$APP_DIR"
install -d -m 0750 "$RUNTIME_DIR"

parameters_json="$(mktemp)"
cleanup() {
  rm -f "$parameters_json"
}
trap cleanup EXIT

aws ssm get-parameters-by-path   --path "$PARAMETER_PREFIX"   --recursive   --with-decryption   --output json > "$parameters_json"

python3 - "$parameters_json" "$ENV_FILE" "$KEYS_FILE" <<'PY'
import json
import re
import shlex
import sys
from pathlib import Path

source, env_path, keys_path = sys.argv[1:4]
payload = json.loads(Path(source).read_text(encoding="utf-8"))
parameters = payload.get("Parameters", [])

entries: dict[str, str] = {}
for parameter in parameters:
    name = str(parameter.get("Name", ""))
    value = str(parameter.get("Value", ""))
    leaf = name.rsplit("/", 1)[-1].strip().upper().replace("-", "_")
    if not leaf:
        continue
    key = leaf if leaf.startswith("PRODUCT_IDENTITY_") else f"PRODUCT_IDENTITY_{leaf}"
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
        raise SystemExit(f"Unsupported runtime parameter name: {name}")
    entries[key] = value

entries.setdefault("PRODUCT_IDENTITY_ENVIRONMENT", "production")
entries.setdefault("PRODUCT_IDENTITY_RUNTIME", "server")

required = ["PRODUCT_IDENTITY_DATABASE_URL"]
missing = [key for key in required if not entries.get(key)]
if missing:
    raise SystemExit(
        "Missing required SSM runtime parameters: " + ", ".join(missing)
    )

Path(env_path).write_text(
    "".join(f"export {key}={shlex.quote(value)}\n" for key, value in sorted(entries.items())),
    encoding="utf-8",
)
Path(keys_path).write_text(
    "".join(f"{key}\n" for key in sorted(entries)),
    encoding="utf-8",
)
PY

chmod 0600 "$ENV_FILE" "$KEYS_FILE"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

env_args=()
while IFS= read -r key; do
  [[ -n "$key" ]] && env_args+=("--env" "$key")
done < "$KEYS_FILE"

echo "Pulling Product Identity image..."
docker pull "$IMAGE_URI" >/dev/null

echo "Applying database migrations..."
docker run --rm   --network host   "${env_args[@]}"   "$IMAGE_URI"   alembic upgrade head

previous_image="$(docker inspect --format '{{.Config.Image}}' "$CONTAINER_NAME" 2>/dev/null || true)"

if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
  docker stop "$CONTAINER_NAME" >/dev/null || true
  docker rm "$CONTAINER_NAME" >/dev/null || true
fi

echo "Starting Product Identity API..."
docker run -d   --name "$CONTAINER_NAME"   --restart unless-stopped   --network host   "${env_args[@]}"   "$IMAGE_URI" >/dev/null

ready=false
for _ in $(seq 1 60); do
  if body="$(python3 - <<'PY' 2>/dev/null
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8000/ready", timeout=3) as response:
    print(response.read().decode("utf-8"))
PY
  )"; then
    if python3 - "$body" <<'PY' >/dev/null 2>&1
import json
import sys

payload = json.loads(sys.argv[1])
raise SystemExit(
    0
    if payload.get("status") == "ok" and payload.get("database_configured") is True
    else 1
)
PY
    then
      ready=true
      break
    fi
  fi
  sleep 2
done

if [[ "$ready" != "true" ]]; then
  echo "Product Identity readiness failed. Container logs remain on the EC2 host." >&2
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

  if [[ -n "$previous_image" && "$previous_image" != "$IMAGE_URI" ]]; then
    echo "Attempting to restore the previous application image..." >&2
    docker run -d       --name "$CONTAINER_NAME"       --restart unless-stopped       --network host       "${env_args[@]}"       "$previous_image" >/dev/null || true
  fi
  exit 1
fi

echo "Product Identity API is database-ready."
docker image inspect "$IMAGE_URI" --format 'deployed_image={{index .RepoDigests 0}}' 2>/dev/null || true
