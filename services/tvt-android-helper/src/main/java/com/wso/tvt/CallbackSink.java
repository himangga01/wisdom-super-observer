package com.wso.tvt;

public interface CallbackSink {
    void onCallback(CallbackKind kind, int first, int second, int third, int fourth,
                    byte[] bytes, int declaredLength, long context);
}
