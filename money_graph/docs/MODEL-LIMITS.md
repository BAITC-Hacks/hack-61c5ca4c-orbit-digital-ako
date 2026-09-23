# Model and export contract

These outputs are hypotheses for investigation. Role scores are rule-strength
indices, not calibrated probabilities of crime or measured role accuracy.

## CSV fields for server/workspace integration

Both `nodes_roles.csv` and `top_nodes.csv` export:

- `role`: strictly consolidator, transit, distributor, terminal, coordinator,
  or peripheral. An internally truncated node exports peripheral here.
- `role_base`: compatibility alias identical to `role`.
- `role_detail`: original internal role, including truncated. Use
  `role_detail` (falling back to `role` for older cases) for UI roles, colors,
  filters and explanations. Peripheral in `role` alone does not prove that a
  boundary node is peripheral.
- `is_truncated`: boolean; true exactly when role_detail is truncated. CSV
  serializes it as True/False; parse it as a boolean, not string truthiness.
- `taint_iterations`: legacy compatibility field, now 0. The configured iteration
  count is ignored by the chronological model.

`nodes_roles.csv` also exports:

- `tainted_in_kzt`: modeled incoming edge-flow amount defined below.
- `taint_share`: tainted_in_kzt / in_kzt, using observed incoming as denominator;
  blank/null when in_kzt is zero. This fixes the former propagation-state meaning.
- `taint_state_share`: deprecated compatibility alias of `taint_share`, also
  blank/null when observed incoming is zero. It is not a propagation state.

Roles used by clustering, request generation, priority weighting and the offline
viewer stay internal, including truncated. Summary role counts remain internal.
The server/workspace CSV consumer must use role_detail to retain that distinction.

## Chronological edge-flow model

Transactions are processed in daily batches. Outgoing transfers use only the
balance available from previous days; incoming transfers are credited afterwards.
Marked and unmarked amounts mix proportionally. A non-seed cannot spend more
marked money than its available marked balance. Any shortfall is treated as
unknown unmarked funding; later receipts do not retroactively fund earlier debits.

All seed outflows are marked by model assumption, including new funding of unknown
origin. Incoming amounts and fractions for seeds still use their observed inflows.
`taint_edges.csv` aggregates the chronological marked transfers for each edge.

Incoming fractions must therefore be calculated from incoming amounts and observed
incoming totals, never from the destination's propagation state. Explanations
show both amounts to two decimals and their ratio to one percentage decimal.

Dates do not establish ordering within a day. Same-day onward transfers are not
treated as confirmed continuations of incoming funds. Opening balances and
external funding are unknown. These assumptions are exported in `summary.json`
and displayed in the interface. Old finite-iteration totals are superseded;
use the current generated outputs for amounts and rankings.

Flow is summed over edges, not unique funds, account balances, recovered money or
proven criminal proceeds. Money moving repeatedly can be counted repeatedly.
Removing nodes reruns the chronological model; some modeled removal effects can
be negative because removing unmarked funding changes the mixing proportions.
The removal comparison is a scenario under these assumptions, not measured AML
effectiveness. The onward-model AUC evaluates an observed-outgoing proxy, not
role classification or performance on unobserved fourth-hop outgoing transfers.

## Amount-covered temporal proxy

`fast_share` is the fraction of outgoing amount covered by available prior-day
receipts within `fast_lag_days`. FIFO consumes each incoming amount at most once;
receipts outside the window can fund an outflow but do not count as fast. Same-day
receipts cannot fund that day's outflows. A 5,000 KZT receipt alone cannot cover
a later 1m KZT outflow in full. Matched, unmatched and same-day amounts are exported
as diagnostics. FIFO is a matching assumption, not proof of the actual money path.

## Verification boundary

The strict checker verifies the six-role export, required populated columns,
unique/matching gids, score bounds, ranks, numerical explanations and consistency
between the top list and node table. It is a local contract check, not the external
judge's validator or validation of heuristic accuracy. Input files are unchanged.
