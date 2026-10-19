# GitHub development admission

Own applications use feature/fix -> develop -> release -> main. A selective
release can start at a historical feature commit accepted by a real develop PR;
its complete head must remain reachable from develop. This preserves unfinished
work on develop without manufacturing ancestry or merging unapproved features.
External forks use their maintained dinext/main/<line> branch through a reviewed PR.

Dinext policy runs pinned trusted code without executing the PR. The trusted
registry, not a proposed gitflow flag, selects the route and validation profile.
Every maintained line requires its applicable validation and policy status.

An interface change needs an executed successful GitHub Actions check named
`Cypress acceptance`; a runtime change to an external fork also needs
`Compatibility acceptance`. Evidence must belong to the exact current PR head
or test-merge SHA; skipped checks and other revisions do not qualify. Run these
checks in a read-only `Dinext acceptance` workflow or add applicable jobs to
`Dinext validation`. Policy refreshes when either workflow completes. Include
the repeatable test command, fixtures, JUnit output and artifact in that job;
one tested browser scenario per specified user scenario. CI/docs-only changes
do not require browser checks. Validation jobs receive no production secrets.

Before a future release, use the pinned shared `.github/ci/prepare_release.py`
with repository, stable branch, exact SHA, proposed tag and output path. It is
read-only: it validates version/CI and writes a preparation record. Creating a
tag or Release requires the owner's separate publishing decision and reviewed
release notes, compatibility evidence and manifest. Existing tags are immutable.

Deployment, publishing, paid agents, live smoke and external notifications remain
disabled. Imported upstream workflows remain under imported-workflows-disabled.

## DocType Permission compatibility

`Dinext acceptance` runs `Compatibility acceptance` for maintained-line PRs and
pushes. It checks out the current PR test-merge revision and builds an isolated
Frappe/ERPNext/HRMS 15 bench using pinned public dependency commits. Synthetic
Employee fixtures provide the baseline required by inherited permission tests.
All application tests run, including additional tests proposed in the PR.

The normal repository validation profile remains unchanged. Compatibility uses
temporary runner-only configuration; no deployment secrets or production sites
are used. Empty, missing, skipped or unsuccessful JUnit results fail acceptance.
The `compatibility-results` artifact retains JUnit and tested revision/dependency
provenance for 14 days. Completion refreshes the existing trusted integration
policy; old checks cannot qualify a different PR head or test-merge revision.

Company-managed fork branches use exactly one `dinext/` prefix, including integration, vendor and task branches. External contributors may keep names such as `patch-1` in their own fork. Future authorized release tags use `dinext/<upstream-tag>` or `dinext/<upstream-tag>-dinext.N`; application and upstream versions remain unchanged. Historical unprefixed tags remain immutable. No release or deployment is published by this reference-name transition.
