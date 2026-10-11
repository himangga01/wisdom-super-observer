import type {LocalLiveBinding} from './local-live-api';
import {createLocalWall, heartbeatLocalWall, stopLocalWall, reserveLocalFocus, settleLocalFocus, type LocalFocusResponse} from './local-live-wall-api';
import type {LiveWallTimer} from './live-wall-scheduler';

export const LIVE_WALL_HEARTBEAT_MS = 10_000;
export const LIVE_WALL_FOCUS_MS = 20_000;
const systemTimer: LiveWallTimer = {set: (callback, ms) => setTimeout(callback, ms), clear: handle => clearTimeout(handle as ReturnType<typeof setTimeout>)};
export type LiveWallGroupApi = {
  create: typeof createLocalWall;
  heartbeat: typeof heartbeatLocalWall;
  stop: typeof stopLocalWall;
  reserve: typeof reserveLocalFocus;
  settle: typeof settleLocalFocus;
};
const defaultApi = (): LiveWallGroupApi => ({create: createLocalWall, heartbeat: heartbeatLocalWall, stop: stopLocalWall, reserve: reserveLocalFocus, settle: settleLocalFocus});
type Reference = {value: LocalFocusResponse; pending: boolean; timer: unknown; closing?: Promise<void>};
export type LiveWallGroupEvent = {kind: 'failed'} | {kind: 'expired'; referenceId: string};
const cancelled = () => new Error('Live wall intent ended');

/** Owns public wall/reference metadata only. Terminal metadata is not a native cleanup receipt. */
export class LiveWallGroupController {
  private readonly timer: LiveWallTimer;
  private readonly api: LiveWallGroupApi;
  private wallId: string | null = null;
  private generation = 0;
  private disposed = false;
  private fenced = false;
  private lifecycle = new AbortController();
  private creating: Promise<string> | null = null;
  private readonly waiters = new Set<AbortSignal>();
  private closing: Promise<void> | null = null;
  private beatTimer: unknown;
  private beating: Promise<void> | null = null;
  private readonly refs = new Map<string, Reference>();
  private readonly operations = new Set<Promise<unknown>>();
  private readonly originalStops = new Map<string, Promise<void>>();
  private readonly reserving = new Set<string>();
  private readonly listeners = new Set<(event: LiveWallGroupEvent) => void>();

  constructor(private readonly options: {tenantId: string; csrf: string; timer?: LiveWallTimer; api?: LiveWallGroupApi}) {
    this.timer = options.timer ?? systemTimer;
    this.api = options.api ?? defaultApi();
  }
  get isFenced() {return this.fenced || this.disposed;}
  subscribe(listener: (event: LiveWallGroupEvent) => void) {this.listeners.add(listener); return () => {this.listeners.delete(listener);};}
  private emit(event: LiveWallGroupEvent) {for (const listener of [...this.listeners]) listener(event);}
  private track<T>(original: Promise<T>): Promise<T> {
    this.operations.add(original);
    void original.then(() => this.operations.delete(original), () => this.operations.delete(original));
    return original;
  }
  private armBeat() {
    this.timer.clear(this.beatTimer);
    if (this.disposed || this.fenced || !this.wallId) return;
    this.beatTimer = this.timer.set(() => {this.armBeat(); void this.heartbeat().catch(() => undefined);}, LIVE_WALL_HEARTBEAT_MS);
  }
  async ensure(signal: AbortSignal): Promise<string> {
    if (signal.aborted || this.disposed || this.fenced || this.closing) throw cancelled();
    if (this.wallId) return this.wallId;
    this.waiters.add(signal);
    if (!this.creating) {
      const generation = this.generation;
      const original = this.api.create(this.options.tenantId, this.options.csrf, this.lifecycle.signal).then(async value => {
        const id = value.wall.id;
        if (generation !== this.generation || this.disposed || this.fenced || ![...this.waiters].some(waiter => !waiter.aborted)) {
          await this.retireWall(id);
          throw cancelled();
        }
        if (value.wall.state !== 'ACTIVE') throw cancelled();
        this.wallId = id;
        this.armBeat();
        return id;
      });
      this.creating = this.track(original);
      void original.then(() => {if (this.creating === original) this.creating = null;}, () => {if (this.creating === original) this.creating = null;});
    }
    try {const id = await this.creating; if (signal.aborted || this.fenced || this.disposed) throw cancelled(); return id;}
    finally {this.waiters.delete(signal);}
  }
  heartbeat(): Promise<void> {
    if (this.beating) return this.beating;
    const id = this.wallId;
    if (!id || this.disposed || this.fenced) return Promise.resolve();
    const generation = this.generation;
    const original = this.api.heartbeat(this.options.tenantId, id, this.options.csrf, this.lifecycle.signal).then(value => {
      if (generation !== this.generation) return;
      if (value.wall.id !== id || value.wall.state !== 'ACTIVE') throw cancelled();
    }).catch(error => {
      if (generation === this.generation && !this.disposed && !this.fenced) {
        this.emit({kind: 'failed'});
        void this.stopAll().catch(() => undefined);
      }
      throw error;
    }).finally(() => {if (this.beating === original) this.beating = null;});
    this.beating = this.track(original);
    return original;
  }
  beginFocus(binding: LocalLiveBinding, player: {readonly currentLeaseId: string | null; readonly closed: boolean}, direction: 'FORWARD' | 'RETURN', signal: AbortSignal): Promise<LocalFocusResponse> {
    const lease = player.currentLeaseId;
    const wall = this.wallId;
    const target = `${binding.connectionId}/${binding.channelId}`;
    if (!lease || player.closed || signal.aborted || !wall || binding.tenantId !== this.options.tenantId || binding.wallId !== wall || this.fenced || this.disposed || this.reserving.size > 0
      || [...this.refs.values()].some(record => record.pending || record.closing)) return Promise.reject(cancelled());
    this.reserving.add(target);
    const generation = this.generation;
    const deadline = Date.now() + LIVE_WALL_FOCUS_MS;
    const request = new AbortController();
    let expired = false;
    const requestTimer = this.timer.set(() => {expired = true; request.abort();}, LIVE_WALL_FOCUS_MS);
    const abort = AbortSignal.any([signal, this.lifecycle.signal, request.signal]);
    const original = this.api.reserve(binding, lease, direction, this.options.csrf, abort).then(async value => {
      const ref = value.reference;
      if (ref.wall_id !== wall || ref.lease_id !== lease || ref.connection_id !== binding.connectionId || ref.channel_id !== binding.channelId || ref.direction !== direction) throw new Error('Focus source mismatch');
      const record: Reference = {value, pending: true, timer: undefined};
      this.refs.set(ref.id, record);
      const remaining = Math.min(deadline, Date.parse(ref.expires_at)) - Date.now();
      if (abort.aborted || generation !== this.generation || player.closed || player.currentLeaseId !== lease || expired || remaining <= 0 || ref.state !== 'PENDING') {
        await this.cancelFocus(ref.id, expired || remaining <= 0 ? 'FAILED' : 'CANCELLED');
        throw cancelled();
      }
      record.timer = this.timer.set(() => {
        if (!record.pending || this.refs.get(ref.id) !== record) return;
        record.pending = false;
        void this.cancelFocus(ref.id, 'FAILED').catch(() => undefined);
        this.emit({kind: 'expired', referenceId: ref.id});
      }, remaining);
      return value;
    }).finally(() => {this.timer.clear(requestTimer); this.reserving.delete(target);});
    return this.track(original);
  }
  isUsable(referenceId: string): boolean {
    const record = this.refs.get(referenceId);
    return !!record && record.pending && !record.closing && !this.disposed && !this.fenced && Date.parse(record.value.reference.expires_at) > Date.now();
  }
  /** Called only after this exact replacement player accepted its viewer lease. */
  attached(referenceId: string) {
    const record = this.refs.get(referenceId);
    if (!record || !this.isUsable(referenceId)) return;
    record.pending = false;
    this.timer.clear(record.timer);
    // This exact replacement lease already accepted its authoritative transfer.
    // Keep pending/expired/in-flight cleanup records; retire only this attached one.
    this.refs.delete(referenceId);
  }
  cancelFocus(referenceId: string, outcome: 'CANCELLED' | 'FAILED'): Promise<void> {
    const record = this.refs.get(referenceId);
    if (!record) return Promise.resolve();
    if (record.closing) return record.closing;
    record.pending = false;
    this.timer.clear(record.timer);
    const known = record.value.reference;
    const original = this.api.settle(this.options.tenantId, known.wall_id, known.id, outcome, this.options.csrf, new AbortController().signal).then(value => {
      const ref = value.reference;
      if (ref.id !== known.id || ref.wall_id !== known.wall_id || ref.lease_id !== known.lease_id || ref.connection_id !== known.connection_id || ref.channel_id !== known.channel_id || ref.direction !== known.direction || ref.state !== 'CLOSED') throw new Error('Focus settlement mismatch');
      if (this.refs.get(referenceId) === record) this.refs.delete(referenceId);
    });
    record.closing = this.track(original);
    return original;
  }
  private retireWall(id: string): Promise<void> {
    const retained = this.originalStops.get(id);
    if (retained) return retained;
    const original = this.api.stop(this.options.tenantId, id, this.options.csrf).then(value => {
      if (value.wall.id !== id || value.wall.state !== 'CLOSED') throw new Error('Original wall stop not terminal');
      this.originalStops.delete(id);
    });
    this.originalStops.set(id, original);
    return original;
  }
  stopAll(owners: Promise<void> = Promise.resolve()): Promise<void> {
    if (this.closing) return this.closing;
    this.fenced = true;
    this.generation++;
    this.lifecycle.abort();
    this.timer.clear(this.beatTimer);
    const id = this.wallId;
    const refs = [...this.refs.keys()].map(ref => this.cancelFocus(ref, 'CANCELLED'));
    const operations = [...this.operations];
    const original = (async () => {
      // Wait every original caller even after one fails; wall cleanup remains a
      // backstop, while that original failure still fences this group.
      const first = await Promise.allSettled([owners, ...refs]);
      await Promise.allSettled(operations);
      const late = await Promise.allSettled([...this.refs.values()].flatMap(record => record.closing ? [record.closing] : []).concat([...this.originalStops.values()]));
      const value = id ? await this.api.stop(this.options.tenantId, id, this.options.csrf) : null;
      if (value && (value.wall.id !== id || value.wall.tenant_id !== this.options.tenantId)) throw new Error('Wall stop mismatch');
      if (value && value.wall.state !== 'CLOSED') throw new Error('Wall stop not terminal');
      const failed = [...first, ...late].find((result): result is PromiseRejectedResult => result.status === 'rejected');
      if (failed) throw failed.reason;
      this.wallId = null;
      if (!this.disposed) {
        this.fenced = false;
        this.lifecycle = new AbortController();
        this.closing = null;
      }
    })();
    this.closing = original;
    return original;
  }
  dispose(): Promise<void> {
    this.disposed = true;
    this.listeners.clear();
    return this.stopAll();
  }
}
