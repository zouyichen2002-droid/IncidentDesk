# First load run: failed

20 RPS for 600 seconds, 12,000 requests, p95 7.16 ms, 6.1% non-success. 655 responses were explicit team admission quota rejections and 77 were transport failures during a development container replacement. The three-slot worker configuration did not sustain the creation rate before backlog hit the 200/team cap. This is a failed test, not a success with 429 responses excluded.

Follow-up: re-run on a stable build with three worker replicas (nine slots, global cap ten), current-scope cache, and no service replacement during the run. Keep this original result for comparison; throughput of the deterministic workflow does not measure model throughput.
