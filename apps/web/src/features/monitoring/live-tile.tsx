'use client';
import {useEffect, useRef, type Ref} from 'react';
import type {LiveTileState} from '../../lib/tvt/live-wall-scheduler';

export type VideoFit = 'fill' | 'contain';
export type LiveTileModel = {id: string; label: string; ordinal: number};

/**
 * Accent focus outline for the dark wall. The app's global focus ring is an
 * unlayered rule, so overriding it from Tailwind's utility layer needs `!`.
 */
export const focusRing = 'focus-visible:outline-[var(--lw-accent)]!';
/** Inset variant for controls inside clipped (overflow-hidden) tiles. */
const insetFocusRing = `${focusRing} focus-visible:outline-offset-[-3px]!`;
const iconButton = `grid h-11 w-11 shrink-0 place-items-center rounded-md text-base text-[var(--lw-text)] hover:bg-white/10 ${insetFocusRing}`;

export const channelBadge = (ordinal: number) => `CH ${String(ordinal).padStart(2, '0')}`;

/**
 * Shows a player's MediaStream and reports its first presented frame, as
 * LocalLivePanel does: the server marks a lease PLAYING only after the browser
 * reports a frame that was actually presented. `onFrame` is read when the frame
 * arrives, so the caller can check that the reporting player is still current.
 */
export function LiveVideo({stream, label, fit, onFrame, decorative = false, className = ''}: {
  stream: MediaStream | null;
  label: string;
  fit: VideoFit;
  onFrame?: (presentedFrames: number) => void;
  decorative?: boolean;
  className?: string;
}) {
  const video = useRef<HTMLVideoElement | null>(null);
  const report = useRef(onFrame);
  useEffect(() => { report.current = onFrame; });
  useEffect(() => {
    const element = video.current;
    if (!element || !stream) return;
    element.srcObject = stream;
    let frame: number | null = null;
    // Browsers without frame callbacks cannot confirm a presented frame; the scheduler's start deadline then applies.
    if (typeof element.requestVideoFrameCallback === 'function') {
      frame = element.requestVideoFrameCallback((_now, metadata) => {
        frame = null;
        report.current?.(metadata.presentedFrames);
      });
    }
    void element.play().catch(() => undefined);
    return () => {
      if (frame !== null) element.cancelVideoFrameCallback(frame);
      element.srcObject = null;
    };
  }, [stream]);
  return <video
    ref={video}
    autoPlay
    muted
    playsInline
    controls={false}
    aria-label={decorative ? undefined : label}
    aria-hidden={decorative || undefined}
    className={`h-full w-full bg-black ${fit === 'fill' ? 'object-fill' : 'object-contain'} ${className}`}
  />;
}

/** Amber is reserved for live video and always carries the word LIVE. */
export function LivePill({className = ''}: {className?: string}) {
  return <span className={`inline-flex items-center gap-1 rounded-full bg-[var(--lw-live)] px-2 py-0.5 text-[11px] font-bold leading-4 tracking-wider text-[var(--lw-on-accent)] ${className}`}>
    <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-[var(--lw-on-accent)]"/>LIVE
  </span>;
}

/**
 * Placeholder for every non-live state; the error and its retry stay on the affected tile.
 * `busy` marks a queued tile whose last start the device refused (HTTP 429) for now.
 */
export function TileStatus({state, queuePosition, retrying, busy = false, label, onRetry, large = false}: {
  state: LiveTileState;
  queuePosition: number;
  retrying: boolean;
  busy?: boolean;
  label: string;
  onRetry(): void;
  large?: boolean;
}) {
  if (state === 'live') return null;
  const inset = large ? 'gap-2 px-6' : 'gap-1 px-3 pb-11';
  if (state === 'starting') return <div className={`absolute inset-0 flex flex-col items-center justify-center bg-black/55 ${inset}`}>
    <span className="flex items-center gap-2 rounded-md bg-[var(--lw-panel)] px-3 py-2 text-sm font-medium">
      <span aria-hidden="true" className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--lw-border-strong)] border-t-[var(--lw-accent)] motion-reduce:animate-none"/>
      연결 중
    </span>
  </div>;
  return <div className={`absolute inset-0 flex flex-col items-center justify-center bg-[var(--lw-panel)] text-center ${inset}`}>
    {state === 'queued' ? <>
      <span className="text-sm font-medium">{busy ? '재생 대기 (장치 사용 중)' : '재생 대기'}</span>
      <span className="text-xs text-[var(--lw-muted)]">대기 순서 {queuePosition}</span>
    </> : state === 'failed' ? <>
      <span className="flex items-center gap-1.5 text-sm font-semibold text-[var(--lw-danger)]"><span aria-hidden="true">!</span>연결 실패</span>
      {retrying && <span className="text-xs text-[var(--lw-muted)]">잠시 후 자동으로 다시 연결합니다.</span>}
      <button type="button" onClick={onRetry} aria-label={`${label} 다시 시도`} className={`mt-1 inline-flex min-h-11 items-center rounded-lg border border-[var(--lw-border-strong)] bg-[var(--lw-panel-raised)] px-4 text-sm font-semibold hover:border-[var(--lw-accent)] ${insetFocusRing}`}>다시 시도</button>
    </> : <span className="text-sm text-[var(--lw-muted)]">정지됨</span>}
  </div>;
}

/** One 16:9 wall tile: video, channel badge, LIVE pill, state placeholder and the bottom control bar. */
export function LiveTile({tile, state, queuePosition, retrying, busy = false, requested, stream, onFrame, onToggle, onRetry, onEnlarge, enlargeRef}: {
  tile: LiveTileModel;
  state: LiveTileState;
  queuePosition: number;
  retrying: boolean;
  busy?: boolean;
  requested: boolean;
  stream: MediaStream | null;
  onFrame(presentedFrames: number): void;
  onToggle(): void;
  onRetry(): void;
  onEnlarge(): void;
  enlargeRef?: Ref<HTMLButtonElement>;
}) {
  const live = state === 'live';
  const frame = state === 'queued' ? 'border-dashed border-[var(--lw-border-strong)]' : live ? 'border-[var(--lw-border-strong)]' : 'border-[var(--lw-border)]';
  return <div className={`relative aspect-video overflow-hidden rounded-lg border bg-black ${frame}`}>
    <LiveVideo stream={stream} label={tile.label} fit="fill" onFrame={onFrame} className="absolute inset-0"/>
    <TileStatus state={state} queuePosition={queuePosition} retrying={retrying} busy={busy} label={tile.label} onRetry={onRetry}/>
    <span className="absolute left-2 top-2 rounded bg-black/75 px-1.5 py-0.5 font-mono text-[11px] font-semibold tracking-wide text-[var(--lw-text)]">{channelBadge(tile.ordinal)}</span>
    {live && <LivePill className="absolute right-2 top-2"/>}
    <div className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-2 bg-linear-to-t from-black/90 via-black/75 to-transparent pl-3 pr-1 pt-2">
      <span className="truncate text-sm font-medium text-[var(--lw-text)]">{tile.ordinal}번 채널</span>
      <span className="flex shrink-0">
        <button type="button" onClick={onToggle} aria-label={`${tile.label} ${requested ? '중지' : '재생'}`} className={iconButton}>
          <span aria-hidden="true">{requested ? '■' : '▶︎'}</span>
        </button>
        <button type="button" ref={enlargeRef} onClick={onEnlarge} aria-label={`${tile.label} 크게 보기`} className={iconButton}>
          <span aria-hidden="true">⤢</span>
        </button>
      </span>
    </div>
  </div>;
}
