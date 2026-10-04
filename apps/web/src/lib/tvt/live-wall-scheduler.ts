/**
 * Pure start/stop scheduling for the multi-camera live wall (통합 관제).
 *
 * A wall can show many channels, but the local media backend runs only a few
 * native live sessions at once and rejects starts that overlap. This module
 * owns the order and pace of starts. It never touches the DOM or the network:
 * the React layer performs the actual player start/stop through `onStart` and
 * `onStop`, and reports each outcome back with `reportLive`/`reportFailed`.
 *
 * Invariants: at most `capacity` tiles are `starting|live`; at most one tile is
 * `starting` (starts are strictly sequential); every queued id appears once.
 *
 * Pacing (ruling R118): a native session that fails keeps the device busy while
 * it retires, and the provider then refuses new starts with HTTP 429. After any
 * failed start the scheduler therefore cools down before the next start, with
 * exponential back-off (3 s, 6 s, 12 s, then 15 s) that resets once any tile is
 * live. A `busy` (429) start goes back to its original queue place without
 * spending the tile's single retry; other failures keep the one 2 s retry.
 */

/**
 * Current backend limit: the local media worker admits two concurrent live
 * sessions (SQL separately allows at most four non-closed leases per
 * tenant/actor). Raise it here, in one place, when the worker capacity grows.
 */
export const LIVE_WALL_CONCURRENCY = 2;
/** A start that has reported neither live nor failed by then counts as failed. */
export const LIVE_WALL_START_TIMEOUT_MS = 15_000;
/** A failed start is retried once after this delay while it is still requested. */
export const LIVE_WALL_RETRY_DELAY_MS = 2_000;
/** First cool-down after a failed start; each further consecutive failure doubles it. */
export const LIVE_WALL_COOLDOWN_BASE_MS = 3_000;
/** Upper bound of the cool-down back-off. */
export const LIVE_WALL_COOLDOWN_MAX_MS = 15_000;

export type LiveTileState = 'idle' | 'queued' | 'starting' | 'live' | 'failed' | 'stopped';
/** How a start failed: `busy` (HTTP 429, try later) re-queues the tile; `failed` uses its single retry. */
export type LiveStartFailure = 'failed' | 'busy';

export type LiveWallSnapshot = Readonly<{
  /** Every tile the scheduler has handled; an absent id is `idle`. */
  states: Readonly<Record<string, LiveTileState>>;
  /** Queued tile ids in start order (the focused tile, when queued, is first). */
  queue: readonly string[];
  /** Failed tiles whose single automatic retry is still pending. */
  retrying: readonly string[];
  /** Queued tiles whose last start was refused as busy (HTTP 429). */
  busy: readonly string[];
  /** No new start begins until the post-failure cool-down ends. */
  coolingDown: boolean;
  focused: string | null;
  capacity: number;
}>;

/** Injectable timer so deadlines, retries and cool-downs can be driven by fake clocks in tests. */
export type LiveWallTimer = {
  set(callback: () => void, ms: number): unknown;
  clear(handle: unknown): void;
};

export type LiveWallSchedulerOptions = {
  /** Start the tile's player. Throwing counts as a failed start. */
  onStart(id: string): void;
  /** Stop and release the tile's player. Called whenever a tile leaves `starting|live`. */
  onStop(id: string): void;
  capacity?: number;
  startTimeoutMs?: number;
  retryDelayMs?: number;
  cooldownBaseMs?: number;
  cooldownMaxMs?: number;
  timer?: LiveWallTimer;
};

export type LiveWallScheduler = {
  /** Enqueue in the given order; tiles already queued, starting or live are ignored. */
  requestPlay(ids: readonly string[]): void;
  /** Stop one tile, or several atomically so nothing starts in between. */
  requestStop(ids: string | readonly string[]): void;
  stopAll(): void;
  /** Give one tile scheduling priority (or clear it with `null`). */
  focus(id: string | null): void;
  /** The tile's player confirmed its first presented frame. */
  reportLive(id: string): void;
  /** The tile's player failed while starting or playing; `busy` marks a start refused with HTTP 429. */
  reportFailed(id: string, kind?: LiveStartFailure): void;
  getSnapshot(): LiveWallSnapshot;
  subscribe(listener: (snapshot: LiveWallSnapshot) => void): () => void;
};

const systemTimer: LiveWallTimer = {
  set: (callback, ms) => setTimeout(callback, ms),
  clear: handle => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export const tileState = (snapshot: LiveWallSnapshot, id: string): LiveTileState => snapshot.states[id] ?? 'idle';

/** Whether the user currently wants the tile playing, including a pending automatic retry. */
export function isRequested(snapshot: LiveWallSnapshot, id: string): boolean {
  const state = tileState(snapshot, id);
  return state === 'queued' || state === 'starting' || state === 'live' || snapshot.retrying.includes(id);
}

export function createLiveWallScheduler(options: LiveWallSchedulerOptions): LiveWallScheduler {
  const capacity = options.capacity ?? LIVE_WALL_CONCURRENCY;
  if (!Number.isSafeInteger(capacity) || capacity < 1) throw new RangeError('Live wall capacity must be a positive integer');
  const startTimeoutMs = options.startTimeoutMs ?? LIVE_WALL_START_TIMEOUT_MS;
  const retryDelayMs = options.retryDelayMs ?? LIVE_WALL_RETRY_DELAY_MS;
  const cooldownBaseMs = options.cooldownBaseMs ?? LIVE_WALL_COOLDOWN_BASE_MS;
  const cooldownMaxMs = options.cooldownMaxMs ?? LIVE_WALL_COOLDOWN_MAX_MS;
  const timer = options.timer ?? systemTimer;

  const states = new Map<string, LiveTileState>();
  const queue: string[] = [];
  /** Sequence number of each tile's most recent start; orders preemption and identifies attempts. */
  const startOrder = new Map<string, number>();
  /** Tiles whose single automatic retry has been used since the user last asked to play. */
  const retrySpent = new Set<string>();
  const deadlines = new Map<string, unknown>();
  const retries = new Map<string, {handle: unknown}>();
  /** Queue ticket from each tile's latest play request or re-queue; retried and busy tiles resume in ticket order. */
  const tickets = new Map<string, number>();
  let ticketSequence = 0;
  const busy = new Set<string>();
  let cooldown: {handle: unknown} | null = null;
  /** Consecutive failed starts since a tile was last live; sets the next cool-down. */
  let failedStarts = 0;
  const listeners = new Set<(snapshot: LiveWallSnapshot) => void>();
  /** onStart/onStop calls run after the state change that caused them, in order. */
  const effects: (() => void)[] = [];
  let focused: string | null = null;
  let sequence = 0;
  let dirty = false;
  let flushing = false;
  let snapshot = build();

  const state = (id: string) => states.get(id) ?? 'idle';
  function set(id: string, next: LiveTileState) {
    if (state(id) === next) return;
    states.set(id, next);
    dirty = true;
  }
  function activeCount() {
    let count = 0;
    for (const value of states.values()) if (value === 'starting' || value === 'live') count++;
    return count;
  }
  function removeFromQueue(id: string) {
    const index = queue.indexOf(id);
    if (index < 0) return;
    queue.splice(index, 1);
    dirty = true;
  }
  function enqueue(id: string, position: 'resume' | 'tail') {
    removeFromQueue(id);
    if (position === 'tail') tickets.set(id, ++ticketSequence);
    if (id === focused) queue.unshift(id);
    else if (position === 'tail') queue.push(id);
    else {
      // A retried or busy tile resumes its original place: ahead of every waiting tile queued
      // after it (and behind a queued focused tile), so re-entries keep their original order.
      const ticket = tickets.get(id) ?? 0;
      let index = focused !== null && queue[0] === focused ? 1 : 0;
      while (index < queue.length && (tickets.get(queue[index]) ?? 0) < ticket) index++;
      queue.splice(index, 0, id);
    }
    set(id, 'queued');
    dirty = true;
  }
  function clearDeadline(id: string) {
    if (!deadlines.has(id)) return;
    timer.clear(deadlines.get(id));
    deadlines.delete(id);
  }
  function cancelRetry(id: string) {
    const pending = retries.get(id);
    if (!pending) return;
    retries.delete(id);
    timer.clear(pending.handle);
    dirty = true;
  }
  function clearBusy(id: string) {
    if (busy.delete(id)) dirty = true;
  }
  /** Hold every new start for 3 s after a failed start, doubling per consecutive failure up to 15 s. */
  function beginCooldown() {
    failedStarts++;
    const delay = Math.min(cooldownBaseMs * 2 ** (failedStarts - 1), cooldownMaxMs);
    if (cooldown) timer.clear(cooldown.handle);
    const pending = {handle: undefined as unknown};
    pending.handle = timer.set(() => transact(() => {
      if (cooldown !== pending) return;
      cooldown = null;
      dirty = true;
    }), delay);
    cooldown = pending;
    dirty = true;
  }
  function endCooldown() {
    if (!cooldown) return;
    timer.clear(cooldown.handle);
    cooldown = null;
    dirty = true;
  }
  /** Leave `starting|live` and release the player. */
  function halt(id: string, next: 'queued' | 'failed' | 'stopped') {
    clearDeadline(id);
    set(id, next);
    effects.push(() => {
      try { options.onStop(id); } catch { /* The tile is already released here; nothing else to undo. */ }
    });
  }
  const isCurrentStart = (id: string, attempt: number) => state(id) === 'starting' && startOrder.get(id) === attempt;
  function start(id: string) {
    removeFromQueue(id);
    clearBusy(id);
    set(id, 'starting');
    const attempt = ++sequence;
    startOrder.set(id, attempt);
    deadlines.set(id, timer.set(() => transact(() => { if (isCurrentStart(id, attempt)) fail(id); }), startTimeoutMs));
    effects.push(() => {
      if (!isCurrentStart(id, attempt)) return;
      try { options.onStart(id); } catch { transact(() => { if (isCurrentStart(id, attempt)) fail(id); }); }
    });
  }
  /**
   * A busy (429) start goes back to its queue place and keeps its single retry. Other failed
   * starts earn that one retry. Every failed start cools down; a live failure does neither.
   */
  function fail(id: string, kind: LiveStartFailure = 'failed') {
    const failedStart = state(id) === 'starting';
    if (failedStart && kind === 'busy') {
      halt(id, 'queued');
      enqueue(id, 'resume');
      busy.add(id);
      beginCooldown();
      return;
    }
    halt(id, 'failed');
    if (!failedStart) return;
    if (!retrySpent.has(id)) {
      retrySpent.add(id);
      const pending = {handle: undefined as unknown};
      pending.handle = timer.set(() => transact(() => {
        if (retries.get(id) !== pending) return;
        retries.delete(id);
        dirty = true;
        if (state(id) === 'failed') enqueue(id, 'resume');
      }), retryDelayMs);
      retries.set(id, pending);
      dirty = true;
    }
    beginCooldown();
  }
  function stopOne(id: string) {
    cancelRetry(id);
    clearBusy(id);
    const current = state(id);
    if (current === 'queued') { removeFromQueue(id); set(id, 'stopped'); }
    else if (current === 'starting' || current === 'live') halt(id, 'stopped');
    else if (current === 'failed') set(id, 'stopped');
  }
  /**
   * A queued focused tile may take the slot of the least-recently-started
   * non-focused live tile, which goes back to the tail of the queue.
   */
  function preemptForFocus() {
    if (focused === null || state(focused) !== 'queued' || activeCount() < capacity) return;
    let victim: string | null = null;
    for (const [id, value] of states) {
      if (value !== 'live' || id === focused) continue;
      if (victim === null || (startOrder.get(id) ?? 0) < (startOrder.get(victim) ?? 0)) victim = id;
    }
    if (victim === null) return;
    halt(victim, 'queued');
    tickets.set(victim, ++ticketSequence);
    queue.push(victim);
    dirty = true;
  }
  function pump() {
    // While cooling down nothing starts, and no live tile is preempted for a start that must wait.
    if (cooldown) return;
    preemptForFocus();
    if (queue.length === 0 || activeCount() >= capacity) return;
    for (const value of states.values()) if (value === 'starting') return;
    start(queue[0]);
  }
  function build(): LiveWallSnapshot {
    return Object.freeze({
      states: Object.freeze(Object.fromEntries(states)),
      queue: Object.freeze([...queue]),
      retrying: Object.freeze([...retries.keys()]),
      busy: Object.freeze([...busy]),
      coolingDown: cooldown !== null,
      focused,
      capacity,
    });
  }
  /** Run queued effects, then publish one snapshot. Re-entrant calls from effects join the outer drain. */
  function flush() {
    if (flushing) return;
    flushing = true;
    try {
      while (effects.length > 0 || dirty) {
        const effect = effects.shift();
        if (effect) { effect(); continue; }
        dirty = false;
        snapshot = build();
        for (const listener of [...listeners]) listener(snapshot);
      }
    } finally {
      flushing = false;
    }
  }
  function transact(change: () => void) {
    change();
    pump();
    flush();
  }

  return {
    requestPlay(ids) {
      transact(() => {
        for (const id of ids) {
          const current = state(id);
          if (current === 'queued' || current === 'starting' || current === 'live') continue;
          cancelRetry(id);
          retrySpent.delete(id);
          enqueue(id, 'tail');
        }
      });
    },
    requestStop(ids) {
      transact(() => { for (const id of typeof ids === 'string' ? [ids] : ids) stopOne(id); });
    },
    stopAll() {
      // Nothing is left to start, so the cool-down timer goes too; the back-off streak is kept.
      transact(() => { for (const id of [...states.keys()]) stopOne(id); endCooldown(); });
    },
    focus(id) {
      transact(() => {
        if (focused !== id) { focused = id; dirty = true; }
        if (id !== null && state(id) === 'queued' && queue[0] !== id) { removeFromQueue(id); queue.unshift(id); dirty = true; }
      });
    },
    reportLive(id) {
      transact(() => {
        if (state(id) !== 'starting') return;
        clearDeadline(id);
        retrySpent.delete(id);
        failedStarts = 0;
        set(id, 'live');
      });
    },
    reportFailed(id, kind = 'failed') {
      transact(() => {
        const current = state(id);
        if (current === 'starting' || current === 'live') fail(id, kind);
      });
    },
    getSnapshot: () => snapshot,
    subscribe(listener) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
  };
}
