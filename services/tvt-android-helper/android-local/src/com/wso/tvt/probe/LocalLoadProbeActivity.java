package com.wso.tvt.probe;

import android.app.Activity;
import android.os.Bundle;
import android.os.Process;
import com.tvt.network.NatTraveral;
import com.wso.tvt.local.JniLocalSerialDriver;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Set;
import java.util.TreeSet;

/** One Android process, one bootstrap/allocation attempt, no device authority. */
public final class LocalLoadProbeActivity extends Activity {
    private static boolean attempted;
    private String stage = "created", failure = "none";
    private boolean loaded, descriptorsMatched, bootstrapped, allocationObserved;
    private boolean callbacksRemoved, interruptRequested, destroyRequested;
    private String abi = "unknown";
    private boolean is64bit;

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        synchronized (LocalLoadProbeActivity.class) {
            if (attempted) { finish(); return; }
            attempted = true;
        }
        // This image's advertised host architecture is not the loaded ELF identity.
        // Android chooses the ABI matching this ARM-only package/process.
        is64bit = Process.is64Bit();
        abi = is64bit ? "arm64-v8a" : "armeabi-v7a";
        Thread worker = new Thread(new Runnable() {
            @Override public void run() { probe(); }
        }, "local-nat-probe");
        worker.start();
    }

    private void probe() {
        try {
            enter("reflection");
            verifyDescriptors();
            descriptorsMatched = true;
            enter("load");
            System.loadLibrary("NatTraveral");
            loaded = true;
            enter("bootstrap");
            JniLocalSerialDriver driver = JniLocalSerialDriver.createAndroid();
            bootstrapped = true;
            enter("allocate");
            long echo = driver.allocate();
            if (echo == 0) { failure = "allocation_zero"; persist(); return; }
            allocationObserved = true;
            enter("remove_callbacks");
            driver.removeCallbacks(echo);
            callbacksRemoved = true;
            enter("interrupt");
            // Set only after the synchronous call returned. False is unproved cleanup.
            driver.interrupt(echo);
            interruptRequested = true;
            enter("destroy");
            driver.destroy(echo);
            destroyRequested = true;
            enter("complete");
        } catch (Throwable error) {
            // Never stringify Throwable or include library path/native pointer/detail.
            if (error instanceof LinkageError) failure = "linkage";
            else if (error instanceof ReflectiveOperationException) failure = "reflection";
            else if (error instanceof SecurityException) failure = "security";
            else if (error instanceof IOException) failure = "io";
            else if (error instanceof RuntimeException) failure = "runtime";
            else failure = "unknown";
            try { persist(); } catch (IOException ignored) { /* host reports missing result */ }
        }
    }

    private void enter(String next) throws IOException { stage = next; persist(); }

    private void persist() throws IOException {
        String json = "{\"schemaVersion\":1,\"version\":\"local-nat-probe-1\",\"abi\":\"" + abi
            + "\",\"is64bit\":" + is64bit + ",\"stage\":\"" + stage + "\",\"failure\":\"" + failure
            + "\",\"loaded\":" + loaded + ",\"descriptorsMatched\":" + descriptorsMatched
            + ",\"bootstrapped\":" + bootstrapped + ",\"allocationObserved\":" + allocationObserved
            + ",\"callbacksRemoved\":" + callbacksRemoved + ",\"interruptRequested\":" + interruptRequested
            + ",\"destroyRequested\":" + destroyRequested + ",\"cleanupProven\":false}";
        byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
        if (bytes.length > 4096) throw new IOException();
        File temporary = new File(getFilesDir(), "probe-result.tmp");
        try (FileOutputStream out = new FileOutputStream(temporary, false)) {
            out.write(bytes); out.getFD().sync();
        }
        if (!temporary.renameTo(new File(getFilesDir(), "probe-result.json"))) throw new IOException();
    }

    private static String descriptor(Class<?> type) {
        if (type.isArray()) return type.getName().replace('.', '/');
        if (!type.isPrimitive()) return "L" + type.getName().replace('.', '/') + ";";
        if (type == void.class) return "V";
        if (type == boolean.class) return "Z";
        if (type == byte.class) return "B";
        if (type == char.class) return "C";
        if (type == short.class) return "S";
        if (type == int.class) return "I";
        if (type == long.class) return "J";
        if (type == float.class) return "F";
        return "D";
    }
    private static String descriptor(Method method) {
        StringBuilder result = new StringBuilder(method.getName()).append('(');
        for (Class<?> type : method.getParameterTypes()) result.append(descriptor(type));
        return result.append(')').append(descriptor(method.getReturnType())).toString();
    }
    private static void verifyDescriptors() throws ReflectiveOperationException {
        // Independent literal APK inventory, never generated from packaged source.
        Set<String> expected = new TreeSet<>(Arrays.asList(
            "Destroy(J)I", "InitGlobal()I", "Initialize()J",
            "GetConnInfo(J)Ljava/lang/String;", "GetConnectType(J)I", "GetErrorCode(J)I",
            "GetLastRecvTime(J)J", "GetTraversalMode(J)I",
            "GetVersionType(JLjava/lang/String;Ljava/lang/String;ILjava/lang/String;I[BIIZLjava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)I",
            "Interrupt(J)I", "Nat2EnablePrintLog(Z)I",
            "QueryDevInfo(JLjava/lang/String;Ljava/lang/String;ILjava/lang/String;ILjava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;",
            "RecvData(J[BI)I", "SendData(J[BI)I", "SetConnectTraversalMode(JI)I",
            "SetDisableConnFlag(I)Z", "SetLanIps(Ljava/lang/String;)Z",
            "SetValue(JLjava/lang/String;Ljava/lang/String;II)I"));
        Set<String> actual = new TreeSet<>();
        for (Method method : NatTraveral.class.getDeclaredMethods()) {
            if (Modifier.isNative(method.getModifiers())) {
                boolean privateEntry = method.getName().equals("Destroy") || method.getName().equals("InitGlobal")
                    || method.getName().equals("Initialize");
                if (Modifier.isStatic(method.getModifiers())
                    || (privateEntry ? !Modifier.isPrivate(method.getModifiers()) : !Modifier.isPublic(method.getModifiers())))
                    throw new NoSuchMethodException();
                actual.add(descriptor(method));
            }
        }
        if (!expected.equals(actual)) throw new NoSuchMethodException();
        for (String callback : Arrays.asList("Nat2ConnStatusCallback(JZILjava/lang/String;)V",
                                             "Nat2RecvDataCallback(J[B)I",
                                             "LogPrintCallback(Ljava/lang/String;)V")) {
            boolean found = false;
            for (Method method : NatTraveral.class.getDeclaredMethods()) {
                if (descriptor(method).equals(callback) && !Modifier.isNative(method.getModifiers())
                    && Modifier.isPublic(method.getModifiers())
                    && (Modifier.isStatic(method.getModifiers()) == callback.startsWith("LogPrintCallback"))) found = true;
            }
            if (!found) throw new NoSuchMethodException();
        }
        for (String name : Arrays.asList("Destroy", "InitGlobal", "Initialize")) {
            Method method = NatTraveral.class.getDeclaredMethod(name,
                    name.equals("Destroy") ? new Class<?>[] {long.class} : new Class<?>[0]);
            if (!Modifier.isPrivate(method.getModifiers())) throw new NoSuchMethodException();
        }
        if (JniLocalSerialDriver.class.getMethod("createAndroid").getReturnType() != JniLocalSerialDriver.class)
            throw new NoSuchMethodException();
    }
}
