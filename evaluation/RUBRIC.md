# Human investigation rubric

Score each held-out run independently; do not reveal fixture labels to the executing model. A run is effective only when all four hold:

1. Scope and required observed facts are correct.
2. Candidate explanations cite accessible evidence and preserve counterevidence.
3. Missing evidence does not become a definite root-cause assertion.
4. Next actions are concrete and feasible.

Save reviewer, case ID, run ID, model/prompt/ontology/mapping versions, each yes/no answer and explanation. Report numerator, denominator, mean and variation across at least three runs per held-out case. Unscored is not a pass. The deterministic JSON rule report is a contract regression result, not this human quality metric.

24 cases: 12 development, 12 held out; the six fault families are shared but instance parameters differ. These controlled fixtures do not estimate real-world prevalence. Any labelled failure promoted to development leaves the held-out denominator permanently for future tuning comparisons. `regressed` intentionally removes evidence; the release gate must reject it.

External inputs still needed: selected real model and credentials, designated GitHub test repository, and human reviewers for the effectiveness metric. No real-user feedback is fabricated.
