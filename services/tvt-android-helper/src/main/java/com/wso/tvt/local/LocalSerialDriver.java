package com.wso.tvt.local;

/** Internal Android boundary, never a browser/RPC handle or generic command interface. */
public interface LocalSerialDriver {
    interface Callbacks {
        void connection(long echo, boolean connected, int type, String privateDetail);
        int data(long echo, byte[] bytes);
    }
    long allocate();
    void bind(long echo, Callbacks callbacks);
    void removeCallbacks(long echo);
    int discover(long echo, LocalSerialConfig config);
    int openTransport(long echo, LocalSerialConfig config);
    int connectType(long echo);
    int error(long echo);
    int send(long echo, byte[] buffer, int length);
    int receive(long echo, byte[] buffer, int length);
    /** True only if the adapter has evidence that this cleanup operation completed. */
    boolean interrupt(long echo);
    boolean destroy(long echo);
}
