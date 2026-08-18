# Post-V4 V5 Architecture Hypothesis

## Current V3/V4 Retrieval Objective

- query = whole event
- retrieval unit = historical case
- objective = overall event similarity

## V5 Hypothesis

- query = current shock / mechanism representation
- retrieval unit = (case_id, node, TransmissionContext)
- objective = retrieve mechanism-relevant transmission fragments

Core hypothesis: historical retrieval should participate in candidate-node
discovery by retrieving mechanism-level transmission fragments, rather than
only retrieving globally similar events and validating already-proposed nodes.

Status: V5 hypothesis only. NOT implemented. NOT evaluated. NOT used to alter
V3, V4, benchmark selection, or benchmark ground truth.
