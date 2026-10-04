package com.tvt.network;

import java.util.concurrent.ConcurrentHashMap;

/** Exact APK JNI identity. Host class inspection never loads the Android ELF. */
public final class NatTraveral {
    public static final int NAT_CONN_TYPE_LAN = 2, NAT_CONN_TYPE_P2P = 1,
            NAT_CONN_TYPE_RELAY = 8, NAT_CONN_TYPE_UPNP = 4;
    private static NatTraveral instance;
    private static boolean creationAttempted;
    private final ConcurrentHashMap<Long, a> status = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<Long, b> receive = new ConcurrentHashMap<>();
    public interface a { void a(boolean connected, int type, String detail); }
    public interface b { int a(byte[] bytes); }

    public NatTraveral() {
        synchronized (NatTraveral.class) {
            String vm = System.getProperty("java.vm.name", "");
            if (!vm.equals("Dalvik") && !vm.equals("ART"))
                throw new IllegalStateException("Android runtime required");
            if (creationAttempted) throw new IllegalStateException("Native singleton already attempted");
            creationAttempted = true;
            System.loadLibrary("NatTraveral");
            // Return values do not establish connection or successful cleanup.
            InitGlobal();
            Nat2EnablePrintLog(false);
            instance = this;
        }
    }
    public static synchronized NatTraveral getInstance() {
        if (instance == null) new NatTraveral();
        return instance;
    }
    public static void LogPrintCallback(String ignored) { /* Never format or forward source logs. */ }
    public long InitEchoClient() { return Initialize(); }
    public void InitNatGlobal() { /* Constructor owns the only global bootstrap. */ }
    public void DestroyEchoClient(long echo) { if (echo != 0) destroyEchoClientResult(echo); }
    public int destroyEchoClientResult(long echo) {
        if (echo == 0) throw new IllegalArgumentException("Zero echo");
        removeNat2ConnStatusCallback(echo);
        removeNat2RecvDataCallback(echo);
        return Destroy(echo);
    }
    public void addNat2ConnStatusCallback(long echo, a callback) {
        if (echo == 0 || callback == null) throw new IllegalArgumentException("Callback ownership");
        if (status.putIfAbsent(echo, callback) != null) throw new IllegalStateException("Echo callback already owned");
    }
    public void addNat2RecvDataCallback(long echo, b callback) {
        if (echo == 0 || callback == null) throw new IllegalArgumentException("Callback ownership");
        if (receive.putIfAbsent(echo, callback) != null) throw new IllegalStateException("Echo callback already owned");
    }
    public void removeNat2ConnStatusCallback(long echo) { status.remove(echo); }
    public void removeNat2RecvDataCallback(long echo) { receive.remove(echo); }
    public void Nat2ConnStatusCallback(long echo, boolean connected, int type, String detail) {
        a callback = status.get(echo);
        if (callback != null) callback.a(connected, type, detail);
    }
    public int Nat2RecvDataCallback(long echo, byte[] bytes) {
        b callback = receive.get(echo);
        return callback == null ? 0 : callback.a(bytes);
    }

    private native int Destroy(long echo);
    private native int InitGlobal();
    private native long Initialize();
    public native String GetConnInfo(long echo);
    public native int GetConnectType(long echo);
    public native int GetErrorCode(long echo);
    public native long GetLastRecvTime(long echo);
    public native int GetTraversalMode(long echo);
    public native int GetVersionType(long echo, String serial, String nat1, int nat1Port,
            String nat2, int nat2Port, byte[] opaque66, int networkFlag, int traversalMode,
            boolean disableUPnP, String path, String platform, String version, String app, String model);
    public native int Interrupt(long echo);
    public native int Nat2EnablePrintLog(boolean enabled);
    public native String QueryDevInfo(long echo, String serial, String nat1, int nat1Port,
            String nat2, int nat2Port, String path, String platform, String version, String app, String model);
    public native int RecvData(long echo, byte[] buffer, int length);
    public native int SendData(long echo, byte[] buffer, int length);
    public native int SetConnectTraversalMode(long echo, int mode);
    public native boolean SetDisableConnFlag(int flags);
    public native boolean SetLanIps(String ips);
    public native int SetValue(long echo, String serial, String nat1, int port, int mode);
}
