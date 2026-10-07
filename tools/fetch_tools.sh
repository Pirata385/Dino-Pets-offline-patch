#!/usr/bin/env bash
# Download the build tools used by build.sh into $TOOLS_DIR (default ./.tools).
# Needs: java (17+), python3, curl, unzip, and ARM binutils
# (Debian/Ubuntu: apt install binutils-arm-linux-gnueabi).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS_DIR="${TOOLS_DIR:-$ROOT/.tools}"
mkdir -p "$TOOLS_DIR"
cd "$TOOLS_DIR"

[ -f apktool.jar ] || curl -fsSL -o apktool.jar \
  https://github.com/iBotPeaches/Apktool/releases/download/v2.10.0/apktool_2.10.0.jar
[ -f baksmali.jar ] || curl -fsSL -o baksmali.jar \
  https://bitbucket.org/JesusFreke/smali/downloads/baksmali-2.5.2.jar

if [ ! -x android-sdk/cmdline-tools/latest/bin/sdkmanager ]; then
  curl -fsSL -o cmdline-tools.zip https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
  mkdir -p android-sdk/cmdline-tools
  unzip -q cmdline-tools.zip -d android-sdk/cmdline-tools
  mv android-sdk/cmdline-tools/cmdline-tools android-sdk/cmdline-tools/latest
  rm cmdline-tools.zip
fi
SDKM=android-sdk/cmdline-tools/latest/bin/sdkmanager
yes | "$SDKM" --sdk_root="$TOOLS_DIR/android-sdk" --licenses >/dev/null || true
"$SDKM" --sdk_root="$TOOLS_DIR/android-sdk" "build-tools;34.0.0" "platforms;android-25" >/dev/null
echo "tools ready in $TOOLS_DIR"
