package com.tvt.network;

import com.wso.tvt.CallbackKind;
import com.wso.tvt.CallbackSink;

/** APK-compatible binary class. Loading is explicit and Android-only. Never log native text. */
public final class NetClientProtocal {
    private static boolean loaded;
    private final CallbackSink callback;
    public NetClientProtocal(CallbackSink callback) {
        if (callback == null) { throw new IllegalArgumentException("Callback is required"); }
        this.callback = callback;
    }
    public static synchronized void loadOnAndroid() {
        String vm = System.getProperty("java.vm.name", "");
        if (!"Dalvik".equals(vm) && !"ART".equals(vm)) {
            throw new IllegalStateException("Android runtime is required");
        }
        try { Class.forName("android.os.Build", false, NetClientProtocal.class.getClassLoader()); }
        catch (ClassNotFoundException absent) { throw new IllegalStateException("Android runtime is required"); }
        if (!loaded) { System.loadLibrary("NetClientProtocal"); loaded = true; }
    }

    private native int ConnectDevByToken(String token, long expiry, int timeout, String deviceId);
    private native void Disconnect(int connection);
    private native int FindCloudStorageEncryptPwd(int a, long b, String c, long d);
    private native boolean Init(String config);
    private native boolean JniCloseLiveStream(int task);
    private native boolean JniCloseLiveTalkBack(int task);
    private native boolean JniClosePlayback(int task);
    private native int ModifyCloudStorageEncryptByAccount(int a, long b, String c, String d, long e);
    private native int ModifyCloudStorageEncryptByPwd(int a, String b, String c, long d);
    private native int PlaybackSearchLogRec(int a, int b, int c, long d, short e, short f, long g);
    private native int PlaybackSearchRecChannel(int a, long b, int c, int d, long e);
    private native int PlaybackSearchRecDate(int a, long b, short c, short d, int[] e, long f);
    private native int QueryCloudStorageEncryptStatus(int a, long b);
    private native boolean RegisterNotifyObserver(int a);
    private native int RenewDaToken(int a, String b, long c);
    private native int RequestApiTransport(int a, byte[] b, int c, long d);
    private native int RequestLiveStreamTask(int a, int b, int c, int d, long e);
    private native int RequestLiveTalkBack(int a, int b, int c, int d, long e);
    private native int RequestPlaybackStream(int a, int b, int c, long d, int e, int f, long g);
    private native int SearchKeyFrameByTimeTask(int a, int b, int c, int d, int e, int f, long g);
    private native int SetSuperUserPassword(int a, long b, String c, String d, long e);
    private native int SnapLivePictureTask(int a, int b, long c);
    private native int Subscribe(int a, String b, boolean c, long d);
    private native boolean UnRegisterNotifyObserver(int a);
    public native boolean ChangeLiveStream(int a, int b, int c, String d, String e, int f, int g, int h, int i);
    public native boolean ChangeToKeyFramePlay(int a, long b, int c, boolean d);
    public native boolean ChangeToKeyFramePlayRewind(int a, long b, int c, boolean d);
    public native boolean CloseLiveAudio(int a);
    public native boolean ClosePlaybackAudio(int a);
    public native boolean ConnectNatServer(String a);
    public native void DisConnectNatServer();
    public native int GetAuthorizationCode(int a, int b, long c);
    public native int GetPTZInfo(int a, int b, int c, long d);
    public native String GetReqLiveStatInfo(int a);
    public native byte[] GetTransportEncryptKey(int a);
    public native boolean IsConnected(int a);
    public native boolean OpenLiveAudio(int a);
    public native boolean OpenPlaybackAudio(int a);
    public native void Quit();
    public native boolean RequestPTZ3DControl(int a, int b, int c, int d, int e);
    public native boolean SendLiveTalkBackData(int a, int b, byte[] c, int d, String e);
    public native int SendPTZCtlCmd(int a, int b, int c, int d, int e);
    public native boolean SendPlaybackIndex(int a, int b);
    public native boolean SetDisableConnFlag(int a);
    public native boolean SetLanIps(String a);
    public native boolean Start();
    public native void Stop();
    public native void setLogDebug(boolean a);

    public boolean initialize(String privateJson) { return Init(privateJson); }
    public int connectByToken(String token, long expiry, int timeout, String deviceId) {
        return ConnectDevByToken(token, expiry, timeout, deviceId);
    }
    public void disconnect(int connection) { Disconnect(connection); }
    public int requestLive(int connection, int channel, int stream, int mode, long context) {
        return RequestLiveStreamTask(connection, channel, stream, mode, context);
    }
    public boolean closeLive(int task) { return JniCloseLiveStream(task); }
    // Playback/Talk declarations retained, but routing, pacing and consumers require their own acceptance.

    private void OnNetClientConnect(int a, int b, int c, byte[] data, int length) {
        callback.onCallback(CallbackKind.CONNECT, a, b, c, 0, data, length, 0L);
    }
    private void OnNetClientDisconnect(int a) {
        callback.onCallback(CallbackKind.DISCONNECT, a, 0, 0, 0, null, 0, 0L);
    }
    private void OnNetClientTaskData(int a, byte[] data, int length, long context) {
        callback.onCallback(CallbackKind.TASK_DATA, a, 0, 0, 0, data, length, context);
    }
    private void OnNetClientTaskErr(int a, int b, long context) {
        callback.onCallback(CallbackKind.TASK_ERR, a, b, 0, 0, null, 0, context);
    }
    private void OnSwitchConnect(int a, int b) {
        callback.onCallback(CallbackKind.SWITCH_CONNECT, a, b, 0, 0, null, 0, 0L);
    }
    private void OnRenewDaToken(int a) {
        callback.onCallback(CallbackKind.RENEW_TOKEN, a, 0, 0, 0, null, 0, 0L);
    }
    private void OnConnectNatServer(boolean connected) {
        callback.onCallback(CallbackKind.NAT_CONNECT, connected ? 1 : 0, 0, 0, 0, null, 0, 0L);
    }
    private void OnDisConnectNatServer() {
        callback.onCallback(CallbackKind.NAT_DISCONNECT, 0, 0, 0, 0, null, 0, 0L);
    }
    private void OnRecvNatServerTransData(byte[] data, int length) {
        callback.onCallback(CallbackKind.NAT_DATA, 0, 0, 0, 0, data, length, 0L);
    }
    private void OnNetClientNotifyData(int a, byte[] data, int length) {
        callback.onCallback(CallbackKind.NOTIFY_DATA, a, 0, 0, 0, data, length, 0L);
    }
    private void OnNetClientSubscribeData(int a, int b, int c, int d, byte[] data, int length) {
        callback.onCallback(CallbackKind.SUBSCRIBE_DATA, a, b, c, d, data, length, 0L);
    }
    private static void LogPrintCallback(String privateNativeText) { /* Intentionally discard secret-bearing native logs. */ }
    @Override public String toString() { return "NetClientProtocal[private]"; }
}
