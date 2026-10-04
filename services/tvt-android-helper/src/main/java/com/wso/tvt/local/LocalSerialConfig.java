package com.wso.tvt.local;

import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;

/** Private helper configuration. Structural validation is not actor/store authority. */
public final class LocalSerialConfig {
    private final String serial, nat1Host, nat2Host, privateFilesPath, platform, appVersion, appName, model;
    private final int nat1Port, nat2Port, networkFlag, traversalMode, maxBufferBytes, maxQueuedEvents, maxQueuedBytes;
    private final boolean disableUPnP;
    private final long budgetNanos;

    private LocalSerialConfig(String sn, String nat1, int port1, String nat2, int port2,
            int network, int mode, boolean upnp, String path, String platformValue,
            String version, String app, String modelValue, int bufferCap, int eventCap, int byteCap, long budget) {
        serial = checked(sn, 63);
        if (!serial.matches("[A-Za-z0-9]{1,63}")) throw new IllegalArgumentException("ASCII serial required");
        StringBuilder normalized = new StringBuilder(serial.length());
        for (int i = 0; i < serial.length(); i++) {
            char c = serial.charAt(i); normalized.append(c >= 'a' && c <= 'z' ? (char)(c - 32) : c);
        }
        this.normalizedSerial = normalized.toString();
        nat1Host = checked(nat1, 127); nat2Host = checked(nat2, 63);
        nat1Port = port(port1); nat2Port = port(port2);
        if (network != 0 && network != 1) throw new IllegalArgumentException("Network flag must be explicit 0/1");
        if (mode != 0 && mode != 1) throw new IllegalArgumentException("Traversal mode must be explicit 0/1");
        networkFlag = network; traversalMode = mode; disableUPnP = upnp;
        privateFilesPath = checked(path, 255);
        if (!path.startsWith("/") || path.contains("\\") || path.contains("//"))
            throw new IllegalArgumentException("Reviewed absolute Android private path required");
        for (String part : path.split("/")) if (part.equals(".") || part.equals(".."))
            throw new IllegalArgumentException("Path traversal");
        // Conservative policy for source checked concatenation path + separator + SN.
        // Sixteen extra bytes are an admission margin, not a recovered native suffix.
        if (path.getBytes(StandardCharsets.UTF_8).length + normalizedSerial.length() + 16 > 255)
            throw new IllegalArgumentException("Composed native cache path overflow");
        platform = checked(platformValue, 31); appVersion = checked(version, 63);
        appName = checked(app, 63); model = checked(modelValue, 63);
        if (bufferCap < 1 || bufferCap > 10240 || eventCap < 1 || eventCap > 1024
                || byteCap < bufferCap || byteCap > 1048576)
            throw new IllegalArgumentException("Explicit bounded buffer/queue caps required");
        if (budget < 1 || budget > TimeUnit.HOURS.toNanos(1)) throw new IllegalArgumentException("Monotonic budget out of bounds");
        maxBufferBytes = bufferCap; maxQueuedEvents = eventCap; maxQueuedBytes = byteCap; budgetNanos = budget;
    }
    private final String normalizedSerial;
    public static LocalSerialConfig operatorReviewed(String serial, String nat1Host, int nat1Port,
            String nat2Host, int nat2Port, int networkFlag, int traversalMode, boolean disableUPnP,
            String privateFilesPath, String platform, String appVersion, String appName, String model,
            int maxBufferBytes, int maxQueuedEvents, int maxQueuedBytes, long budgetNanos) {
        return new LocalSerialConfig(serial, nat1Host, nat1Port, nat2Host, nat2Port, networkFlag,
                traversalMode, disableUPnP, privateFilesPath, platform, appVersion, appName, model,
                maxBufferBytes, maxQueuedEvents, maxQueuedBytes, budgetNanos);
    }
    private static int port(int value) {
        if (value < 1 || value > 65535) throw new IllegalArgumentException("Port out of bounds"); return value;
    }
    private static String checked(String value, int bytes) {
        if (value == null || value.isEmpty()) throw new IllegalArgumentException("Explicit nonempty config required");
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c == 0) throw new IllegalArgumentException("NUL config input");
            if (Character.isHighSurrogate(c)) {
                if (++i >= value.length() || !Character.isLowSurrogate(value.charAt(i)))
                    throw new IllegalArgumentException("Malformed Unicode config");
            } else if (Character.isLowSurrogate(c)) throw new IllegalArgumentException("Malformed Unicode config");
        }
        if (value.getBytes(StandardCharsets.UTF_8).length > bytes) throw new IllegalArgumentException("UTF8 config overflow");
        return value;
    }
    String serial() { return normalizedSerial; }
    String nat1Host() { return nat1Host; } String nat2Host() { return nat2Host; }
    String privateFilesPath() { return privateFilesPath; } String platform() { return platform; }
    String appVersion() { return appVersion; } String appName() { return appName; } String model() { return model; }
    int nat1Port() { return nat1Port; } int nat2Port() { return nat2Port; }
    int networkFlag() { return networkFlag; } int traversalMode() { return traversalMode; }
    boolean disableUPnP() { return disableUPnP; }
    int maxBufferBytes() { return maxBufferBytes; } int maxQueuedEvents() { return maxQueuedEvents; }
    int maxQueuedBytes() { return maxQueuedBytes; } long budgetNanos() { return budgetNanos; }
    void buffer(byte[] value, int length) {
        if (value == null || length < 1 || length > value.length || value.length > maxBufferBytes)
            throw new IllegalArgumentException("Buffer length/cap");
    }
}
