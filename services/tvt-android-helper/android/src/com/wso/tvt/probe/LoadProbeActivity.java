package com.wso.tvt.probe;

import android.app.Activity;
import android.os.Bundle;
import android.util.Log;
import android.widget.TextView;
import com.tvt.network.NetClientProtocal;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.TreeMap;

/** A fixed load/reflection diagnostic. Never invokes JNI methods or callbacks. */
public final class LoadProbeActivity extends Activity {
    private static final String TAG = "WsoTvtLoadProbe";

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        String result;
        try {
            NetClientProtocal.loadOnAndroid();
            result = inventoryMatches()
                    ? "LOAD_ONLY_PASS: library loaded; 48 JNI and 12 callback descriptors/modifiers match."
                    : "LOAD_ONLY_FAIL: descriptor/modifier inventory mismatch.";
        } catch (UnsatisfiedLinkError failure) {
            result = "LOAD_ONLY_FAIL: native library unavailable or unsupported ABI/load dependency.";
        } catch (LinkageError failure) {
            result = "LOAD_ONLY_FAIL: runtime linkage failure.";
        } catch (Exception failure) {
            result = "LOAD_ONLY_FAIL: load or inventory verification failure.";
        }
        String message = result + "\nNo JNI binding invocation, network, context, transport or feature acceptance performed.";
        TextView view = new TextView(this);
        view.setText(message);
        setContentView(view);
        Log.i(TAG, message);
    }

    private boolean inventoryMatches() throws Exception {
        Map<String, Integer> expected = new TreeMap<>();
        int expectedNative = 0;
        int expectedCallbacks = 0;
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                getAssets().open("apk-descriptors.txt"), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                String[] fields = line.split(" ");
                if (fields.length != 3) { return false; }
                int modifiers = Integer.parseInt(fields[2], 16);
                if ("NATIVE".equals(fields[0]) && Modifier.isNative(modifiers)) {
                    expectedNative++;
                } else if ("JAVA".equals(fields[0]) && !Modifier.isNative(modifiers)) {
                    expectedCallbacks++;
                } else { return false; }
                if (expected.put(fields[1], modifiers) != null) { return false; }
            }
        }
        Map<String, Integer> actual = new TreeMap<>();
        int actualNative = 0;
        int actualCallbacks = 0;
        for (Method method : NetClientProtocal.class.getDeclaredMethods()) {
            int modifiers = method.getModifiers();
            boolean nativeMethod = Modifier.isNative(modifiers);
            if (nativeMethod || method.getName().startsWith("On")
                    || method.getName().equals("LogPrintCallback")) {
                if (nativeMethod) { actualNative++; } else { actualCallbacks++; }
                if (actual.put(method.getName() + descriptor(method), modifiers) != null) { return false; }
            }
        }
        return expectedNative == 48 && expectedCallbacks == 12
                && actualNative == 48 && actualCallbacks == 12 && expected.equals(actual);
    }

    private static String descriptor(Method method) {
        StringBuilder value = new StringBuilder("(");
        for (Class<?> parameter : method.getParameterTypes()) { value.append(descriptor(parameter)); }
        return value.append(')').append(descriptor(method.getReturnType())).toString();
    }

    private static String descriptor(Class<?> type) {
        if (type.isArray()) { return type.getName().replace('.', '/'); }
        if (!type.isPrimitive()) { return "L" + type.getName().replace('.', '/') + ";"; }
        if (type == void.class) { return "V"; }
        if (type == boolean.class) { return "Z"; }
        if (type == byte.class) { return "B"; }
        if (type == char.class) { return "C"; }
        if (type == short.class) { return "S"; }
        if (type == int.class) { return "I"; }
        if (type == long.class) { return "J"; }
        if (type == float.class) { return "F"; }
        if (type == double.class) { return "D"; }
        throw new IllegalArgumentException("Unsupported descriptor type");
    }
}
