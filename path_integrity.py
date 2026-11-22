"""Exclude analogue windows crossing missing timestamped source candles."""

def contiguous_path_groups(groups, times, step):
    timestamps=set(int(value) for value in times)
    def usable(row):
        start=int(row['available_at'])
        resolved=row.get('resolved_at')
        if resolved is None:return False
        end=max(start+12*step,int(resolved)+step)
        # All detectors use at most 120 bars of local shape context. This is
        # a source-integrity gate for the analogue library, not a live model
        # warmup rule or a rewrite of the research observation counters.
        return all(time in timestamps for time in range(start-120*step,end,step))
    return {key:[row for row in rows if usable(row)] for key,rows in groups.items()}
