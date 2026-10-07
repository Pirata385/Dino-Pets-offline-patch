package com.miniclip.offline;

import android.app.Activity;
import android.app.Notification;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.widget.Toast;

import com.miniclip.nativeJNI.ClearGLSurfaceView;
import com.miniclip.nativeJNI.CocoJNI;
import com.miniclip.nativeJNI.cocojava;
import com.miniclip.utils.ReceiptValidator;

import java.lang.reflect.Method;

/**
 * Local replacements for services that the original game reached over the
 * network.  Patched smali code calls into this class (see patches/smali).
 */
public final class Offline {
    public static final String TAG = "DinoPetsOffline";

    public static final String MSG_PURCHASES =
            "Purchases are not available in the offline edition.";
    public static final String MSG_FACEBOOK =
            "Facebook features are not available in the offline edition.";
    public static final String MSG_LINK =
            "This online feature is not available in the offline edition.";

    private Offline() {
    }

    static void queueOnGL(Runnable r) {
        ClearGLSurfaceView v = cocojava.mGLView;
        if (v != null) {
            v.queueEvent(r);
        } else {
            Log.w(TAG, "GL view not ready, dropping callback");
        }
    }

    /** Short, non-blocking notice for features that needed a server. */
    public static void toast(final String msg) {
        Log.i(TAG, msg);
        final Context c = cocojava.mContext;
        if (c instanceof Activity) {
            ((Activity) c).runOnUiThread(new Runnable() {
                public void run() {
                    try {
                        Toast.makeText(c, msg, Toast.LENGTH_LONG).show();
                    } catch (Throwable t) {
                        Log.w(TAG, "toast failed", t);
                    }
                }
            });
        }
    }

    /**
     * Replacement for the NTP lookup (pool.ntp.org): report success with a
     * 0.0 s offset, i.e. the device clock is the game's time source.
     */
    public static void networkTimeResponse(final int callback) {
        queueOnGL(new Runnable() {
            public void run() {
                CocoJNI.MnetworkTimeResponce(callback, 0.0d, 0);
            }
        });
    }

    /** Replacement for the TCP "ping": the network is never used. */
    public static void pingResponse(final int callback) {
        queueOnGL(new Runnable() {
            public void run() {
                CocoJNI.MsimplePingResponce(callback, 1);
            }
        });
    }

    /**
     * Google Play / GetJar purchases cannot complete without their servers.
     * Report a failed transaction straight away so the game never waits.
     */
    public static void purchaseUnavailable() {
        toast(MSG_PURCHASES);
        queueOnGL(new Runnable() {
            public void run() {
                cocojava.mInAppResponce = -1;
                CocoJNI.MsetInAppResponce(-1, cocojava.mInAppCallback, cocojava.mInAppSelf,
                        cocojava.mProductId, "", "");
            }
        });
    }

    /** Receipt validation used services.miniclippt.com; answer "failed". */
    public static void receiptValidationUnavailable(final int self, final int callback) {
        queueOnGL(new Runnable() {
            public void run() {
                ReceiptValidator.MvalidateResponse(self, -1, "offline", callback);
            }
        });
    }

    public static void facebookUnavailable() {
        toast(MSG_FACEBOOK);
    }

    public static void linkUnavailable() {
        toast(MSG_LINK);
    }

    /**
     * Same behaviour as the original BootReceiver.onReceive() (local
     * "your pets miss you" reminders scheduled by the game), but built with
     * Notification.Builder because Notification.setLatestEventInfo() no longer
     * exists on Android 6.0+.
     */
    public static void showLocalNotification(Context context, Intent alarmIntent, Class<?> activity) {
        // keys used by com.miniclip.dinopets.BootReceiver.setupAlarm()
        final String prefTitleKey = "Minipets.Notification.Title";
        final String prefTextKey = "Minipets.Notification.Text";
        final String notificationIdKey = "Minipets.Notification.Id";
        try {
            Bundle extras = alarmIntent.getExtras();
            if (extras == null) {
                // the original threw (and swallowed) a NullPointerException here
                Log.d(TAG, "alarm without extras ignored");
                return;
            }
            int nid = alarmIntent.getIntExtra(notificationIdKey, 0);
            String payload = null;
            if (extras.containsKey("user_dict")) {
                payload = extras.getString("user_dict");
            }
            SharedPreferences settings = context.getSharedPreferences(String.format("%d", nid), 0);
            String title = settings.getString(prefTitleKey, "Visit Shelter");
            String text = settings.getString(prefTextKey, "The animals in Dino Pets miss you. Pay them a visit!");

            Intent intent = new Intent(context, activity);
            intent.setAction("android.intent.action.MAIN");
            intent.addCategory("android.intent.category.LAUNCHER");
            intent.addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            if (payload != null) {
                intent.putExtra("user_dict", payload);
            }
            int icon = context.getResources().getIdentifier("icon", "drawable", context.getPackageName());
            PendingIntent pi = PendingIntent.getActivity(context, 0, intent, 0);
            NotificationManager nm = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
            nm.notify(nid, build(context, icon, title, text, pi));
        } catch (Throwable t) {
            Log.w(TAG, "local notification failed", t);
        }
    }

    @SuppressWarnings("deprecation")
    private static Notification build(Context context, int icon, String title, String text, PendingIntent pi)
            throws Exception {
        if (Build.VERSION.SDK_INT >= 11) {
            Notification.Builder b = new Notification.Builder(context)
                    .setSmallIcon(icon)
                    .setContentTitle(title)
                    .setContentText(text)
                    .setTicker(title)
                    .setWhen(System.currentTimeMillis())
                    .setContentIntent(pi)
                    .setAutoCancel(true)
                    .setDefaults(Notification.DEFAULT_LIGHTS);
            // Android 5+ draws the small icon of apps targeting API 21+ as a
            // silhouette; show the full-colour game icon next to the text too.
            Bitmap large = BitmapFactory.decodeResource(context.getResources(), icon);
            if (large != null) {
                b.setLargeIcon(large);
            }
            return Build.VERSION.SDK_INT >= 16 ? b.build() : b.getNotification();
        }
        Notification n = new Notification(icon, title, System.currentTimeMillis());
        n.defaults |= Notification.DEFAULT_LIGHTS;
        n.flags |= Notification.FLAG_AUTO_CANCEL;
        Method m = Notification.class.getMethod("setLatestEventInfo", Context.class,
                CharSequence.class, CharSequence.class, PendingIntent.class);
        m.invoke(n, context, title, text, pi);
        return n;
    }
}
