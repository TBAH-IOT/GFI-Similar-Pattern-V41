/* Attach GFI pattern geometry + V34 projections to an existing company chart.
 * Requires Lightweight Charts 5, pattern-presentation.js, forecast-native.js.
 * The host owns the market candle feed, chart layout and controls.
 */
(function(root,factory){
  if(typeof module==='object' && module.exports) module.exports=factory;
  else root.GFISimilarPatternAdapter=factory(root.GFINativeForecast,root.GFIPatternPresentation);
})(typeof window==='object'?window:this,function(Native,Presentation){
  'use strict';
  return class SimilarPatternAdapter {
    constructor(options) {
      this.o=options;this.generation=0;this.items=[];this.selected=null;this.bars=[];this.enabled=true;
      this.visibility={line:true,candle:true,long:true,short:true};
      this.base=(options.apiBase||'').replace(/\/$/,'');
      this.shape=options.chart.addSeries(options.LC.LineSeries,{color:'#e6c364',lineWidth:2,pointMarkersVisible:true,pointMarkersRadius:3,priceLineVisible:false,lastValueVisible:false});
      this.forecast=new Native.Controller(options.chart,options.candleSeries,options.LC,
        options.formatPrice||String,{getBars:()=>options.getBars?.()||this.bars,
          getEMA:()=>options.getEMA?.()||[],emaSeries:options.emaSeries});
    }
    async start(symbol,timeframe) {
      this.stop();this.symbol=symbol;this.timeframe=timeframe;this.pinned=null;
      const generation=this.generation;
      this.abort=new AbortController();
      try {
        const data=await this.request('/api/market',generation);
        if(!data)return;
        this.bars=data.candles;
        this.o.onMarket?.(data); // Host paints its real candles/EMA first.
        this.apply(data);
        if(data.mode!=='snapshot') this.schedule(generation);
      } catch(error) {if(error.name!=='AbortError')this.o.onError?.(error);}
    }
    async request(path,generation) {
      const query=new URLSearchParams({symbol:this.symbol,tf:this.timeframe,view:'v34'});
      const response=await fetch(this.base+path+'?'+query,{signal:this.abort.signal});
      if(!response.ok)throw new Error(`Similar Pattern API: ${response.status}`);
      const data=await response.json();
      if(generation!==this.generation)return null;
      if(data.symbol!==this.symbol||data.timeframe!==this.timeframe)throw new Error('Pattern response belongs to a different market');
      return data;
    }
    schedule(generation) {
      this.timer=setTimeout(async()=>{
        try {const data=await this.request('/api/patterns',generation);if(data)this.apply(data);}
        catch(error){if(error.name!=='AbortError')this.o.onError?.(error);}
        finally {if(generation===this.generation)this.schedule(generation);}
      },this.o.pollMs||5000);
    }
    apply(data) {
      const view=Presentation.timeline(data.signals,this.pinned);
      this.items=view.items;this.selected=view.main;
      this.o.onSignals?.(view);this.o.onPipeline?.(data.pipeline);
      this.draw();
    }
    select(id) {
      this.pinned=id;
      const view=Presentation.timeline(this.items,id);
      this.selected=view.main;this.o.onSignals?.(view);this.draw();
    }
    setVisibility(flags) {
      this.visibility={...this.visibility,...flags};
      const v=this.visibility;this.forecast.visibility(v.line,v.candle,v.long,v.short);
    }
    setEnabled(enabled) {this.enabled=Boolean(enabled);this.draw();}
    draw() {
      if(!this.enabled||!this.selected){this.shape.setData([]);this.forecast.clear();return;}
      const points=this.selected.points.filter((p,i,list)=>i===list.length-1||p.time!==list[i+1].time);
      this.shape.setData(points);
      this.forecast.show(this.selected,{'15m':900,'1h':3600,'4h':14400}[this.timeframe]);
      this.setVisibility(this.visibility);
      // Deliberately never call fitContent/setVisibleRange: host zoom stays intact.
    }
    stop() {this.generation++;clearTimeout(this.timer);this.abort?.abort();this.forecast.clear();this.shape.setData([]);}
    dispose() {this.stop();this.forecast.dispose();this.o.chart.removeSeries(this.shape);}
  };
});
