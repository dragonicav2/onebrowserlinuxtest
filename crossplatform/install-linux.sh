#!/usr/bin/env bash
# ZeroDownloader Installer for Linux (Ubuntu/Debian/Fedora/Arch, x86_64 & ARM64)
set -e

mkdir -p "$HOME/.local/bin"
cp "$(dirname "$0")/zerodownloader.py" "$HOME/.local/bin/zdl"
chmod +x "$HOME/.local/bin/zdl"

if command -v pip3 >/dev/null 2>&1; then
  pip3 install --user -U yt-dlp || true
fi

echo "ZeroDownloader installed to $HOME/.local/bin/zdl"
echo "  CLI usage:    zdl <url> -c 8 -q best"
echo "  Web UI usage: zdl --ui"
