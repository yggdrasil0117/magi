# Agent evaluations

Representative cases for differentiation, evidence use, abstention, revision,
latency, and cost belong here.

`v1/consensus-baseline.json` is the first portable `EvaluationBundle`. It is
deterministic and provider-neutral: the model name and token prices are fixture
values, not claims about a live provider. Run it with:

~~~powershell
magi-eval tests/evals/v1/consensus-baseline.json --fail-on-threshold
~~~
