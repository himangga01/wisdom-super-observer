import com.wso.tvt.*;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** Each invocation owns a fresh host process because failed native cleanup quarantines its lease. */
public final class CleanupFailureTest {
    private CleanupFailureTest() { }
    private static final class Driver implements NativeDriver {
        final String fail;
        final List<String> calls = new ArrayList<>();
        Driver(String fail) { this.fail = fail; }
        private void call(String stage) { calls.add(stage); if (fail.equals(stage)) { throw new IllegalStateException("private"); } }
        public void bind(CallbackSink callback) { }
        public boolean init(RuntimeConfig config) { return true; }
        public boolean start() { return true; }
        public int connect(DeviceCredential credential) { return 2; }
        public int requestLive(int connection, int channel, int stream, int mode, long context) { return 5; }
        public boolean closeLive(int task) { call("close"); return true; }
        public void disconnect(int connection) { call("disconnect"); }
        public void stop() { call("stop"); }
        public void quit() { call("quit"); }
    }
    public static void main(String[] args) {
        String stage = args[0];
        int expectedFlag = Integer.parseInt(args[1]);
        Driver driver = new Driver(stage);
        LifecycleController controller = new LifecycleController(driver, 1, 1, 8, () -> 0L);
        controller.start(new RuntimeConfig(4, "synthetic", null, "", "synthetic.invalid", 1, null, "v"));
        controller.connect(new DeviceCredential("synthetic", 1L, 1, "synthetic"));
        long context = controller.openLive(0, 0, 0, 1L);
        if (args.length == 3 && args[2].equals("cancel")) {
            controller.cancel(context);
            if (controller.cleanupStatus().failureBits() != 1 || controller.cleanupStatus().released()) { throw new AssertionError("cancellation release failure hidden before close"); }
            try { controller.openLive(0, 0, 0, 1L); throw new AssertionError("new task admitted after unresolved cancel"); }
            catch (LifecycleController.OperationFailure expectedFailure) { }
        }
        controller.close();
        if (!driver.calls.equals(Arrays.asList("close", "disconnect", "stop", "quit"))) { throw new AssertionError("cleanup stopped at failed stage"); }
        if (controller.cleanupStatus().released() || controller.cleanupStatus().failureBits() != expectedFlag) { throw new AssertionError("unresolved stage hidden"); }
        controller.close();
        if (driver.calls.size() != 4) { throw new AssertionError("unsafe native cleanup retry"); }
        System.out.println("PASS cleanup failure at " + stage + ": all stages attempted; bounded unresolved status; lease quarantined");
    }
}
