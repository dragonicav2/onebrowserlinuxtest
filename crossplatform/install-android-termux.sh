#!/data/data/com.termux/files/usr/bin/bash
# ZeroDownloader One-Step Installer for Android (Termux)
# Enables both `zdl` CLI, `zdl --ui` Mobile Web UI, AND Android system Share-Sheet ("Share -> Termux")!
set -e

echo "[1/4] Updating Termux packages & installing Python + FFmpeg..."
pkg update -y
pkg install -y python ffmpeg termux-api

echo "[2/4] Installing yt-dlp streaming media backend..."
pip install -U yt-dlp

echo "[3/4] Requesting Android Downloads folder storage access..."
termux-setup-storage || true

mkdir -p "$HOME/.local/bin" "$HOME/bin"
cp "$(dirname "$0")/zerodownloader.py" "$HOME/.local/bin/zdl"
chmod +x "$HOME/.local/bin/zdl"

cat > "$HOME/bin/termux-url-opener" <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
URL="$1"
echo "=== ZeroDownloader Android ==="
echo "Target: $URL"
echo "1) Best Quality Video + Audio (4K/1080p) [Default]"
echo "2) 1080p Video"
echo "3) Audio Only"
echo "4) Accelerated Direct File (8 Connections)"
read -r -p "Select [1-4]: " CHOICE
case "$CHOICE" in
  2) python3 "$HOME/.local/bin/zdl" -q 1080p "$URL" ;;
  3) python3 "$HOME/.local/bin/zdl" -q audio "$URL" ;;
  *) python3 "$HOME/.local/bin/zdl" -c 8 -q best "$URL" ;;
esac
read -r -p "Done! Saved to /sdcard/Download/ZeroDownloader. Press Enter to close..." _
EOF
chmod +x "$HOME/bin/termux-url-opener"

echo "[4/4] Installed! Share any link in Android -> Termux, or run: ~/.local/bin/zdl --ui"
