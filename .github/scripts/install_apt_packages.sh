#!/usr/bin/env bash
# Install apt packages from a directory of .deb files, downloading them first
# if the directory is empty so that it can be cached between runs.
#
# GitHub's runners download from azure.archive.ubuntu.com, which is sometimes
# slow enough to time out the job. If a download takes longer than
# APT_MIRROR_TIMEOUT seconds, this switches to archive.ubuntu.com and retries.
#
# Usage: install_apt_packages.sh DEBS_DIR PACKAGE...
set -euo pipefail

debs_dir=$1
shift
packages=("$@")
mirror_timeout=${APT_MIRROR_TIMEOUT:-300}

download() {
  timeout "$@" sudo apt-get update
  timeout "$@" sudo apt-get install --download-only --no-install-recommends -y \
    -o Dir::Cache::archives="$debs_dir" "${packages[@]}"
}

if ! compgen -G "$debs_dir/*.deb" >/dev/null; then
  mkdir -p "$debs_dir/partial"
  if ! download "$mirror_timeout"; then
    echo "::warning::apt download did not finish in ${mirror_timeout}s, retrying with archive.ubuntu.com"
    echo "http://archive.ubuntu.com/ubuntu/" | sudo tee /etc/apt/apt-mirrors.txt >/dev/null
    download 0
  fi
  # Leave only the .deb files to cache.
  sudo rm -rf "$debs_dir/partial" "$debs_dir/lock"
fi

sudo dpkg -i "$debs_dir"/*.deb
