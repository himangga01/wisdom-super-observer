package com.wso.tvt;

/** Fixed, bounded status; no native exception text, handle or secret. */
public final class CleanupStatus {
    public static final int TASK_CLOSE = 1, DISCONNECT = 2, STOP = 4, QUIT = 8, BUSY = 16;
    private final int failures;
    private final boolean released;
    CleanupStatus(int failures, boolean released) { this.failures = failures; this.released = released; }
    public int failureBits() { return failures; }
    public boolean released() { return released; }
    @Override public String toString() { return "CleanupStatus[failures=" + failures + ",released=" + released + "]"; }
}
