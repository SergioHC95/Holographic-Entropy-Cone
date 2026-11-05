# Balancing complete CI audits

The ray-rank checks dominate the current CI runtime. In the completed
[main run 41912434568](https://github.com/SergioHC95/Holographic-Entropy-Cone/actions/runs/41912434568),
the 16 n=6 ray jobs took 28–112 minutes each. Graph jobs took 6–11 minutes;
complete-map proof jobs took less than five minutes.

Ray checks now have their own cap of 128 jobs, independent of the 16-job graph
cap. The current complete validation matrix has 242 jobs, within GitHub's
[256-job matrix limit](https://docs.github.com/en/actions/reference/limits).
All other audit partitions and the required final gate are retained.

## Measured-cost contiguous ranges

`src/hec/_ci_ray_costs.json` contains elapsed-millisecond increments from each
1,000-completion progress line and the final completion of all 16 successful
ray jobs in that run. The first batch includes serial warm-up and the final
partial batch is included. Its source commit, job IDs, facet-index digest and
ordered ray-index SHA256 are recorded. These timings are approximate work
estimates from four workers, never mathematical certificates.

The planner divides cumulative estimated work at equal quantiles, interpolates
within a batch with integer arithmetic and rounds to row boundaries. Every
range is contiguous; sparse checkout needs only overlapping payload shards.
The rank executor recomputes the same ranges from the same committed profile
and ray index. Actual row results must still be complete, unique and in range.
The public default remains round-robin.

On that historical profile, 128 partitions have about 583 seconds of estimated
rank work each, versus 1,638–6,698 seconds across the previous 16 ranges.
This is a replay of scheduling estimates, not a measured new CI runtime.
Setup, runner availability, hardware differences, new facet data and imperfect
batch estimates can change actual wall time. More shards expose work to the
existing runner pool; they do not raise the account's concurrency limit.

If the ordered ray index changes, its digest no longer matches the profile.
The planner and executor then use equal-row contiguous ranges with the finer
128-job cap. No old ordering or mathematical result is reused. Refresh timing
hints only from a successful complete audit, include every batch through the
last row, and record the new run/commit/index identities with the profile.
Balanced jobs print their absolute owned row endpoints and whether timing
hints matched, so a later timing refresh can recover their exact row ranges.

Large ray jobs are listed first, followed by large graph jobs, with the
existing proof-work ordering retained within the remaining jobs. This gives
the measured critical-path work an early queue preference; GitHub can still
choose a different execution order.

## Coverage checks

Partition controls cover heterogeneous costs, extreme skew, changed indexes,
equal-row fallback, nonempty ranges, missing/duplicate/out-of-range results,
exact planned row counts and sparse payload ownership. Planning reads indexes,
not proof, ray or graph payloads. The installed-wheel acceptance exercises the
balanced mode as well, including the packaged timing profile.

No test, proof, rank kernel, mathematical row, required gate or deadline is
removed or weakened by scheduling hints. Missing work cannot pass the gate.
