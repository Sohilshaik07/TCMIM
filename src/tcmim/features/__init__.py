"""
TCMIM — Feature extraction package (S2).

Modules
-------
vibration   : FR-FE-1 — RMS, std, kurtosis, skewness, crest factor,
              shape factor, spectral centroid, spectral energy.
pressure    : FR-FE-2 — statistical + temporal features for pressure/current.
temperature : FR-FE-3 — mean, std, slope.
flow_pulse  : FR-FE-4 — pulse count, pulse rate, active ratio.
              NOTE: No physical calibration factor applied.
digital     : FR-FE-5 — state, duty cycle, transitions.
extractor   : High-level extractor that dispatches by modality.
"""
