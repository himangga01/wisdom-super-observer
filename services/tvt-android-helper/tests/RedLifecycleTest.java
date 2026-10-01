import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.List;
import java.util.function.LongSupplier;

/** Test-first contract: successful startup must call Init before Start. */
public final class RedLifecycleTest {
    private RedLifecycleTest() { }
    public static void main(String[] args) throws Exception {
        Class<?> driverType;
        Class<?> controllerType;
        Class<?> configType;
        try {
            driverType = Class.forName("com.wso.tvt.NativeDriver");
            controllerType = Class.forName("com.wso.tvt.LifecycleController");
            configType = Class.forName("com.wso.tvt.RuntimeConfig");
        } catch (ClassNotFoundException missing) {
            throw new AssertionError("Startup cannot perform Init then Start: helper implementation absent", missing);
        }
        List<String> calls = new ArrayList<>();
        Object driver = Proxy.newProxyInstance(driverType.getClassLoader(), new Class<?>[] { driverType },
            (proxy, method, arguments) -> {
                calls.add(method.getName());
                if (method.getReturnType() == boolean.class) { return true; }
                return null;
            });
        Object config = configType.getConstructor(int.class, String.class, String.class, String.class,
            String.class, int.class, String.class, String.class).newInstance(
                4, "synthetic-token", "", "", "synthetic.invalid", 1234, "", "synthetic-version");
        Object controller = controllerType.getConstructor(driverType, int.class, int.class, int.class,
            LongSupplier.class).newInstance(driver, 8, 8, 1024, (LongSupplier) () -> 0L);
        controllerType.getMethod("start", configType).invoke(controller, config);
        if (!calls.equals(java.util.Arrays.asList("bind", "init", "start"))) {
            throw new AssertionError("Startup order was " + calls);
        }
        controllerType.getMethod("close").invoke(controller);
        System.out.println("PASS startup Init then Start contract");
    }
}
