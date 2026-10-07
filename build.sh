#!/usr/bin/env bash
# Rebuild the offline edition of Dino Pets 1.1.4 from the original APK.
#
#   ./build.sh [path/to/Dino.Pets_1.1.4.apk]
#
# Environment:
#   TOOLS_DIR     where tools/fetch_tools.sh put apktool, smali, the Android SDK (default: ./.tools)
#   TARGET_SDK    targetSdkVersion of the rebuilt APK (default 24, original was 17)
#   DEBUG=1       route the game's native NSLog output to logcat (tag DinoNSLog)
#   KEYSTORE / KEYSTORE_PASS / KEY_ALIAS   signing key (generated in signing/ when absent)
#   OUT           output APK path (default output/DinoPets-1.1.4-offline.apk)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
TOOLS_DIR="${TOOLS_DIR:-$ROOT/.tools}"
TARGET_SDK="${TARGET_SDK:-24}"
OUT="${OUT:-$ROOT/output/DinoPets-1.1.4-offline.apk}"
BUILD="$ROOT/build"
APK_URL="https://github.com/Pirata385/Dino-Pets-offline-patch/releases/download/v1.0.0-offline/Dino.Pets_1.1.4.apk"
APK_SHA256="146e8d7f84ffcb08231323fab3bb4113ad138492a233f478871b458d77bdeea9"

APKTOOL="$TOOLS_DIR/apktool.jar"
BAKSMALI="$TOOLS_DIR/baksmali.jar"
SDK="$TOOLS_DIR/android-sdk"
BT="$SDK/build-tools/34.0.0"
ANDROID_JAR="$SDK/platforms/android-25/android.jar"
for f in "$APKTOOL" "$BAKSMALI" "$BT/d8" "$BT/zipalign" "$BT/apksigner" "$ANDROID_JAR"; do
  [ -e "$f" ] || { echo "missing $f - run tools/fetch_tools.sh first" >&2; exit 1; }
done
command -v arm-linux-gnueabi-as >/dev/null || { echo "missing ARM binutils (apt install binutils-arm-linux-gnueabi)" >&2; exit 1; }

rm -rf "$BUILD"; mkdir -p "$BUILD" "$(dirname "$OUT")"

# 1. original APK (from the GitHub release unless a path is given)
SRC_APK="${1:-$BUILD/original.apk}"
if [ -z "${1:-}" ]; then
  echo "== downloading original APK"
  curl -fsSL -o "$SRC_APK" "$APK_URL"
fi
echo "$APK_SHA256  $SRC_APK" | sha256sum -c -

# 2. decode
echo "== decoding"
java -jar "$APKTOOL" d -f -o "$BUILD/decoded" "$SRC_APK" >/dev/null

# 3. native patches
echo "== patching libgame.so"
NATIVE_FLAGS=(--fix-dt-needed)
[ "${DEBUG:-0}" = "1" ] && NATIVE_FLAGS+=(--debug-nslog)
python3 -I "$ROOT/patches/native/patch_libgame.py" "$BUILD/decoded/lib/armeabi/libgame.so" \
  "$BUILD/libgame.so" "${NATIVE_FLAGS[@]}"
cp "$BUILD/libgame.so" "$BUILD/decoded/lib/armeabi/libgame.so"

# 4. helper classes (Java -> dex -> smali)
echo "== building helper classes"
mkdir -p "$BUILD/helpers/classes" "$BUILD/helpers/dex"
javac -nowarn -source 8 -target 8 -bootclasspath "$ANDROID_JAR" -d "$BUILD/helpers/classes" \
  $(find "$ROOT/patches/java/src" "$ROOT/patches/java/stubs" -name '*.java') 2>&1 | grep -v -E "warning|^Picked up" || true
"$BT/d8" --min-api 8 --lib "$ANDROID_JAR" --output "$BUILD/helpers/dex" \
  "$BUILD"/helpers/classes/com/miniclip/offline/*.class
java -jar "$BAKSMALI" d -o "$BUILD/helpers/smali" "$BUILD/helpers/dex/classes.dex"

# 5. Java-layer and manifest patches
echo "== patching smali"
python3 -I "$ROOT/patches/smali/patch_smali.py" "$BUILD/decoded/smali" "$BUILD/helpers/smali"
echo "== patching manifest"
python3 -I "$ROOT/patches/manifest/patch_manifest.py" "$BUILD/decoded" --target-sdk "$TARGET_SDK"

# 6. rebuild, align, sign
echo "== rebuilding"
java -jar "$APKTOOL" b -o "$BUILD/unsigned.apk" "$BUILD/decoded" >/dev/null
"$BT/zipalign" -f -p 4 "$BUILD/unsigned.apk" "$BUILD/aligned.apk"

KEYSTORE="${KEYSTORE:-$ROOT/signing/dinopets-offline.keystore}"
KEYSTORE_PASS="${KEYSTORE_PASS:-dinopets-offline}"
KEY_ALIAS="${KEY_ALIAS:-dinopets-offline}"
if [ ! -f "$KEYSTORE" ]; then
  echo "== generating signing key $KEYSTORE"
  mkdir -p "$(dirname "$KEYSTORE")"
  keytool -genkeypair -keystore "$KEYSTORE" -storepass "$KEYSTORE_PASS" -keypass "$KEYSTORE_PASS" \
    -alias "$KEY_ALIAS" -keyalg RSA -keysize 2048 -validity 36500 \
    -dname "CN=Dino Pets Offline Edition, O=Community preservation build" 2>&1 | grep -v "^Picked up" || true
fi
"$BT/apksigner" sign --ks "$KEYSTORE" --ks-pass "pass:$KEYSTORE_PASS" --ks-key-alias "$KEY_ALIAS" \
  --v1-signing-enabled true --v2-signing-enabled true --out "$OUT" "$BUILD/aligned.apk"
"$BT/apksigner" verify --verbose "$OUT" | grep -E "Verified|Number of signers" || true
rm -f "$OUT.idsig"
echo "== done: $OUT"
sha256sum "$OUT"
