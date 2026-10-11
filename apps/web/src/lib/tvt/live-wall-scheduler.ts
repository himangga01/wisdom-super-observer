import type {LivePlayerStartupPhase} from './local-live-player';

/**
 * Pure start/stop scheduling for the multi-camera live wall (통합 관제).
 *
 * A wall can show many channels, but the local media backend runs only a few
 * native live sessions at once and rejects starts that overlap. This module
 * owns the order and pace of starts. It never touches the DOM or the network:
 * the React layer performs the actual player start/stop through `onStart` and
 * `onStop`, and reports each outcome back with `reportLive`/`reportFailed`.
 *
 * Invariants: active tiles plus queued replacement slot reservations never
 * exceed `capacity`; at most one tile is `starting`; queued ids appear once.
 *
 * Pacing (R118/R141): generic failed starts hold every new start for
 * 3 s, 6 s, 12 s, then 15 s, resetting once any tile is live. A `busy` (429)
 * start parks only that target for its own 3/6/12/15 s backoff, keeping its
 * original queue ticket and single ordinary retry. Other ready targets can
 * progress; parked replacements retain their freed slots. A different tile
 * going live never resets a target's busy backoff. Other failures retry once
 * after 2 s. The runtime still owns the original Stop settlement barrier.
 * A no-signal result is terminal until manual play and never starts a cooldown.
 */

/**
 * Stage-1 backend limit: sixteen live sources and sixteen non-closed leases
 * per tenant/actor. Starts remain sequential even while sixteen tiles play.
 */
export const LIVE_WALL_CONCURRENCY = 16;
/** Original Stop wait: the client's 25 s request bound plus a 1 s delivery margin. */
export const LIVE_WALL_START_TIMEOUT_MS = 26_000;
/** Starts when the player's HTTP start request begins, after the original Stop barrier. */
export const LIVE_WALL_REQUEST_TIMEOUT_MS = 26_000;
/** Offer creation, ICE (8 s), offer HTTP (25 s), and 2 s scheduling margin. */
export const LIVE_WALL_NEGOTIATION_TIMEOUT_MS = 35_000;
/** Combined frame/playing confirmation fallback: nominal 15 s frame allowance plus 25 s HTTP. */
export const LIVE_WALL_PRESENTATION_TIMEOUT_MS = 40_000;
/** A failed start is retried once after this delay while it is still requested. */
export const LIVE_WALL_RETRY_DELAY_MS = 2_000;
/** First cool-down after a failed start; each further consecutive failure doubles it. */
export const LIVE_WALL_COOLDOWN_BASE_MS = 3_000;
/** Upper bound of the cool-down back-off. */
export const LIVE_WALL_COOLDOWN_MAX_MS = 15_000;

export type LiveTileState = 'idle' | 'queued' | 'starting' | 'live' | 'failed' | 'nosignal' | 'stopped';
/** Busy re-queues, failed uses its single retry, and no signal waits for manual play. */
export type LiveStartFailure = 'failed' | 'busy' | 'nosignal' | 'handoff';

export type LiveWallSnapshot = Readonly<{
  /** Every tile the scheduler has handled; an absent id is `idle`. */
  states: Readonly<Record<string, LiveTileState>>;
  /** Queued ids in priority order; parked ids wait while eligible ids may start. */
  queue: readonly string[];
  /** Failed tiles whose single automatic retry is still pending. */
  retrying: readonly string[];
  /** Queued tiles whose last start was refused as busy (HTTP 429). */
  busy: readonly string[];
  /** No new start begins until the generic failed-start cool-down ends. */
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
  onStop(id: string, reason: 'queued' | 'failed' | 'nosignal' | 'stopped'): void;
  capacity?: number;
  /** Initial original-Stop wait only; later phases use their explicit bounded budgets. */
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
  /** Give one tile priority; atomically stop/requeue requested tiles whose stream changes. */
  focus(id: string | null, restart?: readonly string[]): void;
  /** The tile's player confirmed its first presented frame. */
  reportLive(id: string): void;
  /** Forward-only startup transitions; the caller must fence events to the current player. */
  reportStartupPhase(id: string, phase: LivePlayerStartupPhase): void;
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
  const startupPhases = new Map<string, number>();
  const retries = new Map<string, {handle: unknown}>();
  /** Queue ticket from each tile's latest play request or re-queue; retried and busy tiles resume in ticket order. */
  const tickets = new Map<string, number>();
  /** Stream replacements keep their freed slot through busy until live, stopped or failed. */
  const replacements = new Set<string>();
  /** Actual freed replacement slots, held only while their owners are queued. */
  const heldSlots = new Set<string>();
  let ticketSequence = 0;
  const busy = new Set<string>();
  const parks = new Map<string, {handle: unknown}>();
  /** Per-target delay persists across starts and other targets becoming live. */
  const busyDelays = new Map<string, number>();
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
      // Focus first, then pending stream replacements, then ordinary ticket order.
      // A replacement's busy requeue keeps its slot even if an older ordinary
      // ticket exists; ordinary retries cannot leapfrog pending replacements.
      const ticket = tickets.get(id) ?? 0;
      let index = focused !== null && queue[0] === focused ? 1 : 0;
      if (replacements.has(id)) {
        while (index < queue.length && replacements.has(queue[index])) index++;
      } else {
        while (index < queue.length && (replacements.has(queue[index]) || (tickets.get(queue[index]) ?? 0) < ticket)) index++;
      }
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
  function cancelPark(id: string) {
    const pending = parks.get(id);
    if (!pending) return;
    parks.delete(id);
    timer.clear(pending.handle);
  }
  function resetBusy(id: string) {
    cancelPark(id);
    busyDelays.delete(id);
    clearBusy(id);
  }
  function park(id: string) {
    cancelPark(id);
    const delay = Math.min(busyDelays.has(id) ? busyDelays.get(id)! * 2 : cooldownBaseMs, cooldownMaxMs);
    busyDelays.set(id, delay);
    const pending = {handle: undefined as unknown};
    pending.handle = timer.set(() => transact(() => {
      if (parks.get(id) !== pending) return;
      parks.delete(id);
      dirty = true;
    }), delay);
    parks.set(id, pending);
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
  function halt(id: string, next: 'queued' | 'failed' | 'nosignal' | 'stopped') {
    clearDeadline(id);
    startupPhases.delete(id);
    set(id, next);
    effects.push(() => {
      try { options.onStop(id, next); } catch { /* The tile is already released here; nothing else to undo. */ }
    });
  }
  const isCurrentStart = (id: string, attempt: number) => state(id) === 'starting' && startOrder.get(id) === attempt;
  function armDeadline(id: string, attempt: number, phase: number, ms: number) {
    clearDeadline(id);
    startupPhases.set(id, phase);
    deadlines.set(id, timer.set(() => transact(() => {
      if (isCurrentStart(id, attempt) && startupPhases.get(id) === phase) fail(id);
    }), ms));
  }
  function start(id: string) {
    removeFromQueue(id);
    heldSlots.delete(id);
    clearBusy(id);
    set(id, 'starting');
    const attempt = ++sequence;
    startOrder.set(id, attempt);
    armDeadline(id, attempt, 0, startTimeoutMs);
    effects.push(() => {
      if (!isCurrentStart(id, attempt)) return;
      try { options.onStart(id); } catch { transact(() => { if (isCurrentStart(id, attempt)) fail(id); }); }
    });
  }
  /**
   * A busy (429) start parks at its queue place and keeps its single retry. Other failed
   * starts earn that one retry. No signal has neither retry nor cooldown; a live failure also does neither.
   */
  function fail(id: string, kind: LiveStartFailure = 'failed') {
    if (kind !== 'busy') {
      replacements.delete(id);
      heldSlots.delete(id);
      resetBusy(id);
    }
    if (kind === 'nosignal' || kind === 'handoff') {
      cancelRetry(id);
      clearBusy(id);
      halt(id, kind === 'nosignal' ? 'nosignal' : 'failed');
      return;
    }
    const failedStart = state(id) === 'starting';
    if (failedStart && kind === 'busy') {
      if (replacements.has(id)) heldSlots.add(id);
      halt(id, 'queued');
      enqueue(id, 'resume');
      busy.add(id);
      park(id);
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
    replacements.delete(id);
    heldSlots.delete(id);
    cancelRetry(id);
    resetBusy(id);
    const current = state(id);
    if (current === 'queued') { removeFromQueue(id); set(id, 'stopped'); }
    else if (current === 'starting' || current === 'live') halt(id, 'stopped');
    else if (current === 'failed' || current === 'nosignal') set(id, 'stopped');
  }
  /**
   * A queued focused tile may take the slot of the least-recently-started
   * non-focused live tile, which goes back to the tail of the queue.
   */
  function preemptForFocus() {
    if (focused === null || state(focused) !== 'queued' || parks.has(focused) || heldSlots.has(focused)
      || activeCount() + heldSlots.size < capacity) return;
    let victim: string | null = null;
    for (const [id, value] of states) {
      if (value !== 'live' || id === focused) continue;
      if (victim === null || (startOrder.get(id) ?? 0) < (startOrder.get(victim) ?? 0)) victim = id;
    }
    if (victim === null) return;
    halt(victim, 'queued');
    // Protect the focused owner's slot even if another replacement has priority.
    heldSlots.add(focused);
    tickets.set(victim, ++ticketSequence);
    queue.push(victim);
    dirty = true;
  }
  function pump() {
    // While cooling down nothing starts, and no live tile is preempted for a start that must wait.
    if (cooldown) return;
    for (const value of states.values()) if (value === 'starting') return;
    preemptForFocus();
    const occupied = activeCount() + heldSlots.size;
    const next = queue.find(id => !parks.has(id) && (heldSlots.has(id) || occupied < capacity));
    if (next !== undefined) start(next);
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
          resetBusy(id);
          retrySpent.delete(id);
          replacements.delete(id);
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
    focus(id, restart = []) {
      transact(() => {
        const owned = restart.filter(tile => state(tile) === 'starting' || state(tile) === 'live' || heldSlots.has(tile));
        for (const tile of restart) stopOne(tile);
        if (focused !== id) { focused = id; dirty = true; }
        for (const tile of restart) {
          retrySpent.delete(tile);
          replacements.add(tile);
          if (owned.includes(tile)) heldSlots.add(tile);
          enqueue(tile, 'resume');
          // Stream replacements retain their slot ahead of ordinary waiters,
          // including returning to sub when focus closes on a full wall.
          removeFromQueue(tile);
          queue.unshift(tile);
        }
        if (id !== null && state(id) === 'queued' && queue[0] !== id) { removeFromQueue(id); queue.unshift(id); dirty = true; }
      });
    },
    reportLive(id) {
      transact(() => {
        if (state(id) !== 'starting') return;
        clearDeadline(id);
        startupPhases.delete(id);
        retrySpent.delete(id);
        replacements.delete(id);
        heldSlots.delete(id);
        resetBusy(id);
        failedStarts = 0;
        set(id, 'live');
      });
    },
    reportStartupPhase(id, phase) {
      transact(() => {
        if (state(id) !== 'starting') return;
        const [next, ms] = phase === 'requesting' ? [1, LIVE_WALL_REQUEST_TIMEOUT_MS]
          : phase === 'negotiating' ? [2, LIVE_WALL_NEGOTIATION_TIMEOUT_MS]
          : [3, LIVE_WALL_PRESENTATION_TIMEOUT_MS];
        // Repeated and regressive events cannot keep a hung start alive.
        if (next <= (startupPhases.get(id) ?? 0)) return;
        armDeadline(id, startOrder.get(id)!, next, ms);
      });
    },
    reportFailed(id, kind = 'failed') {
      transact(() => {
        const current = state(id);
        if (current === 'queued' && kind === 'handoff') {removeFromQueue(id); fail(id, kind); return;}
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
