# DeepSeek Codex orchestrator

- Keep the DeepSeek API key outside this repository. The wrapper reads `DEEPSEEK_API_KEY` or `/home/hgff/api deepseek.txt` at runtime; never print or copy the value into reports, logs, tests, or commits.
- Treat `--dangerous` as an explicit per-run opt-in. It grants Codex full filesystem and command access.
- Keep generated tasks, reports, logs, sessions, and state out of Git.
- Maintain the one-controller lock and exact final `STATUS:` report contract.
- Do not retry a coding task automatically after an interrupted or failed run; it may have changed files already.
- Show token counts only when Codex reports usage. Label wallet percentage as relative to the locally recorded baseline, since the DeepSeek API does not provide a quota percentage.
- Keep the dated model prices and routing explanation current with the official DeepSeek pricing page; distinguish measured usage, estimated cost, and vendor quality claims.
- Run the tests in `tests/` and `bin/orchestrate doctor` before claiming runtime changes complete. A live API check is needed to verify provider access.
