# Eval: claim_checker

| model | accuracy | false_supported | false_supported_incl_partial | false_supported_rate | mean_latency_s | confusion |
|---|---|---|---|---|---|---|
| qwen3-32b | 0.85 | 0 | 2 | 0.091 | 2.55 | {'SUPPORTED->SUPPORTED': 16, 'SUPPORTED->PARTIAL': 1, 'UNSUPPORTED->UNSUPPORTED': 16, 'PARTIAL->SUPPORTED': 2, 'PARTIAL->PARTIAL': 2, 'PARTIAL->UNSUPPORTED': 2, 'SUPPORTED->UNSUPPORTED': 1} |
