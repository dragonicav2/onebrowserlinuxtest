#!/usr/bin/env bash
# Builds and packages OneBrowser Zen into a distributable .flatpak bundle for Bazzite Linux
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MANIFEST="${SCRIPT_DIR}/io.github.onebrowser.OneBrowser.yml"
BUILD_DIR="${ROOT_DIR}/obj_flatpak_build"
REPO_DIR="${ROOT_DIR}/obj_flatpak_repo"
OUT_BUNDLE="${ROOT_DIR}/dist/linux/OneBrowser-x86_64.flatpak"

mkdir -p "${ROOT_DIR}/dist/linux"

echo "==> Building OneBrowser Zen Flatpak repository..."
flatpak-builder --force-clean --repo="${REPO_DIR}" "${BUILD_DIR}" "${MANIFEST}"

echo "==> Exporting single-file Flatpak bundle -> ${OUT_BUNDLE}"
flatpak build-bundle "${REPO_DIR}" "${OUT_BUNDLE}" io.github.onebrowser.OneBrowser

echo "==> SUCCESS: Flatpak bundle ready at ${OUT_BUNDLE}"
echo "    Install on Bazzite with: flatpak install --user ${OUT_BUNDLE}"
echo "    Run with:                flatpak run io.github.onebrowser.OneBrowser"
