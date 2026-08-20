# Agent evaluations

Representative cases for differentiation, evidence use, abstention, revision,
latency, and cost belong here.

`v1/consensus-baseline.json` is the first portable `EvaluationBundle`. It is
deterministic and provider-neutral: the model name and token prices are fixture
values, not claims about a live provider. Run it with:

~~~powershell
magi-eval tests/evals/v1/consensus-baseline.json --fail-on-threshold
~~~

M5d adds `v1/representative-outcomes.json`, a frozen synthetic acceptance
matrix exercised by `test_representative_suite.py`. It covers consensus,
cross-review revision, insufficient information, a missing perspective,
performance-budget failure, and fail-closed invalid citations. All cases are
synthetic and deterministic; live provider quality is evaluated separately by
the opt-in M5 acceptance test.
