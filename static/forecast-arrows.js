/* V40: the pattern engine's reversal ZigZag, with a forecast-scaled limit. */
(function(root, factory) {
  const api = factory(typeof module === 'object' && module.exports ? require('./forecast-native.js') : root.GFINativeForecast);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.GFIArrowForecast = api;
})(typeof window === 'object' ? window : this, function(Native) {
  'use strict';
  const COLORS = {up:'#70e0bf', down:'#f07e91'};

  function accuracyEmphasis(signal) {
    const source=signal?.accuracy_source;
    const qualified=source==='frozen_btc' ||
      (['out_of_sample','expanding_oos'].includes(source) &&
        Number(signal?.validation_samples)>=Number(signal?.minimum_samples??100));
    const rate=Number(signal?.configured_win_rate);
    if (!qualified || signal?.reference_only || !Number.isFinite(rate) || rate<0 || rate>1) return .7;
    // Visual emphasis uses the pattern's validated win rate. Directional
    // probabilities still decide which branch is primary within a pattern.
    // Smooth, strictly increasing across the full 0–100% range. Tanh keeps
    // extreme win rates legible without turning the forecast into a fat band.
    return 1.02+.32*Math.tanh((rate-.6)/.12);
  }

  function median(values) {
    const v=[...values].sort((a,b)=>a-b),m=Math.floor(v.length/2);
    return v.length ? (v[m]+v[Math.ceil(v.length/2)-1])/2 : 0;
  }

  function standardDeviation(values) {
    if (values.length<2) return 0;
    const mean=values.reduce((sum,value)=>sum+value,0)/values.length;
    const variance=values.reduce((sum,value)=>sum+(value-mean)**2,0)/(values.length-1);
    return Math.sqrt(Math.max(0,variance));
  }

  function preEntrySigma(bars, startTime) {
    const closes=(bars||[]).filter(bar=>Number.isFinite(bar?.time) && bar.time<startTime && Number.isFinite(bar.close))
      .sort((a,b)=>a.time-b.time).slice(-32).map(bar=>bar.close);
    return standardDeviation(closes);
  }

  function displayTargetLevels(entry, upper, lower, sigma) {
    const upDistance=Math.max(0,upper-entry);
    const downDistance=Math.max(0,entry-lower);
    const nearest=Math.min(upDistance,downDistance);
    if (!(nearest>0) || !(Number.isFinite(sigma) && sigma>nearest)) {
      return {upper,lower,scale:1};
    }
    // Stretch both sides by one shared factor. This keeps the TP/SL ratio
    // unchanged while giving low-range setups the same visual breathing room
    // as ordinary patterns. The cap avoids an extreme display-only jump.
    const scale=Math.min(3,Math.max(1,sigma/nearest));
    return {upper:entry+upDistance*scale,lower:entry-downDistance*scale,scale};
  }

  function sharedDisplayPaths(summary, signal) {
    const rawUpper=Math.max(Number(signal?.tp),Number(signal?.sl));
    const rawLower=Math.min(Number(signal?.tp),Number(signal?.sl));
    const upDistance=Math.max(0,rawUpper-summary.entry);
    const downDistance=Math.max(0,summary.entry-rawLower);
    const nearest=Math.min(upDistance,downDistance);
    const sigma=Number(summary.entrySigma);
    // Keep the original TP/SL ratio, but do not let a large pattern target
    // stretch the forecast layer across the whole chart.  A display-only
    // budget of roughly three local sigmas gives the pivots room while
    // keeping the two branches close enough to read with the real candles.
    // The statistical TP/SL values remain unchanged in the signal payload.
    const visualBudget=Number.isFinite(sigma) && sigma>0
      ? Math.max(sigma*3,summary.entry*.003) : 0;
    let scale=nearest>0 && visualBudget>0
      ? Math.max(.4,Math.min(3,visualBudget/nearest)) : 1;
    const upper=summary.entry+upDistance*scale;
    const lower=summary.entry-downDistance*scale;
    const options={entrySigma:sigma};
    // One shared display scale is enough.  Never enlarge TP/SL merely to
    // manufacture extra turns: every visible pivot must come from an actual
    // High/Low in the twenty-bar representative path.
    const up=zigzag(summary.up,summary.entry,summary.time,upper,options);
    const down=zigzag(summary.down,summary.entry,summary.time,lower,options);
    return {up,down,upper,lower,scale};
  }

  // Guided Path keeps the historical turns and stops before a trailing
  // reversal would point the arrowhead against its scenario. TP/SL are
  // separate reference prices, not a forced endpoint.
  function guidedDisplayPaths(summary, signal) {
    const upper=Math.max(Number(signal?.tp),Number(signal?.sl));
    const lower=Math.min(Number(signal?.tp),Number(signal?.sl));
    const options={entrySigma:Number(summary.entrySigma)};
    const step=Number(summary.up?.[0]?.time-summary.time)||Number(summary.down?.[0]?.time-summary.time);
    const horizon=Math.max(Number(summary.upHorizon)||summary.up?.length||0,
      Number(summary.downHorizon)||summary.down?.length||0);
    const branch=side=>{
      const primary=guidedHistoricalPath(summary[side],summary.entry,summary.time,side,options);
      const display=constrainGuidedPath(primary,summary.entry,side,summary.time,step,horizon);
      if (guidedPathHasDirection(display,summary.entry,side)) return display;
      // A representative outcome can spend its entire first horizon on the
      // opposite side of Entry. Use the historical group mean for this rare
      // case, instead of fabricating a mirrored or flat arrow.
      const source=signal?.prediction?.[`${side}_candles`] || [];
      const scale=Number(summary[`${side}Calibration`]?.scale) || 1;
      const rows=Native.projectOHLC(source.slice(0,summary[`${side}Horizon`]||source.length),
        summary.entry,summary.time,step,summary[`${side}Horizon`]||source.length,
        signal?.prediction?.path_start==='entry_bar',scale);
      const fallback=guidedHistoricalPath(rows,summary.entry,summary.time,side,options);
      return constrainGuidedPath(fallback,summary.entry,side,summary.time,step,horizon);
    };
    return {
      up:branch('up'),
      down:branch('down'),
      upper,lower,scale:1,
    };
  }

  // V41 is a directional drawing, not another price forecast. Use the
  // representative's real turns (or its OHLC extremes when ZigZag suppresses
  // a small turn), then show one restrained pullback before a terminal high
  // or low. Only the presentation geometry is adjusted; TP/SL and the native
  // candle sequence remain untouched.
  function spotlightDisplayPaths(summary, signal) {
    const display=guidedDisplayPaths(summary,signal);
    const entry=Number(summary.entry);
    const step=Number(summary.up?.[0]?.time-summary.time)||Number(summary.down?.[0]?.time-summary.time);
    const horizon=Math.max(Number(summary.upHorizon)||summary.up?.length||0,
      Number(summary.downHorizon)||summary.down?.length||0);
    if (!(step>0 && horizon>=5)) return display;
    for (const [side,target] of [['up',display.upper],['down',display.lower]]) {
      const points=display[side];
      if (points.length<2 || !Number.isFinite(target)) continue;
      const sign=side==='up'?1:-1;
      const targetDistance=sign*(target-entry);
      if (!(targetDistance>0)) continue;
      const source=summary[side]||[];
      const favorable=bar=>sign*((side==='up'?bar.high:bar.low)-entry);
      const adverse=bar=>sign*((side==='up'?bar.low:bar.high)-entry);
      const peakDistance=Math.max(0,...points.map(point=>sign*(point.value-entry)),
        ...source.map(favorable).filter(Number.isFinite));
      const candidates=[];
      const offer=(first,second,firstSlot,secondSlot,origin)=>{
        const drop=first-second;
        if (!(first>0 && drop>0 && firstSlot>=1 && secondSlot>firstSlot && secondSlot<horizon)) return;
        const phaseA=firstSlot/horizon,phaseB=secondSlot/horizon;
        const ratio=drop/Math.max(peakDistance,1e-9);
        const score=Math.abs(ratio-.18)*1.2+Math.abs(phaseA-.3)*.8+
          Math.abs(phaseB-.55)*.8+(origin==='candle'?.14:0);
        candidates.push({first,drop,firstSlot,secondSlot,score});
      };
      // Prefer turns already confirmed in the existing historical ZigZag.
      for (let i=1;i<points.length-2;i++) for (let j=i+1;j<points.length-1;j++) {
        offer(sign*(points[i].value-entry),sign*(points[j].value-entry),
          Math.round((points[i].time-summary.time)/step),
          Math.round((points[j].time-summary.time)/step),'zigzag');
      }
      if (!candidates.length) {
        // A muted ZigZag may drop a real, small counter-swing. Search the
        // projected historical H/L, without inventing a pivot time.
        for (let i=0;i<source.length-3;i++) for (let j=i+1;j<source.length-1;j++) {
          offer(favorable(source[i]),adverse(source[j]),i+1,j+1,'candle');
        }
      }
      candidates.sort((a,b)=>a.score-b.score);
      const bend=candidates[0];
      // The aggregate adverse excursion supplies a fallback depth only if
      // this representative offers no counter-swing inside the horizon.
      const historicPullback=Number(signal?.prediction?.[`${side}_pullback_pct`])||0;
      const firstSlot=Math.max(2,Math.min(Math.floor(horizon*.48),bend?.firstSlot||Math.round(horizon*.3)));
      const secondSlot=Math.max(firstSlot+2,Math.min(horizon-2,bend?.secondSlot||Math.round(horizon*.55)));
      const amplitude=Math.min(targetDistance*.78,
        Math.max(targetDistance*.55,peakDistance*1.35,Number(summary.entrySigma||0)*.7));
      const firstFraction=bend && peakDistance>0 ? bend.first/peakDistance : .55;
      const firstRise=amplitude*Math.max(.42,Math.min(.64,firstFraction));
      const observedDrop=bend && peakDistance>0 ? bend.drop/peakDistance : historicPullback*entry/Math.max(peakDistance,1e-9);
      const pullback=amplitude*Math.max(.11,Math.min(.22,observedDrop));
      const trough=Math.max(amplitude*.23,firstRise-pullback);
      display[side]=[
        {time:summary.time,value:entry,index:0},
        {time:summary.time+firstSlot*step,value:entry+sign*firstRise,index:firstSlot},
        {time:summary.time+secondSlot*step,value:entry+sign*trough,index:secondSlot},
        {time:summary.time+horizon*step,value:entry+sign*amplitude,index:horizon},
      ];
    }
    return display;
  }

  function guidedPathHasDirection(path,entry,direction) {
    if (path.length<2) return false;
    const sign=direction==='up'?1:-1;
    return sign*(path.at(-1).value-entry)>1e-8
      && sign*(path.at(-1).value-path.at(-2).value)>1e-8;
  }

  function constrainGuidedPath(path,entry,direction,startTime,step,horizon) {
    if (path.length<2 || !(step>0) || !(horizon>0)) return path;
    const sign=direction==='up'?1:-1;
    const lastIndex=path.at(-1).index;
    if (!(lastIndex>0)) return path;
    // Two branches use the same display width. The source pivots retain
    // their order and relative spacing, while their time positions are
    // stretched to the shared forecast horizon. Native OHLC is untouched.
    return path.map((point,index)=>{
      const slot=index===0?0:index===path.length-1?horizon:Math.round(point.index*horizon/lastIndex);
      const favorable=index===0?0:Math.max(0,sign*(point.value-entry));
      return {...point,time:startTime+slot*step,value:entry+sign*favorable};
    });
  }

  function guidedHistoricalPath(rows,entry,time,direction,options={}) {
    if (!rows?.length) return [];
    const source=zigzag(rows,entry,time,undefined,{...options,direction,guided:true});
    const sign=direction==='up'?1:-1;
    const points=[...source];
    // The final incomplete swing is often a pullback. It is not a forecast
    // of the opposite scenario, so end at the last confirmed favorable
    // high/low instead of drawing a green arrow down or a red arrow up.
    while (points.length>2 && sign*(points.at(-1).value-points.at(-2).value)<=0) points.pop();
    if (points.length<2 || sign*(points.at(-1).value-points.at(-2).value)<=0) return [];
    return points;
  }

  function confirmedZigzag(values, limit) {
    // Same state machine, inclusive comparisons and initial down state as
    // PatternMatcher.extract_extrema_zigzag. Keep all turns for rendering;
    // the detector's last-five gate is only for template matching.
    const pivots=[];
    let state='down', extreme=0;
    for (let i=1;i<values.length;i++) {
      const price=values[i].close,current=values[extreme].close;
      if (state==='down') {
        if (price<=current) extreme=i;
        else if (price>=current*(1+limit)) {pivots.push(extreme);state='up';extreme=i;}
      } else {
        if (price>=current) extreme=i;
        else if (price<=current*(1-limit)) {pivots.push(extreme);state='down';extreme=i;}
      }
    }
    return {pivots,extreme};
  }

  function simplifyPivotIndices(values, pivots, maxPivots=3) {
    if (pivots.length<=maxPivots) return pivots;
    const last=values.length-1;
    const candidates=[...new Set([0,...pivots,last])].sort((a,b)=>a-b);
    const priceValues=candidates.map(index=>values[index].close);
    const minValue=Math.min(...priceValues),maxValue=Math.max(...priceValues);
    const priceSpan=Math.max(maxValue-minValue,1e-9);
    const xScale=Math.max(1,last);
    const normalize=point=>({x:point.index/xScale,y:(point.value-minValue)/priceSpan});
    const selected=[candidates[0],candidates.at(-1)];
    while (selected.length<maxPivots+2) {
      selected.sort((a,b)=>a-b);
      let best=null;
      for (let segment=0;segment<selected.length-1;segment++) {
        const left=selected[segment],right=selected[segment+1];
        const start=normalize({index:left,value:values[left].close});
        const end=normalize({index:right,value:values[right].close});
        const dx=end.x-start.x,dy=end.y-start.y,denominator=dx*dx+dy*dy;
        for (const index of candidates) {
          if (index<=left || index>=right || selected.includes(index)) continue;
          const point=normalize({index,value:values[index].close});
          const t=denominator ? ((point.x-start.x)*dx+(point.y-start.y)*dy)/denominator : 0;
          const projection={x:start.x+t*dx,y:start.y+t*dy};
          const distance=Math.hypot(point.x-projection.x,point.y-projection.y);
          if (!best || distance>best.distance) best={index,distance};
        }
      }
      if (!best) break;
      selected.push(best.index);
    }
    return selected.sort((a,b)=>a-b).filter(index=>index>0 && index<last && pivots.includes(index));
  }

  function zigzag(rows, entry, time, target, options = {}) {
    if (!rows.length) return [];
    // Keep the helper backwards-compatible with the archived V40 arrow
    // experiment, whose fourth argument was the options object.
    if (target && typeof target === 'object') { options=target; target=undefined; }
    // The forecast guide is a path through the forecast candles, not a
    // second close-only average. Keep each candle's H/L so the guide can
    // turn at the same real extremes a trader would see on the chart.
    const rawValues=[{time,close:entry,high:entry,low:entry},...rows.map(row=>({
      time:row.time,
      close:Number(row.close),
      high:Number.isFinite(Number(row.high))?Number(row.high):Number(row.close),
      low:Number.isFinite(Number(row.low))?Number(row.low):Number(row.close),
    }))];
    const upward=options.direction ? options.direction==='up' : (!Number.isFinite(target) || target>=entry);
    // Normalize the historical path around Entry so its actual wiggles are
    // preserved.  The old implementation added a linear drift to every
    // candle in order to force the last close to TP/SL; on low-range setups
    // that drift dominated the source path and made the forecast look like a
    // straight line.  Scaling the whole relative path keeps the historical
    // pullbacks and endpoint shape while still landing on the displayed
    // target.  A nearly-flat source path uses the old correction only as a
    // defensive fallback because there is no stable relative displacement to
    // scale.
    const rawEnd=Number(rawValues.at(-1)?.close);
    const rawEndDelta=rawEnd-entry;
    const targetDelta=Number(target)-entry;
    const scaleFloor=Math.max(Math.abs(entry)*0.00005,1e-9);
    // Size the source against its actual favorable H/L excursion, rather
    // than only its final close. A wick that happens early in the 20-bar
    // sample must not hit a compressed display TP/SL on bar 2 and cut away
    // the rest of the representative shape.
    const rawExtremeDelta=upward
      ? Math.max(...rawValues.slice(1).map(value=>Number(value.high)-entry).filter(Number.isFinite),0)
      : Math.max(...rawValues.slice(1).map(value=>entry-Number(value.low)).filter(Number.isFinite),0);
    const rawShapeDelta=rawExtremeDelta>scaleFloor ? rawExtremeDelta/.92 : Math.abs(rawEndDelta);
    const rawScale=Number.isFinite(target) && rawShapeDelta>scaleFloor && Number.isFinite(targetDelta)
      ? Math.abs(targetDelta)/rawShapeDelta : null;
    // A source sequence that finishes on the opposite side of Entry is not
    // a valid shape for this branch.  Keep the defensive drift fallback for
    // that rare case rather than mirroring the source.  Also cap expansion:
    // an almost-flat historical finish must not turn a few ordinary candles
    // into an artificial vertical spike.
    const proportionalScale=rawScale!==null && rawScale>0
      ? Math.max(.25,Math.min(4,rawScale)) : null;
    const driftable=Number.isFinite(target) && Number.isFinite(rawEnd) && rawValues.length>1;
    const projectValue=(value,index)=> {
      const drifted=proportionalScale!==null
        ? entry+(value-entry)*proportionalScale
        : driftable ? value + (index/(rawValues.length-1))*(target-rawEnd) : value;
      if (options.guided && !Number.isFinite(target)) return drifted;
      return Number.isFinite(target)
        ? (upward ? Math.min(target,Math.max(entry,drifted)) : Math.max(target,Math.min(entry,drifted)))
        : (upward ? Math.max(entry,drifted) : Math.min(entry,drifted));
    };
    let values=rawValues.map((value,index)=>{
      const close=index===0 ? entry : projectValue(value.close,index);
      const high=index===0 ? entry : projectValue(Math.max(value.high,value.close),index);
      const low=index===0 ? entry : projectValue(Math.min(value.low,value.close),index);
      return {...value,close,high:Math.max(close,high,low),low:Math.min(close,high,low)};
    });
    // Choose the visible swing extreme from each candle's H/L. Favor the
    // high on a favorable candle and the low on a pullback candle for LONG;
    // reverse that for SHORT. The ZigZag state machine then filters these
    // real extremes into pivot-to-pivot straight segments.
    const pivotValues=values.map((value,index)=> {
      if (!index) return {...value,close:entry};
      const previous=values[index-1].close;
      const favorable=upward ? value.close>=previous : value.close<=previous;
      const candidate=upward
        ? (favorable ? value.high : value.low)
        : (favorable ? value.low : value.high);
      return {...value,close:candidate};
    });
    // Once a branch reaches its TP/SL level, the forecast is considered
    // complete. Stop the path at the first touch instead of drawing a later
    // reversal back away from the target and then forcing the final point
    // onto it. This keeps the arrow's endpoint physically locked at TP/SL.
    if (Number.isFinite(target) && pivotValues.length>1) {
      const hitIndex=pivotValues.findIndex((value,index)=>index>0 && (upward ? value.close>=target : value.close<=target));
      if (hitIndex>0) {
        pivotValues.splice(hitIndex+1);
        pivotValues[hitIndex]={...pivotValues[hitIndex],close:target};
      }
    }
    const moves=pivotValues.slice(1).map((v,i)=>Math.abs(v.close-pivotValues[i].close));
    const ranges=pivotValues.slice(1).map(v=>Math.max(0,v.high-v.low)).filter(Number.isFinite);
    // Keep smaller, real pullbacks so a 20-bar historical path does not
    // collapse into one long diagonal. The cap below removes only noisy
    // micro-turns; it never creates a pivot that is absent from the source.
    let limit=options.limit ?? Math.max(median(moves)*.2,median(ranges)*.04,entry*.00002)/entry;
    let result=confirmedZigzag(pivotValues,limit);
    if (options.limit==null) {
      // Prefer a few visible pivots. Search thresholds in both directions
      // and select the closest real-pivot result; do not keep multiplying a
      // threshold after the count has already overshot, which can turn a
      // genuinely wiggly path back into a straight line.
      // The hand-drawn reference uses several meaningful swings:
      // impulse, pullback, continuation, pullback, then TP/SL. Keep the
      // 20-bar source intact, but prefer 3–6 confirmed pivots instead of
      // tracing every micro-wick.
      const desiredPivots=values.length>=12 ? 4 : 3;
      const candidates=[];
      for (let i=0;i<=14;i++) candidates.push(limit*Math.pow(.55,i));
      for (let i=1;i<=14;i++) candidates.push(limit*Math.pow(1.3,i));
      const evaluated=candidates.filter(candidateLimit=>candidateLimit>0).map(candidateLimit=>({
        limit:candidateLimit,result:confirmedZigzag(pivotValues,candidateLimit)
      }));
      const hasAnyPivot=evaluated.some(candidate=>candidate.result.pivots.length>0);
      let best={limit,result,score:Number.POSITIVE_INFINITY};
      for (const candidate of evaluated) {
        const candidateLimit=candidate.limit;
        const candidateResult=candidate.result;
        const count=candidateResult.pivots.length;
        const phases=candidateResult.pivots.map(index=>index/Math.max(1,values.length-1));
        const hasMidPullback=phases.some(phase=>phase>=.18 && phase<=.82);
        const firstTooLate=phases.length>0 && phases[0]>.42;
        const lastTooEarly=phases.length>1 && phases.at(-1)<.58;
        const penalty=count===0 && hasAnyPivot ? 30 : count<3 ? (3-count)*4 : count>5 ? (count-5)*1.5 : 0;
        const phasePenalty=(hasMidPullback?0:2)+(firstTooLate?1.5:0)+(lastTooEarly?1:0);
        const score=Math.abs(count-desiredPivots)+penalty+phasePenalty;
        if (score<best.score || (score===best.score && candidateLimit>best.limit)) {
          best={limit:candidateLimit,result:candidateResult,score};
        }
      }
      limit=best.limit; result=best.result;
    }
    if (result.pivots.length>5) {
      result={...result,pivots:simplifyPivotIndices(pivotValues,result.pivots,5)};
    }
    // An unconfirmed running extreme near the endpoint used to produce a
    // tiny hook just before the arrowhead. Only confirmed turns + horizon
    // endpoint belong in this display path.
    const indices=[0,...result.pivots,pivotValues.length-1].filter((v,i,a)=>i===0||v>a[i-1]);
    const points=indices.map(index=>({time:pivotValues[index].time,value:pivotValues[index].close,index,confirmed:result.pivots.includes(index),reversalLimit:limit}));
    // The arrow endpoint is the statistical TP/SL level, not whichever close
    // happened to be last in the representative candle sequence. Keep the
    // historical zigzag until the final slot, then finish exactly on the
    // level shown on the price axis.
    if (Number.isFinite(target) && points.length) {
      const endTime=pivotValues.at(-1).time;
      const endpoint={time:endTime,value:target,index:pivotValues.length-1,confirmed:true,reversalLimit:limit};
      if (points.at(-1).time===endTime) points[points.length-1]=endpoint;
      else points.push(endpoint);
    }
    // Leave a readable gap around the white Entry line. The gap scales with
    // the actual TP/SL distance and is capped so it cannot consume the
    // branch's target range.
    if (points.length>1 && Number.isFinite(target)) {
      const distance=Math.abs((Number.isFinite(target)?target:points.at(-1).value)-entry);
      // Keep the first visible turn comfortably away from Entry. The gap is
      // one local pre-Entry sigma; the fallback only applies when that
      // volatility history is unavailable.
      const sigma=Number(options.entrySigma);
      const requestedGap=Number.isFinite(sigma) && sigma>0 ? sigma : Math.abs(entry)*.001;
      // Use one local pre-Entry standard deviation when available. The cap
      // only prevents a very volatile regime from consuming the whole
      // Entry→TP/SL range and collapsing the arrow endpoint.
      const gap=Math.min(distance*.65,requestedGap);
      for (let i=1;i<points.length;i++) {
        points[i].value=upward ? Math.max(points[i].value,entry+gap) : Math.min(points[i].value,entry-gap);
      }
      if (Number.isFinite(target)) points[points.length-1].value=target;
    }
    return points;
  }

  function smoothSegments(points) {
    if (points.length<2) return [];
    const slopes=points.slice(1).map((p,i)=>(p.y-points[i].y)/(p.x-points[i].x));
    const tangents=points.map((_,i)=> {
      if (!i) return slopes[0]*.8;
      if (i===points.length-1) return slopes.at(-1)*.8;
      const a=slopes[i-1],b=slopes[i];
      return a*b<=0 ? 0 : Math.sign(a)*Math.min(Math.abs((a+b)/2),3*Math.min(Math.abs(a),Math.abs(b)));
    });
    return points.slice(1).map((end,i)=> {
      const start=points[i],dx=(end.x-start.x)/3;
      return {start,c1:{x:start.x+dx,y:start.y+dx*tangents[i]},c2:{x:end.x-dx,y:end.y-dx*tangents[i+1]},end};
    });
  }

  class ArrowAxis {
    constructor(owner,side) {this.owner=owner; this.side=side;}
    coordinate() {
      const value=this.owner.guided ? this.owner.targets?.[this.side] : this.owner.paths[this.side]?.at(-1)?.value;
      return this.owner.series.priceToCoordinate(value) ?? -1;
    }
    text() {
      const value=this.owner.guided ? this.owner.targets?.[this.side] : this.owner.paths[this.side]?.at(-1)?.value;
      return this.owner.format(value);
    }
    textColor() {return '#09201a';}
    backColor() {return COLORS[this.side];}
    tickVisible() {return false;}
    visible() {const y=this.coordinate(); return this.owner.branchVisible(this.side) && y>=0 && y<=this.owner.height();}
  }

  class ArrowGuide {
    constructor(chart,series,format) {
      this.chart=chart; this.series=series; this.format=format;
      this.paths={up:[],down:[]}; this.visible=true; this.long=true; this.short=true;
      this.spotlight=false;
      this.probabilities={up:0,down:0};
      this.accuracyWeight=1;
      this.lowRange={up:false,down:false};
      this.targets={up:null,down:null};
      this.axes=['up','down'].map(side=>new ArrowAxis(this,side));
      this.view={zOrder:()=> 'top',renderer:()=>({draw:target=>this.draw(target)})};
    }
    attached({requestUpdate}) {this.requestUpdate=requestUpdate;}
    detached() {this.requestUpdate=null;}
    paneViews() {return [this.view];}
    priceAxisViews() {return this.axes;}
    height() {return this.chart.panes()[0].getHeight();}
    branchVisible(side) {
      const path=this.paths[side];
      if (!this.visible || !(side==='up'?this.long:this.short) || path.length<2) return false;
      const a=this.chart.timeScale().timeToCoordinate(path[0].time), b=this.chart.timeScale().timeToCoordinate(path.at(-1).time);
      return a!=null && b!=null && b>=0 && a<=this.chart.timeScale().width();
    }
    autoscaleInfo() {
      const prices=['up','down'].flatMap(side=>this.branchVisible(side)
        ? [...this.paths[side].map(p=>p.value), ...(this.guided && Number.isFinite(this.targets?.[side]) ? [this.targets[side]] : [])]
        : []);
      return prices.length ? {priceRange:{minValue:Math.min(...prices),maxValue:Math.max(...prices)}} : null;
    }
    set(summary, signal) {
      this.paths={up:[],down:[]};
      this.lowRange={up:false,down:false};
      this.probabilities={up:Number(signal?.prediction?.up_probability)||0,down:Number(signal?.prediction?.down_probability)||0};
      this.accuracyWeight=this.spotlight?accuracyEmphasis(signal):1;
      if (summary) {
        const display=this.spotlight ? spotlightDisplayPaths(summary,signal)
          : this.guided ? guidedDisplayPaths(summary,signal) : sharedDisplayPaths(summary,signal);
        this.lowRange={up:display.scale>1,down:display.scale>1};
        this.displayScale=display.scale;
        this.targets={up:display.upper,down:display.lower};
        this.paths.up=display.up;
        this.paths.down=display.down;
      }
      this.requestUpdate?.();
    }
    draw(target) {
      const screen=side=>this.paths[side].map(p=>({x:this.chart.timeScale().timeToCoordinate(p.time), y:this.series.priceToCoordinate(p.value)}));
      target.useMediaCoordinateSpace(({context:ctx, mediaSize:size})=> {
        ctx.save(); ctx.beginPath(); ctx.rect(0,0,size.width,size.height); ctx.clip();
        if (this.spotlight && this.visible) {
          const paths=['up','down'].filter(side=>this.branchVisible(side)).map(side=>this.paths[side]);
          if (paths.length) {
            const entryX=this.chart.timeScale().timeToCoordinate(paths[0][0].time);
            const endX=Math.max(...paths.map(path=>this.chart.timeScale().timeToCoordinate(path.at(-1).time)));
            if (Number.isFinite(entryX) && Number.isFinite(endX) && endX>entryX) {
              const left=Math.max(0,entryX), right=Math.min(size.width,endX+9);
              if (right>left) {
                const shade=ctx.createLinearGradient(left,0,right,0);
                shade.addColorStop(0,'rgba(8,23,21,.30)');
                shade.addColorStop(1,'rgba(8,23,21,.58)');
                ctx.fillStyle=shade; ctx.fillRect(left,0,right-left,size.height);
                ctx.strokeStyle='rgba(165,203,180,.25)'; ctx.lineWidth=1;
                ctx.setLineDash([3,5]); ctx.beginPath();ctx.moveTo(entryX,0);ctx.lineTo(entryX,size.height);ctx.stroke();ctx.setLineDash([]);
                if (right-left>120 && entryX>=0) {
                  ctx.fillStyle='#a4cbb9';ctx.font='600 9px Segoe UI, sans-serif';ctx.textAlign='left';
                  ctx.fillText('ĐƯỜNG KỊCH BẢN',Math.min(entryX+10,size.width-136),20);
                }
              }
            }
          }
        }
        const labels=[];
        const drawOrder=['down','up'].sort((a,b)=>this.spotlight ? this.probabilities[a]-this.probabilities[b] : 0);
        for (const side of drawOrder) {
          if (!this.branchVisible(side)) continue;
          const points=screen(side);
          if (points.some(p=>!Number.isFinite(p.x)||!Number.isFinite(p.y))) continue;
          const end=points.at(-1),previous=points.at(-2);
          if (!previous) continue;
          const strong=this.probabilities[side]>=.5;
          const accuracyLevel=Math.max(0,Math.min(1,(this.accuracyWeight-.7)/.64));
          const branchAlpha=this.spotlight
            ? (strong ? .84+.16*accuracyLevel : .48+.13*accuracyLevel)
            : (strong ? 1 : .78);
          const trace=()=> {
            ctx.beginPath(); ctx.moveTo(points[0].x,points[0].y);
            for (const point of points.slice(1)) ctx.lineTo(point.x,point.y);
          };
          ctx.lineCap='round'; ctx.lineJoin='round'; ctx.setLineDash([]);
          // Use straight pivot-to-pivot segments, matching the pattern
          // geometry elsewhere in the terminal. No Bezier smoothing here.
          trace(); ctx.lineWidth=this.spotlight?7*this.accuracyWeight:5.5; ctx.strokeStyle=this.spotlight?'rgba(10,18,16,.95)':'rgba(23,23,20,.9)'; ctx.stroke();
          const compact=this.lowRange[side];
          trace(); ctx.lineWidth=this.spotlight ? (strong?3.7:1.8)*this.accuracyWeight : strong?(compact?3.35:2.8):(compact?2.7:2.1);
          ctx.strokeStyle=COLORS[side]; ctx.globalAlpha=branchAlpha;
          if (this.spotlight && strong) {ctx.shadowColor=COLORS[side];ctx.shadowBlur=4+8*accuracyLevel;}
          ctx.stroke();ctx.shadowBlur=0;
          const angle=Math.atan2(end.y-previous.y,end.x-previous.x),a=this.spotlight?(strong?10:7)*Math.sqrt(this.accuracyWeight):11,w=this.spotlight?(strong?4.4:3)*Math.sqrt(this.accuracyWeight):4.8;
          const bx=end.x-a*Math.cos(angle),by=end.y-a*Math.sin(angle);
          ctx.fillStyle=COLORS[side];
          ctx.beginPath(); ctx.moveTo(end.x+1.5*Math.cos(angle),end.y+1.5*Math.sin(angle));
          ctx.lineTo(bx+w*Math.sin(angle),by-w*Math.cos(angle));
          ctx.lineTo(bx-w*Math.sin(angle),by+w*Math.cos(angle));
          ctx.closePath(); ctx.fill();
          // TP/SL are independent reference levels. Keep a short dashed
          // ruler near the price axis without suggesting the historical
          // arrow path has reached that level.
          ctx.globalAlpha=branchAlpha;
          const referenceY=this.guided ? this.series.priceToCoordinate(this.targets?.[side]) : end.y;
          ctx.strokeStyle=COLORS[side]; ctx.lineWidth=this.guided?1.35*(this.spotlight?this.accuracyWeight:1):1.7; ctx.setLineDash([5,5]);
          const referenceStart=this.guided ? Math.max(0,size.width-105) : end.x;
          if (Number.isFinite(referenceY)) {
            ctx.beginPath(); ctx.moveTo(referenceStart,referenceY); ctx.lineTo(size.width-3,referenceY); ctx.stroke();
          }
          if (Number.isFinite(referenceY) && referenceY >= 0 && referenceY <= size.height) {
            ctx.setLineDash([]); ctx.fillStyle=COLORS[side];
            ctx.beginPath(); ctx.arc(size.width-3,referenceY,3.3,0,Math.PI*2); ctx.fill();
          }
          ctx.globalAlpha=1;
          labels.push({side,strong,x:Math.max(44,Math.min(size.width-48,end.x-7)),y:Math.max(16,Math.min(size.height-16,end.y+(side==='up'?-17:18)))});
        }
        if (labels.length===2 && Math.abs(labels[0].y-labels[1].y)<30 && Math.abs(labels[0].x-labels[1].x)<100) {
          const center=(labels[0].y+labels[1].y)/2;
          labels.find(l=>l.side==='up').y=Math.max(16,center-17);
          labels.find(l=>l.side==='down').y=Math.min(size.height-16,center+17);
        }
        for (const l of labels) {
          const text=this.guided
            ? `${l.side==='up'?'TĂNG':'GIẢM'} · ${Math.round(this.probabilities[l.side]*100)}%`
            : `${l.side==='up'?'↑':'↓'} ${Math.round(this.probabilities[l.side]*100)}%`;
          ctx.font=`600 ${this.spotlight && !l.strong ? 10 : 12}px Segoe UI, sans-serif`; ctx.textAlign='right'; ctx.textBaseline='middle';
          ctx.lineWidth=5; ctx.strokeStyle='#171714'; ctx.strokeText(text,l.x,l.y);
          ctx.fillStyle=COLORS[l.side]; ctx.globalAlpha=this.spotlight && !l.strong ? .72 : 1; ctx.fillText(text,l.x,l.y);ctx.globalAlpha=1;
        }
        ctx.restore();
      });
    }
  }

  class Controller extends Native.Controller {
    constructor(chart,series,LC,format,marketView) {
      super(chart,series,LC,format,marketView);
      this.guided=Boolean(marketView?.guidedMode);
      this.arrows=new ArrowGuide(chart,series,format);
      this.arrows.guided=this.guided;
      this.arrows.spotlight=Boolean(marketView?.spotlightMode);
      series.attachPrimitive(this.arrows);
    }
    show(signal, step) {
      // The source representative remains at least twenty candles long for
      // statistics, but the directional arrow is deliberately shown over a
      // compact 10–15-bar window, like the reference Pattern Path UI. This
      // keeps the arrow legible while preserving the same historical source.
      const prediction=signal?.prediction;
      // Guided Path keeps the historical close path (so the guide can still
      // zigzag), but makes the scenario colour unambiguous when hollow
      // candles are enabled: every LONG candle has a bullish body and every
      // SHORT candle has a bearish body. Wick lengths and body sizes still
      // come from the historical representative instead of being cloned.
      const directionalizeSource=(source,side)=> {
        if (!this.guided || !source?.candles?.length) return source;
        const upward=side==='up';
        const candles=source.candles.map((row,index)=> {
          const open=Number(row.open), high=Number(row.high), low=Number(row.low), close=Number(row.close);
          if (![open,high,low,close].every(Number.isFinite)) return row;
          const range=Math.max(0,high-low);
          const originalBody=Math.abs(close-open);
          const bodyFloor=Math.max(range*.18, Math.abs(close)*.00003, 1e-8);
          const body=Math.max(originalBody,bodyFloor);
          let nextOpen=open, nextClose=close;
          // Preserve the historical close path whenever its body already has
          // the requested direction. Only repair the body orientation.
          if (upward && !(nextClose>nextOpen)) nextOpen=nextClose-body;
          if (!upward && !(nextClose<nextOpen)) nextOpen=nextClose+body;
          // The first source candle is the entry anchor in the API. Keep its
          // normalized open at 1 when possible so projection alignment does
          // not introduce a jump before the first visible forecast candle.
          if (index===0 && Number.isFinite(open)) {
            const anchor=open;
            if (upward) {
              if (nextClose<=anchor) nextClose=anchor+body;
              nextOpen=anchor;
            } else {
              if (nextClose>=anchor) nextClose=anchor-body;
              nextOpen=anchor;
            }
          }
          const bodyLow=Math.min(nextOpen,nextClose), bodyHigh=Math.max(nextOpen,nextClose);
          const sourceLowWick=Math.max(0,Math.min(open,close)-low);
          const sourceHighWick=Math.max(0,high-Math.max(open,close));
          const nextLow=Math.max(0,bodyLow-sourceLowWick);
          const nextHigh=bodyHigh+sourceHighWick;
          return {...row,open:nextOpen,high:Math.max(nextHigh,nextOpen,nextClose),low:Math.min(nextLow,nextOpen,nextClose),close:nextClose};
        });
        return {...source,candles};
      };
      const capSide=side=> {
        const source=directionalizeSource(prediction?.[side+'_representative'],side);
        const raw=Number(prediction?.[side+'_horizon_bars']||prediction?.candle_horizon_bars)||20;
        const visible=Math.max(10,Math.min(15,raw));
        if (!source?.candles?.length) return {visible,source};
        return {visible,source:{...source,candles:source.candles.slice(0,visible)}};
      };
      const up=capSide('up'),down=capSide('down');
      const displaySignal=prediction ? {...signal,prediction:{...prediction,
        up_horizon_bars:up.visible,down_horizon_bars:down.visible,
        candle_horizon_bars:Math.max(up.visible,down.visible),
        up_representative:up.source,down_representative:down.source,
      }} : signal;
      super.show(displaySignal,step);
      this.summary.entrySigma=preEntrySigma(this.marketView.getBars?.(),signal.available_at);
      this.arrows.set(this.summary,signal);
      this.visibility(this.lineVisible,this.candleVisible,this.longVisible,this.shortVisible);
    }
    clear() {super.clear(); this.arrows?.set(null,null);}
    visibility(line,arrow,long=this.longVisible,short=this.shortVisible) {
      // V40 uses this controller's zigzag as the only colored forecast
      // guide. Keep the native controller's white Entry line/marker, but
      // suppress its old green/red TP/SL curves and axis labels so the two
      // renderers never stack on top of each other.
      super.visibility(false,arrow,long,short);
      // Native.Controller stores its first argument as lineVisible. Restore
      // the V40 meaning after deliberately passing false to the native guide:
      // here LINE controls the zigzag, while CANDLE is the second argument.
      this.lineVisible=line;
      if (this.arrows) {
        Object.assign(this.arrows,{visible:line,long,short}); this.arrows.requestUpdate?.();
      }
    }
    dispose() {this.realSeries.detachPrimitive(this.arrows); super.dispose();}
  }
  return {Controller,zigzag,confirmedZigzag,smoothSegments,ArrowGuide,sharedDisplayPaths,guidedHistoricalPath,constrainGuidedPath,guidedDisplayPaths,spotlightDisplayPaths};
});
