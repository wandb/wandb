#!/usr/bin/env bash
# Bootstrap a wandb development environment (see wandb/CONTRIBUTING.md).
#
# Usage: cd /path/to/wandb && setup-wandb.sh [OPTIONS]
#
# Options:
#   --check       Verify prerequisites without installing
#   -y, --yes     Non-interactive (use GIT_USER_NAME / GIT_USER_EMAIL env vars)
#   --skip-go     Skip Go installation
#   --skip-rust   Skip Rust installation
#
# Native Windows: use setup-wandb.ps1 instead (or run this script from Git Bash).

set -euo pipefail

readonly GO_MIN_VERSION="1.26.5"
readonly PYTHON_VERSION="3.13"
readonly UV_INSTALL_URL="https://docs.astral.sh/uv/getting-started/installation/"

CHECK_ONLY=false
NONINTERACTIVE=false
SKIP_GO=false
SKIP_RUST=false

log_info() { printf 'INFO: %s\n' "$*"; }
log_warn() { printf 'WARN: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

have_cmd() { command -v "$1" >/dev/null 2>&1; }

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --check) CHECK_ONLY=true ;;
      -y|--yes) NONINTERACTIVE=true ;;
      --skip-go) SKIP_GO=true ;;
      --skip-rust) SKIP_RUST=true ;;
      -h|--help)
        sed -n '2,12p' "$0" | sed 's/^# //' | sed 's/^#//'
        exit 0
        ;;
      *)
        die "unknown option: $1 (try --help)"
        ;;
    esac
    shift
  done
}

ensure_repo_root() {
  if [[ ! -f pyproject.toml ]] || [[ ! -f core/go.mod ]]; then
    die "run this script from the wandb repository root (expected pyproject.toml and core/go.mod)"
  fi
}

version_ge() {
  local want="$1"
  local current="$2"
  [[ "$(printf '%s\n' "$want" "$current" | sort -V | head -n1)" == "$want" ]]
}

go_version() {
  if ! have_cmd go; then
    return 1
  fi
  go version | awk '{print $3}' | sed 's/^go//'
}

ensure_path_local_bin() {
  export PATH="${HOME}/.local/bin:${PATH}"
}

activate_venv() {
  if [[ -f .venv/Scripts/activate ]]; then
    # shellcheck source=/dev/null
    source .venv/Scripts/activate
  elif [[ -f .venv/bin/activate ]]; then
    # shellcheck source=/dev/null
    source .venv/bin/activate
  else
    die ".venv exists but no activate script was found"
  fi
}

ensure_git_identity() {
  local name email

  name="$(git config user.name 2>/dev/null || true)"
  email="$(git config user.email 2>/dev/null || true)"

  if [[ -n "$name" && -n "$email" ]]; then
    log_info "git identity: $name <$email>"
    return 0
  fi

  if $CHECK_ONLY; then
    [[ -n "$name" ]] || log_warn "git user.name is not set"
    [[ -n "$email" ]] || log_warn "git user.email is not set"
    return 0
  fi

  if [[ -z "$name" ]]; then
    if [[ -n "${GIT_USER_NAME:-}" ]]; then
      name="$GIT_USER_NAME"
    elif $NONINTERACTIVE; then
      die "git user.name is not set; export GIT_USER_NAME or run without -y"
    else
      read -r -p "git user.name: " name
      [[ -n "$name" ]] || die "git user.name is required"
    fi
    git config --local user.name "$name"
  fi

  if [[ -z "$email" ]]; then
    if [[ -n "${GIT_USER_EMAIL:-}" ]]; then
      email="$GIT_USER_EMAIL"
    elif $NONINTERACTIVE; then
      die "git user.email is not set; export GIT_USER_EMAIL or run without -y"
    else
      read -r -p "git user.email: " email
      [[ -n "$email" ]] || die "git user.email is required"
    fi
    git config --local user.email "$email"
  fi

  log_info "configured local git identity: $name <$email>"
}

install_uv_brew() {
  if ! have_cmd brew; then
    return 1
  fi
  log_info "installing uv via Homebrew"
  brew install uv
}

install_uv_standalone() {
  if ! have_cmd curl; then
    return 1
  fi
  log_info "installing uv via standalone installer"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ensure_path_local_bin
}

install_uv_pipx() {
  if ! have_cmd pipx; then
    return 1
  fi
  log_info "installing uv via pipx"
  pipx install uv
  ensure_path_local_bin
}

install_uv_pip() {
  local python_cmd=""
  if have_cmd python3; then
    python_cmd=python3
  elif have_cmd python; then
    python_cmd=python
  else
    return 1
  fi
  log_warn "installing uv via pip (isolated install via pipx or standalone is preferred)"
  "$python_cmd" -m pip install uv
  ensure_path_local_bin
}

ensure_uv() {
  ensure_path_local_bin
  if have_cmd uv; then
    log_info "uv: $(uv --version)"
    return 0
  fi

  if $CHECK_ONLY; then
    log_warn "uv is not installed"
    return 0
  fi

  install_uv_brew \
    || install_uv_standalone \
    || install_uv_pipx \
    || install_uv_pip \
    || die "could not install uv; see $UV_INSTALL_URL"

  if ! have_cmd uv; then
    die "uv install finished but uv is not on PATH; see $UV_INSTALL_URL"
  fi
  log_info "uv: $(uv --version)"
}

go_linux_arch() {
  local machine
  machine="$(uname -m)"
  case "$machine" in
    x86_64|amd64) echo amd64 ;;
    aarch64|arm64) echo arm64 ;;
    *)
      die "unsupported Linux architecture for Go install: $machine"
      ;;
  esac
}

install_go_brew() {
  if ! have_cmd brew; then
    return 1
  fi
  log_info "installing Go via Homebrew (go@1.26)"
  brew install go@1.26
  local brew_prefix
  brew_prefix="$(brew --prefix go@1.26 2>/dev/null || brew --prefix go)"
  export PATH="${brew_prefix}/bin:${PATH}"
}

install_go_tarball() {
  local os_name arch tarball dest
  os_name="$(uname -s)"
  dest="${HOME}/.local"

  case "$os_name" in
    Linux)
      arch="$(go_linux_arch)"
      tarball="go${GO_MIN_VERSION}.linux-${arch}.tar.gz"
      ;;
    Darwin)
      arch="$(uname -m)"
      case "$arch" in
        x86_64) arch=amd64 ;;
        arm64) arch=arm64 ;;
        *) die "unsupported macOS architecture for Go install: $arch" ;;
      esac
      tarball="go${GO_MIN_VERSION}.darwin-${arch}.tar.gz"
      ;;
    *)
      return 1
      ;;
  esac

  if ! have_cmd curl; then
    return 1
  fi

  log_info "installing Go ${GO_MIN_VERSION} to ${dest}/go"
  local tmp
  tmp="$(mktemp -d)"
  curl -fsSL "https://go.dev/dl/${tarball}" -o "${tmp}/${tarball}"
  rm -rf "${dest}/go"
  tar -C "$dest" -xzf "${tmp}/${tarball}"
  rm -rf "$tmp"
  export PATH="${dest}/go/bin:${PATH}"
}

ensure_go() {
  if $SKIP_GO; then
    log_info "skipping Go setup (--skip-go)"
    return 0
  fi

  local current=""
  if have_cmd go; then
    current="$(go_version)"
    if version_ge "$GO_MIN_VERSION" "$current"; then
      log_info "go: $(go version)"
      return 0
    fi
    log_warn "go ${current} is older than required ${GO_MIN_VERSION}"
  elif $CHECK_ONLY; then
    log_warn "go is not installed (need >= ${GO_MIN_VERSION})"
    return 0
  fi

  if $CHECK_ONLY; then
    return 0
  fi

  install_go_brew || install_go_tarball || die "could not install Go; see https://go.dev/doc/install"

  current="$(go_version)"
  if ! version_ge "$GO_MIN_VERSION" "$current"; then
    die "go ${current} is still older than required ${GO_MIN_VERSION}"
  fi
  log_info "go: $(go version)"
}

source_cargo_env() {
  if [[ -f "${HOME}/.cargo/env" ]]; then
    # shellcheck source=/dev/null
    source "${HOME}/.cargo/env"
  fi
}

install_rustup() {
  if ! have_cmd curl; then
    return 1
  fi
  log_info "installing Rust via rustup"
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  source_cargo_env
}

ensure_rust() {
  source_cargo_env

  if have_cmd rustc; then
    log_info "rustc: $(rustc --version)"
    return 0
  fi

  if $CHECK_ONLY; then
    log_warn "rustc is not installed"
    return 0
  fi

  if $SKIP_RUST; then
    log_info "skipping Rust setup (--skip-rust)"
    return 0
  fi

  install_rustup || die "could not install Rust; see https://www.rust-lang.org/tools/install"
  if ! have_cmd rustc; then
    die "rustup install finished but rustc is not on PATH"
  fi
  log_info "rustc: $(rustc --version)"
}

ensure_envrc() {
  local line='source .venv/bin/activate'

  if [[ -f .envrc ]] && grep -Fxq "$line" .envrc; then
    log_info ".envrc already contains venv activation"
  elif [[ -f .envrc ]]; then
    printf '%s\n' "$line" >> .envrc
    log_info "appended venv activation to .envrc"
  else
    printf '%s\n' "$line" > .envrc
    log_info "wrote .envrc"
  fi
  log_info "run direnv allow if you use direnv"
}

setup_python_env() {
  if $CHECK_ONLY; then
    if [[ -d .venv ]]; then
      log_info ".venv exists"
    else
      log_warn ".venv does not exist"
    fi
    return 0
  fi

  log_info "installing Python ${PYTHON_VERSION}"
  uv python install "${PYTHON_VERSION}"

  if [[ -d .venv ]]; then
    log_warn ".venv already exists; not creating it"
  else
    uv venv
  fi

  activate_venv

  log_info "installing wandb (editable) and dev dependencies"
  uv pip install --reinstall --refresh-package wandb -e .
  uv pip install nox
  uv tool install prek
  prek install
  uv pip install -r requirements/requirements_dev.txt

  ensure_envrc
}

print_summary() {
  log_info "setup complete"
  if have_cmd uv; then
    log_info "  $(uv --version)"
  fi
  if have_cmd go; then
    log_info "  $(go version)"
  fi
  if have_cmd rustc; then
    log_info "  $(rustc --version)"
  fi
  if have_cmd python; then
    log_info "  $(python --version)"
  fi
  if have_cmd direnv; then
    log_info "  run: direnv allow"
  fi
}

main() {
  parse_args "$@"
  ensure_repo_root
  ensure_git_identity
  ensure_uv
  ensure_go
  ensure_rust
  setup_python_env
  if ! $CHECK_ONLY; then
    print_summary
  else
    log_info "check complete (--check; no changes made)"
  fi
}

main "$@"
