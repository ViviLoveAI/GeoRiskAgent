# V4 Transmission Context Schema Proposal

Diagnostic status: design only. This proposal is not connected to production
retrieval, transmission building, evidence grading, market mapping, ranking, or
CAR validation.

## Current Limitation

The current historical case schema is useful for retrieval and broad evidence
support, but it does not encode the role played by each supply-chain node in a
case. A case can list several `supply_chain_nodes`, while each node can play a
different causal role. The current representation therefore allows spurious
consensus:

```text
case A contains node X
case B contains node X
```

This does not necessarily mean:

```text
case A and case B support the same transmission mechanism for node X
```

The Rule-6 error audit showed two concrete failure modes:

- Weak misses: broad nodes such as `defense`, `marine_insurance`, and
  `maritime_chokepoint` can look compatible because supporting cases share
  broad asset types or domain context, even when the target node has a different
  transmission role.
- False rejections: `critical_minerals` cases can share a real input/control
  mechanism while using different event-type and affected-asset-type vocabulary
  such as rare earths, graphite, gallium, battery materials, and semiconductor
  inputs.

## Existing Historical Case Fields

Current `data/historical_cases.json` fields include:

- `event_id`
- `date`
- `event_name`
- `event_type`
- `regions`
- `countries`
- `industries`
- `supply_chain_nodes`
- `summary`
- `transmission_chain`
- `affected_asset_types`
- `affected_assets`
- `retrieval_text`
- `evidence_notes`

`transmission_chain` is currently a list of free-text steps. The historical KB
does not currently include `shock_direction`.

## Proposed Minimal Schema

Add an optional per-node field:

```json
{
  "transmission_contexts": [
    {
      "node": "critical_minerals",
      "shock_type": "export_restriction",
      "constraint_type": "input_access_restriction",
      "upstream_driver": "export_licensing_controls",
      "target_node_role": "upstream_input",
      "canonical_context": "critical_material_input_constraint"
    }
  ]
}
```

This is intentionally minimal. It is not a full causal ontology.

## Field Definitions

### node

Definition: The canonical supply-chain node whose role is being described.

Why needed: Context must attach to a specific node because one case can contain
many nodes with different roles.

Controlled vocabulary: Existing `supply_chain_node` vocabulary.

Required: Required inside each `transmission_contexts[]` entry.

### shock_type

Definition: The geopolitical or physical shock that initiates the chain.

Why needed: Helps distinguish superficially similar node co-occurrence caused
by different mechanisms.

Initial controlled vocabulary:

- `export_restriction`
- `import_restriction`
- `sanctions`
- `tariff`
- `military_escalation`
- `physical_disruption`
- `capacity_constraint`
- `cyber_disruption`
- `labor_disruption`
- `regulatory_restriction`
- `policy_uncertainty`

Required: Optional during migration, recommended for guardrail use.

### constraint_type

Definition: The economic or operational constraint through which the shock
propagates.

Why needed: Better captures mechanism compatibility than raw event type.

Initial controlled vocabulary:

- `route_disruption`
- `input_access_restriction`
- `input_shortage`
- `trade_access_restriction`
- `compliance_constraint`
- `insurance_constraint`
- `financing_constraint`
- `capacity_reduction`
- `cost_increase`
- `security_risk`
- `supplier_substitution`

Required: Optional during migration, recommended for guardrail use.

### upstream_driver

Definition: The immediate upstream factor that drives the target-node exposure.

Why needed: Helps distinguish whether the target node is causally active or
merely contextual.

Controlled vocabulary: Short canonical strings, expandable by review. Initial
examples:

- `export_licensing_controls`
- `customs_documentation_burden`
- `route_rerouting`
- `airspace_closure`
- `vessel_security_risk`
- `war_risk_insurance`
- `supplier_traceability_review`
- `program_participation_restriction`
- `facility_or_terminal_disruption`
- `critical_input_dependency`

Required: Optional.

### target_node_role

Definition: The role this node plays in the historical transmission chain.

Why needed: This is the most important field for broad-node guardrails. It
distinguishes causally active nodes from contextual background labels.

Initial controlled vocabulary:

- `direct_disruption_target`: The node itself is directly disrupted.
- `transmission_channel`: The node transmits the shock to other exposures.
- `upstream_input`: The node is an input dependency affected by the shock.
- `downstream_exposure`: The node is mainly an exposed downstream sector or
  asset category.
- `compliance_channel`: The node transmits legal, customs, sanctions, or
  documentation constraints.
- `financing_or_insurance_channel`: The node transmits financing, payment, or
  insurance constraints.
- `contextual_background`: The node appears in the case context but is not
  central to the mechanism.

Required: Recommended for any node used in second-order support.

### canonical_context

Definition: A compact canonical mechanism label for vocabulary normalization.

Why needed: Preserves raw labels while exposing shared mechanism context across
different asset-type strings.

Initial examples:

- `critical_material_input_constraint`
- `customs_compliance_constraint`
- `maritime_route_security_constraint`
- `energy_shipping_insurance_constraint`
- `semiconductor_input_access_constraint`
- `aerospace_defense_procurement_constraint`
- `airspace_route_disruption`

Required: Optional, useful for false-rejection reduction.

## Why Node-Level Context

Case-level context is insufficient because a single case can include multiple
nodes. For example, a maritime security case may include:

- `maritime_chokepoint` as the direct disruption target
- `marine_insurance` as a financing/insurance channel
- `logistics` as a downstream exposure
- `defense` as contextual background

Assigning one global mechanism to the whole case would over-credit every listed
node. V4 mechanism-compatible support should compare node-level context:

```text
current event/node
    vs
historical case/node context
```

not just:

```text
current event
    vs
historical case
```

## Controlled Vocabulary Notes

The vocabulary should preserve domain distinctions. In particular, do not
collapse battery, semiconductor, solar, EV, and rare-earth cases into one
industry. Instead, expose shared mechanism context while retaining raw labels:

```json
{
  "raw_affected_asset_type": "battery manufacturers",
  "canonical_context": "critical_material_input_constraint"
}
```

This lets the system recognize common exposure mechanisms without erasing
useful domain differences.

## Backward Compatibility

The new field should be optional:

```json
"transmission_contexts": []
```

Existing loaders can ignore it until the guardrail is implemented. No current
historical case fields should be removed or overwritten.

## Migration Strategy

1. Start with a small development subset: the historical cases involved in the
   10 Rule-6 error instances.
2. Manually curate `transmission_contexts` for those cases only.
3. Validate whether the structured context explains weak misses and false
   rejections better than current event-type / asset-type overlap.
4. Only after that, expand to a controlled batch of historical cases.
5. Do not rewrite `retrieval_text`, retrieval configuration, evidence labels,
   or ranking weights during this migration.

## Validation Plan

For a production-candidate guardrail, evaluate on development cases first:

- weak co-occurrence rejection
- non-weak retention
- historical-supported retention
- broad-node candidate reduction
- node-level stability across `defense`, `critical_minerals`, `energy`,
  `trade_lanes`, `maritime_chokepoint`, and related broad nodes

Then freeze the guardrail before creating a fresh untouched V4 held-out event
set. Do not use V1/V2/V3 or current diagnostic events as final generalization
evidence.
