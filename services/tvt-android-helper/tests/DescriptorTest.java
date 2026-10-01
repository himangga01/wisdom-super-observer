import com.tvt.network.NetClientProtocal;
import com.wso.tvt.*;
import java.lang.invoke.MethodType;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

public final class DescriptorTest {
    private DescriptorTest() { }
    public static void main(String[] args) throws Exception {
        Map<String, Integer> expected = new TreeMap<>();
        for (String line : Files.readAllLines(Paths.get(args[0]), StandardCharsets.UTF_8)) {
            String[] fields = line.split(" ");
            expected.put(fields[1], Integer.parseInt(fields[2], 16));
        }
        Map<String, Integer> actual = new TreeMap<>();
        for (Method method : NetClientProtocal.class.getDeclaredMethods()) {
            if (Modifier.isNative(method.getModifiers()) || method.getName().startsWith("On")
                    || method.getName().equals("LogPrintCallback")) {
                actual.put(method.getName() + MethodType.methodType(method.getReturnType(), method.getParameterTypes()).toMethodDescriptorString(), method.getModifiers());
            }
        }
        if (!expected.equals(actual)) { throw new AssertionError("Compiled JNI/callback descriptors or modifiers differ from APK inventory"); }
        final List<PrivateEvent> callbacks = new ArrayList<>();
        NetClientProtocal wrapper = new NetClientProtocal((kind, a, b, c, d, data, length, context) -> {
            // Verification only: use reflected callback methods without loading any native library.
            if (kind == CallbackKind.TASK_DATA && a == 71 && length == 2 && context == 123456789L
                    && data[0] == (byte) 0xff && data[1] == 0) { callbacks.add(null); }
        });
        Method taskData = NetClientProtocal.class.getDeclaredMethod("OnNetClientTaskData", int.class, byte[].class, int.class, long.class);
        taskData.setAccessible(true);
        taskData.invoke(wrapper, 71, new byte[] {(byte) 0xff, 0, 42}, 2, 123456789L);
        if (callbacks.size() != 1) { throw new AssertionError("Actual JNI wrapper callback changed bytes, length, task or context"); }
        Method log = NetClientProtocal.class.getDeclaredMethod("LogPrintCallback", String.class);
        log.setAccessible(true); log.invoke(null, "synthetic-private-log");
        try { JniNativeDriver.createOnAndroid(); throw new AssertionError("Host native driver loaded or simulated success"); }
        catch (IllegalStateException expectedHostRejection) {
            if (!expectedHostRejection.getMessage().equals("Android runtime is required")) { throw expectedHostRejection; }
        }
        System.out.println("PASS 48 native + 12 callback descriptors/modifiers; exact wrapper callback forwarding; host native loading rejected");
    }
}
