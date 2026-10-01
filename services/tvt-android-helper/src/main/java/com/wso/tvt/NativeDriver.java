package com.wso.tvt;

/** Injectable JNI boundary. Production uses JniNativeDriver; fakes exist only under tests. */
public interface NativeDriver {
    void bind(CallbackSink callback);
    boolean init(RuntimeConfig config);
    boolean start();
    int connect(DeviceCredential credential);
    int requestLive(int connection, int channel, int stream, int mode, long context);
    boolean closeLive(int task);
    void disconnect(int connection);
    void stop();
    void quit();
}
