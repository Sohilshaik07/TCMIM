"""
TCMIM — Data ingestion package (S0–S1).

Modules
-------
loader       : Load raw CSV / serial data into SensorSample lists.
validator    : Validate timestamp ordering, ranges and completeness.
windower     : Slice validated data into time windows.
metropt3     : MetroPT-3-specific schema mapping and loader.
"""
