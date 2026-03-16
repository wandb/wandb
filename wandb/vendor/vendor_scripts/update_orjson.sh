#!/usr/bin/env bash
set -euo pipefail

# This script provides a convenient way to update the orjson version in the vendor subtree.
# It does so by pulling the latest release tag from the orjson upstream,
# then reapplying the local changes from the wandb_changes.patch file.

info(){ printf '\e[34m[INFO]\e[0m %s\n' "$*"; }
warn(){ printf '\e[33m[WARN]\e[0m %s\n' "$*"; }
err(){ printf '\e[31m[ERROR]\e[0m %s\n' "$*"; exit 1; }

# cd into git root
cd $(git rev-parse --show-toplevel)

# Verify clean working tree
if [ ! -d .git ]; then err "Run from git repo root."; fi
if [ -n "$(git status --porcelain)" ]; then
  git status --porcelain
  err "Working tree not clean. Commit or stash changes and re-run."
fi

# Add orjson-upstream as a remote
UPSTREAM_URL="https://github.com/ijl/orjson.git"
REMOTE_NAME="orjson-upstream"
if git remote get-url "$REMOTE_NAME" >/dev/null 2>&1; then
  info "Remote $REMOTE_NAME already present."
else
  info "Adding remote $REMOTE_NAME -> $UPSTREAM_URL"
  git remote add "$REMOTE_NAME" "$UPSTREAM_URL"
fi

# Get the latest release tag from orjson upstream
git fetch --tags "$REMOTE_NAME"

# Get latest tag name (not the whole ls-remote line)
LATEST_TAG="$(git ls-remote --tags --refs "$REMOTE_NAME" \
  | awk '{print $2}' \
  | sed 's#refs/tags/##' \
  | grep -v '{}' \
  | sort -V \
  | tail -n1 || true)"
FETCH_REF="$LATEST_TAG"

WANDB_VENDOR_PATH="wandb/vendor/wandb_orjson"
# ensure prefix parent directory exists
mkdir -p "$(dirname "$WANDB_VENDOR_PATH")"

# remove existing tracked files under prefix (if tracked) so commit will replace them cleanly
if git ls-files --error-unmatch "$WANDB_VENDOR_PATH" >/dev/null 2>&1; then
  info "Removing tracked files under $WANDB_VENDOR_PATH to prepare replacement..."
  git rm -r --ignore-unmatch "$WANDB_VENDOR_PATH"
  git commit -m "Remove existing vendored $WANDB_VENDOR_PATH to prepare vendor refresh" || true
else
  # untracked: remove directory from working tree to avoid conflict with archive extraction
  if [ -d "$WANDB_VENDOR_PATH" ]; then
    info "Removing untracked directory $WANDB_VENDOR_PATH to prepare replacement..."
    rm -rf "$WANDB_VENDOR_PATH"
  fi
fi


if git show-ref --verify --quiet "refs/tags/${FETCH_REF}"; then
  ARCHIVE_REF="${FETCH_REF}"
else
  ARCHIVE_REF="${REMOTE_NAME}/${FETCH_REF}"
fi
info "Running: git archive ${ARCHIVE_REF} --prefix=${WANDB_VENDOR_PATH}/ | tar -x"
git archive "${ARCHIVE_REF}" --prefix="${WANDB_VENDOR_PATH}/" | tar -x

git add --all "$WANDB_VENDOR_PATH"
git commit -m "Vendor orjson ${FETCH_REF} (snapshot, no upstream history)"

info "Snapshot committed."

PATCH_PATH="wandb/vendor/vendor_scripts/wandb_changes.patch"
info "Applying patch: $PATCH_PATH"
HEAD_LINE="$(head -n1 "$PATCH_PATH" || true)"
if [[ "$HEAD_LINE" =~ ^From\  ]]; then
  info "Detected mbox-style patch; using git am --3way"
  if git am --3way "$PATCH_PATH"; then
    info "git am applied successfully"
  else
    warn "git am failed; resolve conflicts manually (git am --abort to revert)"
    exit 1
  fi
else
  info "Applying plain patch with git apply --index"
  if git apply --index "$PATCH_PATH"; then
    git commit -m "Apply vendoring patch: wandb changes to orjson"
    info "Patch applied & committed."
  else
    warn "git apply --index failed; attempting plain git apply for diagnostics"
    git apply "$PATCH_PATH" || err "git apply failed; inspect patch and apply manually"
    err "Patch applied without index. Please git add & commit manually."
  fi
fi
