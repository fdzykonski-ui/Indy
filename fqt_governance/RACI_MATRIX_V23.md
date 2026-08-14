# FQT Gate-Level RACI Matrix V2.3

`R` = responsible, `A` = accountable, `C` = consulted, `I` = informed.
The roles are logical review lenses coordinated by one project governor.

| Gate / process | Governor | Research | Strategy Eng. | Data Eng. | Validation | Execution | Statistics | QA/Red Team | Release |
|---|---|---|---|---|---|---|---|---|---|
| Contract/freeze | A | C | C | C | R | C | C | C | R |
| Source/data provenance | I | C | C | A/R | C | C | I | C | C |
| Static/metamorphic causality | A | C | R | C | R | I | C | C | I |
| Native lookahead | A | C | R | I | R | C | C | C | I |
| Champion callback causality | A | C | R | I | R | R | C | C | I |
| Recursive/startup convergence | A | C | R | C | R | I | C | C | I |
| Deterministic baseline | A | I | R | C | R | I | C | C | R |
| Funnel instrumentation | A | C | R | I | C | R | C | C | I |
| Execution realism/capacity | A | C | C | C | C | R | C | C | I |
| Challenger design | A | R | R | C | C | C | C | C | I |
| Nested walk-forward | A | C | C | C | R | C | R | C | I |
| Pair holdout/LOPO | A | C | C | R | R | C | R | C | I |
| Statistical decision | A | C | C | C | C | C | R | C | I |
| Final untouched OOS | A | I | I | R | R | C | R | C | I |
| Persistent dry-run | A | I | R | R | R | R | C | C | C |
| Independent review | I | C | C | C | C | C | C | A/R | I |
| Release/canary package | A | I | C | C | C | R | C | C | R |

## Decision separation

- The author of an alpha change cannot be the sole validation approver.
- The validator cannot silently modify alpha to make a gate pass.
- The release manager packages only evidence already accepted by the accountable
  gate owner.
- The project governor owns WIP and sequencing, not the statistical conclusion.
- QA/Red Team may reopen any gate when evidence is missing, ambiguous or
  non-reproducible.
