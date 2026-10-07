# Dino Pets 1.1.4 — network dependency analysis and offline patches

This document records what the original game needed from the network, what
happens to each dependency in the offline edition, and why.  All addresses
refer to the original `lib/armeabi/libgame.so`
(sha256 `74dbc7c7…48874`) with image base 0.

## 1. The original APK

| | |
|---|---|
| File | `Dino.Pets_1.1.4.apk` (GitHub release `v1.0.0-offline`), sha256 `146e8d7f84ffcb08231323fab3bb4113ad138492a233f478871b458d77bdeea9` |
| Package / version | `com.miniclip.dinopets`, versionName 1.1.4, versionCode 13, minSdk 8, targetSdk 17 |
| Game code | `lib/armeabi/libgame.so` — 12 MB, 32-bit ARMv6 (VFPv2), stripped. Objective-C (GNU runtime, module ABI 8) on Cocotron Foundation + cocos2d, with libcurl 7.37.0 and OpenSSL linked in. |
| Java layer | Thin Android shell (`com.miniclip.nativeJNI.*`, `com.miniclip.dinopets.*`) plus SDKs: Google Play billing v2/v3, GetJar, Facebook, GCM, Flurry, Apsalar, Mixpanel, Google Analytics v1/v2, Chartboost, AdX, Tapjoy, MoPub, AdMob, Millennial Media. |
| Game data | `assets/` (textures, audio, VSZ animations, plists). `assets/config.plist` is the complete game configuration (encrypted binary plist, config version 1.1.2): 75 dinos, 20 mythicals, 30 levels, 171 quests, 33 decorations, 45 expansions, 14 shops, daily rewards, tutorial, etc. All 1232 files listed in its checksum table are present in the APK. |

**Behaviour of the unmodified APK without network** (tested on an Android 7.1.1
ARM emulator in airplane mode): the loading screen keeps asking Java for NTP
time on every frame, then the loading thread dies with `SIGSEGV` in
`objc_msg_lookup` and Android shows a crash dialog.  The game is unplayable.

## 2. Startup pipeline

`-[GameLayer performBaseLoadingStep]` runs the loading screen as a state machine
(step index in ivar `+0x244`, sub-state 0 start / 1 waiting / 2 success /
3 failure).  Steps that used the network and what the offline edition does:

| Step | Original behaviour | Offline edition |
|---|---|---|
| 0 | Load local save (`Documents/save.plist`) and bundled `config.plist` | unchanged |
| 2 `loadingStepLoadSaveFile` | Fetch the cloud save from `shelter-services.miniclippt.com/cloud_storage_dinopets.php` | returns immediately (the local save from step 0 is used; no save → new shelter, same as "no cloud save") |
| 3 `loadingStepDownloadNetworkTime` / `-[GameLayer ntpAndroid]` | NTP query (`0-3.pool.ntp.org`) via Java; startup blocked until it succeeded | reports success with a 0.0 s offset (device clock) |
| 4 `loadingStepSetupConfig` | `MCConfigSetup` request to `services.miniclippt.com/configurations/getConfigurationURL.php` (retried forever when unreachable) | returns immediately |
| 5 `loadingStepDownloadConfiguration` | Compare with / download the latest config from `shelter.miniclippt.com/get_dinopets_android_latest_conf_v2.php`; **mandatory on first launch** | after the local config is loaded, jumps to the original "configuration is up to date" block |
| 6, 11 `loadingStepDownloadFiles*` | Download changed assets listed by `get_dinopets_android_files_v2.php` | nothing to download (local config is current) → complete |
| 12 `loadingStepDownloadPrices` | Store prices from Google Play / GetJar | completes without contacting a store |
| 17 | Messaging registry with `messenger.miniclippt.com` | skipped |
| 18 | Facebook session | Facebook disabled (`mUSE_FACEBOOK = false`) |

After step 5 the loading thread spends a while (≈30 s on the software-emulated
test device, a fraction of that on real hardware) building game objects from
the 737 KB configuration.  Native backtraces taken in that window show it in
the Objective-C runtime's method-list search (`strcmp` from `0x293054`, called
by key-value-coding setters), i.e. CPU work that the original game also did, not
a network wait.

## 3. Network dependency inventory

### 3.1 Native code (`libgame.so`)

| Endpoint | Purpose | Offline edition |
|---|---|---|
| `shelter.miniclippt.com/get_dinopets_android_latest_conf_v2(_sb).php` | Remote game configuration | bundled `assets/config.plist` (patch N3) |
| `shelter.miniclippt.com/get_dinopets_android_files_v2(_sb).php` | Remote asset updates | not needed; all referenced assets are in the APK |
| `services.miniclippt.com/configurations/getConfigurationURL.php` | `MCConfigSetup` (where to fetch config) | skipped (N2) |
| `services.miniclippt.com/properties/get_properties.php` | `MCCPS` remote "cloud properties" | refresh skipped (N9); built-in defaults |
| `shelter-services.miniclippt.com/cloud_storage_dinopets.php` | Cloud save backup / restore (`CloudStorage`) | removed (N1, N6, N7); saves are local |
| `shelter-services(.dev).miniclippt.com/dinopets_social.php` | Social server: Dino ID registration, friends by Dino ID, visit/rating notifications, messages | 5-second notification poll skipped (N10); user-initiated requests fail immediately (no `INTERNET` permission) and the game shows its own error dialogs. Community visiting uses the bundled `FakeCommunity*` shelters, which work completely offline. |
| `messenger.miniclippt.com/messenger/dinopets.php` | Push/messaging registration | skipped (N8) |
| `udidmapper.dinopets.miniclippt.com/udidmapper/` | Device-ID mapping | not requested in any test session; would fail immediately like any other request |
| `0-3.pool.ntp.org` (through Java `NtpHandler`) | Trusted time for timers | device clock (N4, Java NTP stubs) |
| `www.google.com` | "Is the internet working?" probe after an NTP failure | never called (N5) |
| `graph.facebook.com`, `www.facebook.com/appcenter/…`, `www.miniclip.com/iphone/assets/DinoPark/facebook/*` | Facebook login, sharing, story images | Facebook disabled; user actions show a notice |
| `market.android.com/…`, `www.miniclip.com/android/mobile`, `www.miniclip.com/smartphone-information` | Rate / More games / Terms links | `openURL` shows a notice |
| `ad-x.co.uk/API/click/…` | AdX install attribution | disabled |

### 3.2 Java layer

| Component | Endpoint(s) | Offline edition |
|---|---|---|
| `com.miniclip.NTP.NtpHandler` | NTP servers | answers immediately with offset 0.0 s |
| `com.miniclip.Ping.PingHandler` | TCP connect to port 53 / ICMP | answers immediately "unreachable" (same code as the original timeout path) |
| `cocojava.isOnline()` | `ConnectivityManager` | always `false` |
| `com.miniclip.newsfeed.*` | `services.miniclippt.com/newsfeed/newsfeed.php` | disabled (`mUSE_NEWSFEED = false`, `update`/`checkServer`/remote images stubbed); the News button is greyed out |
| `InAppActivity` (Google Play billing), `GetJar` | Play Store billing service, GetJar SDK | no billing service binding; coin and gem packs are granted locally as successful purchases (§8); price localisation returns the config prices |
| `utils.ReceiptValidator` | `services.miniclippt.com/receiptValidation/index.php` | answers "valid" immediately, like the original `bypassValidation` switch (§8) |
| Facebook SDK (`cocojava.faceBook_*`) | `graph.facebook.com`, `m.facebook.com` | disabled; login/share/invite/like show a toast |
| `cocojava.openURL` | browser / Play Store | toast instead of an intent to a dead page |
| GCM (`GCMIntentService`, `mUSE_C2DM`) | Google push | disabled, components removed from the manifest |
| Flurry, Apsalar, Mixpanel, Google Analytics v1/v2, AdX | `data.flurry.com`, `e.apsalar.com`, `api.mixpanel.com`, `google-analytics.com`, `ad-x.co.uk` | all entry points used by the game are no-ops. (Flurry's class initialiser still creates an idle `FlurryAgent` handler thread; no session is started and nothing is recorded or sent.) |
| Chartboost, Tapjoy, MoPub, AdMob, Millennial Media | ad networks | Chartboost lifecycle calls are no-ops; Tapjoy (`mUSE_TAPJOY`) and ads (`mUSE_ADS`) were already off in the original; their activities are removed from the manifest |
| `nativeJNI.infoTransmitter` | `ftp.miniclippt.com/submit_stats.php` | dead code in the original (never instantiated) |
| `DinoPetsActivity.onStart/onStop` | WiFi lock (keeps WiFi awake for the servers) | removed |

### 3.3 Manifest

Removed permissions: `INTERNET`, `ACCESS_NETWORK_STATE`, `ACCESS_WIFI_STATE`,
`GET_ACCOUNTS`, `READ_PHONE_STATE`, `ACCESS_COARSE_LOCATION`, `GET_TASKS`,
`WAKE_LOCK`, `WRITE_EXTERNAL_STORAGE`, `com.android.vending.BILLING`, GCM
`RECEIVE` / `C2D_MESSAGE`.  Only `VIBRATE` remains.  Without `INTERNET` the
operating system itself guarantees the game cannot open a socket, so any network
code path that was missed fails instantly instead of waiting for a timeout.

Removed components: MoPub, Google Play billing v2 service/receiver, AdX
tracker, GetJar service/receiver/activity/package monitor, GCM service and
receiver, AdMob, Millennial Media (3 activities), Apsalar, Facebook login.
Kept: `DinoPetsActivity` (launcher) and `BootReceiver` (local reminders).

`targetSdkVersion` 17 → 24: Android 14 refuses to install apps targeting
below 23, and Android 15–17 below 24.  24 is the lowest value accepted
everywhere and avoids the behaviour changes of later API levels (notification
channels, `PendingIntent` mutability, runtime notification permission), which
the 2013 code does not handle.  `minSdkVersion` stays 8.

## 4. Native patches (`patches/native/patch_libgame.py`)

Each patch checks the original bytes first; the script refuses any other build.

| # | Address | Function | Change |
|---|---|---|---|
| N1 | `0x5AD868` | `-[GameLayer loadingStepLoadSaveFile]` | `mov r0,#0; bx lr` |
| N2 | `0x5A4A70` | `-[GameLayer loadingStepSetupConfig]` | `mov r0,#0; bx lr` |
| N3 | `0x5A7624` | inside `-[GameLayer loadingStepDownloadConfiguration]` | `ldrb r0,[r9,#0x36d]` → `b 0x5A7998` ("configuration up to date" block) |
| N4 | `0x5A53F8` | `-[GameLayer ntpAndroid]` | calls `ntpCallback(0.0, 0)` (`0x5A535C`) directly |
| N5 | `0x5A21F8` | `-[GameLayer determineIfNTPFailureIsWithWorkingInternetConnection]` | `bx lr` |
| N6 | `0x4B38D0` | `-[CloudStorage startOperation]` | `bx lr` |
| N7 | `0x4B42AC` | `-[CloudStorage storeValue:forKey:]` | `bx lr` |
| N8 | `0x60FA74` | `-[GameLayer updateMessagingRegistry]` | `bx lr` |
| N9 | `0x64DE78` | `-[MCCPS forceUpdateOnAllProperties]` | `bx lr` |
| N10 | `0x4B6B8C` | `-[SocialUtils checkNotifications]` | `beq` → `b 0x4B6C84` (keep the 5 s timer, skip the request) |
| N11 | `0x5A4100` | rest of the dead `-[GameLayer loadingStepSetupID]` | 840 bytes of new code: `fbdino_grant` (Facebook dino unlock, §8) and two hook trampolines |
| N12 | `0x58F17C` | epilogue of `-[GameLayer onTutorialFinished]` | `sub sp,fp,#28` → `b` trampoline that calls `fbdino_grant(self)` and then returns as before |
| N13 | `0x5B8734` | prologue of `-[GameLayer showMainView]` | `push {r4-r9,sl,fp,lr}` → `b` trampoline that calls `fbdino_grant(self)`, re-executes the push and continues the method |
| — | `.dynamic` | `DT_NEEDED` | absolute build-machine paths (`/PortsTools/android/…/libc.so`) → plain sonames; required for targetSdk ≥ 23 |

Debug builds (`DEBUG=1 ./build.sh`) additionally route the compiled-out
`NSLog` to logcat (tag `DinoNSLog`) through a code cave in the dead method
`-[GameLayer loadingStepSetupID]` (`0x5A4010`).

## 5. Java patches (`patches/smali/patch_smali.py`, `patches/java/src`)

Small smali edits redirect the methods listed in §3.2 to
`com.miniclip.offline.Offline`, a helper class compiled from Java
(`patches/java/src`).  It delivers the "offline" answers on the GL thread
exactly as the original asynchronous code would have (NTP, ping, purchase and
receipt-validation callbacks), shows short toasts for the online features that
cannot work offline, and rebuilds the local reminder notification with
`Notification.Builder`.  The original `BootReceiver` used
`Notification.setLatestEventInfo()`, which no longer exists on Android 6.0+.

## 6. Data formats

* **Save game**: `/data/data/com.miniclip.dinopets/files/Contents/Resources/Documents/save.plist`,
  written every 60 s (`TimeLocalSave`) and when the app goes to the
  background.  Same file and format as the original game.
* **Encryption** (saves and `config.plist`): 8-byte header with the plaintext
  length in ASCII decimal, then a Blowfish variant in ECB mode (S-box 0 indexed
  by the low byte in F(), little-endian key packing and data words), key
  `W3LC0M3_T0_M1N1P3TZ`.  `tools/dpcrypt.py` decrypts/encrypts these files
  (it reads the cipher tables from `libgame.so`).
* **Time**: the device clock replaces NTP.  Timers (construction, hatching,
  breeding, income, daily rewards) advance while the game is closed, as before.
  Changing the device clock now affects the game, which the original prevented
  with NTP.

## 7. Verification

Tested on an Android 7.1.1 ARM (armeabi-v7a) emulator with airplane mode on and
no active network (`dumpsys connectivity`: "Active default network: none").

* Original APK: crashes during loading (see §1).
* Offline APK, clean install: loads straight into the tutorial with a new
  shelter (2500 coins, 20 gems).
* Tutorial and core loop: placing and inaugurating homes, nests, eggs, Hatchery,
  hatching, keeper hut, level-up with rewards, Dilophosaurus home, Mystery Cave
  construction, breeding a mythical hybrid (Dilophodocus); coins, gems and XP
  change correctly.
* Persistence: force-stop and relaunch restore the exact state; the decrypted
  `save.plist` matches the HUD.  Timers finish while the app is closed.
* Upgrade from an earlier build of the offline edition keeps the save.
* Store: Google Play and GetJar coin and gem packs complete at once with the
  game's "Purchase complete" pop-up; the amounts are added and saved (§8).
* Facebook-exclusive dino: unlocked when the tutorial finishes, once (§8).
* Social: Profile, Friends, Messages ("No pending messages!"), Community list,
  visiting Kirini's level-20 shelter, rating it and adding her as a friend all
  work.  Adding an unknown Dino ID ends at once with "The entered Dino ID does
  not exist".
* Facebook, Terms & Conditions, More Games: toast, no hang.  News: disabled.
* Local reminder notification ("Visit Park") is posted with the game icon and
  opens the game ([screenshot](screenshots/06-local-reminder-notification.jpg)).
* No `FATAL`/`AndroidRuntime` errors, no `SecurityException`, no native crash
  in logcat during any of the above.
* The only URL the game tried to open in all debug-build sessions was the social
  endpoint (`dinopets_social.php`: Dino ID registration, add-by-Dino-ID, message
  fetch when the Social screen opens).  Each attempt failed within about a
  second and the game showed its normal error handling.

## 8. Local replacements for purchases and the Facebook reward

These two features replace online rewards with local equivalents.  Both reuse
the game's own code paths, so amounts, pop-ups, sounds and save keys are the
original ones.

### Coin and gem packs

The original flow (native `-[GameLayer performTransaction:forState:]`):

1. The shop calls Java `cocojava.callInAppPurchase(sku, inAppResponse, self)`
   (Google Play tab) or `GetJar.inAppPurchase(...)` (GetJar tab).
2. The store reports back through JNI `CocoJNI.MsetInAppResponce(1, callback,
   self, sku, signedData, signature)`.  The native `inAppResponse()` callback
   calls `-[GameLayer transactionComplete:receipt:]` →
   `-[GameLayer finishPurchase:]`, which adds the pack amount (times the
   level multiplier from `premiumCurrencyShopLevelMultiplierMap`), shows the
   "Purchase complete" pop-up, plays the purchase sound and requests a save.
3. `inAppResponse()` then starts receipt validation
   (`ReceiptValidator_validate` → `services.miniclippt.com`).  Its result goes
   to `-[GameLayer handleSuccessWithReceipt:]` (logs the purchase) or
   `handleError:withReceipt:`.

Offline edition:

* `InAppActivity.requestPurchaseAct/requestPurchaseActManaged`,
  `GetJar.inAppPurchase` and `DinoPetsActivity.onGetJarInAppPurchase` call
  `Offline.purchaseSucceeded()`.  It sends `MsetInAppResponce(1, …)` on the
  GL thread with the SKU, a short local purchase record and the signature
  `"offline"`, exactly as the Play Store success callback did.  No Play Store
  dialog appears and nothing is charged.
* `ReceiptValidator_validate` calls `Offline.receiptValidated()`, which
  answers result code 0 ("valid"), the same answer the original
  `ReceiptValidator.bypassValidation` switch gave.  The game logs the purchase
  and does not try to validate it again.
* The currency is added by the game's own `finishPurchase:` and saved in
  `save.plist` (keys `013` coins, `014` gems).  Example from the tests:
  "Bunch of Coins" gave 3800 coins, "Bunch of Gems" 20 gems, and the GetJar
  "Pouch of Gems" 55 gems.  The amounts are those shown in the shop.

### Facebook-exclusive dinosaur

The reward for logging in to Facebook was the quest `q_fbLogin` ("Login to
Facebook", shown by the tutorial's last pop-up: "Login on Facebook to win 10
gems and an exclusive dino!").  Its `other` field is `d_Dimorphodon`, a dino
that is `hidden` in the shop config.  When a quest with a structure reward
completes, `-[GameLayer questRewardPopUpCallback:]` calls
`[[cfg shopEntry] setHidden:NO]` and adds the id to `mUnlockedObjects`
(`NSMutableSet`, `GameLayer+0x1138`).  That set is saved as key `1004` and
re-applied by `-[GameLayer unlockObjects:]` on every load.  The dino itself
(`cost` 0, 1 keeper, insectivore) then behaves like any other dino.

The offline edition does the same thing without Facebook.  `fbdino_grant(self)`
is ARM code in the dead `loadingStepSetupID` method (N11).  It runs:

* at the end of `-[GameLayer onTutorialFinished]` (N12), i.e. right after the
  first tutorial is completed;
* at the start of `-[GameLayer showMainView]` (N13), so that saves which had
  finished the tutorial before this feature existed get the dino too.

It only acts when the tutorial is finished (`mTutorial == nil`), the player is
not visiting another shelter, and `mUnlockedObjects` does not already contain
`d_Dimorphodon`.  It un-hides the shop entry, adds the id to `mUnlockedObjects`,
calls `-[GameLayer forceSave]`, and queues a "Congratulations!" pop-up with the
game's `MessagePopUpParams` / `-showMessagePopUp:` on the main thread.  Because
the unlock is stored in the save's own `1004` set, it is granted once per save.
Restarting the game or replaying does not grant it again, and starting a new
game grants it again only after that game's tutorial is completed.

The quest's 10 gems are not added: this feature restores only the exclusive
dino.  The Facebook login button and quest stay as
they were (logging in still shows the offline notice).

Verified offline on the emulator: clean install → tutorial → pop-up →
Dimorphodon free in the Dinos shop → placed, built and inaugurated
([screenshot](screenshots/11-dimorphodon-in-shelter.jpg)) →
force-stop and relaunch keep `1004 = [d_Dimorphodon]` with no second pop-up.
A save with `053` (tutorial finished) = true and an empty `1004` got the
unlock once when the map opened.

