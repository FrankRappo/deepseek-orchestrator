import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "orchestrate"
loader = importlib.machinery.SourceFileLoader("orchestrate", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
orchestrate = importlib.util.module_from_spec(spec)
loader.exec_module(orchestrate)


class OrchestrateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def make_task(self, name="T01_build.md"):
        task = self.project / "tasks" / name
        task.parent.mkdir(parents=True, exist_ok=True)
        task.write_text("Implement the requested change.\n", encoding="utf-8")
        return task

    def test_report_status_requires_exact_final_nonempty_line(self):
        report = self.project / "report.md"
        report.write_text("STATUS: SUCCESS\nmore text\n", encoding="utf-8")
        self.assertIsNone(orchestrate.report_status(report))
        report.write_text("done\n\nSTATUS: PARTIAL\n\n", encoding="utf-8")
        self.assertEqual(orchestrate.report_status(report), "PARTIAL")
        report.write_text("done\n**STATUS: SUCCESS**\n", encoding="utf-8")
        self.assertIsNone(orchestrate.report_status(report))
        report.write_text("done\n STATUS: SUCCESS \n", encoding="utf-8")
        self.assertIsNone(orchestrate.report_status(report))

    def test_run_task_synthesizes_blocked_report_and_metadata(self):
        task = self.make_task()

        class FakeProcess:
            pid = 4321

            def __init__(self, command, **kwargs):
                self.command = command

            def wait(self):
                return 17

        def fake_popen(command, **kwargs):
            self.assertIsInstance(command, list)
            self.assertIn("--prompt-file", command)
            self.assertNotIn("--dangerous", command)
            self.assertTrue(kwargs["start_new_session"])
            return FakeProcess(command, **kwargs)

        with mock.patch.object(orchestrate.subprocess, "Popen", side_effect=fake_popen):
            metadata = orchestrate.run_task(self.project, task, "deepseek-flash", False)

        report = self.project / "reports" / "report_T01_build.md"
        self.assertEqual(orchestrate.report_status(report), "BLOCKED")
        self.assertEqual(metadata["status"], "BLOCKED")
        saved = json.loads((self.project / "state/deepseek/tasks/T01_build.json").read_text())
        self.assertEqual(saved["returncode"], 17)
        self.assertEqual(saved["report"], str(report))

    def test_run_task_does_not_retry_or_replace_existing_worker_report(self):
        task = self.make_task()
        calls = []

        def fake_popen(command, **kwargs):
            calls.append(command)
            report = self.project / "reports" / "report_T01_build.md"
            report.write_text("completed\nSTATUS: SUCCESS\n", encoding="utf-8")
            return mock.Mock(pid=4322, wait=mock.Mock(return_value=0))

        with mock.patch.object(orchestrate.subprocess, "Popen", side_effect=fake_popen):
            metadata = orchestrate.run_task(self.project, task, "deepseek-v4-pro", True)

        self.assertEqual(len(calls), 1)
        self.assertIn("--dangerous", calls[0])
        self.assertEqual(metadata["status"], "SUCCESS")

    def test_manual_start_rejects_empty_task_queue(self):
        args = orchestrate.parser().parse_args(
            ["start", "--project", str(self.project), "--controller", "manual"]
        )
        with self.assertRaisesRegex(orchestrate.UserError, "requires prepared tasks"):
            orchestrate.cmd_start(args)

    def test_controller_model_is_independent_of_worker_model(self):
        goal = self.project / "GOAL.md"
        goal.write_text("Do a small task.\n", encoding="utf-8")
        args = orchestrate.parser().parse_args(
            ["start", "--project", str(self.project), "--controller", "deepseek",
             "--goal", str(goal), "--controller-model", "deepseek-v4-pro",
             "--model", "deepseek-flash", "--idle-exit"]
        )

        def fake_planner(project, goal_path, model, dangerous):
            self.assertEqual(model, "deepseek-v4-pro")
            self.make_task()

        with mock.patch.object(orchestrate, "preflight"), \
             mock.patch.object(orchestrate, "tmux_has", return_value=False), \
             mock.patch.object(orchestrate, "run_planner", side_effect=fake_planner), \
             mock.patch.object(orchestrate.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0)):
            self.assertEqual(orchestrate.cmd_start(args), 0)
        launch = json.loads((self.project / "orch/launch.json").read_text())
        self.assertEqual(launch["controller_model"], "deepseek-v4-pro")
        self.assertEqual(launch["model"], "deepseek-flash")

    def test_materialize_plan_accepts_json_and_rejects_unsafe_ids(self):
        output = self.project / "plan.md"
        output.write_text(
            '```json\n{"tasks":[{"id":"T01_safe","content":"Do it."}]}\n```\n',
            encoding="utf-8",
        )
        orchestrate.materialize_plan(output, self.project)
        self.assertEqual((self.project / "tasks/T01_safe.md").read_text(), "Do it.\n")
        output.write_text(
            '{"tasks":[{"id":"T02_../../escape","content":"bad"}]}', encoding="utf-8"
        )
        with self.assertRaisesRegex(orchestrate.UserError, "unsafe task id"):
            orchestrate.materialize_plan(output, self.project)

    def test_start_builds_argv_tmux_launch_and_writes_launch_json(self):
        task = self.make_task()
        args = orchestrate.parser().parse_args(
            ["start", "--project", str(self.project), "--controller", "codex",
             "--model", "deepseek-v4-pro", "--dangerous", "--idle-exit"]
        )
        completed = subprocess.CompletedProcess([], 0)
        with mock.patch.object(orchestrate, "preflight"), \
             mock.patch.object(orchestrate, "tmux_has", return_value=False), \
             mock.patch.object(orchestrate.subprocess, "run", return_value=completed) as run:
            self.assertEqual(orchestrate.cmd_start(args), 0)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["tmux", "new-session", "-d"])
        self.assertIn("--dangerous", command)
        self.assertIn("--idle-exit", command)
        launch = json.loads((self.project / "orch/launch.json").read_text())
        self.assertEqual(launch["tasks"], [task.stem])
        self.assertEqual(launch["model"], "deepseek-v4-pro")

    def test_task_discovery_is_sorted_and_rejects_symlink_escape(self):
        self.make_task("T10_last.md")
        self.make_task("T02_first.md")
        outside = self.project / "outside.md"
        outside.write_text("outside", encoding="utf-8")
        (self.project / "tasks" / "T03_escape.md").symlink_to(outside)
        self.assertEqual(
            [path.name for path in orchestrate.task_files(self.project)],
            ["T02_first.md", "T10_last.md"],
        )

    def test_idle_queue_runs_each_task_once_and_marks_all_done(self):
        task = self.make_task()
        task.write_text("Model: deepseek-v4-pro\n\nRun it.\n", encoding="utf-8")
        runs = []

        def fake_task(project, task, model, dangerous, selection_reason=None):
            runs.append((task.stem, model))
            metadata_path = project / "state/deepseek/tasks" / f"{task.stem}.json"
            orchestrate.atomic_json(metadata_path, {"status": "SUCCESS"})
            return {"status": "SUCCESS"}

        with mock.patch.object(orchestrate, "run_task", side_effect=fake_task):
            self.assertEqual(
                orchestrate.queue_run(
                    self.project, "manual", "deepseek-flash", "economy", False, True
                ),
                0,
            )
        self.assertEqual(runs, [("T01_build", "deepseek-v4-pro")])
        self.assertTrue((self.project / "reports/ALL_DONE").is_file())

    def test_nonzero_worker_exit_overrides_success_report(self):
        task = self.make_task()

        def fake_popen(command, **kwargs):
            report = self.project / "reports/report_T01_build.md"
            report.write_text("claimed success\nSTATUS: SUCCESS\n", encoding="utf-8")
            return mock.Mock(pid=5000, wait=mock.Mock(return_value=9))

        with mock.patch.object(orchestrate.subprocess, "Popen", side_effect=fake_popen):
            metadata = orchestrate.run_task(self.project, task, "deepseek-flash", False)
        self.assertEqual(metadata["status"], "FAIL")
        self.assertEqual(orchestrate.report_status(self.project / "reports/report_T01_build.md"), "FAIL")

    def test_stop_terminates_active_worker_process_group(self):
        args = orchestrate.parser().parse_args(["stop", "--project", str(self.project)])
        completed = subprocess.CompletedProcess([], 0)
        with mock.patch.object(orchestrate, "worker_groups", return_value=[4321]), \
             mock.patch.object(orchestrate.os, "killpg") as killpg, \
             mock.patch.object(orchestrate.time, "sleep"), \
             mock.patch.object(orchestrate.subprocess, "run", return_value=completed):
            orchestrate.cmd_stop(args)
        self.assertEqual(
            killpg.call_args_list,
            [mock.call(4321, orchestrate.signal.SIGTERM), mock.call(4321, orchestrate.signal.SIGKILL)],
        )

    def test_preflight_checks_worker_without_exposing_output(self):
        worker = self.project / "deepseek"
        worker.write_text("#!/bin/sh\n", encoding="utf-8")
        worker.chmod(0o700)
        completed = subprocess.CompletedProcess([], 0)
        with mock.patch.object(orchestrate, "WORKER", worker), \
             mock.patch.object(orchestrate.shutil, "which", return_value="/usr/bin/tmux"), \
             mock.patch.object(orchestrate.subprocess, "run", return_value=completed) as run:
            orchestrate.preflight()
        self.assertEqual(run.call_args.args[0], [str(worker), "--check"])
        self.assertIs(run.call_args.kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(run.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_task_model_metadata_overrides_default(self):
        task = self.make_task()
        task.write_text("Model: deepseek-v4-pro\n\nDo the complex task.\n", encoding="utf-8")
        self.assertEqual(orchestrate.task_model(task, "deepseek-flash"), "deepseek-v4-pro")
        task.write_text("Model: auto\n", encoding="utf-8")
        self.assertEqual(orchestrate.task_model(task, "deepseek-flash"), "deepseek-flash")
        task.write_text("Model: imaginary\n", encoding="utf-8")
        with self.assertRaises(orchestrate.UserError):
            orchestrate.task_model(task, "deepseek-flash")

    def test_auto_model_routing_modes_are_deterministic(self):
        task = self.make_task()
        task.write_text("Model: auto\nComplexity: high\n", encoding="utf-8")
        self.assertEqual(orchestrate.task_model(task, "auto", "economy"), "deepseek-flash")
        self.assertEqual(orchestrate.task_model(task, "auto", "balanced"), "deepseek-v4-pro")
        self.assertEqual(orchestrate.task_model(task, "auto", "quality"), "deepseek-v4-pro")
        task.write_text("Model: auto\nComplexity: medium\n", encoding="utf-8")
        self.assertEqual(orchestrate.task_model(task, "auto", "balanced"), "deepseek-flash")
        self.assertEqual(orchestrate.task_model(task, "auto", "quality"), "deepseek-v4-pro")
        task.write_text("Model: auto\n", encoding="utf-8")
        selected, reason = orchestrate.task_selection(task, "auto", "economy")
        self.assertEqual(selected, "deepseek-flash")
        self.assertIn("missing Complexity", reason)
        self.assertEqual(orchestrate.task_model(task, "auto", "quality"), "deepseek-flash")

    def test_explicit_model_precedence_and_invalid_complexity(self):
        task = self.make_task()
        task.write_text("Model: deepseek-flash\nComplexity: high\n", encoding="utf-8")
        selected, reason = orchestrate.task_selection(task, "deepseek-v4-pro", "quality")
        self.assertEqual(selected, "deepseek-flash")
        self.assertIn("task Model", reason)
        task.write_text("Model: auto\nComplexity: high\n", encoding="utf-8")
        selected, reason = orchestrate.task_selection(task, "deepseek-flash", "quality")
        self.assertEqual(selected, "deepseek-flash")
        self.assertIn("CLI --model", reason)
        task.write_text("Model: deepseek-flash\nComplexity: enormous\n", encoding="utf-8")
        with self.assertRaisesRegex(orchestrate.UserError, "unsupported Complexity"):
            orchestrate.task_selection(task, "auto", "economy")
        task.write_text("Model: auto\nComplexity: very high\n", encoding="utf-8")
        with self.assertRaisesRegex(orchestrate.UserError, "malformed Complexity"):
            orchestrate.task_selection(task, "auto", "economy")
        task.write_text("Model: auto\nModel: deepseek-flash\n", encoding="utf-8")
        with self.assertRaisesRegex(orchestrate.UserError, "duplicate Model"):
            orchestrate.task_selection(task, "auto", "economy")

    def test_auto_controller_model_depends_on_routing(self):
        goal = self.project / "GOAL.md"
        goal.write_text("Plan it.\n", encoding="utf-8")
        for routing, expected in (("economy", "deepseek-flash"),
                                  ("balanced", "deepseek-v4-pro"),
                                  ("quality", "deepseek-v4-pro")):
            with self.subTest(routing=routing):
                project = self.project / routing
                project.mkdir()
                local_goal = project / "GOAL.md"
                local_goal.write_text(goal.read_text(), encoding="utf-8")
                args = orchestrate.parser().parse_args([
                    "start", "--project", str(project), "--controller", "deepseek",
                    "--goal", str(local_goal), "--model", "auto", "--routing", routing,
                ])

                def fake_planner(proj, goal_path, model, dangerous):
                    self.assertEqual(model, expected)
                    task = proj / "tasks/T01_plan.md"
                    task.parent.mkdir(parents=True, exist_ok=True)
                    task.write_text("Model: auto\nComplexity: low\n", encoding="utf-8")

                with mock.patch.object(orchestrate, "preflight"), \
                     mock.patch.object(orchestrate, "tmux_has", return_value=False), \
                     mock.patch.object(orchestrate, "run_planner", side_effect=fake_planner), \
                     mock.patch.object(orchestrate.subprocess, "run",
                                       return_value=subprocess.CompletedProcess([], 0)):
                    self.assertEqual(orchestrate.cmd_start(args), 0)
                launch = json.loads((project / "orch/launch.json").read_text())
                self.assertEqual(launch["controller_model"], expected)
                self.assertEqual(launch["routing"], routing)

    def test_usage_uses_only_valid_turn_completed_events(self):
        log = self.project / "logs/T01.log"
        log.parent.mkdir(parents=True)
        log.write_text(
            "warning that is not json\n"
            '{"type":"item.completed","usage":{"input_tokens":999}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":40,"output_tokens":25}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":10,"cached_input_tokens":0,"output_tokens":5}}\n',
            encoding="utf-8",
        )
        record = orchestrate.record_usage(
            self.project, "T01", "deepseek-flash", log
        )
        self.assertEqual(record["input_tokens"], 110)
        self.assertEqual(record["cached_input_tokens"], 40)
        self.assertEqual(record["output_tokens"], 30)
        self.assertEqual(record["total_tokens"], 140)
        self.assertNotIn("usage", record)
        summary = orchestrate.usage_summary(self.project)
        self.assertEqual(summary["records"], 1)
        self.assertEqual(summary["models"]["deepseek-flash"]["total_tokens"], 140)

    def test_usage_does_not_create_record_without_real_token_event(self):
        log = self.project / "worker.log"
        log.write_text('{"type":"turn.completed","usage":{}}\nsecret warning\n', encoding="utf-8")
        self.assertIsNone(orchestrate.record_usage(
            self.project, "T01", "deepseek-flash", log
        ))
        self.assertFalse((self.project / "logs/deepseek_usage.jsonl").exists())
        summary = orchestrate.usage_summary(self.project)
        self.assertFalse(summary["usage_available"])
        self.assertIsNone(summary["totals"])

    def test_usage_supports_last_rollout_token_count_fixture(self):
        log = self.project / "worker.log"
        event = {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": {
                    "input_tokens": 23791,
                    "cached_input_tokens": 3456,
                    "output_tokens": 519,
                    "reasoning_output_tokens": 361,
                    "total_tokens": 24310,
                }},
                "rate_limits": {"primary": {"used_percent": 99}},
            },
        }
        log.write_text(json.dumps(event) + "\n", encoding="utf-8")
        usage = orchestrate.token_usage(log)
        self.assertEqual(usage["input_tokens"], 23791)
        self.assertEqual(usage["total_tokens"], 24310)
        self.assertNotIn("rate_limits", usage)

    def test_usage_cost_is_decimal_snapshot_estimate_range(self):
        ledger = self.project / "logs/deepseek_usage.jsonl"
        ledger.parent.mkdir(parents=True)
        record = {
            "schema_version": 1,
            "task_id": "T01_cost",
            "provider": "deepseek",
            "model": "deepseek-flash",
            "completed_at": 0,
            "input_tokens": 1_000_000,
            "cached_input_tokens": 250_000,
            "output_tokens": 100_000,
            "total_tokens": 1_100_000,
            "turns": 1,
        }
        ledger.write_text(json.dumps(record) + "\n", encoding="utf-8")
        summary = orchestrate.usage_summary(self.project)
        self.assertEqual(summary["estimated_cost_usd"]["offpeak_usd"], "0.17325")
        self.assertEqual(summary["estimated_cost_usd"]["peak_usd"], "0.3465")
        self.assertIn("not actual bill", summary["estimated_cost_usd"]["label"])

    def test_models_output_has_prices_limits_policy_and_unknown_history(self):
        args = orchestrate.parser().parse_args(["models", "--project", str(self.project), "--json"])
        with mock.patch("builtins.print") as output:
            self.assertEqual(orchestrate.cmd_models(args), 0)
        payload = json.loads(output.call_args.args[0])
        self.assertEqual(set(payload["models"]), orchestrate.MODELS)
        self.assertEqual(payload["pricing_snapshot"]["date"], "2026-09-24")
        self.assertEqual(payload["routing"]["default"], "economy")
        for details in payload["models"].values():
            self.assertEqual(details["context_window_tokens"], 1048576)
            self.assertEqual(details["max_output_tokens"], 393216)
            self.assertIsNone(details["historical_usage"])

    def test_models_history_averages_only_actual_task_records(self):
        ledger = self.project / "logs/deepseek_usage.jsonl"
        ledger.parent.mkdir(parents=True)
        base = {"model": "deepseek-flash", "input_tokens": 10,
                "cached_input_tokens": 2, "output_tokens": 5,
                "total_tokens": 15}
        rows = [
            {**base, "task_id": "controller"},
            {**base, "task_id": "T01_one"},
            {**base, "task_id": "T02_two", "input_tokens": 30, "total_tokens": 35},
            {**base, "task_id": "../../escape"},
        ]
        ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        reports = self.project / "reports"
        reports.mkdir()
        (reports / "report_T01_one.md").write_text("done\nSTATUS: SUCCESS\n", encoding="utf-8")
        (reports / "report_T02_two.md").write_text("done\nSTATUS: SUCCESS\n", encoding="utf-8")
        history = orchestrate.model_history(self.project)
        self.assertEqual(history["deepseek-flash"]["completed_tasks"], 2)
        self.assertEqual(history["deepseek-flash"]["average_tokens"]["input_tokens"], "20")
        self.assertIsNone(history["deepseek-v4-pro"])


if __name__ == "__main__":
    unittest.main()
