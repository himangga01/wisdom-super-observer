import com.wso.tvt.*;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

/** Inject only the JNI dependency; exercise the real controller and payload objects. */
public final class HelperTest {
    private HelperTest() { }
    private static int checks;
    private static void check(boolean condition, String message) {
        checks++;
        if (!condition) { throw new AssertionError(message); }
    }
    private static RuntimeConfig config() {
        return new RuntimeConfig(4, "synthetic-secret", "customer", "isp", "synthetic.invalid", 1234, "svn", "v");
    }
    private static final class Driver implements NativeDriver {
        CallbackSink sink;
        final List<String> calls = new ArrayList<>();
        final List<Integer> closedIds = new ArrayList<>();
        String fail = "";
        int nextTask = 7;
        boolean synchronous;
        boolean synchronousError;
        CountDownLatch entered;
        CountDownLatch release;
        private boolean call(String name) {
            calls.add(name);
            if (name.equals(fail)) { throw new IllegalStateException("private-failure-must-not-escape"); }
            return true;
        }
        public void bind(CallbackSink value) { sink = value; call("bind"); }
        public boolean init(RuntimeConfig value) { call("init"); return !fail.equals("initFalse"); }
        public boolean start() { call("start"); return !fail.equals("startFalse"); }
        public int connect(DeviceCredential value) { call("connect"); return fail.equals("connectZero") ? 0 : 3; }
        public int requestLive(int connection, int channel, int stream, int mode, long context) {
            call("live");
            if (entered != null) {
                entered.countDown();
                try {
                    if (!release.await(3, TimeUnit.SECONDS)) { throw new IllegalStateException("test-timeout"); }
                } catch (InterruptedException interrupted) { throw new IllegalStateException(interrupted); }
            }
            if (synchronous) { sink.onCallback(CallbackKind.TASK_DATA, nextTask, 0, 0, 0, new byte[] {1, 2, 3}, 2, context); }
            if (synchronousError) { sink.onCallback(CallbackKind.TASK_ERR, nextTask, 93, 0, 0, null, 0, context); }
            return fail.equals("liveZero") ? 0 : nextTask;
        }
        public boolean closeLive(int task) { closedIds.add(task); call("close"); return !fail.equals("closeFalse"); }
        public void disconnect(int connection) { call("disconnect"); }
        public void stop() { call("stop"); }
        public void quit() { call("quit"); }
    }
    private static LifecycleController controller(Driver driver, AtomicLong clock) {
        return new LifecycleController(driver, 2, 2, 4, clock::get);
    }
    private static void connect(LifecycleController controller) {
        controller.start(config());
        controller.connect(new DeviceCredential("synthetic-access", 123L, 30, "synthetic-device"));
    }
    private static void failure(String stage, List<String> expected) {
        Driver driver = new Driver(); driver.fail = stage;
        LifecycleController controller = controller(driver, new AtomicLong());
        try { connect(controller); throw new AssertionError("expected failure: " + stage); }
        catch (LifecycleController.OperationFailure expectedFailure) {
            check(!expectedFailure.toString().contains("private-failure"), "exception privacy");
        }
        check(driver.calls.equals(expected), "cleanup order " + stage + ": " + driver.calls);
        check(controller.cleanupStatus().released(), "failure cleanup released manager " + stage);
    }
    private static void terminalQueueRegression() {
        Driver driver = new Driver();
        LifecycleController controller = new LifecycleController(driver, 2, 1, 4, () -> 0L);
        connect(controller);
        long context = controller.openLive(1, 0, 0, 100);
        driver.sink.onCallback(CallbackKind.TASK_DATA, 7, 0, 0, 0, new byte[] {1}, 1, context);
        driver.sink.onCallback(CallbackKind.TASK_ERR, 7, 91, 0, 0, null, 0, context);
        check(controller.activeTasks() == 0, "full data queue must retire terminal task before drain");
        check(java.util.Collections.frequency(driver.calls, "close") == 0, "native close must not run on callback thread");
        driver.sink.onCallback(CallbackKind.TASK_ERR, 7, 91, 0, 0, null, 0, context);
        driver.sink.onCallback(CallbackKind.TASK_DATA, 7, 0, 0, 0, new byte[] {2}, 1, context);
        List<PrivateEvent> events = controller.drain();
        check(events.size() == 1 && events.get(0).kind() == CallbackKind.TASK_ERR
            && events.get(0).nativeId(0) == 7 && events.get(0).nativeId(1) == 91
            && events.get(0).nativeContext() == context, "one exact terminal error survives full queue and stale data");
        check(java.util.Collections.frequency(driver.calls, "close") == 1, "terminal native resource closes once on drain");
        controller.cancel(context); controller.expire(); controller.close();
        check(java.util.Collections.frequency(driver.calls, "close") == 1, "terminal cancel/expire/manager close must not close twice");
        System.out.println("PASS Fix1 full-queue terminal ownership regression");
    }
    private static void activeCollisionRegression() {
        Driver driver = new Driver();
        LifecycleController controller = controller(driver, new AtomicLong());
        connect(controller);
        long original = controller.openLive(1, 0, 0, 100);
        driver.sink.onCallback(CallbackKind.TASK_DATA, 7, 0, 0, 0, new byte[] {1}, 1, original);
        try { controller.openLive(1, 0, 0, 100); throw new AssertionError("active duplicate native ID admitted"); }
        catch (LifecycleController.OperationFailure expected) { }
        check(controller.activeTasks() == 0, "active native-ID collision must retire original registration");
        driver.sink.onCallback(CallbackKind.TASK_DATA, 7, 0, 0, 0, new byte[] {2}, 1, original);
        driver.sink.onCallback(CallbackKind.TASK_ERR, 7, 92, 0, 0, null, 0, original);
        check(controller.drain().isEmpty(), "collision purges original queued and late callbacks");
        check(java.util.Collections.frequency(driver.calls, "close") == 1, "collision closes shared native ID once");
        controller.cancel(original); controller.expire(); controller.close();
        check(java.util.Collections.frequency(driver.calls, "close") == 1, "retired collision is never eligible for another close");
        System.out.println("PASS Fix1 active-ID collision ownership regression");
    }
    private static void synchronousTerminalRegression() {
        Driver driver = new Driver(); driver.synchronous = true; driver.synchronousError = true;
        LifecycleController controller = new LifecycleController(driver, 1, 1, 4, () -> 0L);
        connect(controller);
        long context = controller.openLive(1, 0, 0, 100);
        check(controller.activeTasks() == 0 && driver.closedIds.isEmpty(), "synchronous terminal fences pending ownership without JNI close on callback thread");
        try { controller.openLive(1, 0, 0, 100); throw new AssertionError("pending terminal exceeded resource limit"); }
        catch (LifecycleController.OperationFailure expected) { }
        List<PrivateEvent> events = controller.drain();
        check(events.size() == 1 && events.get(0).kind() == CallbackKind.TASK_ERR
            && events.get(0).nativeContext() == context && events.get(0).nativeId(1) == 93,
            "synchronous error survives full data queue before JNI task return");
        controller.close();
        check(driver.closedIds.equals(java.util.Arrays.asList(7)), "synchronous terminal resource closes once");
        System.out.println("PASS Fix1 synchronous terminal and pending resource bound regression");
    }
    private static void concurrentTerminalRegression() throws Exception {
        Driver driver = new Driver();
        LifecycleController controller = new LifecycleController(driver, 2, 1, 4, () -> 0L);
        connect(controller);
        long original = controller.openLive(1, 0, 0, 100);
        driver.sink.onCallback(CallbackKind.TASK_DATA, 7, 0, 0, 0, new byte[] {1}, 1, original);
        driver.nextTask = 8; driver.entered = new CountDownLatch(1); driver.release = new CountDownLatch(1);
        Thread opener = new Thread(() -> controller.openLive(1, 0, 0, 100)); opener.start();
        check(driver.entered.await(2, TimeUnit.SECONDS), "second JNI request entered");
        driver.sink.onCallback(CallbackKind.TASK_ERR, 7, 94, 0, 0, null, 0, original);
        check(controller.activeTasks() == 0 && driver.closedIds.isEmpty(), "terminal retirement during JNI request does not close on native callback thread");
        driver.release.countDown(); opener.join(3000);
        check(!opener.isAlive(), "terminal callback does not deadlock JNI request");
        List<PrivateEvent> events = controller.drain();
        check(events.size() == 1 && events.get(0).kind() == CallbackKind.TASK_ERR, "concurrent error survives queue pressure");
        controller.cancel(original); controller.close();
        check(driver.closedIds.equals(java.util.Arrays.asList(7, 8)), "terminal and remaining resource each close exactly once");
        System.out.println("PASS Fix1 concurrent terminal ownership regression");
    }
    private static void terminalDeadlineRegression(boolean arrivesAtDeadline) {
        Driver driver = new Driver(); AtomicLong clock = new AtomicLong();
        LifecycleController controller = controller(driver, clock); connect(controller);
        long context = controller.openLive(1, 0, 0, 100);
        clock.set(arrivesAtDeadline ? 100 : 99);
        driver.sink.onCallback(CallbackKind.TASK_ERR, 7, 95, 0, 0, null, 0, context);
        check(controller.activeTasks() == 0 && driver.closedIds.isEmpty(), "expired terminal ownership fences without callback-thread cleanup");
        clock.set(100);
        check(controller.drain().isEmpty(), arrivesAtDeadline
            ? "terminal callback arriving at deadline must not be delivered"
            : "terminal callback retained before deadline must not be delivered at deadline");
        check(driver.closedIds.equals(java.util.Arrays.asList(7)), "expired terminal native ownership still closes once");
        driver.sink.onCallback(CallbackKind.TASK_ERR, 7, 95, 0, 0, null, 0, context);
        driver.sink.onCallback(CallbackKind.TASK_DATA, 7, 0, 0, 0, new byte[] {1}, 1, context);
        check(controller.drain().isEmpty(), "expired terminal duplicates and late data never deliver");
        controller.cancel(context); controller.expire(); controller.close();
        check(driver.closedIds.equals(java.util.Arrays.asList(7)) && controller.cleanupStatus().released(),
            "expired terminal cancel/expiry/manager cleanup never double-close native ownership");
        System.out.println("PASS Fix2 terminal " + (arrivesAtDeadline ? "arrival" : "drain") + " deadline regression");
    }
    public static void main(String[] args) throws Exception {
        if (args.length == 1 && args[0].equals("fix2-arrival")) { terminalDeadlineRegression(true); return; }
        if (args.length == 1 && args[0].equals("fix2-drain")) { terminalDeadlineRegression(false); return; }
        if (args.length == 1 && args[0].equals("fix1-queue")) { terminalQueueRegression(); return; }
        if (args.length == 1 && args[0].equals("fix1-collision")) { activeCollisionRegression(); return; }
        if (args.length == 1 && args[0].equals("fix1-sync")) { synchronousTerminalRegression(); return; }
        if (args.length == 1 && args[0].equals("fix1-concurrent")) { concurrentTerminalRegression(); return; }
        terminalDeadlineRegression(true); terminalDeadlineRegression(false);
        terminalQueueRegression(); activeCollisionRegression(); synchronousTerminalRegression(); concurrentTerminalRegression();
        failure("bind", java.util.Arrays.asList("bind"));
        failure("init", java.util.Arrays.asList("bind", "init", "quit"));
        failure("initFalse", java.util.Arrays.asList("bind", "init", "quit"));
        failure("start", java.util.Arrays.asList("bind", "init", "start", "stop", "quit"));
        failure("startFalse", java.util.Arrays.asList("bind", "init", "start", "stop", "quit"));
        failure("connect", java.util.Arrays.asList("bind", "init", "start", "connect", "stop", "quit"));
        failure("connectZero", java.util.Arrays.asList("bind", "init", "start", "connect", "stop", "quit"));

        Driver driver = new Driver(); driver.synchronous = true;
        AtomicLong clock = new AtomicLong();
        LifecycleController controller = controller(driver, clock);
        connect(controller);
        long task = controller.openLive(1, 0, 0, 10);
        List<PrivateEvent> events = controller.drain();
        check(events.size() == 1, "synchronous callback retained until registration");
        PrivateEvent event = events.get(0);
        check(event.kind() == CallbackKind.TASK_DATA && event.nativeId(0) == 7, "native identity retained");
        byte[] copy = event.copyPayload(); copy[0] = 9;
        check(event.copyPayload()[0] == 1 && event.declaredLength() == 2, "valid prefix copied defensively");
        check(!event.toString().contains("1, 2") && !config().toString().contains("synthetic-secret"), "private representations");
        driver.sink.onCallback(CallbackKind.TASK_DATA, 7, 0, 0, 0, new byte[] {8}, 1, task + 1);
        check(controller.drain().isEmpty(), "wrong context rejected");
        driver.sink.onCallback(CallbackKind.TASK_DATA, 7, 0, 0, 0, new byte[5], 5, task);
        driver.sink.onCallback(CallbackKind.TASK_DATA, 7, 0, 0, 0, new byte[1], 2, task);
        driver.sink.onCallback(CallbackKind.TASK_DATA, 7, 0, 0, 0, null, 1, task);
        driver.sink.onCallback(CallbackKind.TASK_DATA, 7, 0, 0, 0, new byte[0], -1, task);
        check(controller.drain().isEmpty(), "oversized and truncated payload rejected");
        driver.sink.onCallback(CallbackKind.TASK_DATA, 7, 0, 0, 0, new byte[0], 0, task);
        driver.sink.onCallback(CallbackKind.TASK_DATA, 7, 0, 0, 0, new byte[0], 0, task);
        driver.sink.onCallback(CallbackKind.TASK_DATA, 7, 0, 0, 0, new byte[0], 0, task);
        check(controller.drain().size() == 2 && controller.droppedCallbacks() >= 1, "bounded queue");
        controller.cancel(task); controller.cancel(task);
        driver.sink.onCallback(CallbackKind.TASK_ERR, 7, 9, 0, 0, null, 0, task);
        check(controller.drain().isEmpty(), "cancel late callback rejected");
        driver.nextTask = 8;
        long expiring = controller.openLive(1, 0, 0, 10);
        clock.set(10);
        controller.expire();
        check(controller.activeTasks() == 0 && controller.drain().isEmpty(), "deadline removes task and queued event");
        check(expiring != task, "unique correlation across tasks");
        driver.nextTask = 8;
        try { controller.openLive(1, 0, 0, 20); throw new AssertionError("recycled task admitted"); }
        catch (LifecycleController.OperationFailure expected) { check(controller.activeTasks() == 0, "recycled ID quarantined"); }
        controller.close();
        check(controller.cleanupStatus().released(), "normal close released");
        CallbackSink stale = driver.sink;
        int count = driver.calls.size(); controller.close();
        check(driver.calls.size() == count, "close idempotent");
        Driver next = new Driver();
        LifecycleController replacement = controller(next, new AtomicLong()); connect(replacement);
        stale.onCallback(CallbackKind.CONNECT, 3, 0, 0, 0, new byte[] {1}, 1, 0);
        check(replacement.drain().isEmpty() && controller.drain().isEmpty(), "stale manager generation fenced");
        replacement.close();

        Driver concurrent = new Driver(); concurrent.entered = new CountDownLatch(1); concurrent.release = new CountDownLatch(1);
        LifecycleController concurrentController = controller(concurrent, new AtomicLong()); connect(concurrentController);
        Thread opener = new Thread(() -> concurrentController.openLive(1, 0, 0, 100)); opener.start();
        check(concurrent.entered.await(2, TimeUnit.SECONDS), "native operation entered");
        Thread closer = new Thread(concurrentController::close); closer.start();
        concurrent.sink.onCallback(CallbackKind.CONNECT, 3, 0, 0, 0, null, 0, 0);
        concurrent.release.countDown(); opener.join(3000); closer.join(3000);
        check(!opener.isAlive() && !closer.isAlive(), "close and synchronous callbacks do not deadlock");
        check(concurrentController.cleanupStatus().released() && concurrentController.drain().isEmpty(), "concurrent close owns returned task and fences queue");

        Driver terminal = new Driver(); LifecycleController terminalController = controller(terminal, new AtomicLong()); connect(terminalController);
        long terminalTask = terminalController.openLive(1, 0, 0, 100);
        terminal.sink.onCallback(CallbackKind.TASK_ERR, 7, 99, 0, 0, null, 0, terminalTask);
        terminal.sink.onCallback(CallbackKind.TASK_ERR, 7, 99, 0, 0, null, 0, terminalTask);
        check(terminalController.drain().size() == 1 && terminalController.activeTasks() == 0, "terminal duplicate rejected");
        terminalController.close();

        Driver failedTask = new Driver(); LifecycleController failedTaskController = controller(failedTask, new AtomicLong()); connect(failedTaskController);
        failedTask.fail = "liveZero";
        try { failedTaskController.openLive(1, 0, 0, 100); throw new AssertionError("zero task admitted"); }
        catch (LifecycleController.OperationFailure expected) { check(failedTaskController.activeTasks() == 0, "failed request has no task"); }
        failedTask.fail = "live";
        try { failedTaskController.openLive(1, 0, 0, 100); throw new AssertionError("exception task admitted"); }
        catch (LifecycleController.OperationFailure expected) { check(failedTaskController.activeTasks() == 0, "thrown request has no task"); }
        failedTask.fail = ""; failedTaskController.close();

        // This intentionally runs last: unresolved native cleanup quarantines the process lease.
        Driver badCleanup = new Driver(); LifecycleController unresolved = controller(badCleanup, new AtomicLong()); connect(unresolved);
        unresolved.openLive(1, 0, 0, 100); badCleanup.fail = "closeFalse"; unresolved.close();
        check(!unresolved.cleanupStatus().released() && unresolved.cleanupStatus().failureBits() == 1, "failed close remains unresolved");
        check(badCleanup.calls.subList(badCleanup.calls.size()-4, badCleanup.calls.size()).equals(java.util.Arrays.asList("close", "disconnect", "stop", "quit")), "cleanup attempts every stage");
        try { controller(new Driver(), new AtomicLong()).start(config()); throw new AssertionError("quarantined manager reused"); }
        catch (LifecycleController.OperationFailure expected) { check(true, "one live manager lease retained"); }
        System.out.println("PASS " + checks + " lifecycle, payload, generation, failure and concurrency checks");
    }
}
