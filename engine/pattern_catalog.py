"""Public chart-only catalogue. No candle or harmonic detector is imported."""
import numpy as np
from chart_library import CATALOG, SEARCHABLE, LEGACY as CHARTS, CURVES, BY_NAME, GROUPS, coverage

# Historical adapters accept a precomputed matrix; chart-only research has no
# candle-recognition matrix. Keeping this empty adapter does not run TA-Lib.
def candle_matrix(frame):
    return np.empty((0,len(frame['close'])),dtype='int16')
