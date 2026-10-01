package com.wso.tvt;

/** Private device-access inputs, distinct from account and P2P tokens. */
public final class DeviceCredential {
    private final String token, deviceId;
    private final long expiry;
    private final int timeout;
    public DeviceCredential(String token, long expiry, int timeout, String deviceId) {
        if (token == null || token.isEmpty() || token.length() > 4096 || deviceId == null
                || deviceId.isEmpty() || deviceId.length() > 4096 || expiry <= 0 || timeout <= 0) {
            throw new IllegalArgumentException("Invalid private device credential");
        }
        this.token = token; this.expiry = expiry; this.timeout = timeout; this.deviceId = deviceId;
    }
    String token() { return token; }
    String deviceId() { return deviceId; }
    long expiry() { return expiry; }
    int timeout() { return timeout; }
    @Override public String toString() { return "DeviceCredential[private]"; }
}
