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
- `taint_iterations`: configured propagation horizon.

`nodes_roles.csv` also exports:

- `tainted_in_kzt`: modeled incoming edge-flow amount defined below.
- `taint_share`: tainted_in_kzt / in_kzt, using observed incoming as denominator;
  blank/null when in_kzt is zero. This fixes the former propagation-state meaning.
- `taint_state_share`: propagation state after H updates. Seed states are forced
  to 1; this is not the fraction of observed incoming funds traced to seeds.

Roles used by clustering, request generation, priority weighting and the offline
viewer stay internal, including truncated. Summary role counts remain internal.
The server/workspace CSV consumer must use role_detail to retain that distinction.

## Finite-step edge-flow model

The existing algorithm is retained. Start with seed state 1 and other states 0.
Perform H updates from `config.json` taint_iterations (currently 8), forcing seed
state to 1 after each update. Then define each modeled edge flow as its observed
amount times its source's state after H updates. Incoming amount is the sum of
these same final edge flows entering the node; total flow is their sum.

Incoming fractions must therefore be calculated from incoming amounts and observed
incoming totals, never from the destination's propagation state. Explanations
show both amounts to two decimals and their ratio to one percentage decimal.

This is a finite-horizon estimate, without a convergence guarantee. A diagnostic
on the supplied data gave about 253.1m KZT at H=8 and 310.6m at H=16. Changes to
H may change scores, rankings and removal effects. H is exported in the summary
and both node CSVs; these diagnostics do not establish a preferred horizon.

Flow is summed over edges, not unique funds, account balances, recovered money or
proven criminal proceeds. Money moving repeatedly can be counted repeatedly.
Aggregation ignores transaction chronology and opening balances. Removing nodes
recomputes mixing denominators; some modeled removal effects can be negative.
The removal comparison is a scenario under these assumptions, not measured AML
effectiveness. The onward-model AUC evaluates an observed-outgoing proxy, not
role classification or performance on unobserved fourth-hop outgoing transfers.

## Temporal proxy

fast_share is the share of outgoing amount with any preceding incoming date no
more than fast_lag_days earlier. It does not allocate incoming amounts to outgoing
transactions. A 5,000 KZT incoming transfer can therefore precede 1m KZT outgoing
and yield fast_share=1. Dates without timestamps cannot establish ordering within
the same day. Treat this as date proximity, not proof of forwarded funds.

## Verification boundary

The strict checker verifies the six-role export, required populated columns,
unique/matching gids, score bounds, ranks, numerical explanations and consistency
between the top list and node table. It is a local contract check, not the external
judge's validator or validation of heuristic accuracy. Input files are unchanged.
