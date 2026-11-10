#!/usr/bin/env bash
# Builds and packages OneBrowser Zen into a distributable .flatpak bundle for Bazzite Linux
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MANIFEST="${SCRIPT_DIR}/io.github.onebrowser.OneBrowser.yml"
BUILD_DIR="/tmp/onebrowser_flatpak_build"
REPO_DIR="/tmp/onebrowser_flatpak_repo"
OUT_BUNDLE="${ROOT_DIR}/dist/linux/OneBrowser-x86_64.flatpak"

mkdir -p "${ROOT_DIR}/dist/linux"

echo "==> Ensuring Flathub remote & GNOME 47 runtime..."
flatpak remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user -y flathub org.gnome.Platform//47 org.gnome.Sdk//47

echo "==> Building OneBrowser Zen Flatpak repository..."
flatpak-builder --user --disable-rofiles-fuse --force-clean --repo="${REPO_DIR}" "${BUILD_DIR}" "${MANIFEST}"

echo "==> Exporting single-file Flatpak bundle -> ${OUT_BUNDLE}"
flatpak build-bundle "${REPO_DIR}" "${OUT_BUNDLE}" io.github.onebrowser.OneBrowser --runtime-repo=https://flathub.org/repo/flathub.flatpakrepo

echo "==> SUCCESS: Flatpak bundle ready at ${OUT_BUNDLE}"
echo "    Install on Bazzite with: flatpak install --user -y ${OUT_BUNDLE}"
echo "    Run with:                flatpak run io.github.onebrowser.OneBrowser"
