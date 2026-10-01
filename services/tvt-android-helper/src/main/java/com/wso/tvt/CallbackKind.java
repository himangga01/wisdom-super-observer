package com.wso.tvt;

/** Exact callback names; payload meanings are deliberately undecoded. */
public enum CallbackKind {
    CONNECT, DISCONNECT, TASK_DATA, TASK_ERR, SWITCH_CONNECT, RENEW_TOKEN,
    NAT_CONNECT, NAT_DISCONNECT, NAT_DATA, NOTIFY_DATA, SUBSCRIBE_DATA
}
