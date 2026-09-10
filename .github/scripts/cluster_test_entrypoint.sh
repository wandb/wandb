#!/usr/bin/env bash
set -euo pipefail

mkdir -p /workspace/source /workspace/results
cd /workspace/source
collect() {
  local status=$?
  trap - EXIT
  for report in test-results coverage.xml coverage.txt; do
    if [[ -e "$report" ]]; then
      cp -a "$report" /workspace/results/ || true
    fi
  done
  exit "$status"
}
trap collect EXIT

git init
git remote add origin https://github.com/wandb/wandb.git
git fetch --depth=1 origin "$SOURCE_COMMIT"
git checkout --detach FETCH_HEAD
[[ $(git rev-parse HEAD) == "$SOURCE_COMMIT" ]]
git rev-parse HEAD > /workspace/results/source-commit.txt

shopt -s nullglob
wheels=(/workspace/input/wheel/*.whl)
[[ ${#wheels[@]} -eq 1 ]]
export WANDB_TEST_WHEEL="${wheels[0]}"
printf '%s  %s\n' "$WHEEL_SHA256" "$WANDB_TEST_WHEEL" | sha256sum --check

apt-get update
apt-get install --no-install-recommends -y ffmpeg libsndfile1
python -m pip install --upgrade pip nox uv==0.12.11
export UV_CACHE_DIR=/workspace/uv-cache
export WANDB_TEST_MAX_WORKERS=8

go_version=$(awk '$1 == "go" { print $2 }' core/go.mod)
curl --fail --location --retry 3 "https://go.dev/dl/go${go_version}.linux-amd64.tar.gz" --output /workspace/go.tar.gz
mkdir -p /workspace/toolchains
tar -xzf /workspace/go.tar.gz -C /workspace/toolchains
export PATH="/workspace/toolchains/go/bin:$PATH"
export GOTOOLCHAIN=local

if [[ "$NOX_SESSION" == experimental_tests ]]; then
  curl --fail --location --retry 3 https://dot.net/v1/dotnet-install.sh --output /workspace/dotnet-install.sh
  bash /workspace/dotnet-install.sh --channel 9.0
  export PATH="$HOME/.dotnet:$PATH"
fi

if [[ -n "${SERVER_IMAGE:-}" ]]; then
  python -m pip install click filelock pydantic requests
  python tools/local_wandb_server.py start --hostname localhost --base-port 8080 --fixture-port 9015
fi

python --version
go version
started=$SECONDS
status=0
nox -s "$NOX_SESSION" --python "$PYTHON_VERSION" --verbose || status=$?
printf 'Nox session: %s seconds, including package installation.\n' "$((SECONDS - started))" > /workspace/results/timing.txt
exit "$status"
