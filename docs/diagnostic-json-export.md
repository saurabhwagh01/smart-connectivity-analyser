# Diagnostic JSON Export

## Overview

Smart Connectivity Analyser supports exporting the latest completed diagnostic as a JSON file. The export includes measurement results, timestamps, network type, schema version, and measurement units.

The export supports both complete and partial diagnostic results.

## Exporting a Diagnostic

1. Run a network diagnostic.
2. Once the diagnostic completes, click **Export JSON**.
3. The JSON report will be downloaded to your device.

If no completed diagnostic is available, the export is not generated.

## Schema

| Field | Description |
|---|---|
| `schema_version` | Version of the JSON export schema |
| `exported_at` | Timestamp when the export was generated |
| `diagnostic.status` | Completion status of the diagnostic |
| `diagnostic.result_status` | `complete` or `partial`, based on metric availability |
| `diagnostic.timestamp` | Timestamp of the diagnostic measurement |
| `diagnostic.network_type` | Detected network type |
| `measurement_metadata.source` | Source application |
| `measurement_metadata.units` | Units used for each metric |
| `metrics` | Diagnostic measurements |

## Metrics and Units

| Metric | JSON Field | Unit |
|---|---|---|
| Download speed | `download_mbps` | Mbps |
| Upload speed | `upload_mbps` | Mbps |
| Ping | `ping_ms` | ms |
| Jitter | `jitter_ms` | ms |
| Packet loss | `packet_loss_percent` | % |
| Connectivity score | `connectivity_score` | Score |

## Missing Metrics

Unavailable metrics are represented as `null`, not `0`.

A zero is a valid measurement and is preserved in the export. If some metrics are unavailable, the diagnostic is marked as `partial`, while available measurements remain included.

## Privacy

The JSON export includes only diagnostic information needed for the report. Precise latitude and longitude are not included in the exported JSON.

## Schema Versioning

The export currently uses schema version `1.0.0`. The version allows future changes to the export structure to be tracked.