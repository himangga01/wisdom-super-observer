package com.wso.tvt;

import java.util.Arrays;

/** Internal callback envelope. No log representation or public transport serializer. */
public final class PrivateEvent {
    private final CallbackKind kind;
    private final int[] identifiers;
    private final byte[] payload;
    private final int declaredLength;
    private final long context, managerGeneration, sessionGeneration;
    PrivateEvent(CallbackKind kind, int a, int b, int c, int d, byte[] bytes, int length,
                 long context, long managerGeneration, long sessionGeneration) {
        this.kind = kind; identifiers = new int[] {a, b, c, d};
        payload = bytes == null ? new byte[0] : Arrays.copyOf(bytes, length);
        declaredLength = length; this.context = context;
        this.managerGeneration = managerGeneration; this.sessionGeneration = sessionGeneration;
    }
    public CallbackKind kind() { return kind; }
    public int nativeId(int index) { return identifiers[index]; }
    public long nativeContext() { return context; }
    public long managerGeneration() { return managerGeneration; }
    public long sessionGeneration() { return sessionGeneration; }
    public int declaredLength() { return declaredLength; }
    public byte[] copyPayload() { return payload.clone(); }
    @Override public String toString() { return "PrivateEvent[private]"; }
}
