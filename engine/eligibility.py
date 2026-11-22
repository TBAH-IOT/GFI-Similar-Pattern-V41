"""Fixed timeframe sample gate, with archived age-tier policy compatibility."""
import calendar
from datetime import datetime,timezone

SAMPLE_POLICY={'15m':100,'1h':75,'4h':50,'1d':30}

def minimum_samples(tf,anchor,as_of,policy,market=None):
    market_overrides=policy.get('minimum_samples_by_market',{})
    if market and market in market_overrides:
        return int(market_overrides[market])
    tiers=policy.get('sample_policy_by_test_age')
    if policy.get('sample_policy_mode')=='fixed' or not tiers:
        return int(policy.get('min_test_samples_by_timeframe',SAMPLE_POLICY).get(tf,policy.get('min_test_samples',100)))
    start=datetime.fromtimestamp(anchor,tz=timezone.utc)
    year=start.year+2
    anniversary=start.replace(year=year,day=min(start.day,calendar.monthrange(year,start.month)[1]))
    tier='over_two_years' if as_of>anniversary.timestamp() else 'up_to_two_years'
    return int(tiers[tier][tf])
