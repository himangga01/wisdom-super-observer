package com.wso.tvt.local;

import java.util.ArrayDeque;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/** One private manager/generation per process. No credential or media acceptance state. */
public final class LocalSerialTransport implements AutoCloseable {
    public enum State { NEW, DISCOVERING, DISCOVERED, OPENING, OPEN, FAILED, CLOSING, CLOSED, QUARANTINED }
    enum ReceiveMode { CALLBACK, POLL }
    static final class Event {
        enum Kind { CONNECTION, DATA }
        private final Kind kind;
        private final byte[] bytes;
        private final boolean connected;
        private final int deviceType;
        Event(Kind k, byte[] data, boolean connection, int type) {
            kind = k; bytes = data; connected = connection; deviceType = type;
        }
        Kind kind() { return kind; }
        byte[] bytes() { return bytes == null ? null : bytes.clone(); }
        boolean connected() { return connected; } int deviceType() { return deviceType; }
    }
    private static final Object PROCESS = new Object();
    private static final Set<Long> SEEN_ECHOES = new HashSet<>();
    private static LocalSerialTransport processOwner;
    private final Object stateMonitor = new Object();
    private final Object cleanupMonitor = new Object();
    private final LocalSerialDriver driver;
    private final LocalSerialConfig config;
    private final long startedNanos = System.nanoTime();
    private final ArrayDeque<Event> events = new ArrayDeque<>();
    private State state = State.NEW;
    private ReceiveMode receiveMode;
    private long echo, generation = 1;
    private int inFlight, queuedBytes, nativeError;
    private boolean closing, cleanupStarted, callbacksRemoved, interruptStarted, interruptProved,
            cleanupUncertain, recycled, openingNat2Failed;

    public LocalSerialTransport(LocalSerialDriver driver, LocalSerialConfig config) {
        if (driver == null || config == null) throw new IllegalArgumentException("Explicit driver/config required");
        this.driver = driver; this.config = config;
        synchronized (PROCESS) {
            if (processOwner != null) throw new IllegalStateException("Native process manager already owned or quarantined");
            if (SEEN_ECHOES.size() >= 1024) throw new IllegalStateException("Process echo history exhausted; replace process");
            processOwner = this;
        }
    }
    public State state() { synchronized (stateMonitor) { return state; } }
    ReceiveMode receiveMode() { synchronized (stateMonitor) { return receiveMode; } }
    int lastNativeError() { synchronized (stateMonitor) { return nativeError; } }
    private boolean expired() { return System.nanoTime() - startedNanos >= config.budgetNanos(); }
    private long begin(State expected, State next) {
        if (expired()) { close(); throw new IllegalStateException("Caller monotonic budget expired"); }
        synchronized (stateMonitor) {
            if (closing || state != expected || inFlight != 0) throw new IllegalStateException("Transport operation/state conflict");
            if (next == State.OPENING) openingNat2Failed = false;
            state = next; inFlight++; return echo;
        }
    }
    private void end() {
        boolean drain;
        synchronized (stateMonitor) { inFlight--; drain = closing && inFlight == 0; }
        if (drain) cleanup();
    }
    private void current() {
        if (expired()) { close(); throw new IllegalStateException("Caller monotonic budget expired"); }
        synchronized (stateMonitor) { if (closing) throw new IllegalStateException("Retired generation"); }
    }
    public int discover() {
        begin(State.NEW, State.DISCOVERING);
        try {
            long allocated;
            try { allocated = driver.allocate(); }
            catch (RuntimeException | Error unknownAllocation) {
                // Native allocation may have occurred before the boundary threw.
                synchronized (stateMonitor) { cleanupUncertain = true; }
                throw unknownAllocation;
            }
            synchronized (stateMonitor) { echo = allocated; }
            if (allocated == 0) {
                synchronized (stateMonitor) { state = State.FAILED; }
                throw new IllegalStateException("Zero echo allocation");
            }
            synchronized (PROCESS) {
                if (!SEEN_ECHOES.add(allocated)) {
                    synchronized (stateMonitor) {
                        recycled = true; closing = true; generation++; state = State.QUARANTINED;
                    }
                    throw new IllegalStateException("Recycled echo cannot identify callback generation");
                }
            }
            current();
            final long callbackGeneration;
            synchronized (stateMonitor) { callbackGeneration = generation; }
            try {
                driver.bind(allocated, new LocalSerialDriver.Callbacks() {
                    public void connection(long callbackEcho, boolean connected, int type, String ignored) {
                        acceptConnection(callbackEcho, callbackGeneration, connected, type);
                    }
                    public int data(long callbackEcho, byte[] bytes) {
                        return acceptData(callbackEcho, callbackGeneration, bytes);
                    }
                });
            } finally {
                // A concurrent close may have removed maps before bind finished inserting.
                // Drain cleanup must remove them again after this call returns.
                synchronized (stateMonitor) { callbacksRemoved = false; }
            }
            current();
            int type = driver.discover(allocated, config);
            current();
            int error = driver.error(allocated);
            current();
            synchronized (stateMonitor) {
                if (closing) throw new IllegalStateException("Retired generation");
                nativeError = error;
                if (state != State.FAILED) state = supported(type) ? State.DISCOVERED : State.FAILED;
            }
            return type;
        } catch (RuntimeException | Error failure) {
            synchronized (stateMonitor) { if (!closing) state = State.FAILED; }
            throw failure;
        } finally { end(); }
    }
    private static boolean supported(int type) { return type == 3 || type == 10001 || type == 20001; }
    public int openTransport() {
        long owned = begin(State.DISCOVERED, State.OPENING);
        try {
            int result = driver.openTransport(owned, config);
            current();
            int connect = result == 0 ? driver.connectType(owned) : 0;
            current();
            synchronized (stateMonitor) {
                if (closing) throw new IllegalStateException("Retired generation");
                if (state != State.FAILED) {
                    state = result == 0 ? State.OPEN : State.FAILED;
                    receiveMode = result == 0 ? (connect == 3 ? ReceiveMode.CALLBACK : ReceiveMode.POLL) : null;
                    if (receiveMode == ReceiveMode.CALLBACK && openingNat2Failed) state = State.FAILED;
                    if (receiveMode == ReceiveMode.POLL) {
                        // Only type three owns callback bytes. Pending opening data from any
                        // other selected type must not be mixed with poll receive.
                        events.removeIf(event -> event.kind == Event.Kind.DATA);
                        queuedBytes = 0;
                    }
                }
            }
            return result;
        } catch (RuntimeException | Error failure) {
            synchronized (stateMonitor) { if (!closing) state = State.FAILED; }
            throw failure;
        } finally { end(); }
    }
    // Package access: only a separately authorized protocol adapter may send allowlisted frames.
    int send(byte[] bytes, int length) {
        config.buffer(bytes, length);
        long owned = begin(State.OPEN, State.OPEN);
        try {
            int sent = driver.send(owned, bytes, length); current();
            if (sent > length) throw new IllegalStateException("Native send exceeds requested length");
            synchronized (stateMonitor) {
                if (closing) throw new IllegalStateException("Retired generation");
                if (sent < 0) state = State.FAILED;
            }
            return sent; // Caller must retain/retry unsent suffix under the same independent budget.
        } catch (RuntimeException | Error failure) {
            synchronized (stateMonitor) { if (!closing) state = State.FAILED; }
            throw failure;
        } finally { end(); }
    }
    int receive(byte[] bytes, int length) {
        config.buffer(bytes, length);
        synchronized (stateMonitor) { if (receiveMode != ReceiveMode.POLL) throw new IllegalStateException("Callback receive selected"); }
        long owned = begin(State.OPEN, State.OPEN);
        try {
            int count = driver.receive(owned, bytes, length); current();
            if (count > length) throw new IllegalStateException("Native receive exceeds actual/requested buffer");
            synchronized (stateMonitor) {
                if (closing) throw new IllegalStateException("Retired generation");
                if (count < 0) state = State.FAILED;
                else if (count > 0) enqueue(new Event(Event.Kind.DATA, Arrays.copyOf(bytes, count), false, 0));
            }
            return count;
        } catch (RuntimeException | Error failure) {
            synchronized (stateMonitor) { if (!closing) state = State.FAILED; }
            throw failure;
        } finally { end(); }
    }
    private boolean callbackCurrent(long callbackEcho, long callbackGeneration) {
        return !closing && !expired() && echo != 0 && callbackEcho == echo && callbackGeneration == generation
                && state != State.FAILED && state != State.QUARANTINED && state != State.CLOSED;
    }
    private void acceptConnection(long callbackEcho, long callbackGeneration, boolean connected, int type) {
        synchronized (stateMonitor) {
            if (!callbackCurrent(callbackEcho, callbackGeneration)) return;
            enqueue(new Event(Event.Kind.CONNECTION, null, connected, type));
            if (!connected) {
                // Discovery races independent NAT1/NAT2 branches. Only the selected
                // callback socket treats this NAT2 status as a transport failure.
                if (state == State.OPENING) openingNat2Failed = true;
                else if (state == State.OPEN && receiveMode == ReceiveMode.CALLBACK) state = State.FAILED;
            }
        }
    }
    private int acceptData(long callbackEcho, long callbackGeneration, byte[] bytes) {
        synchronized (stateMonitor) {
            if (!callbackCurrent(callbackEcho, callbackGeneration) || (state != State.OPEN && state != State.OPENING)
                    || (state == State.OPEN && receiveMode != ReceiveMode.CALLBACK) || bytes == null || bytes.length == 0
                    || bytes.length > config.maxBufferBytes()) return 0;
            if (events.size() >= config.maxQueuedEvents() || bytes.length > config.maxQueuedBytes() - queuedBytes) {
                state = State.FAILED; return 0;
            }
            enqueue(new Event(Event.Kind.DATA, bytes.clone(), false, 0)); return bytes.length;
        }
    }
    private void enqueue(Event event) {
        int size = event.bytes == null ? 0 : event.bytes.length;
        if (events.size() >= config.maxQueuedEvents() || size > config.maxQueuedBytes() - queuedBytes) {
            state = State.FAILED; return;
        }
        events.add(event); queuedBytes += size;
    }
    Event pollEvent() {
        if (expired()) { close(); return null; }
        synchronized (stateMonitor) {
            if (closing) return null;
            Event event = events.poll();
            if (event != null && event.bytes != null) queuedBytes -= event.bytes.length;
            return event;
        }
    }
    public void close() {
        boolean drain;
        synchronized (stateMonitor) {
            if (state == State.CLOSED || state == State.QUARANTINED) return;
            if (!closing) { closing = true; generation++; state = State.CLOSING; events.clear(); queuedBytes = 0; }
            drain = inFlight == 0;
        }
        // Interrupt may run concurrently with the outstanding JNI operation. Never destroy until drained.
        interrupt();
        if (drain) cleanup();
    }
    private void removeCallbacks() {
        long owned;
        synchronized (stateMonitor) { if (callbacksRemoved || echo == 0 || recycled) return; callbacksRemoved = true; owned = echo; }
        try { driver.removeCallbacks(owned); }
        catch (RuntimeException | Error failure) { synchronized (stateMonitor) { cleanupUncertain = true; } }
    }
    private void interrupt() {
        // Serialize cleanup operations, independently of callback/state monitors.
        synchronized (cleanupMonitor) {
            long owned;
            synchronized (stateMonitor) { if (interruptStarted || echo == 0 || recycled) return; interruptStarted = true; owned = echo; }
            removeCallbacks();
            boolean proved = false;
            try { proved = driver.interrupt(owned); }
            catch (RuntimeException | Error ignored) { /* Retain original resource and process lease. */ }
            synchronized (stateMonitor) { interruptProved = proved; }
        }
    }
    private void cleanup() {
        synchronized (cleanupMonitor) {
            long owned;
            synchronized (stateMonitor) {
                if (cleanupStarted || inFlight != 0 || !closing || recycled) return;
                cleanupStarted = true; owned = echo;
            }
            removeCallbacks(); interrupt();
            boolean mayDestroy;
            synchronized (stateMonitor) { mayDestroy = !cleanupUncertain; }
            boolean destroyed = owned == 0;
            if (owned != 0 && mayDestroy) {
                try { destroyed = driver.destroy(owned); }
                catch (RuntimeException | Error ignored) { /* Unknown native outcome is quarantined. */ }
            }
            boolean proved;
            synchronized (stateMonitor) {
                proved = destroyed && (owned == 0 || interruptProved) && !cleanupUncertain;
                state = proved ? State.CLOSED : State.QUARANTINED;
                // Keep original echo even on uncertainty; never substitute a recycled handle.
            }
            if (proved) synchronized (PROCESS) { if (processOwner == this) processOwner = null; }
        }
    }
}
