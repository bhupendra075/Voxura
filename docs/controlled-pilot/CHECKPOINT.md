# Work-Window Checkpoint Contract

Update a new checkpoint outside source control at the end of every work window. Never include secrets, PHI, tokens, or downloaded patient data.

```yaml
timestamp_utc: ""
release_gate: ""
git_commit: ""
working_tree_changes: []
completed_acceptance_criteria: []
test_evidence: []
failures: []
running_services: []
file_ownership: []
next_three_tasks: []
blockers_and_required_approvals: []
safety_status: "GO | NO-GO | FEATURE-DISABLED"
```

On resume: inspect this checkpoint, Git status, attached worktrees, running services, and test evidence before changing files. Do not redo completed work, discard local changes, deploy, use PHI, accept licenses, or weaken a release gate unattended.
