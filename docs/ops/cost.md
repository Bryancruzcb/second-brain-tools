# What this costs

The bill, how it is measured, and which lever moves it. Written in week 5;
the measured columns fill in as the months close.

## The shape of it

One node, running only while there is work to do, is the whole story. Nothing
else in this project has a knob big enough to matter at this size.

| What | How it is charged | Runs when |
|---|---|---|
| The node, one `m7i-flex.large` (`deploy/terraform/ec2.tf`) | per hour | only between `ops.py up` and `ops.py down` |
| Its 30 GB gp3 root volume | per GB-month | it is created and destroyed with the node |
| Its public IPv4 address | per hour | with the node. It has no inbound rules; it is there so the node can reach GHCR, S3 and SSM without a NAT gateway, which would cost more |
| The vault bucket and the state bucket (`deploy/terraform/s3.tf`) | per GB-month, plus requests | always. A few hundred notes |
| The deploys table (`deploy/terraform/dynamodb.tf`) | on demand, per request | one write per deploy |
| Cost Explorer | per API call | once a night, from `nightly-cost.yml` |
| SSM Run Command, Session Manager, Parameter Store standard parameters | no charge at this usage | — |

The node is destroyed between work sessions, so its hours are the only
number that moves much. Everything else is a few hundred megabytes of
storage and a handful of requests.

## The guardrails

- A `$15` monthly budget, created by hand before anything else and adopted by
  Terraform (`deploy/terraform/budget.tf`). It counts usage **before**
  credits, so it still says something while Free plan credits are paying.
- `nightly-cost.yml` checks every night whether a node is running and whether
  the `OPS_STATE` repo variable says one should be, and opens an issue when
  they disagree. A forgotten node is the one mistake here that runs for a
  month. It also records the month-to-date figure, which is where the
  measured column below comes from.
- `ops.py down` destroys the node rather than stopping it, so nothing is
  charged for a stopped instance's volume either. The cost of that choice is
  the index: it lives on the node's root disk, so the next `up` rebuilds it,
  about 22 minutes for 5,941 chunks (`deploy/k8s/README.md`).

## Measured

Month-to-date figures come from `nightly-cost.yml`, which reads unblended
cost from Cost Explorer. The account is on the AWS Free plan with credits, so
two numbers matter and they are not the same: what was **charged**, and what
the usage would have cost without credits, which is what the budget tracks.

| Month | Node hours | Usage, per the budget | Charged | Notes |
|---|---|---|---|---|
| September 2026 | not yet recorded | not yet recorded | not yet recorded | first month; weeks 1 to 4 built, the node ran only in short sessions |

Nothing is filled in yet on purpose: the first month has not closed, and a
guess here would be worth less than an empty cell. Fill a row from the AWS
Cost Explorer console (Billing and Cost Management, Cost Explorer, group by
service) once the month closes, and keep the node-hours column from the
deploy history and the nightly issues rather than from memory.

## What would change it

- Leaving the node up. It is the only per-hour charge here, and the nightly
  check exists because of it.
- A bigger node. `m7i-flex.large`'s two vCPUs are one physical core, which is
  why a full index build roughly doubles search latency
  (`deploy/monitoring/README.md`). The fix for that is a bigger instance, and
  it is a cost decision rather than a code one.
- Leaving the Free plan. It closes the account at six months or at the credit
  limit unless it is upgraded first (`docs/ops/PLAN.md`, section 7), so the
  end of the window is a date to watch, not a surprise to discover.
