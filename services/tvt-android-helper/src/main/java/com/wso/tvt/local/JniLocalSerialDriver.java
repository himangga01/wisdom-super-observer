package com.wso.tvt.local;

import com.tvt.network.NatTraveral;
import java.util.Arrays;

/** Created explicitly inside the isolated Android process; no host eager library load. */
public final class JniLocalSerialDriver implements LocalSerialDriver {
    private final NatTraveral nat;
    private long ownedEcho;
    private LocalSerialConfig config;
    private boolean allocationAttempted;
    private boolean retired;
    private JniLocalSerialDriver(NatTraveral value) { nat = value; }
    public static JniLocalSerialDriver createAndroid() { return new JniLocalSerialDriver(NatTraveral.getInstance()); }
    public synchronized long allocate() {
        if (allocationAttempted) throw new IllegalStateException("Driver allocation already attempted");
        allocationAttempted = true; ownedEcho = nat.InitEchoClient(); return ownedEcho;
    }
    private void owned(long echo) {
        if (echo == 0 || echo != ownedEcho || retired) throw new IllegalStateException("Unowned/retired echo");
    }
    public void bind(final long echo, final Callbacks callbacks) {
        owned(echo);
        nat.addNat2ConnStatusCallback(echo, (connected, type, detail) -> callbacks.connection(echo, connected, type, detail));
        try { nat.addNat2RecvDataCallback(echo, bytes -> callbacks.data(echo, bytes)); }
        catch (RuntimeException failure) { nat.removeNat2ConnStatusCallback(echo); throw failure; }
    }
    public void removeCallbacks(long echo) {
        owned(echo); nat.removeNat2ConnStatusCallback(echo); nat.removeNat2RecvDataCallback(echo);
    }
    public int discover(long echo, LocalSerialConfig value) {
        owned(echo); config = value;
        byte[] opaque66 = new byte[66];
        try {
            return nat.GetVersionType(echo, value.serial(), value.nat1Host(), value.nat1Port(),
                    value.nat2Host(), value.nat2Port(), opaque66, value.networkFlag(), value.traversalMode(),
                    value.disableUPnP(), value.privateFilesPath(), value.platform(), value.appVersion(), value.appName(), value.model());
        } finally { Arrays.fill(opaque66, (byte)0); } // Best effort only; no native memory-zeroing claim.
    }
    public int openTransport(long echo, LocalSerialConfig value) {
        owned(echo); nat.SetConnectTraversalMode(echo, value.traversalMode());
        return nat.SetValue(echo, value.serial(), value.nat1Host(), value.nat1Port(), value.traversalMode());
    }
    public int connectType(long echo) { owned(echo); return nat.GetConnectType(echo); }
    public int error(long echo) { owned(echo); return nat.GetErrorCode(echo); }
    public int send(long echo, byte[] buffer, int length) { owned(echo); config.buffer(buffer, length); return nat.SendData(echo, buffer, length); }
    public int receive(long echo, byte[] buffer, int length) { owned(echo); config.buffer(buffer, length); return nat.RecvData(echo, buffer, length); }
    public boolean interrupt(long echo) {
        owned(echo); nat.Interrupt(echo);
        return false; // A JNI integer alone is not a proved cleanup completion contract.
    }
    public boolean destroy(long echo) {
        owned(echo);
        try { nat.destroyEchoClientResult(echo); }
        finally { retired = true; }
        return false; // Production process must be replaced after uncertain cleanup.
    }
}
