package com.wso.tvt;

import com.tvt.network.NetClientProtocal;

/** Real production driver. No host fallback or simulated native result. */
public final class JniNativeDriver implements NativeDriver {
    private NetClientProtocal instance;
    private JniNativeDriver() { }
    public static JniNativeDriver createOnAndroid() {
        NetClientProtocal.loadOnAndroid();
        return new JniNativeDriver();
    }
    @Override public void bind(CallbackSink callback) {
        if (instance != null) { throw new IllegalStateException("Native callback already bound"); }
        instance = new NetClientProtocal(callback);
    }
    @Override public boolean init(RuntimeConfig config) { return instance.initialize(config.nativeJson()); }
    @Override public boolean start() { return instance.Start(); }
    @Override public int connect(DeviceCredential credential) {
        return instance.connectByToken(credential.token(), credential.expiry(), credential.timeout(), credential.deviceId());
    }
    @Override public int requestLive(int connection, int channel, int stream, int mode, long context) {
        return instance.requestLive(connection, channel, stream, mode, context);
    }
    @Override public boolean closeLive(int task) { return instance.closeLive(task); }
    @Override public void disconnect(int connection) { instance.disconnect(connection); }
    @Override public void stop() { instance.Stop(); }
    @Override public void quit() {
        instance.Quit();
        instance = null; // Only after native Quit returned: global JNI reference release is runtime-unverified.
    }
    @Override public String toString() { return "JniNativeDriver[private]"; }
}
