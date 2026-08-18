# V4 Mechanism Compatibility Freeze Candidate

Version: `mechanism_compatibility_candidate_v1`

Status: diagnostic freeze candidate. This specification is not connected to
production retrieval, historical-case loading, transmission building, evidence
grading, market mapping, ranking, or CAR validation.

## Purpose

This rule determines whether a historical case should count as a
mechanism-compatible support vote for a current event/node instance. It is
designed to avoid treating broad-node co-occurrence as evidence unless the node
plays a compatible role in a compatible transmission mechanism.

## Node-Level Context Schema

Each diagnostic node context has:

- `node`: canonical supply-chain node.
- `shock_type`: initiating geopolitical, policy, cyber, physical, or capacity
  shock.
- `constraint_type`: economic or operational propagation channel.
- `upstream_driver`: immediate upstream driver for the node exposure.
- `target_node_role`: node role in the transmission chain.
- `canonical_context`: compact mechanism label used for deterministic
  compatibility.

## Controlled Vocabulary

### Active Roles

- `direct_disruption_target`
- `transmission_channel`
- `upstream_input`
- `downstream_exposure`
- `downstream_strategic_exposure`
- `compliance_channel`
- `financing_or_insurance_channel`

### Non-Voting Roles

- `contextual_background`

Historical cases with `target_node_role = contextual_background` cannot count
as support votes. Current event/node contexts marked `contextual_background`
also cannot receive mechanism-compatible support.

### Canonical Context Families

`critical_material_constraint`

- `critical_material_input_constraint`
- `critical_material_compliance_constraint`
- `critical_material_cost_constraint`

`maritime_route_disruption`

- `maritime_route_capacity_constraint`
- `maritime_route_security_constraint`
- `oil_shipping_security_constraint`
- `energy_chokepoint_security_constraint`
- `energy_shipping_sanctions_route_constraint`

`strategic_technology_downstream_exposure`

- `semiconductor_input_access_constraint`
- `semiconductor_strategic_downstream_exposure`

## Compatibility Semantics

For a current event/node context and one historical case/node context:

1. If either context is missing required fields, return
   `insufficient_context`.
2. If either `target_node_role` is `contextual_background`, return
   `incompatible`.
3. If either role is outside the controlled active-role vocabulary, return
   `insufficient_context`.
4. If `canonical_context` is exactly equal, return `compatible`.
5. If both canonical contexts map to the same canonical family, return
   `compatible`.
6. If `constraint_type` is equal and both roles are active roles, return
   `compatible`.
7. Otherwise return `incompatible`.

## Support Threshold

A second-order node is support-qualified only when:

```text
mechanism_compatible_support_count >= 2
```

The threshold is diagnostic-only in this stage and must not be changed during
freeze-candidate validation.

## Insufficient Context Behavior

`insufficient_context` is neither accepted nor rejected as evidence of
mechanism compatibility. It is recorded as a representation-coverage gap. The
freeze candidate does not auto-accept insufficient context.

## Non-Goals

This freeze candidate does not:

- change production `top_k`
- migrate `data/historical_cases.json`
- alter retrieval
- alter Transmission Builder
- alter Evidence Agent
- alter Market Mapper
- alter Asset Ranker
- inspect CAR or market outcomes
- introduce weights, scores, thresholds, node blacklists, or LLM judging
