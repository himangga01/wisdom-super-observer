package com.wso.tvt;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.LongSupplier;

/** One native manager and one session per lifetime. Native calls never hold the state monitor. */
public final class LifecycleController implements AutoCloseable {
    private static final Object PROCESS_LEASE = new Object();
    private static LifecycleController owner;
    private static final AtomicLong GENERATIONS = new AtomicLong();
    private static final AtomicLong CONTEXTS = new AtomicLong();
    private final Object state = new Object();
    private final NativeDriver driver;
    private final LongSupplier clock;
    private final int maxTasks, maxQueue, maxPayload, maxTaskIds;
    private final long maxQueuedBytes;
    private final long managerGeneration = GENERATIONS.incrementAndGet();
    private final long sessionGeneration = GENERATIONS.incrementAndGet();
    private final CallbackSink callback;
    private final Map<Long, Task> tasks = new HashMap<>();
    private final Set<Integer> usedTaskIds = new HashSet<>();
    private final ArrayDeque<PrivateEvent> queue = new ArrayDeque<>();
    private boolean claimed, initialized, initAttempted, startAttempted, started;
    private boolean busy, closing, closed, connected, fenced;
    private Thread operationThread;
    private int connection, failures, dropped;
    private long queuedBytes;
    private CleanupStatus cleanup = new CleanupStatus(0, false);

    public static final class OperationFailure extends IllegalStateException {
        private static final long serialVersionUID = 1L;
        OperationFailure() { super("Native helper operation failed"); }
    }
    private static final class Task {
        final long context, deadline;
        int nativeId;
        boolean terminal;
        PrivateEvent terminalEvent;
        Task(long context, int nativeId, long deadline) {
            this.context = context; this.nativeId = nativeId; this.deadline = deadline;
        }
    }
    public LifecycleController(NativeDriver driver, int maxTasks, int maxQueue, int maxPayload, LongSupplier clock) {
        if (driver == null || clock == null || maxTasks < 1 || maxTasks > 4096 || maxQueue < 1
                || maxQueue > 4096 || maxPayload < 1 || maxPayload > 8 * 1024 * 1024) {
            throw new IllegalArgumentException("Invalid helper resource limits");
        }
        this.driver = driver; this.clock = clock; this.maxTasks = maxTasks;
        this.maxQueue = maxQueue; this.maxPayload = maxPayload; maxTaskIds = maxTasks * 16;
        maxQueuedBytes = Math.min(16L * 1024 * 1024, (long) maxPayload * maxQueue);
        final long capturedManager = managerGeneration;
        final long capturedSession = sessionGeneration;
        callback = (kind, a, b, c, d, data, length, context) ->
            enqueue(capturedManager, capturedSession, kind, a, b, c, d, data, length, context);
    }
    private void begin() {
        synchronized (state) {
            if (busy || closed || closing || fenced) { throw new OperationFailure(); }
            busy = true; operationThread = Thread.currentThread();
        }
    }
    private void end() {
        synchronized (state) { busy = false; operationThread = null; state.notifyAll(); }
    }
    public void start(RuntimeConfig config) {
        if (config == null) { throw new IllegalArgumentException("Private configuration is required"); }
        begin(); boolean failed = false;
        try {
            synchronized (state) { if (initialized || claimed) { throw new OperationFailure(); } }
            synchronized (PROCESS_LEASE) {
                if (owner != null) { throw new OperationFailure(); }
                owner = this; claimed = true;
            }
            driver.bind(callback);
            synchronized (state) { initAttempted = true; }
            if (!driver.init(config)) { throw new OperationFailure(); }
            synchronized (state) { initialized = true; startAttempted = true; }
            if (!driver.start()) { throw new OperationFailure(); }
            synchronized (state) { started = true; }
        } catch (RuntimeException | LinkageError failure) { failed = true; }
        finally { end(); }
        if (failed) { close(); throw new OperationFailure(); }
    }
    public void connect(DeviceCredential credential) {
        if (credential == null) { throw new IllegalArgumentException("Private credential is required"); }
        begin(); boolean failed = false;
        try {
            synchronized (state) { if (!started || connected) { throw new OperationFailure(); } }
            int result = driver.connect(credential);
            if (result <= 0) { throw new OperationFailure(); }
            synchronized (state) { connection = result; connected = true; }
        } catch (RuntimeException | LinkageError failure) { failed = true; }
        finally { end(); }
        if (failed) { close(); throw new OperationFailure(); }
    }
    /** Returns a private correlation token, never a stream-success claim. Absolute monotonic deadline. */
    public long openLive(int channel, int stream, int mode, long deadline) {
        if (channel < 0 || stream < 0 || mode < 0 || deadline <= clock.getAsLong()) {
            throw new IllegalArgumentException("Invalid live request");
        }
        begin();
        long context = 0;
        boolean accepted = false;
        try {
            final int nativeConnection;
            synchronized (state) {
                if (!connected || tasks.size() >= maxTasks || usedTaskIds.size() >= maxTaskIds) { throw new OperationFailure(); }
                nativeConnection = connection;
            }
            context = CONTEXTS.incrementAndGet();
            if (context <= 0) { throw new OperationFailure(); }
            // Reserve bounded ownership before JNI so synchronous errors do not depend on data queue space.
            synchronized (state) { tasks.put(context, new Task(context, 0, deadline)); }
            int nativeTask = driver.requestLive(nativeConnection, channel, stream, mode, context);
            if (nativeTask <= 0) { throw new OperationFailure(); }
            boolean recycled;
            synchronized (state) {
                recycled = !usedTaskIds.add(nativeTask);
                if (!recycled) {
                    Task task = tasks.get(context);
                    task.nativeId = nativeTask;
                    // A synchronous callback is attributable only after its ID matches the JNI return.
                    if (task.terminalEvent != null && task.terminalEvent.nativeId(0) != nativeTask) {
                        task.terminal = false; task.terminalEvent = null;
                    }
                    accepted = true;
                } else {
                    // Retire the rejected context and any current owner before closing their shared ID.
                    Iterator<Task> owned = tasks.values().iterator();
                    while (owned.hasNext()) {
                        Task task = owned.next();
                        if (task.context == context || task.nativeId == nativeTask) {
                            removeQueuedTaskEvents(task.context); owned.remove();
                        }
                    }
                }
            }
            if (recycled) {
                // Never attach a new task to an ID that could still have late native callbacks.
                try { if (!driver.closeLive(nativeTask)) { addFailure(CleanupStatus.TASK_CLOSE); } }
                catch (RuntimeException | LinkageError failure) { addFailure(CleanupStatus.TASK_CLOSE); }
                throw new OperationFailure();
            }
            return context;
        } catch (RuntimeException | LinkageError failure) { throw new OperationFailure(); }
        finally {
            if (!accepted && context != 0) {
                synchronized (state) { tasks.remove(context); removeQueuedTaskEvents(context); }
            }
            end();
        }
    }
    private void enqueue(long manager, long session, CallbackKind kind, int a, int b, int c, int d,
                         byte[] data, int length, long context) {
        synchronized (state) {
            if (closed || closing || fenced || !claimed || manager != managerGeneration || session != sessionGeneration) { return; }
            if (kind == null || length < 0 || length > maxPayload || (data == null && length != 0)
                    || (data != null && length > data.length)) {
                if (dropped < Integer.MAX_VALUE) { dropped++; }
                return;
            }
            if (taskEvent(kind)) {
                Task task = tasks.get(context);
                if (task == null || task.terminal || a <= 0 || (task.nativeId != 0 && task.nativeId != a)) { return; }
                if (kind == CallbackKind.TASK_ERR) {
                    // One zero-payload terminal record per owned task; independent of data queue pressure.
                    if (length != 0) { return; }
                    task.terminal = true;
                    task.terminalEvent = new PrivateEvent(kind, a, b, c, d, null, 0, context, manager, session);
                    removeQueuedTaskEvents(context);
                    return;
                }
            }
            if (queue.size() >= maxQueue || queuedBytes + length > maxQueuedBytes) {
                if (dropped < Integer.MAX_VALUE) { dropped++; }
                return;
            }
            queue.addLast(new PrivateEvent(kind, a, b, c, d, data, length, context, manager, session));
            queuedBytes += length;
        }
    }
    private static boolean taskEvent(CallbackKind kind) { return kind == CallbackKind.TASK_DATA || kind == CallbackKind.TASK_ERR; }
    private static boolean connectionEvent(CallbackKind kind) {
        return kind == CallbackKind.CONNECT || kind == CallbackKind.DISCONNECT || kind == CallbackKind.SWITCH_CONNECT
            || kind == CallbackKind.RENEW_TOKEN || kind == CallbackKind.NOTIFY_DATA || kind == CallbackKind.SUBSCRIBE_DATA;
    }
    /** Pull-based delivery avoids executing consumer code on native threads or under any controller lock. */
    public List<PrivateEvent> drain() {
        List<PrivateEvent> result = new ArrayList<>();
        List<Task> terminal = new ArrayList<>();
        try { begin(); }
        catch (OperationFailure unavailable) { return result; }
        try {
            synchronized (state) {
                if (fenced) { return result; }
                Iterator<Task> owned = tasks.values().iterator();
                while (owned.hasNext()) {
                    Task task = owned.next();
                    if (task.terminal) {
                        if (task.deadline > clock.getAsLong()) { result.add(task.terminalEvent); }
                        terminal.add(task); owned.remove();
                    }
                }
                while (!queue.isEmpty()) {
                    PrivateEvent event = queue.removeFirst(); queuedBytes -= event.declaredLength();
                    if (taskEvent(event.kind())) {
                        Task task = tasks.get(event.nativeContext());
                        if (task == null || task.terminal || task.nativeId != event.nativeId(0) || task.deadline <= clock.getAsLong()) { continue; }
                        result.add(event);
                    } else if (!connectionEvent(event.kind()) || (connected && event.nativeId(0) == connection)) {
                        result.add(event);
                    }
                }
            }
            for (Task task : terminal) {
                try { if (!driver.closeLive(task.nativeId)) { addFailure(CleanupStatus.TASK_CLOSE); } }
                catch (RuntimeException | LinkageError failure) { addFailure(CleanupStatus.TASK_CLOSE); }
            }
            // A concurrent close fences any data collected before it began.
            synchronized (state) {
                if (fenced) { result.clear(); }
                else {
                    // Errors arriving while drain closes another task fence previously collected data too.
                    Iterator<PrivateEvent> delivered = result.iterator();
                    while (delivered.hasNext()) {
                        PrivateEvent event = delivered.next();
                        if (event.kind() == CallbackKind.TASK_DATA) {
                            Task task = tasks.get(event.nativeContext());
                            if (task == null || task.terminal) { delivered.remove(); }
                        }
                    }
                }
            }
            return result;
        } finally { end(); }
    }
    /** Explicit cancellation/removal/terminal completion all release the native live task. */
    public void cancel(long context) {
        begin();
        try {
            Task task;
            synchronized (state) {
                task = tasks.remove(context);
                removeQueuedTaskEvents(context);
            }
            if (task != null) {
                try { if (!driver.closeLive(task.nativeId)) { addFailure(CleanupStatus.TASK_CLOSE); } }
                catch (RuntimeException | LinkageError failure) { addFailure(CleanupStatus.TASK_CLOSE); }
            }
        } finally { end(); }
    }
    // Caller holds state. No JNI is allowed in callback ownership transitions.
    private void removeQueuedTaskEvents(long context) {
        Iterator<PrivateEvent> events = queue.iterator();
        while (events.hasNext()) {
            PrivateEvent event = events.next();
            if (taskEvent(event.kind()) && event.nativeContext() == context) {
                queuedBytes -= event.declaredLength(); events.remove();
            }
        }
    }
    public void expire() {
        List<Long> expired = new ArrayList<>();
        synchronized (state) {
            long now = clock.getAsLong();
            for (Task task : tasks.values()) { if (task.deadline <= now) { expired.add(task.context); } }
        }
        for (long context : expired) { cancel(context); }
    }
    private void addFailure(int flag) {
        synchronized (state) {
            failures |= flag; cleanup = new CleanupStatus(failures, false);
            // A resource-release failure fences further work immediately, even before manager close.
            fenced = true; queue.clear(); queuedBytes = 0;
        }
    }
    @Override public void close() {
        List<Task> ownedTasks;
        int ownedConnection;
        boolean needStop, needQuit;
        synchronized (state) {
            if (closed) { return; }
            if (closing) { return; }
            closing = true; fenced = true; queue.clear(); queuedBytes = 0;
            long deadline = System.nanoTime() + 5_000_000_000L;
            while (busy) {
                if (operationThread == Thread.currentThread()) {
                    closing = false; cleanup = new CleanupStatus(failures | CleanupStatus.BUSY, false); return;
                }
                long remaining = deadline - System.nanoTime();
                if (remaining <= 0) {
                    closing = false; cleanup = new CleanupStatus(failures | CleanupStatus.BUSY, false); return;
                }
                try { state.wait(Math.max(1L, Math.min(100L, remaining / 1_000_000L))); }
                catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt(); closing = false;
                    cleanup = new CleanupStatus(failures | CleanupStatus.BUSY, false); return;
                }
            }
            ownedTasks = new ArrayList<>(tasks.values()); tasks.clear();
            ownedConnection = connected ? connection : 0;
            connected = false; needStop = startAttempted; needQuit = initAttempted;
        }
        for (Task task : ownedTasks) {
            try { if (!driver.closeLive(task.nativeId)) { addFailure(CleanupStatus.TASK_CLOSE); } }
            catch (RuntimeException | LinkageError failure) { addFailure(CleanupStatus.TASK_CLOSE); }
        }
        if (ownedConnection > 0) {
            try { driver.disconnect(ownedConnection); }
            catch (RuntimeException | LinkageError failure) { addFailure(CleanupStatus.DISCONNECT); }
        }
        if (needStop) {
            try { driver.stop(); }
            catch (RuntimeException | LinkageError failure) { addFailure(CleanupStatus.STOP); }
        }
        if (needQuit) {
            try { driver.quit(); }
            catch (RuntimeException | LinkageError failure) { addFailure(CleanupStatus.QUIT); }
        }
        synchronized (state) {
            closed = true; closing = false; queue.clear(); queuedBytes = 0;
            cleanup = new CleanupStatus(failures, failures == 0);
        }
        // Any unresolved cleanup quarantines this process. Recovery requires controlled process restart.
        if (failures == 0) { synchronized (PROCESS_LEASE) { if (owner == this) { owner = null; } } }
    }
    public CleanupStatus cleanupStatus() { synchronized (state) { return cleanup; } }
    public int activeTasks() {
        synchronized (state) {
            int active = 0;
            for (Task task : tasks.values()) { if (task.nativeId > 0 && !task.terminal) { active++; } }
            return active;
        }
    }
    public int droppedCallbacks() { synchronized (state) { return dropped; } }
    @Override public String toString() { return "LifecycleController[private]"; }
}
