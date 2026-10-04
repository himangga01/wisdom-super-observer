import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {
  createLiveWallScheduler,
  LIVE_WALL_CONCURRENCY,
  LIVE_WALL_COOLDOWN_BASE_MS,
  LIVE_WALL_COOLDOWN_MAX_MS,
  LIVE_WALL_RETRY_DELAY_MS,
  LIVE_WALL_START_TIMEOUT_MS,
  type LiveWallScheduler,
  type LiveWallSchedulerOptions,
  type LiveWallSnapshot,
  type LiveWallTimer,
} from '../src/lib/tvt/live-wall-scheduler';

// Start deadlines, retries and cool-downs run on fake timers so no real timer outlives a test.
beforeEach(()=>{vi.useFakeTimers();});
afterEach(()=>{vi.useRealTimers();});

/** Records callbacks and checks the scheduling invariants on every published snapshot. */
function harness(options:Partial<LiveWallSchedulerOptions>={}){
  const log:string[]=[];const violations:string[]=[];const running=new Set<string>();
  const scheduler=createLiveWallScheduler({
    onStart:id=>{log.push(`start ${id}`);running.add(id);},
    onStop:id=>{log.push(`stop ${id}`);running.delete(id);},
    ...options,
  });
  scheduler.subscribe(snapshot=>{
    const states=Object.values(snapshot.states);
    const active=states.filter(state=>state==='starting'||state==='live').length;
    const starting=states.filter(state=>state==='starting').length;
    if(active>snapshot.capacity)violations.push(`capacity exceeded: ${active}`);
    if(starting>1)violations.push(`parallel starts: ${starting}`);
    if(new Set(snapshot.queue).size!==snapshot.queue.length)violations.push('duplicate queue entry');
    for(const id of snapshot.queue)if(snapshot.states[id]!=='queued')violations.push(`queue holds ${id} as ${snapshot.states[id]}`);
    for(const id of snapshot.retrying)if(snapshot.states[id]!=='failed')violations.push(`retry pending for ${id} as ${snapshot.states[id]}`);
  });
  const state=(id:string)=>scheduler.getSnapshot().states[id]??'idle';
  return {scheduler,log,violations,running,state};
}
const starts=(log:string[])=>log.filter(entry=>entry.startsWith('start '));

describe('live wall scheduler',()=>{
  it('documents the current backend limit as the default capacity',()=>{
    expect(LIVE_WALL_CONCURRENCY).toBe(2);
    expect(LIVE_WALL_START_TIMEOUT_MS).toBe(15_000);
    expect(LIVE_WALL_RETRY_DELAY_MS).toBe(2_000);
    expect(LIVE_WALL_COOLDOWN_BASE_MS).toBe(3_000);
    expect(LIVE_WALL_COOLDOWN_MAX_MS).toBe(15_000);
    const {scheduler}=harness();
    expect(scheduler.getSnapshot().capacity).toBe(LIVE_WALL_CONCURRENCY);
  });

  it('rejects a capacity that is not a positive integer',()=>{
    for(const capacity of [0,-1,1.5,Number.NaN])expect(()=>createLiveWallScheduler({capacity,onStart(){},onStop(){}})).toThrow(RangeError);
  });

  it('starts strictly one tile at a time, only after the previous start settles',()=>{
    const {scheduler,log,state,violations}=harness({capacity:4});
    scheduler.requestPlay(['a','b','c']);
    expect(log).toEqual(['start a']);
    expect(state('b')).toBe('queued');
    expect(scheduler.getSnapshot().queue).toEqual(['b','c']);
    scheduler.reportLive('a');
    expect(log).toEqual(['start a','start b']);
    scheduler.reportFailed('b');
    // A failed start pauses new starts; b's 2 s retry re-queues it ahead of c before the 3 s cool-down ends.
    expect(log).toEqual(['start a','start b','stop b']);
    expect(state('b')).toBe('failed');
    vi.advanceTimersByTime(LIVE_WALL_COOLDOWN_BASE_MS);
    expect(log).toEqual(['start a','start b','stop b','start b']);
    scheduler.reportLive('b');
    expect(log.at(-1)).toBe('start c');
    expect(violations).toEqual([]);
  });

  it('never exceeds capacity and ignores live reports for tiles that are not starting',()=>{
    const {scheduler,log,state,violations}=harness();
    scheduler.requestPlay(['a','b','c','d']);
    scheduler.reportLive('a');scheduler.reportLive('b');
    expect(log).toEqual(['start a','start b']);
    expect(state('c')).toBe('queued');
    scheduler.reportLive('c');scheduler.reportLive('missing');
    expect(state('c')).toBe('queued');expect(state('missing')).toBe('idle');
    expect(log).toEqual(['start a','start b']);
    expect(violations).toEqual([]);
  });

  it('keeps capacity and sequential starts under a long mixed sequence of operations',()=>{
    for(const capacity of [1,2,3]){
      let seed=capacity*7919;const random=(limit:number)=>{seed=(seed*1103515245+12345)%2147483648;return seed%limit;};
      const ids=['a','b','c','d','e','f','g'];const unsettled=new Set<string>();const problems:string[]=[];
      const running=new Set<string>();let startCount=0;let peak=0;
      const scheduler:LiveWallScheduler=createLiveWallScheduler({capacity,
        onStart:id=>{if(running.size>=capacity)problems.push(`start ${id} with ${running.size} running`);if(unsettled.size>0)problems.push(`start ${id} while ${[...unsettled]} starting`);running.add(id);unsettled.add(id);startCount++;peak=Math.max(peak,running.size);},
        onStop:id=>{running.delete(id);unsettled.delete(id);},
      });
      scheduler.subscribe(snapshot=>{
        const states=Object.values(snapshot.states);
        if(states.filter(s=>s==='starting'||s==='live').length>capacity)problems.push('snapshot over capacity');
        if(states.filter(s=>s==='starting').length>1)problems.push('snapshot parallel starts');
      });
      // 1,200 steps: cool-downs after failed starts slow the walk, so it needs more time to stay non-vacuous.
      for(let step=0;step<1_200;step++){
        const id=ids[random(ids.length)];
        switch(random(9)){
          case 0:case 1:scheduler.requestPlay([id,ids[random(ids.length)]]);break;
          case 2:scheduler.requestStop(id);break;
          case 3:scheduler.focus(random(4)===0?null:id);break;
          case 4:case 5:{const pending=[...unsettled];if(pending.length){unsettled.delete(pending[0]);scheduler.reportLive(pending[0]);}break;}
          case 6:{const pending=[...unsettled];const kind=random(2)===0?'busy':'failed';if(pending.length)scheduler.reportFailed(pending[0],kind);else scheduler.reportFailed(id,kind);break;}
          case 7:vi.advanceTimersByTime(random(4)*1_000+random(2)*15_000);break;
          default:if(random(10)===0)scheduler.stopAll();
        }
      }
      expect(problems).toEqual([]);
      // Guard against a vacuous run: the sequence must keep starting tiles and fill every slot.
      expect(startCount).toBeGreaterThan(30);
      expect(peak).toBe(capacity);
    }
  });

  it('starts the next queued tile when a live tile stops or fails, without retrying or cooling down after a live failure',()=>{
    const {scheduler,log,state}=harness();
    scheduler.requestPlay(['a','b','c','d']);
    scheduler.reportLive('a');scheduler.reportLive('b');
    scheduler.requestStop('a');
    expect(state('a')).toBe('stopped');
    expect(log.slice(-2)).toEqual(['stop a','start c']);
    scheduler.reportLive('c');
    scheduler.reportFailed('b');
    expect(state('b')).toBe('failed');
    expect(log.slice(-2)).toEqual(['stop b','start d']);
    expect(scheduler.getSnapshot().retrying).toEqual([]);
    expect(scheduler.getSnapshot().coolingDown).toBe(false);
    vi.advanceTimersByTime(10_000);
    expect(starts(log)).toEqual(['start a','start b','start c','start d']);
  });

  it('stopAll clears queued, starting and live tiles and cancels pending retries and the cool-down',()=>{
    const {scheduler,log,state,running}=harness({capacity:3});
    scheduler.requestPlay(['a','b','c','d','e']);
    scheduler.reportLive('a');scheduler.reportLive('b');
    expect(state('c')).toBe('starting');
    scheduler.stopAll();
    expect(['a','b','c','d','e'].map(state)).toEqual(['stopped','stopped','stopped','stopped','stopped']);
    expect(scheduler.getSnapshot().queue).toEqual([]);
    expect(running.size).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
    scheduler.requestPlay(['a','b']);
    scheduler.reportFailed('a');
    expect(scheduler.getSnapshot().retrying).toEqual(['a']);
    expect(scheduler.getSnapshot().coolingDown).toBe(true);
    scheduler.stopAll();
    expect(scheduler.getSnapshot().retrying).toEqual([]);
    expect(scheduler.getSnapshot().coolingDown).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(60_000);
    expect(starts(log)).toEqual(['start a','start b','start c','start a']);
  });

  it('focus preempts the least-recently-started non-focused live tile and re-queues it at the tail',()=>{
    const {scheduler,log,state,violations}=harness();
    scheduler.requestPlay(['a','b','c','d']);
    scheduler.reportLive('a');scheduler.reportLive('b');
    scheduler.focus('d');
    expect(log.slice(-2)).toEqual(['stop a','start d']);
    expect(state('a')).toBe('queued');
    expect(scheduler.getSnapshot().queue).toEqual(['c','a']);
    expect(scheduler.getSnapshot().focused).toBe('d');
    scheduler.reportLive('d');
    scheduler.focus('a');
    expect(log.slice(-2)).toEqual(['stop b','start a']);
    expect(scheduler.getSnapshot().queue).toEqual(['c','b']);
    expect(violations).toEqual([]);
  });

  it('moves a focused queued tile to the head without preempting while capacity remains',()=>{
    const {scheduler,log}=harness({capacity:3});
    scheduler.requestPlay(['a','b','c','d']);
    scheduler.focus('d');
    expect(scheduler.getSnapshot().queue).toEqual(['d','b','c']);
    scheduler.reportLive('a');
    expect(log).toEqual(['start a','start d']);
  });

  it('defers focus preemption until a live tile exists and never preempts the focused tile',()=>{
    const {scheduler,log}=harness({capacity:1});
    scheduler.requestPlay(['a','b']);
    scheduler.focus('b');
    expect(log).toEqual(['start a']);
    scheduler.reportLive('a');
    expect(log).toEqual(['start a','stop a','start b']);
    scheduler.reportLive('b');
    scheduler.focus('b');
    expect(log).toEqual(['start a','stop a','start b']);
    expect(scheduler.getSnapshot().queue).toEqual(['a']);
  });

  it('does not start a focused tile that was never requested, but plays it first once requested',()=>{
    const {scheduler,log,state}=harness();
    scheduler.focus('x');
    expect(log).toEqual([]);expect(state('x')).toBe('idle');
    scheduler.requestPlay(['a','b','c']);
    scheduler.reportLive('a');scheduler.reportLive('b');
    scheduler.requestPlay(['x']);
    expect(log.slice(-2)).toEqual(['stop a','start x']);
    expect(scheduler.getSnapshot().queue).toEqual(['c','a']);
    scheduler.focus(null);
    expect(scheduler.getSnapshot().focused).toBeNull();
  });

  it('retries a failed start once after 2 s, then stays failed until the user retries',()=>{
    const {scheduler,log,state}=harness();
    scheduler.requestPlay(['a']);
    scheduler.reportFailed('a');
    expect(state('a')).toBe('failed');
    expect(scheduler.getSnapshot().retrying).toEqual(['a']);
    expect(log).toEqual(['start a','stop a']);
    vi.advanceTimersByTime(1_999);
    expect(state('a')).toBe('failed');
    vi.advanceTimersByTime(1);
    // The retry re-queues after 2 s and starts when the 3 s cool-down ends.
    expect(state('a')).toBe('queued');
    expect(scheduler.getSnapshot().retrying).toEqual([]);
    expect(starts(log)).toHaveLength(1);
    vi.advanceTimersByTime(1_000);
    expect(state('a')).toBe('starting');
    expect(starts(log)).toHaveLength(2);
    scheduler.reportFailed('a');
    expect(state('a')).toBe('failed');
    expect(scheduler.getSnapshot().retrying).toEqual([]);
    vi.advanceTimersByTime(60_000);
    expect(starts(log)).toHaveLength(2);
    scheduler.requestPlay(['a']);
    expect(starts(log)).toHaveLength(3);
    scheduler.reportFailed('a');
    vi.advanceTimersByTime(2_000);
    expect(state('a')).toBe('queued');
    vi.advanceTimersByTime(LIVE_WALL_COOLDOWN_MAX_MS);
    expect(starts(log)).toHaveLength(4);
  });

  it('counts a start that does not settle within 15 s as failed and ignores its late report',()=>{
    const {scheduler,log,state}=harness();
    scheduler.requestPlay(['a','b']);
    vi.advanceTimersByTime(14_999);
    expect(state('a')).toBe('starting');
    vi.advanceTimersByTime(1);
    expect(state('a')).toBe('failed');
    expect(log).toEqual(['start a','stop a']);
    expect(scheduler.getSnapshot().coolingDown).toBe(true);
    scheduler.reportLive('a');
    expect(state('a')).toBe('failed');
    vi.advanceTimersByTime(2_000);
    expect(state('a')).toBe('queued');
    expect(scheduler.getSnapshot().queue).toEqual(['a','b']);
    vi.advanceTimersByTime(1_000);
    expect(log.slice(-1)).toEqual(['start a']);
  });

  it('cancels a pending retry when the user stops the tile',()=>{
    const {scheduler,log,state}=harness();
    scheduler.requestPlay(['a']);scheduler.reportFailed('a');
    scheduler.requestStop('a');
    expect(state('a')).toBe('stopped');
    expect(scheduler.getSnapshot().retrying).toEqual([]);
    vi.advanceTimersByTime(10_000);
    expect(log).toEqual(['start a','stop a']);
  });

  it('cools down 3, 6, 12 and then 15 s after consecutive failed starts and resets once a tile is live',()=>{
    const {scheduler,log,violations}=harness();
    scheduler.requestPlay(['a','b']);
    let count=1;
    for(const delay of [3_000,6_000,12_000,15_000,15_000]){
      expect(starts(log)).toHaveLength(count);
      scheduler.reportFailed('a','busy');
      expect(scheduler.getSnapshot().coolingDown).toBe(true);
      vi.advanceTimersByTime(delay-1);
      expect(starts(log)).toHaveLength(count);
      vi.advanceTimersByTime(1);
      count++;
      expect(starts(log)).toHaveLength(count);
      expect(log.at(-1)).toBe('start a');
      expect(scheduler.getSnapshot().coolingDown).toBe(false);
    }
    scheduler.reportLive('a');
    expect(log.at(-1)).toBe('start b');
    scheduler.reportFailed('b','busy');
    vi.advanceTimersByTime(LIVE_WALL_COOLDOWN_BASE_MS-1);
    expect(log.at(-1)).toBe('stop b');
    vi.advanceTimersByTime(1);
    expect(log.at(-1)).toBe('start b');
    expect(violations).toEqual([]);
  });

  it('re-queues a busy (HTTP 429) start at its place without spending its single retry',()=>{
    const {scheduler,log,state}=harness();
    scheduler.requestPlay(['a','b','c']);
    scheduler.reportLive('a');
    scheduler.reportFailed('b','busy');
    expect(state('b')).toBe('queued');
    expect(scheduler.getSnapshot().queue).toEqual(['b','c']);
    expect(scheduler.getSnapshot().busy).toEqual(['b']);
    expect(scheduler.getSnapshot().retrying).toEqual([]);
    expect(log.slice(-1)).toEqual(['stop b']);
    vi.advanceTimersByTime(LIVE_WALL_COOLDOWN_BASE_MS);
    expect(log.slice(-1)).toEqual(['start b']);
    expect(scheduler.getSnapshot().busy).toEqual([]);
    scheduler.reportFailed('b');
    expect(state('b')).toBe('failed');
    expect(scheduler.getSnapshot().retrying).toEqual(['b']);
  });

  it('mixes busy refusals and real failures: busy tiles wait their turn, failed tiles retry once',()=>{
    const {scheduler,log,state,violations}=harness();
    scheduler.requestPlay(['a','b','c','d']);
    scheduler.reportFailed('a');
    expect(state('a')).toBe('failed');
    vi.advanceTimersByTime(LIVE_WALL_RETRY_DELAY_MS);
    expect(scheduler.getSnapshot().queue).toEqual(['a','b','c','d']);
    expect(starts(log)).toEqual(['start a']);
    vi.advanceTimersByTime(1_000);
    expect(starts(log)).toEqual(['start a','start a']);
    scheduler.reportFailed('a','busy');
    expect(state('a')).toBe('queued');
    vi.advanceTimersByTime(6_000);
    expect(starts(log)).toEqual(['start a','start a','start a']);
    scheduler.reportFailed('a');
    expect(state('a')).toBe('failed');
    expect(scheduler.getSnapshot().retrying).toEqual([]);
    vi.advanceTimersByTime(12_000);
    expect(log.at(-1)).toBe('start b');
    scheduler.reportLive('b');
    expect(log.at(-1)).toBe('start c');
    scheduler.reportFailed('c','busy');
    expect(scheduler.getSnapshot().queue).toEqual(['c','d']);
    vi.advanceTimersByTime(LIVE_WALL_COOLDOWN_BASE_MS);
    expect(log.at(-1)).toBe('start c');
    expect(state('a')).toBe('failed');
    expect(violations).toEqual([]);
  });

  it('re-queues retried and busy starts at their original queue position',()=>{
    const {scheduler,log,violations}=harness({capacity:3});
    scheduler.requestPlay(['a','b','c','d']);
    scheduler.reportFailed('a','busy');
    expect(scheduler.getSnapshot().queue).toEqual(['a','b','c','d']);
    vi.advanceTimersByTime(LIVE_WALL_COOLDOWN_BASE_MS);
    expect(log.at(-1)).toBe('start a');
    scheduler.reportLive('a');
    expect(log.at(-1)).toBe('start b');
    scheduler.reportFailed('b');
    vi.advanceTimersByTime(LIVE_WALL_RETRY_DELAY_MS);
    expect(scheduler.getSnapshot().queue).toEqual(['b','c','d']);
    expect(violations).toEqual([]);
  });

  it('keeps a queued focused tile first when tiles re-enter the queue',()=>{
    const {scheduler}=harness();
    scheduler.requestPlay(['a','b','c']);
    scheduler.focus('c');
    expect(scheduler.getSnapshot().queue).toEqual(['c','b']);
    scheduler.reportFailed('a','busy');
    expect(scheduler.getSnapshot().queue).toEqual(['c','a','b']);
  });

  it('uses the injected timer for start deadlines, retries and the cool-down',()=>{
    const pending:{callback:()=>void;ms:number;cleared:boolean}[]=[];
    const timer:LiveWallTimer={set:(callback,ms)=>{const handle={callback,ms,cleared:false};pending.push(handle);return handle;},clear:handle=>{(handle as typeof pending[number]).cleared=true;}};
    const {scheduler,log}=harness({timer});
    scheduler.requestPlay(['a']);
    expect(pending.map(entry=>entry.ms)).toEqual([LIVE_WALL_START_TIMEOUT_MS]);
    scheduler.reportFailed('a');
    expect(pending[0].cleared).toBe(true);
    expect(pending.slice(1).map(entry=>entry.ms)).toEqual([LIVE_WALL_RETRY_DELAY_MS,LIVE_WALL_COOLDOWN_BASE_MS]);
    pending[1].callback();
    expect(log).toEqual(['start a','stop a']);
    pending[2].callback();
    expect(log).toEqual(['start a','stop a','start a']);
  });

  it('ignores duplicate play requests',()=>{
    const {scheduler,log}=harness();
    scheduler.requestPlay(['a','a','b','b']);
    expect(log).toEqual(['start a']);
    expect(scheduler.getSnapshot().queue).toEqual(['b']);
    scheduler.requestPlay(['b','a']);
    expect(log).toEqual(['start a']);
    expect(scheduler.getSnapshot().queue).toEqual(['b']);
    scheduler.reportLive('a');
    scheduler.requestPlay(['a','b']);
    expect(log).toEqual(['start a','start b']);
  });

  it('stays sequential when a player reports synchronously from the start callback',()=>{
    const log:string[]=[];const peaks:number[]=[];
    const scheduler:LiveWallScheduler=createLiveWallScheduler({onStart:id=>{log.push(`start ${id}`);scheduler.reportLive(id);},onStop:id=>log.push(`stop ${id}`)});
    scheduler.subscribe(snapshot=>peaks.push(Object.values(snapshot.states).filter(s=>s==='starting'||s==='live').length));
    scheduler.requestPlay(['a','b','c']);
    expect(log).toEqual(['start a','start b']);
    expect(scheduler.getSnapshot().states).toEqual({a:'live',b:'live',c:'queued'});
    expect(Math.max(...peaks)).toBeLessThanOrEqual(2);
  });

  it('treats a throwing start callback as a failed start',()=>{
    const stops:string[]=[];
    const scheduler=createLiveWallScheduler({onStart:()=>{throw new Error('unavailable');},onStop:id=>stops.push(id)});
    scheduler.requestPlay(['a','b']);
    expect(scheduler.getSnapshot().states.a).toBe('failed');
    expect(scheduler.getSnapshot().states.b).toBe('queued');
    expect(stops).toEqual(['a']);
    vi.advanceTimersByTime(LIVE_WALL_COOLDOWN_BASE_MS);
    expect(scheduler.getSnapshot().states.a).toBe('failed');
    expect(scheduler.getSnapshot().retrying).toEqual([]);
    expect(stops).toEqual(['a','a']);
  });

  it('publishes immutable snapshots only when something changes',()=>{
    const {scheduler}=harness();
    const first:LiveWallSnapshot=scheduler.getSnapshot();
    expect(scheduler.getSnapshot()).toBe(first);
    expect(first.states).toEqual({});
    expect(first.busy).toEqual([]);
    expect(first.coolingDown).toBe(false);
    const listener=vi.fn();const unsubscribe=scheduler.subscribe(listener);
    scheduler.requestStop('missing');scheduler.focus(null);scheduler.reportFailed('missing');
    expect(listener).not.toHaveBeenCalled();
    scheduler.requestPlay(['a']);
    expect(listener).toHaveBeenCalledTimes(1);
    const second=scheduler.getSnapshot();
    expect(second).not.toBe(first);
    expect(listener).toHaveBeenLastCalledWith(second);
    expect(Object.isFrozen(second)).toBe(true);
    expect(Object.isFrozen(second.states)).toBe(true);
    expect(Object.isFrozen(second.queue)).toBe(true);
    unsubscribe();
    scheduler.reportLive('a');
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
