# Eval: claim_checker

| model | accuracy | false_supported | mean_latency_s | confusion |
|---|---|---|---|---|
| qwen25-7b | 0.75 | 0 | 0.29 | {'SUPPORTED->SUPPORTED': 15, 'SUPPORTED->UNSUPPORTED': 3, 'UNSUPPORTED->UNSUPPORTED': 15, 'PARTIAL->SUPPORTED': 4, 'PARTIAL->UNSUPPORTED': 2, 'UNSUPPORTED->PARTIAL': 1} |
| gpt-oss-20b | 1.0 | 0 | 0.64 | {'SUPPORTED->SUPPORTED': 18, 'UNSUPPORTED->UNSUPPORTED': 16, 'PARTIAL->PARTIAL': 6} |
