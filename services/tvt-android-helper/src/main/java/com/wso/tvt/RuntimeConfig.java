package com.wso.tvt;

/** Private injected native configuration. Never serialize this object into a public DTO. */
public final class RuntimeConfig {
    private final int cliType;
    private final int natServerPort;
    private final String clientToken, customerId, ispCode, natServerAddress, svnCodeId, szClientVer;
    public RuntimeConfig(int cliType, String clientToken, String customerId, String ispCode,
                         String natServerAddress, int natServerPort, String svnCodeId, String szClientVer) {
        if (cliType < 0 || natServerPort < 1 || natServerPort > 65535) {
            throw new IllegalArgumentException("Invalid native configuration");
        }
        this.cliType = cliType; this.natServerPort = natServerPort;
        this.clientToken = required(clientToken); this.customerId = optional(customerId);
        this.ispCode = optional(ispCode); this.natServerAddress = required(natServerAddress);
        this.svnCodeId = optional(svnCodeId); this.szClientVer = required(szClientVer);
    }
    private static String required(String value) {
        if (value == null || value.isEmpty()) { throw new IllegalArgumentException("Missing private configuration"); }
        return optional(value);
    }
    private static String optional(String value) {
        if (value != null && value.length() > 4096) { throw new IllegalArgumentException("Private configuration exceeds bound"); }
        return value;
    }
    private static String quote(String value) {
        if (value == null) { return "null"; }
        StringBuilder result = new StringBuilder("\"");
        for (int index = 0; index < value.length(); index++) {
            char c = value.charAt(index);
            switch (c) {
                case '"': result.append("\\\""); break;
                case '\\': result.append("\\\\"); break;
                case '\b': result.append("\\b"); break;
                case '\f': result.append("\\f"); break;
                case '\n': result.append("\\n"); break;
                case '\r': result.append("\\r"); break;
                case '\t': result.append("\\t"); break;
                default:
                    if (c < 32 || Character.isSurrogate(c)) {
                        String hex = Integer.toHexString(c);
                        result.append("\\u");
                        for (int padding = hex.length(); padding < 4; padding++) { result.append('0'); }
                        result.append(hex);
                    } else { result.append(c); }
            }
        }
        return result.append('"').toString();
    }
    // Package-private: only the native driver receives the serialized secret body.
    String nativeJson() {
        return "{\"cliType\":" + cliType + ",\"clientToken\":" + quote(clientToken)
            + ",\"customerId\":" + quote(customerId) + ",\"ispCode\":" + quote(ispCode)
            + ",\"natServerAddress\":" + quote(natServerAddress) + ",\"natServerPort\":" + natServerPort
            + ",\"svnCodeId\":" + quote(svnCodeId) + ",\"szClientVer\":" + quote(szClientVer) + "}";
    }
    @Override public String toString() { return "RuntimeConfig[private]"; }
}
