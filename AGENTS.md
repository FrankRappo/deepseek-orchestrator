# DeepSeek Codex orchestrator

- Owner standing authorization, 24.10.2026: launch authorized coding work through the ordinary framework with broad CLI permissions. Always pass `--dangerous` to `bin/deepseek` or `bin/orchestrate start`; do not ask for the same launch permission again.
- Do not add custom users, profiles, Landlock/bubblewrap/container layers, restrictive launch hooks, or overrides of `DEEPSEEK_CODEX_BIN` / `DEEPSEEK_CODEX_HOME`. Use the framework's existing provider configuration and standard launch commands. Extra launcher isolation caused repeated startup failures on 24.10.2026.
- When the owner says access is ready, start the assigned task without preliminary `--check`, `doctor`, `balance`, or provider-access probes. Diagnose a concrete startup error when one occurs. Confirm a real model response and successful task command before reporting that the agent is working; a queued tmux session is insufficient.
- All application runtimes, tests, databases, fixtures, dependency installs, builds and browser QA run only on the authorized VPS. WSL/Windows are thin control clients for orchestration, permitted source/Git work and small reports. Keep SQL data, dumps, backups, large archives and build artifacts on the VPS; never use a local stand as a fallback. Every task records the VPS target and remote source/artifact paths. Preserve shared sessions; never stop WSL or the host without explicit authorization for that exact action.
- Keep the DeepSeek API key outside this repository. The wrapper reads `DEEPSEEK_API_KEY` or `/home/hgff/api deepseek.txt` at runtime; never print or copy the value into reports, logs, tests, or commits.
- Broad CLI permissions do not expand task scope: preserve unrelated files and the owner's production, data and service-change restrictions.
- Keep generated tasks, reports, logs, sessions, and state out of Git.
- Maintain the one-controller lock and exact final `STATUS:` report contract.
- Do not retry a coding task automatically after an interrupted or failed run; it may have changed files already.
- Show token counts only when Codex reports usage. Label wallet percentage as relative to the locally recorded baseline, since the DeepSeek API does not provide a quota percentage.
- Keep the dated model prices and routing explanation current with the official DeepSeek pricing page; distinguish measured usage, estimated cost, and vendor quality claims.
- For changes to the framework runtime itself, run its required tests and runtime verification on the VPS before claiming completion. This is not a prerequisite for ordinary task launches or documentation-only edits.
