package com.miniclip.nativeJNI;

/** Compile-time stub: only the members referenced by com.miniclip.offline. */
public class CocoJNI {
    public static native void MnetworkTimeResponce(int callback, double offset, int error);

    public static native void MsimplePingResponce(int callback, int result);

    public static native void MsetInAppResponce(int responce, int callback, int self, String productId,
                                                String data, String signature);
}
