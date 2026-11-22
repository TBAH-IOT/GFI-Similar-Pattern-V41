export type Timeframe = '15m'|'1h'|'4h'|'1d';
export interface Candle { time:number; open:number; high:number; low:number; close:number; volume:number; closed:boolean }
export interface Representative {
  basis:'closest_real_path_to_group_mean'; source_symbol:string; source_time:number;
  sample_count:number; pullback_pct:number; pullback_bar:number|null;
  mean_pullback_pct:number; mean_pullback_phase:number;
  candles:Array<{time_offset:number;open:number;high:number;low:number;close:number}>;
}
export interface PatternSignal {
  id:string; symbol:string; tf:Timeframe; name:string; base_pattern?:string; display_name?:string;
  method:string; direction:'LONG'|'SHORT'; similarity:number;
  detected_at:number; available_at:number; entry:number; tp:number; sl:number;
  points:Array<{time:number;value:number}>;
  status:'PENDING'|'OPEN'|'TP'|'SL'|'EXPIRED'|'AMBIGUOUS';
  actionable:boolean; reference_only?:boolean; bootstrap_snapshot?:boolean; statistics_as_of?:number;
  configured_win_rate?:number; validation_samples?:number; minimum_samples?:number;
  occurrence_aliases?:string[]; occurrence_revisions?:number; last_seen_at?:number;
  prediction:null|{up_probability:number;down_probability:number;sample_count:number|null;
    path_start?:'entry_bar';candle_horizon_bars?:number;path_sample_count?:number;
    up_representative?:Representative|null;down_representative?:Representative|null;
    probability_population?:string;basis:string};
}
export interface MarketResponse {
  symbol:string;timeframe:Timeframe;mode:'live'|'snapshot';source:'Binance Spot';
  server_time:number;updated_at:number;last:number;change_24h:number;
  candles:Candle[];signals:PatternSignal[];pipeline:{status:string;[key:string]:unknown};
  snapshot_as_of?:number;
}
// Seconds: Candle.time, signal timestamps, source_time. Milliseconds:
// server_time, updated_at, statistics_as_of, snapshot_as_of.
