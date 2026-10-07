#!/usr/bin/env python3
"""Java-layer (smali) offline patches for Dino Pets 1.1.4.

usage: patch_smali.py <apktool smali dir> <helper smali dir>

<helper smali dir> holds the baksmali'd com/miniclip/offline/* classes built
from patches/java/src.  Every edit verifies its target first and aborts if the
smali does not look exactly like the original 1.1.4 build.
"""
import os
import re
import shutil
import sys

SMALI = HELPERS = None
EDITS = []


def path(cls):
    return os.path.join(SMALI, cls.replace(".", "/") + ".smali")


def replace_method(cls, header, body, why):
    """Replace the whole method whose `.method` line equals `header`."""
    EDITS.append(("method", cls, header, body, why))


def replace_text(cls, old, new, why, count=1):
    EDITS.append(("text", cls, old, new, why, count))


VOID = "    .locals 0\n    return-void\n"
FALSE = "    .locals 1\n    const/4 v0, 0x0\n    return v0\n"


def stub_void(cls, header, why):
    replace_method(cls, header, VOID, why)


# ---------------------------------------------------------------------------
# Time source: NTP (pool.ntp.org) -> device clock
# ---------------------------------------------------------------------------
replace_method("com.miniclip.NTP.NtpHandler",
               ".method public getOffsetFromServerListAsync(Ljava/lang/String;II)V",
               "    .locals 0\n"
               "    invoke-static {p2}, Lcom/miniclip/offline/Offline;->networkTimeResponse(I)V\n"
               "    return-void\n",
               "report a 0.0s NTP offset immediately (device clock)")
replace_method("com.miniclip.NTP.NtpHandler",
               ".method public getOffsetFromServer(Ljava/lang/String;)D",
               "    .locals 2\n    const-wide/16 v0, 0x0\n    return-wide v0\n",
               "synchronous NTP lookup -> 0.0s offset")

# ---------------------------------------------------------------------------
# Connectivity checks
# ---------------------------------------------------------------------------
replace_method("com.miniclip.Ping.PingHandler",
               ".method public simplePingAsync(Ljava/lang/String;II)V",
               "    .locals 0\n"
               "    invoke-static {p2}, Lcom/miniclip/offline/Offline;->pingResponse(I)V\n"
               "    return-void\n",
               "no TCP ping; report unreachable")
replace_method("com.miniclip.Ping.PingHandler",
               ".method private simplePing(Ljava/lang/String;I)Z", FALSE, "no TCP ping")
replace_method("com.miniclip.nativeJNI.cocojava", ".method public isOnline()Z", FALSE,
               "offline edition never uses the network")

# ---------------------------------------------------------------------------
# Newsfeed (services.miniclippt.com/newsfeed) and GCM push
# ---------------------------------------------------------------------------
replace_method("com.miniclip.newsfeed.Newsfeed", ".method public update()I", FALSE, "no newsfeed polling")
replace_method("com.miniclip.newsfeed.Newsfeed", ".method public checkServer()I", FALSE, "no newsfeed download")
replace_method("com.miniclip.newsfeed.NewsfeedDialog$URLImageView",
               ".method public loadFromURL(Ljava/lang/String;)Z", FALSE, "no remote images")

# ---------------------------------------------------------------------------
# Purchases (Google Play billing, GetJar) and receipt validation: coin and gem
# packs are granted locally through the game's own success callback
# ---------------------------------------------------------------------------
replace_method("com.miniclip.nativeJNI.InAppActivity",
               ".method public onCreate(Landroid/os/Bundle;)V",
               "    .locals 1\n"
               "    invoke-super {p0, p1}, Lcom/miniclip/nativeJNI/cocojava;->onCreate(Landroid/os/Bundle;)V\n"
               "    const/4 v0, 0x0\n"
               "    iput-boolean v0, p0, Lcom/miniclip/nativeJNI/InAppActivity;->mHelperReady:Z\n"
               "    iput-boolean v0, p0, Lcom/miniclip/nativeJNI/InAppActivity;->mBusy:Z\n"
               "    return-void\n",
               "do not bind to the Play Store billing service")
replace_method("com.miniclip.nativeJNI.InAppActivity",
               ".method public onActivityResult(IILandroid/content/Intent;)V",
               "    .locals 0\n"
               "    invoke-super {p0, p1, p2, p3}, Lcom/miniclip/nativeJNI/cocojava;->onActivityResult(IILandroid/content/Intent;)V\n"
               "    return-void\n",
               "no IabHelper")
for m in ("requestPurchaseAct", "requestPurchaseActManaged"):
    replace_method("com.miniclip.nativeJNI.InAppActivity",
                   ".method public %s(Ljava/lang/String;)V" % m,
                   "    .locals 0\n"
                   "    invoke-static {}, Lcom/miniclip/offline/Offline;->purchaseSucceeded()V\n"
                   "    return-void\n",
                   "grant the pack locally (successful purchase, no store)")
replace_method("com.miniclip.utils.ReceiptValidator",
               ".method public static ReceiptValidator_validate(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;II)V",
               "    .locals 0\n"
               "    invoke-static {p3, p4}, Lcom/miniclip/offline/Offline;->receiptValidated(II)V\n"
               "    return-void\n",
               "receipt answered 'valid' locally (original bypassValidation path)")
stub_void("com.miniclip.utils.ReceiptValidator",
          ".method public validate(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Lcom/miniclip/utils/ReceiptValidator$ReceiptValidatorResponseCallback;)V",
          "no HTTP POST")
stub_void("com.miniclip.GetJar.GetJar",
          ".method public static setup(Landroid/app/Activity;Lcom/miniclip/GetJar/GetJar$GetJarListener;Ljava/lang/String;Ljava/lang/String;Landroid/os/ResultReceiver;)V",
          "GetJar SDK disabled")
replace_method("com.miniclip.GetJar.GetJar",
               ".method public static inAppPurchase(Ljava/lang/String;ILjava/lang/String;III)V",
               "    .locals 0\n"
               "    sput p3, Lcom/miniclip/nativeJNI/cocojava;->mInAppCallback:I\n"
               "    sput p4, Lcom/miniclip/nativeJNI/cocojava;->mInAppSelf:I\n"
               "    sput-object p0, Lcom/miniclip/nativeJNI/cocojava;->mProductId:Ljava/lang/String;\n"
               "    invoke-static {}, Lcom/miniclip/offline/Offline;->purchaseSucceeded()V\n"
               "    return-void\n",
               "GetJar purchases -> granted locally")
replace_method("com.miniclip.GetJar.GetJar", ".method public static recommendedPrice([II)[I",
               "    .locals 0\n    return-object p0\n", "no GetJar price localisation")
replace_method("com.miniclip.GetJar.GetJar", ".method public static recommendedPrice(I)I",
               "    .locals 0\n    return p0\n", "no GetJar price localisation")
replace_method("com.miniclip.dinopets.DinoPetsActivity",
               ".method public onGetJarInAppPurchase(Ljava/lang/String;ILjava/lang/String;III)V",
               "    .locals 0\n"
               "    sput p4, Lcom/miniclip/nativeJNI/cocojava;->mInAppCallback:I\n"
               "    sput p5, Lcom/miniclip/nativeJNI/cocojava;->mInAppSelf:I\n"
               "    sput-object p1, Lcom/miniclip/nativeJNI/cocojava;->mProductId:Ljava/lang/String;\n"
               "    invoke-static {}, Lcom/miniclip/offline/Offline;->purchaseSucceeded()V\n"
               "    return-void\n",
               "GetJar page -> granted locally")

# ---------------------------------------------------------------------------
# Facebook: disabled (mUSE_FACEBOOK=false below); explain user-initiated actions
# ---------------------------------------------------------------------------
for h in (".method public static faceBook_authorizeAndRun(Ljava/lang/String;Ljava/lang/Runnable;)V",
          ".method public static faceBook_dialog(Ljava/lang/String;Ljava/lang/String;)V"):
    replace_method("com.miniclip.nativeJNI.cocojava", h,
                   "    .locals 0\n"
                   "    invoke-static {}, Lcom/miniclip/offline/Offline;->facebookUnavailable()V\n"
                   "    return-void\n",
                   "Facebook needs graph.facebook.com")
stub_void("com.miniclip.nativeJNI.cocojava",
          ".method public static faceBook_reauthorizeWithPublishPermissions(Ljava/lang/String;)V", "Facebook disabled")
stub_void("com.miniclip.nativeJNI.cocojava",
          ".method public static faceBook_request(Ljava/lang/String;Ljava/lang/String;I)V", "Facebook disabled")

# External web links (More games, Rate us, Facebook page, update prompts)
replace_method("com.miniclip.nativeJNI.cocojava", ".method private openURL(Ljava/lang/String;)V",
               "    .locals 0\n"
               "    invoke-static {}, Lcom/miniclip/offline/Offline;->linkUnavailable()V\n"
               "    return-void\n",
               "external Miniclip/Play/Facebook pages are gone")

# ---------------------------------------------------------------------------
# Analytics / attribution / ads SDKs: entry points become no-ops
# ---------------------------------------------------------------------------
for h in (".method public static ADX_init(Z)V", ".method public static ADX_reportAppOpen()V",
          ".method public static ADX_sendEvent(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V"):
    stub_void("com.miniclip.nativeJNI.cocojava", h, "AdX attribution disabled")
replace_method("com.miniclip.nativeJNI.cocojava", ".method public static ADX_getReferral()Ljava/lang/String;",
               "    .locals 1\n    const-string v0, \"\"\n    return-object v0\n", "AdX attribution disabled")

for h in ("clearSuperProperties()V", "flush()V", "identify(Ljava/lang/String;)V",
          "initializeWithAPIToken(Ljava/lang/String;)V", "peopleIdentify(Ljava/lang/String;)V",
          "peopleSet(Ljava/lang/String;)V", "peopleSetPushRegistrationId(Ljava/lang/String;)V",
          "peopleTrackCharge(DLjava/lang/String;)V", "registerSuperProperties(Ljava/lang/String;)V",
          "setFlushInterval(I)V", "setup(Landroid/app/Activity;Lcom/miniclip/Mixpanel/Mixpanel$MixpanelListener;)V",
          "track(Ljava/lang/String;Ljava/lang/String;)V"):
    stub_void("com.miniclip.Mixpanel.Mixpanel", ".method public static " + h, "Mixpanel analytics disabled")

for h in ("startSession(Landroid/content/Context;Ljava/lang/String;Ljava/lang/String;)V",
          "eventJSON(Ljava/lang/String;Lorg/json/JSONObject;)V"):
    stub_void("com.apsalar.sdk.Apsalar", ".method public static " + h, "Apsalar analytics disabled")

for h in ("onStartSession(Landroid/content/Context;Ljava/lang/String;)V", "onEndSession(Landroid/content/Context;)V",
          "logEvent(Ljava/lang/String;)V", "logEvent(Ljava/lang/String;Ljava/util/Map;)V",
          "logEvent(Ljava/lang/String;Ljava/util/Map;Z)V", "logEvent(Ljava/lang/String;Z)V",
          "endTimedEvent(Ljava/lang/String;)V"):
    stub_void("com.flurry.android.FlurryAgent", ".method public static " + h, "Flurry analytics disabled")

for h in ("onCreate(Landroid/app/Activity;Ljava/lang/String;Ljava/lang/String;Lcom/chartboost/sdk/ChartboostDelegate;)V",
          "startSession()V", "onStart(Landroid/app/Activity;)V", "onStop(Landroid/app/Activity;)V",
          "onDestroy(Landroid/app/Activity;)V"):
    stub_void("com.chartboost.sdk.Chartboost", ".method public " + h, "Chartboost ads disabled")
replace_method("com.chartboost.sdk.Chartboost", ".method public onBackPressed()Z", FALSE, "Chartboost ads disabled")

for h in ("activityStart(Landroid/app/Activity;)V", "activityStop(Landroid/app/Activity;)V"):
    stub_void("com.google.analytics.tracking.android.EasyTracker", ".method public " + h, "Google Analytics v2 disabled")
for h in ("startNewSession(Ljava/lang/String;Landroid/content/Context;)V",
          "startNewSession(Ljava/lang/String;ILandroid/content/Context;)V", "stopSession()V",
          "trackEvent(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;I)V", "trackPageView(Ljava/lang/String;)V"):
    stub_void("com.google.android.apps.analytics.GoogleAnalyticsTracker", ".method public " + h,
              "Google Analytics v1 disabled")
replace_method("com.google.android.apps.analytics.GoogleAnalyticsTracker", ".method public dispatch()Z", FALSE,
               "Google Analytics v1 disabled")

# ---------------------------------------------------------------------------
# Activity: feature flags + lifecycle without WiFi lock / trackers
# ---------------------------------------------------------------------------
A = "com.miniclip.dinopets.DinoPetsActivity"
replace_text(A, "    sput-boolean v7, Lcom/miniclip/dinopets/DinoPetsActivity;->mUSE_C2DM:Z\n",
             "    sput-boolean v6, Lcom/miniclip/dinopets/DinoPetsActivity;->mUSE_C2DM:Z\n",
             "no GCM push registration")
replace_text(A, "    sput-boolean v7, Lcom/miniclip/dinopets/DinoPetsActivity;->mUSE_FACEBOOK:Z\n",
             "    sput-boolean v6, Lcom/miniclip/dinopets/DinoPetsActivity;->mUSE_FACEBOOK:Z\n",
             "no Facebook session")
replace_text(A, "    sput-boolean v6, Lcom/miniclip/dinopets/DinoPetsActivity;->mUSE_ADS:Z\n",
             "    sput-boolean v6, Lcom/miniclip/dinopets/DinoPetsActivity;->mUSE_ADS:Z\n"
             "\n    sput-boolean v6, Lcom/miniclip/dinopets/DinoPetsActivity;->mUSE_NEWSFEED:Z\n",
             "no Miniclip newsfeed")
replace_method(A, ".method public onStart()V",
               "    .locals 1\n"
               "    invoke-super {p0}, Lcom/miniclip/nativeJNI/InAppActivity;->onStart()V\n"
               "    sget-object v0, Lcom/miniclip/dinopets/DinoPetsActivity;->mGLView:Lcom/miniclip/nativeJNI/ClearGLSurfaceView;\n"
               "    invoke-static {v0}, Lcom/miniclip/utils/ReceiptValidator;->setGLView(Lcom/miniclip/nativeJNI/ClearGLSurfaceView;)V\n"
               "    return-void\n",
               "no WiFi lock / EasyTracker / Chartboost")
replace_method(A, ".method public onStop()V",
               "    .locals 0\n"
               "    invoke-super {p0}, Lcom/miniclip/nativeJNI/InAppActivity;->onStop()V\n"
               "    return-void\n",
               "no WiFi lock / EasyTracker / Chartboost")

# ---------------------------------------------------------------------------
# Local reminders: same content, built with Notification.Builder (API 23+ safe)
# ---------------------------------------------------------------------------
replace_method("com.miniclip.dinopets.BootReceiver",
               ".method public onReceive(Landroid/content/Context;Landroid/content/Intent;)V",
               "    .locals 1\n"
               "    sget-object v0, Lcom/miniclip/dinopets/BootReceiver;->intentClass:Ljava/lang/Class;\n"
               "    if-nez v0, :have_class\n"
               "    const-class v0, Lcom/miniclip/dinopets/DinoPetsActivity;\n"
               "    :have_class\n"
               "    invoke-static {p1, p2, v0}, Lcom/miniclip/offline/Offline;->showLocalNotification(Landroid/content/Context;Landroid/content/Intent;Ljava/lang/Class;)V\n"
               "    return-void\n",
               "setLatestEventInfo() was removed in Android 6.0")


def apply_method(text, header, body):
    lines = text.split("\n")
    idx = [i for i, l in enumerate(lines) if l == header]
    if len(idx) != 1:
        raise SystemExit("ABORT: method header %r found %d times" % (header, len(idx)))
    start = idx[0]
    end = next(i for i in range(start, len(lines)) if lines[i] == ".end method")
    new = [header] + body.rstrip("\n").split("\n") + [".end method"]
    return "\n".join(lines[:start] + new + lines[end + 1:])


def main():
    global SMALI, HELPERS
    SMALI, HELPERS = sys.argv[1], sys.argv[2]
    for e in EDITS:
        p = path(e[1])
        text = open(p, encoding="utf-8").read()
        if e[0] == "method":
            _, cls, header, body, why = e
            text = apply_method(text, header, body)
            print("  [ok] %-45s %-60s %s" % (cls.split(".")[-1], header.split(" ")[-1][:60], why))
        else:
            _, cls, old, new, why, count = e
            n = text.count(old)
            if n != count:
                raise SystemExit("ABORT: %s: expected %d occurrence(s) of %r, found %d" % (cls, count, old, n))
            text = text.replace(old, new)
            print("  [ok] %-45s %-60s %s" % (cls.split(".")[-1], "(text edit)", why))
        open(p, "w", encoding="utf-8").write(text)
    # add helper classes
    dst = os.path.join(SMALI, "com", "miniclip", "offline")
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(os.path.join(HELPERS, "com", "miniclip", "offline"), dst)
    print("  [ok] added helper classes:", ", ".join(sorted(os.listdir(dst))))


if __name__ == "__main__":
    main()
