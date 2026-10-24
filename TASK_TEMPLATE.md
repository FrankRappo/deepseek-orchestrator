# T01_short_name — task title

Model: auto
Complexity: medium

## Objective

Describe one observable result.

## Scope

- Allowed files:
- Constraints:
- VPS target, remote application path and remote artifact/backup paths:
- Application execution, SQL, tests, dependencies and builds only on that VPS; no local fallback.
- Standard framework launch with `--dangerous`; no custom restrictive launcher, UID or profile layers. Do not run preliminary access probes when access is already confirmed by the owner.

## Acceptance

- [ ] Expected behavior is present.
- [ ] Targeted verification passes.

## Verification commands

```bash
# Add commands for this project.
```

## Report

The worker writes `reports/report_T01_short_name.md` and ends it with exactly one
of `STATUS: SUCCESS`, `STATUS: FAIL`, `STATUS: BLOCKED`, or `STATUS: PARTIAL`.
