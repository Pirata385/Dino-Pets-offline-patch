#!/usr/bin/env python3
"""Rewrite the decoded AndroidManifest.xml / apktool.yml for the offline build.

usage: patch_manifest.py <apktool dir> [--target-sdk N]

Removed (all only served online services):
  permissions INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, GET_ACCOUNTS,
  READ_PHONE_STATE, ACCESS_COARSE_LOCATION, GET_TASKS, WAKE_LOCK, BILLING,
  C2D_MESSAGE / c2dm RECEIVE, WRITE_EXTERNAL_STORAGE (all game data lives in
  internal storage);
  components for MoPub, Google Play billing v2, AdX, GetJar, GCM, AdMob,
  Millennial Media, Apsalar and Facebook login; the apsalar deep link.
Kept: the game activity and BootReceiver (local "your pets miss you" reminders).
Without the INTERNET permission the OS itself guarantees the app can never
open a network socket.
"""
import os
import re
import sys

NEW_MANIFEST = """<?xml version="1.0" encoding="utf-8" standalone="no"?><manifest xmlns:android="http://schemas.android.com/apk/res/android" android:installLocation="preferExternal" package="com.miniclip.dinopets">
    <uses-permission android:name="android.permission.VIBRATE"/>
    <application android:icon="@drawable/icon" android:label="@string/app_name">
        <activity android:configChanges="keyboardHidden|orientation|screenSize" android:label="@string/app_name" android:name=".DinoPetsActivity" android:screenOrientation="landscape" android:theme="@android:style/Theme.NoTitleBar.Fullscreen">
            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="android.intent.category.LAUNCHER"/>
            </intent-filter>
        </activity>
        <receiver android:name=".BootReceiver">
            <intent-filter>
                <action android:name="android.intent.action.BOOT_COMPLETED"/>
                <category android:name="android.intent.category.HOME"/>
            </intent-filter>
        </receiver>
    </application>
    <supports-screens android:largeScreens="true" android:normalScreens="true" android:smallScreens="true" android:xlargeScreens="true"/>
</manifest>
"""

EXPECTED = [
    'package="com.miniclip.dinopets"',
    'android:name=".DinoPetsActivity"',
    'android:name=".BootReceiver"',
    'android:name="android.permission.INTERNET"',
    'android:name="com.getjar.sdk.rewards.GetJarService"',
]


def main():
    d = sys.argv[1]
    target = "24"
    if "--target-sdk" in sys.argv:
        target = sys.argv[sys.argv.index("--target-sdk") + 1]
    mpath = os.path.join(d, "AndroidManifest.xml")
    old = open(mpath, encoding="utf-8").read()
    for e in EXPECTED:
        if e not in old:
            raise SystemExit("ABORT: unexpected AndroidManifest.xml (missing %s)" % e)
    open(mpath, "w", encoding="utf-8").write(NEW_MANIFEST)
    print("  [ok] AndroidManifest.xml rewritten (offline components only)")

    ypath = os.path.join(d, "apktool.yml")
    y = open(ypath, encoding="utf-8").read()
    if "minSdkVersion: 8" not in y or "targetSdkVersion: 17" not in y:
        raise SystemExit("ABORT: unexpected apktool.yml sdkInfo")
    y = re.sub(r"targetSdkVersion: \d+", "targetSdkVersion: " + target, y)
    open(ypath, "w", encoding="utf-8").write(y)
    print("  [ok] apktool.yml targetSdkVersion -> %s" % target)


if __name__ == "__main__":
    main()
