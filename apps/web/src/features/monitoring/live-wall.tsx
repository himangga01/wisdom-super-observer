'use client';
import {useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type Dispatch, type Ref, type SetStateAction} from 'react';
import type {ConnectionView} from '../../lib/connections';
import type {Store} from '../../lib/session';
import {LocalDeviceError, localDeviceMessage, readLocalDevice, type LocalDeviceView} from '../../lib/tvt/local-device-api';
import type {LocalLiveBinding} from '../../lib/tvt/local-live-api';
import {LocalLivePlayer, type LivePlayerState} from '../../lib/tvt/local-live-player';
import {createLiveWallScheduler, isRequested, LIVE_WALL_CONCURRENCY, tileState, type LiveStartFailure, type LiveWallScheduler, type LiveWallSnapshot, type LiveWallTimer} from '../../lib/tvt/live-wall-scheduler';
import {channelBadge, focusRing, LivePill, LiveTile, LiveVideo, TileStatus, type LiveTileModel, type VideoFit} from './live-tile';

/** The subset of LocalLivePlayer the wall drives; tests inject a fake through `createPlayer`. */
export type LiveWallPlayer = {
  start(): Promise<void>;
  stop(): Promise<void>;
  presented(decodedFrames: number): Promise<void>;
  readonly closed: boolean;
  /** HTTP status that failed the start/offer/playing request (429: device busy), or null. */
  readonly failureStatus: number | null;
};
export type LiveWallPlayerEvents = {state(value: LivePlayerState): void; stream(value: MediaStream | null): void};
export type LiveWallPlayerFactory = (binding: LocalLiveBinding, csrf: string, events: LiveWallPlayerEvents) => LiveWallPlayer;
/** External store for the header clock (`read` returns `YYYY-MM-DD HH:MM:SS`, or '' before the first tick). */
export type LiveWallClock = {subscribe(onTick: () => void): () => void; read(): string};
export type LiveWallProps = {
  tenantId: string;
  csrf: string;
  stores: Store[];
  connections: ConnectionView[];
  createPlayer?: LiveWallPlayerFactory;
  clock?: LiveWallClock;
  /** Scheduler timer for start deadlines, retries and cool-downs; injected in tests. */
  timer?: LiveWallTimer;
};

const createLocalPlayer: LiveWallPlayerFactory = (binding, csrf, events) => new LocalLivePlayer(binding, csrf, events);

const pad = (value: number) => String(value).padStart(2, '0');
export const formatClock = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
/** Local wall clock ticking on each second boundary while anything displays it. */
function createSystemClock(): LiveWallClock {
  const listeners = new Set<() => void>();
  let value = '';
  let timer: ReturnType<typeof setTimeout> | null = null;
  const schedule = () => {
    timer = setTimeout(() => {
      value = formatClock(new Date());
      for (const listener of [...listeners]) listener();
      schedule();
    }, 1000 - (Date.now() % 1000));
  };
  return {
    subscribe(listener) {
      listeners.add(listener);
      if (timer === null) { value = formatClock(new Date()); schedule(); }
      return () => {
        listeners.delete(listener);
        if (listeners.size > 0 || timer === null) return;
        clearTimeout(timer);
        timer = null;
        value = '';
      };
    },
    read: () => value,
  };
}
const systemClock = createSystemClock();
const readServerClock = () => '';

/** Control-room palette, exposed to the wall and its tiles as custom properties. */
const wallTheme = {
  '--lw-ground': '#0B0E12',
  '--lw-panel': '#0E1217',
  '--lw-panel-raised': '#12161C',
  '--lw-border': '#1E2630',
  '--lw-border-strong': '#2A313B',
  '--lw-text': '#E8ECF1',
  '--lw-muted': '#98A2AF',
  '--lw-accent': '#5AA7E0',
  '--lw-on-accent': '#0B0E12',
  '--lw-live': '#FFB547',
  // Failure text only (about 7.8:1 on the panels); the approved palette has no error colour.
  '--lw-danger': '#F28B82',
} as CSSProperties;

const layouts = [{value: 'auto', label: '자동'}, {value: '2', label: '2열'}, {value: '3', label: '3열'}, {value: '4', label: '4열'}] as const;
type Layout = (typeof layouts)[number]['value'];
/** `grid-cols-N` is `repeat(N, minmax(0, 1fr))`; phones always stack to one or two columns. */
const gridColumns: Record<Layout, string> = {
  auto: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4',
  '2': 'grid-cols-1 sm:grid-cols-2',
  '3': 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3',
  '4': 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-4',
};

const pill = 'inline-flex min-h-8 items-center rounded-full border border-[var(--lw-border)] bg-[var(--lw-panel-raised)] px-3 text-sm font-medium';
const primaryButton = `inline-flex min-h-11 items-center gap-2 rounded-lg bg-[var(--lw-accent)] px-4 text-sm font-semibold text-[var(--lw-on-accent)] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50 ${focusRing}`;
const secondaryButton = `inline-flex min-h-11 items-center gap-2 rounded-lg border border-[var(--lw-border-strong)] bg-[var(--lw-panel-raised)] px-4 text-sm font-semibold text-[var(--lw-text)] hover:border-[var(--lw-accent)] ${focusRing}`;
const segment = (pressed: boolean) => `min-h-11 min-w-11 rounded-md px-3 text-sm font-medium ${pressed ? 'bg-[var(--lw-accent)] text-[var(--lw-on-accent)]' : 'text-[var(--lw-muted)] hover:text-[var(--lw-text)]'} ${focusRing}`;
const chip = (pressed: boolean) => `inline-flex min-h-11 items-center rounded-full border px-4 text-sm font-medium ${pressed ? 'border-[var(--lw-accent)] bg-[var(--lw-accent)] text-[var(--lw-on-accent)]' : 'border-[var(--lw-border-strong)] bg-[var(--lw-panel)] text-[var(--lw-text)] hover:border-[var(--lw-accent)]'} ${focusRing}`;
const connectionsHref = (tenantId: string) => `/connections?tenant_id=${encodeURIComponent(tenantId)}`;

const INVENTORY_READ_CONCURRENCY = 4;
const INVENTORY_READ_TIMEOUT_MS = 25_000;

type Source = {key: string; store: Store; connection: ConnectionView};
type Load = {status: 'ready'; view: LocalDeviceView} | {status: 'error'; message: string};
type Tile = LiveTileModel & {storeId: string; binding: LocalLiveBinding};
type Section = {store: Store; aliases: string[]; tiles: Tile[]; loading: boolean; needsCheck: string[]; problems: string[]};
type Feed = {stream: MediaStream; player: LiveWallPlayer};

/** Each active store paired with every usable TVT recorder linked to it, in store order. */
function pairSources(tenantId: string, stores: Store[], connections: ConnectionView[]): Source[] {
  const recorders = connections.filter(item => item.kind === 'TVT_DEVICE' && item.status !== 'DISCONNECTED' && item.tenant_id === tenantId);
  return stores
    .filter(store => store.active && store.tenant_id === tenantId)
    .flatMap(store => recorders.filter(item => item.store_ids.includes(store.id)).map(connection => ({key: `${connection.id}/${store.id}`, store, connection})));
}

/** Reads the SAVED channel inventory (no device call), bounded like the connections page. */
async function readInventory(tenantId: string, source: Source, cancel: AbortSignal): Promise<Load> {
  const request = new AbortController();
  const abort = () => request.abort();
  cancel.addEventListener('abort', abort, {once: true});
  let timedOut = false;
  const deadline = setTimeout(() => { timedOut = true; request.abort(); }, INVENTORY_READ_TIMEOUT_MS);
  try {
    return {status: 'ready', view: await readLocalDevice(tenantId, source.connection, source.store.id, request.signal)};
  } catch (reason) {
    return {status: 'error', message: localDeviceMessage(timedOut ? 504 : reason instanceof LocalDeviceError ? reason.status : 503)};
  } finally {
    clearTimeout(deadline);
    cancel.removeEventListener('abort', abort);
  }
}

const playable = (view: LocalDeviceView) => view.inventory_state === 'AVAILABLE' && view.device_id !== null && view.channels.length > 0;

function buildSections(tenantId: string, sources: Source[], loads: Record<string, Load>): Section[] {
  const sections = new Map<string, Section>();
  const recorderCount = new Map<string, number>();
  for (const source of sources) {
    const load = loads[source.key];
    if (load?.status === 'ready' && playable(load.view)) recorderCount.set(source.store.id, (recorderCount.get(source.store.id) ?? 0) + 1);
  }
  for (const source of sources) {
    const {store, connection} = source;
    let section = sections.get(store.id);
    if (!section) {
      section = {store, aliases: [], tiles: [], loading: false, needsCheck: [], problems: []};
      sections.set(store.id, section);
    }
    section.aliases.push(connection.alias);
    const load = loads[source.key];
    if (!load) { section.loading = true; continue; }
    if (load.status === 'error') { section.problems.push(`${store.name} · ${connection.alias}: ${load.message}`); continue; }
    const view = load.view;
    if (!playable(view) || view.device_id === null) { section.needsCheck.push(connection.alias); continue; }
    // A store with two recorders repeats channel numbers, so their labels name the recorder too.
    const prefix = (recorderCount.get(store.id) ?? 0) > 1 ? `${store.name} ${connection.alias}` : store.name;
    for (const channel of [...view.channels].sort((a, b) => a.ordinal - b.ordinal)) {
      section.tiles.push({
        id: `${source.key}/${channel.id}`,
        storeId: store.id,
        label: `${prefix} ${channel.ordinal}번 채널`,
        ordinal: channel.ordinal,
        binding: {tenantId, connectionId: view.connection_id, storeId: view.store_id, deviceId: view.device_id, channelId: channel.id, generation: view.connection_generation, inventoryRevision: view.inventory_revision},
      });
    }
  }
  return [...sections.values()];
}

type RuntimeConfig = {tiles: ReadonlyMap<string, Tile>; csrf: string; createPlayer: LiveWallPlayerFactory};
type WallRuntime = {
  scheduler: LiveWallScheduler;
  configure(config: RuntimeConfig): void;
  presented(id: string, player: LiveWallPlayer, presentedFrames: number): void;
  dispose(): void;
};

/**
 * Owns one player per started tile and connects it to the scheduler. Player
 * events count only while that player is still the tile's current one, so a
 * late event from a stopped or timed-out attempt cannot change the wall.
 *
 * The backend counts a closing session until its native close is confirmed,
 * and a stop request settles only then. A new session therefore opens only
 * after every stop already in flight has settled; meanwhile the tile shows
 * 연결 중, and the scheduler's start deadline still bounds the wait.
 *
 * A start refused with HTTP 429 is reported as `busy` (the device is still
 * retiring a session), so the scheduler re-queues it instead of failing it.
 */
function createWallRuntime(setFeeds: Dispatch<SetStateAction<Record<string, Feed>>>, timer?: LiveWallTimer): WallRuntime {
  const players = new Map<string, LiveWallPlayer>();
  const stopping = new Set<Promise<void>>();
  let config: RuntimeConfig | null = null;
  const failure = (player: LiveWallPlayer): LiveStartFailure => player.failureStatus === 429 ? 'busy' : 'failed';
  const dropFeed = (id: string) => setFeeds(feeds => {
    if (!(id in feeds)) return feeds;
    const next = {...feeds};
    delete next[id];
    return next;
  });
  const scheduler: LiveWallScheduler = createLiveWallScheduler({
    timer,
    onStart(id) {
      const tile = config?.tiles.get(id);
      if (!config || !tile) throw new Error('Unknown live wall tile');
      const player = config.createPlayer(tile.binding, config.csrf, {
        state(value) {
          if (players.get(id) !== player) return;
          if (value === 'playing') scheduler.reportLive(id);
          else if (value === 'failed') scheduler.reportFailed(id, failure(player));
          // The wall forgets a player before stopping it, so 'stopped' from the current one means it
          // failed: LocalLivePlayer.fail() emits 'stopped' at once but 'failed' only after its stop
          // request settles. Report after this stop() call returns, so onStop gets its closing promise.
          else if (value === 'stopped') queueMicrotask(() => { if (players.get(id) === player) scheduler.reportFailed(id, failure(player)); });
        },
        stream(stream) {
          if (players.get(id) !== player) return;
          if (stream) setFeeds(feeds => ({...feeds, [id]: {stream, player}}));
          else dropFeed(id);
        },
      });
      players.set(id, player);
      const begin = () => {
        if (players.get(id) !== player) return;
        player.start().catch(() => { if (players.get(id) === player) scheduler.reportFailed(id, failure(player)); });
      };
      if (stopping.size === 0) begin();
      else void Promise.allSettled([...stopping]).then(begin);
    },
    onStop(id) {
      const player = players.get(id);
      players.delete(id);
      dropFeed(id);
      if (!player) return;
      const closing = player.stop().catch(() => undefined);
      stopping.add(closing);
      void closing.finally(() => { stopping.delete(closing); });
    },
  });
  return {
    scheduler,
    configure(next) { config = next; },
    presented(id, player, presentedFrames) {
      if (players.get(id) === player && !player.closed) player.presented(presentedFrames).catch(() => undefined);
    },
    dispose() { scheduler.stopAll(); },
  };
}

const idleSnapshot: LiveWallSnapshot = Object.freeze({states: Object.freeze({}), queue: Object.freeze([]), retrying: Object.freeze([]), busy: Object.freeze([]), coolingDown: false, focused: null, capacity: LIVE_WALL_CONCURRENCY});

function Clock({clock}: {clock: LiveWallClock}) {
  const value = useSyncExternalStore(clock.subscribe, clock.read, readServerClock);
  return <p className="min-h-5 font-mono text-sm tabular-nums text-[var(--lw-muted)]">
    <span className="sr-only">현재 시각 </span>
    <time dateTime={value ? value.replace(' ', 'T') : undefined}>{value}</time>
  </p>;
}

/**
 * "통합 관제": every channel of every store on one dark control-room wall.
 * Nothing plays until the user presses 전체 재생 or a tile's play button; the
 * scheduler then starts tiles one at a time within the backend capacity.
 */
export function LiveWall({tenantId, csrf, stores, connections, createPlayer = createLocalPlayer, clock = systemClock, timer}: LiveWallProps) {
  const [loads, setLoads] = useState<Record<string, Load>>({});
  const [snapshot, setSnapshot] = useState<LiveWallSnapshot>(idleSnapshot);
  const [feeds, setFeeds] = useState<Record<string, Feed>>({});
  const [layout, setLayout] = useState<Layout>('auto');
  const [storeFilter, setStoreFilter] = useState<string | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [fit, setFit] = useState<VideoFit>('fill');
  const runtime = useRef<WallRuntime | null>(null);
  const enlargeButtons = useRef(new Map<string, HTMLButtonElement>());
  const backButton = useRef<HTMLButtonElement | null>(null);
  const restoreFocus = useRef<string | null>(null);

  const sources = pairSources(tenantId, stores, connections);
  const sections = buildSections(tenantId, sources, loads);
  const tiles = sections.flatMap(section => section.tiles);
  const tileIndex = new Map(tiles.map(tile => [tile.id, tile]));
  const loading = sources.some(source => !loads[source.key]);
  const visibleSections = storeFilter === null ? sections : sections.filter(section => section.store.id === storeFilter);
  const visibleTiles = visibleSections.flatMap(section => section.tiles);
  const focusedTile = focusedId === null ? undefined : tileIndex.get(focusedId);
  const focusOpen = focusedTile !== undefined;
  const liveCount = tiles.filter(tile => tileState(snapshot, tile.id) === 'live').length;
  const queuedCount = tiles.filter(tile => tileState(snapshot, tile.id) === 'queued').length;
  const anyRequested = tiles.some(tile => isRequested(snapshot, tile.id));

  // Layout effects: the runtime and its tile map are updated in the same commit
  // that renders new tile buttons, so no click can reach the scheduler with a stale map.
  useLayoutEffect(() => {
    const created = createWallRuntime(setFeeds, timer);
    runtime.current = created;
    const unsubscribe = created.scheduler.subscribe(setSnapshot);
    return () => {
      unsubscribe();
      created.dispose();
      if (runtime.current === created) runtime.current = null;
    };
  }, [timer]);
  useLayoutEffect(() => { runtime.current?.configure({tiles: tileIndex, csrf, createPlayer}); });
  useEffect(() => {
    const controller = new AbortController();
    const pending = pairSources(tenantId, stores, connections);
    let next = 0;
    const work = async () => {
      while (next < pending.length && !controller.signal.aborted) {
        const source = pending[next++];
        const load = await readInventory(tenantId, source, controller.signal);
        if (!controller.signal.aborted) setLoads(current => ({...current, [source.key]: load}));
      }
    };
    for (let worker = 0; worker < Math.min(INVENTORY_READ_CONCURRENCY, pending.length); worker++) void work();
    return () => controller.abort();
  }, [tenantId, stores, connections]);
  useEffect(() => {
    if (focusOpen) { backButton.current?.focus(); return; }
    const id = restoreFocus.current;
    restoreFocus.current = null;
    if (id !== null) enlargeButtons.current.get(id)?.focus();
  }, [focusOpen]);

  const scheduler = () => runtime.current?.scheduler;
  const requested = (id: string) => {
    const current = scheduler()?.getSnapshot();
    return current ? isRequested(current, id) : false;
  };
  const playAll = () => scheduler()?.requestPlay(visibleTiles.map(tile => tile.id));
  const stopAll = () => scheduler()?.stopAll();
  const toggle = (tile: Tile) => { if (requested(tile.id)) scheduler()?.requestStop(tile.id); else scheduler()?.requestPlay([tile.id]); };
  const retry = (tile: Tile) => scheduler()?.requestPlay([tile.id]);
  function selectStore(storeId: string | null) {
    setStoreFilter(storeId);
    if (storeId === null) return;
    // Tiles hidden by the filter would hold the scarce live slots out of sight.
    const hidden = tiles.filter(tile => tile.storeId !== storeId && requested(tile.id)).map(tile => tile.id);
    if (hidden.length > 0) scheduler()?.requestStop(hidden);
  }
  function openFocus(tile: Tile) {
    setFocusedId(tile.id);
    scheduler()?.focus(tile.id);
  }
  function closeFocus() {
    restoreFocus.current = focusedId;
    setFocusedId(null);
    scheduler()?.focus(null);
  }
  const reportFrame = (id: string) => (presentedFrames: number) => {
    const feed = feeds[id];
    if (feed) runtime.current?.presented(id, feed.player, presentedFrames);
  };
  const registerEnlarge = (id: string) => (element: HTMLButtonElement | null) => {
    if (!element) return;
    enlargeButtons.current.set(id, element);
    return () => { enlargeButtons.current.delete(id); };
  };
  const view = {snapshot, feeds, onToggle: toggle, onRetry: retry, reportFrame};

  return <div style={wallTheme} className="min-w-0 space-y-5 rounded-2xl border border-[var(--lw-border)] bg-[var(--lw-ground)] p-4 text-[var(--lw-text)] sm:p-5">
    <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">통합 관제</h1>
        <p className="mt-1 text-sm text-[var(--lw-muted)]">모든 매장의 모든 채널을 한 화면에서 실시간으로 확인합니다.</p>
      </div>
      <Clock clock={clock}/>
    </header>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p role="status" aria-label="재생 현황" className="flex flex-wrap gap-2">
        <span className={pill}>{`실시간 ${liveCount}`}</span>
        <span className={pill}>{`재생 대기 ${queuedCount}`}</span>
        <span className={pill}>{`전체 채널 ${tiles.length}`}</span>
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="화면 배치" className="inline-flex rounded-lg border border-[var(--lw-border-strong)] bg-[var(--lw-panel)] p-0.5">
          {layouts.map(option => <button key={option.value} type="button" aria-pressed={layout === option.value} onClick={() => setLayout(option.value)} className={segment(layout === option.value)}>{option.label}</button>)}
        </div>
        <button type="button" onClick={anyRequested ? stopAll : playAll} disabled={!anyRequested && visibleTiles.length === 0} className={primaryButton}>
          <span aria-hidden="true">{anyRequested ? '■' : '▶︎'}</span>{anyRequested ? '전체 정지' : '전체 재생'}
        </button>
      </div>
    </div>
    {sources.length === 0 || (!loading && tiles.length === 0)
      ? <EmptyCard tenantId={tenantId} problems={sections.flatMap(section => section.problems)}/>
      : focusedTile
        ? <FocusView {...view} tile={focusedTile} sections={visibleSections} fit={fit} onFit={setFit} onBack={closeFocus} onSelect={openFocus} backRef={backButton}/>
        : <>
          <div role="group" aria-label="매장 선택" className="flex flex-wrap gap-2">
            <button type="button" aria-pressed={storeFilter === null} onClick={() => selectStore(null)} className={chip(storeFilter === null)}>{`전체 매장 · ${tiles.length}`}</button>
            {sections.map(section => <button key={section.store.id} type="button" aria-pressed={storeFilter === section.store.id} onClick={() => selectStore(section.store.id)} className={chip(storeFilter === section.store.id)}>{`${section.store.name} · ${section.tiles.length}`}</button>)}
          </div>
          <div className="space-y-4">
            {visibleSections.map(section => <StoreSection key={section.store.id} {...view} section={section} layout={layout} tenantId={tenantId} filtered={storeFilter === section.store.id} onFilter={selectStore} onEnlarge={openFocus} registerEnlarge={registerEnlarge}/>)}
          </div>
        </>}
  </div>;
}

type TileView = {
  snapshot: LiveWallSnapshot;
  feeds: Record<string, Feed>;
  onToggle(tile: Tile): void;
  onRetry(tile: Tile): void;
  reportFrame(id: string): (presentedFrames: number) => void;
};

function StoreSection({section, layout, tenantId, filtered, onFilter, onEnlarge, registerEnlarge, snapshot, feeds, onToggle, onRetry, reportFrame}: TileView & {
  section: Section;
  layout: Layout;
  tenantId: string;
  filtered: boolean;
  onFilter(storeId: string | null): void;
  onEnlarge(tile: Tile): void;
  registerEnlarge(id: string): Ref<HTMLButtonElement>;
}) {
  const headingId = useId();
  const live = section.tiles.filter(tile => tileState(snapshot, tile.id) === 'live').length;
  return <section aria-labelledby={headingId} className="rounded-xl border border-[var(--lw-border)] bg-[var(--lw-panel)] p-4">
    <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 id={headingId} className="text-base font-semibold">{section.store.name}</h2>
        <p className="mt-1 break-words text-sm text-[var(--lw-muted)]">{section.aliases.join(' · ')}</p>
        <p className="mt-1 text-sm text-[var(--lw-muted)]">{section.tiles.length}채널 · 실시간 {live}</p>
      </div>
      <button type="button" onClick={() => onFilter(filtered ? null : section.store.id)} className={secondaryButton}>{filtered ? '전체 매장 보기' : '이 매장만 보기'}</button>
    </div>
    {section.loading && <p className="mb-3 text-sm text-[var(--lw-muted)]">채널 정보를 불러오고 있습니다…</p>}
    {section.problems.map((problem, index) => <p key={index} className="mb-2 text-sm text-[var(--lw-danger)]">{problem}</p>)}
    {section.needsCheck.length > 0 && <p className="mb-2 text-sm text-[var(--lw-muted)]">{`${section.needsCheck.join(' · ')}: 확인된 채널 정보가 없거나 오래되었습니다. 연결 관리에서 ‘기기 확인’을 실행하세요.`}</p>}
    {(section.problems.length > 0 || section.needsCheck.length > 0) && <a href={connectionsHref(tenantId)} className={`${secondaryButton} mb-3`}>연결 관리에서 확인</a>}
    {section.tiles.length > 0 && <ul role="list" aria-label={`${section.store.name} 채널`} data-columns={layout} className={`grid gap-3 ${gridColumns[layout]}`}>
      {section.tiles.map(tile => <li key={tile.id} className="min-w-0">
        <LiveTile
          tile={tile}
          state={tileState(snapshot, tile.id)}
          queuePosition={snapshot.queue.indexOf(tile.id) + 1}
          retrying={snapshot.retrying.includes(tile.id)}
          busy={snapshot.busy.includes(tile.id)}
          requested={isRequested(snapshot, tile.id)}
          stream={feeds[tile.id]?.stream ?? null}
          onFrame={reportFrame(tile.id)}
          onToggle={() => onToggle(tile)}
          onRetry={() => onRetry(tile)}
          onEnlarge={() => onEnlarge(tile)}
          enlargeRef={registerEnlarge(tile.id)}
        />
      </li>)}
    </ul>}
  </section>;
}

const stripStatus = (snapshot: LiveWallSnapshot, id: string) => ({
  idle: '정지됨', stopped: '정지됨', starting: '연결 중', live: '', failed: '연결 실패', queued: `대기 ${snapshot.queue.indexOf(id) + 1}`,
})[tileState(snapshot, id)];

function FocusView({tile, sections, fit, onFit, onBack, onSelect, backRef, snapshot, feeds, onToggle, onRetry, reportFrame}: TileView & {
  tile: Tile;
  sections: Section[];
  fit: VideoFit;
  onFit(fit: VideoFit): void;
  onBack(): void;
  onSelect(tile: Tile): void;
  backRef: Ref<HTMLButtonElement>;
}) {
  const headingId = useId();
  const state = tileState(snapshot, tile.id);
  const playing = isRequested(snapshot, tile.id);
  return <section aria-labelledby={headingId} className="space-y-4" onKeyDown={event => { if (event.key === 'Escape') onBack(); }}>
    <div className="flex flex-wrap items-center gap-3">
      <button ref={backRef} type="button" onClick={onBack} className={secondaryButton}><span aria-hidden="true">←</span>통합 관제</button>
      <h2 id={headingId} className="min-w-0 break-words text-lg font-semibold">{tile.label}</h2>
      {state === 'live' && <LivePill/>}
      <div className="flex flex-wrap items-center gap-2 sm:ml-auto">
        <button type="button" onClick={() => onToggle(tile)} aria-label={`${tile.label} ${playing ? '중지' : '재생'}`} className={primaryButton}>
          <span aria-hidden="true">{playing ? '■' : '▶︎'}</span>{playing ? '중지' : '재생'}
        </button>
        <div role="group" aria-label="화면 맞춤" className="inline-flex rounded-lg border border-[var(--lw-border-strong)] bg-[var(--lw-panel)] p-0.5">
          <button type="button" aria-pressed={fit === 'fill'} onClick={() => onFit('fill')} className={segment(fit === 'fill')}>화면 채우기</button>
          <button type="button" aria-pressed={fit === 'contain'} onClick={() => onFit('contain')} className={segment(fit === 'contain')}>원본 비율</button>
        </div>
      </div>
    </div>
    <div className="relative aspect-video overflow-hidden rounded-xl border border-[var(--lw-border-strong)] bg-black">
      <LiveVideo stream={feeds[tile.id]?.stream ?? null} label={tile.label} fit={fit} onFrame={reportFrame(tile.id)} className="absolute inset-0"/>
      <TileStatus state={state} queuePosition={snapshot.queue.indexOf(tile.id) + 1} retrying={snapshot.retrying.includes(tile.id)} busy={snapshot.busy.includes(tile.id)} label={tile.label} onRetry={() => onRetry(tile)} large/>
      <span className="absolute left-3 top-3 rounded bg-black/75 px-2 py-0.5 font-mono text-xs font-semibold tracking-wide">{channelBadge(tile.ordinal)}</span>
    </div>
    <nav aria-label="채널 목록" className="space-y-3">
      {sections.filter(section => section.tiles.length > 0).map(section => <div key={section.store.id}>
        <h3 className="mb-2 text-sm font-semibold text-[var(--lw-muted)]">{section.store.name}</h3>
        <ul role="list" className="flex gap-2 overflow-x-auto pb-1">
          {section.tiles.map(item => {
            const current = item.id === tile.id;
            const feed = feeds[item.id];
            return <li key={item.id} className="shrink-0">
              <button type="button" aria-label={`${item.label} 크게 보기`} aria-current={current ? 'true' : undefined} onClick={() => onSelect(item)} className={`flex w-36 flex-col gap-1 rounded-lg border p-1.5 text-left ${current ? 'border-[var(--lw-accent)] bg-[var(--lw-panel-raised)]' : 'border-[var(--lw-border)] bg-[var(--lw-panel)] hover:border-[var(--lw-border-strong)]'} ${focusRing}`}>
                <span className="relative block aspect-video overflow-hidden rounded bg-black">
                  {feed && <LiveVideo stream={feed.stream} label={item.label} fit="fill" decorative onFrame={reportFrame(item.id)} className="absolute inset-0"/>}
                  <span className="absolute left-1 top-1 rounded bg-black/75 px-1 font-mono text-[10px] font-semibold">{channelBadge(item.ordinal)}</span>
                  {tileState(snapshot, item.id) === 'live' && <LivePill className="absolute bottom-1 right-1"/>}
                </span>
                <span className="flex items-center justify-between gap-1 px-0.5 text-xs">
                  <span className="truncate font-medium">{item.ordinal}번 채널</span>
                  <span className="shrink-0 text-[var(--lw-muted)]">{stripStatus(snapshot, item.id)}</span>
                </span>
              </button>
            </li>;
          })}
        </ul>
      </div>)}
    </nav>
  </section>;
}

function EmptyCard({tenantId, problems}: {tenantId: string; problems: string[]}) {
  const headingId = useId();
  return <section aria-labelledby={headingId} className="rounded-xl border border-[var(--lw-border)] bg-[var(--lw-panel)] p-6 text-center sm:p-10">
    <div aria-hidden="true" className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-xl bg-[var(--lw-panel-raised)] text-xl text-[var(--lw-accent)]">◉</div>
    <h2 id={headingId} className="text-lg font-semibold">재생할 CCTV 채널이 없습니다</h2>
    <p className="mx-auto mt-3 max-w-xl leading-6 text-[var(--lw-muted)]">연결 관리에서 TVT 기기를 매장에 연결하고 ‘기기 확인’을 실행하면 저장된 채널이 이곳에 표시됩니다.</p>
    {problems.length > 0 && <ul className="mx-auto mt-4 max-w-xl space-y-1 text-left text-sm text-[var(--lw-danger)]">{problems.map((problem, index) => <li key={index}>{problem}</li>)}</ul>}
    <a href={connectionsHref(tenantId)} className={`${primaryButton} mt-5`}>연결 관리로 이동</a>
  </section>;
}
