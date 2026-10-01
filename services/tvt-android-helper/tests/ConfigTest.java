package com.wso.tvt;

public final class ConfigTest {
    private ConfigTest() { }
    public static void main(String[] args) {
        RuntimeConfig config = new RuntimeConfig(4, "a\"\\\n", null, "", "synthetic.invalid", 1234, "s", "v");
        String expected = "{\"cliType\":4,\"clientToken\":\"a\\\"\\\\\\n\",\"customerId\":null,\"ispCode\":\"\",\"natServerAddress\":\"synthetic.invalid\",\"natServerPort\":1234,\"svnCodeId\":\"s\",\"szClientVer\":\"v\"}";
        if (!expected.equals(config.nativeJson())) { throw new AssertionError("eight exact keys/types/nulls/JSON escapes not preserved"); }
        try { new RuntimeConfig(4, "", "", "", "synthetic.invalid", 1, "", "v"); throw new AssertionError("missing token admitted"); }
        catch (IllegalArgumentException expectedInvalid) { }
        try { new RuntimeConfig(4, "synthetic", "", "", "synthetic.invalid", 65536, "", "v"); throw new AssertionError("invalid port admitted"); }
        catch (IllegalArgumentException expectedInvalid) { }
        try { new DeviceCredential("synthetic", 0, 1, "synthetic"); throw new AssertionError("invalid expiry admitted"); }
        catch (IllegalArgumentException expectedInvalid) { }
        if (config.toString().contains("synthetic") || new DeviceCredential("synthetic", 1, 1, "synthetic").toString().contains("synthetic")) { throw new AssertionError("private config representation leaked"); }
        System.out.println("PASS exact eight-field private configuration, JSON escapes/nulls, validation and redacted representations");
    }
}
