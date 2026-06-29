#!/usr/bin/env bash
# Build the macOS .app and wrap it in an unsigned .dmg.
#
# Usage:
#   ./packaging/build_dmg.sh             # build for the current arch
#   TARGET_ARCH=universal2 ./packaging/build_dmg.sh
#
# Prereqs: run inside the project venv with PyInstaller installed:
#   pip install -e ".[gui,dev]" pyinstaller
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APP_NAME="ElevenLabs Helper"
DIST_APP="dist/${APP_NAME}.app"
DMG_PATH="dist/${APP_NAME}.dmg"

echo "==> Building app bundle (TARGET_ARCH=${TARGET_ARCH:-current})"
pyinstaller --noconfirm packaging/elevenlabs_helper.spec

if [ ! -d "$DIST_APP" ]; then
  echo "error: $DIST_APP not produced" >&2
  exit 1
fi

echo "==> Creating DMG"
rm -f "$DMG_PATH"
STAGE="$(mktemp -d)"
cp -R "$DIST_APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG_PATH"
rm -rf "$STAGE"

echo "==> Done: $DMG_PATH"
echo "==> SHA-256 (publish this so users can verify integrity):"
shasum -a 256 "$DMG_PATH"
echo "Note: unsigned build. First launch: right-click the app -> Open."
echo "To sign+notarize later, see README (codesign + xcrun notarytool)."
