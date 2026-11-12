# Case study: human-directed risk monitoring

## Scenario and goal

This is a **simulated customer scenario**, not a claim of a customer deployment.
An operations team at a mid-size importer needs to scan trade news for events
that could interrupt goods, capacity, or production. The goal is to help an
analyst find stories worth investigating and understand why they were ranked.
The analyst must verify the original reporting and decide what affects their
business; a score is not a verified fact or an instruction to act.

Success would mean the analyst can quickly identify relevant stories, inspect
the evidence, and avoid missing important interruptions. This is a proposed
outcome; review time and accuracy have not yet been measured with users.

The current pipeline fetches and normalizes RSS articles, scores title and
summary text with rules, and publishes a static dashboard with links and
explanations. A hybrid scorer is implemented but has not been tested against
the live API. See [architecture](architecture.md) and
[evaluation](evaluation.md) for implementation and evidence.

## Scope and trade-offs

| Need or constraint | Current approach | Trade-off |
|---|---|---|
| Review a changing stream of public news | Scheduled RSS ingestion and a static dashboard | Feed coverage and freshness depend on publishers and the schedule |
| Show why a story was ranked | Rule explanations and source links | Headline and summary may omit context; the article still needs checking |
| Keep the system usable without an AI service | Rules are the default; hybrid scoring is optional | The default is deterministic but has known false positives and misses |
| Make failures visible | Per-feed outcomes, validation and stale-data banner | A healthy pipeline does not prove that risk judgments are correct |

The [offline demo](../README.md#offline-demo) runs the same parser, scorer and
site builder on synthetic fixture articles. It is repeatable without live feeds
or credentials, but its placeholder links and examples are not real reporting.

## How AI assists development

The project owner sets the outcome and acceptance criteria. An AI coding
assistant can inspect the implementation, propose changes, implement scoped
fixes and run checks. The owner reviews the evidence, makes the decisions and
is accountable for the result. These are roles in a development workflow;
the production pipeline is not a multi-agent system.

For example, during the public-project review the owner requested a general
cleanup. The assistant identified and changed the following:

- A malformed article URL could interrupt feed parsing; it now skips that
  entry and retains valid entries. A regression test covers this case.
- A run with no enabled feeds could appear successful; it now fails explicitly.
- The dashboard could understate the age of stale data; its age calculation
  now includes time elapsed since the site was built.

The assistant ran the automated suite and lint checks. These are implementation
and verification records, not proof that a human reviewed each change or that
the system has achieved a customer outcome. The owner can inspect the changes
and decide whether to accept them.

### Review example: incomplete feed coverage

- **Owner's goal:** prepare a reviewable example of human-directed AI work and
  check whether users can recognize incomplete data-source coverage.
- **Assistant's finding:** the published status checked on 2026-11-11 showed a
  partial run with 8 of 9 feeds successful. Feed failures appeared in Pipeline
  status, but the top banner did not call attention to incomplete coverage.
- **Proposed change:** when the last *published* run is partial, show the
  successful-feed count and direct the reader to Pipeline status. Keep the
  detailed table as the source of per-feed information.
- **Assistant's verification:** the dashboard banner test executes the browser
  JavaScript for both partial and successful runs; the site tests check the
  generated status data. The change is available locally for owner review.
- **Decision still needed:** the owner should decide whether the warning and
  its wording make the completeness risk clear enough for the intended user.
  No owner approval or customer feedback is claimed here.

This is a static site: if a later scheduled run fails before publication, the
page cannot show that failure directly. Its age warning is the existing
backstop; the banner only describes the last published run.

## Evaluation and human review

The [labeling guide](labeling_guide.md) defines a blind review process. Human
labels and machine suggestions are separate; a human-labeled row must name its
labeler. The repository's 100-article set currently has no human labels, and
the existing test set was exposed during development. Its provisional metrics
are not accuracy claims. A later, independently labeled batch is needed for a
more credible comparison.

For a future evaluation, record the sample and selection method, reviewer,
labeling date, scorer version, per-class counts, precision and recall, and
examples of both false alarms and missed events. If comparing review time,
record the task, participants, sample size and method for both approaches;
do not infer a time saving before measuring it.

## Delivery boundaries

- The dashboard is an information and triage tool, not an automated operational
  decision maker. It does not currently save user review decisions.
- No customer interviews, measured business impact, or live LLM evaluation are
  claimed by this case study.
- The next meaningful milestone is independent human labeling and review of a
  fresh batch. Until then, performance claims remain provisional.
