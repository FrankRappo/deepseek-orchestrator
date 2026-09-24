from decimal import Decimal
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "bin" / "balance"
loader = importlib.machinery.SourceFileLoader("deepseek_balance", str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
balance = importlib.util.module_from_spec(spec)
loader.exec_module(balance)


class BalanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.baseline = Path(self.temp.name) / "state" / "balance_baseline.json"
        patcher = mock.patch.object(balance, "BASELINE_PATH", self.baseline)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_percent_uses_recorded_balance_per_currency(self):
        balance.write_baseline({"USD": Decimal("20.00"), "CNY": Decimal("100.00")})
        current = {"USD": Decimal("5.00"), "CNY": Decimal("75.00")}
        result = balance.report({"is_available": True}, current, balance.read_baseline())
        by_currency = {item["currency"]: item for item in result["balances"]}
        self.assertEqual(by_currency["USD"]["remaining_percent_of_baseline"], "25.00")
        self.assertEqual(by_currency["CNY"]["remaining_percent_of_baseline"], "75.00")
        self.assertEqual(self.baseline.stat().st_mode & 0o777, 0o600)

    def test_top_up_is_visible_above_100_percent(self):
        result = balance.report({"is_available": True}, {"USD": Decimal("12")},
                                {"USD": Decimal("10")})
        self.assertEqual(result["balances"][0]["remaining_percent_of_baseline"], "120.00")

    def test_rejects_invalid_amount_and_duplicate_currency(self):
        with self.assertRaises(balance.BalanceError):
            balance.amounts({"balance_infos": [{"currency": "USD", "total_balance": "NaN"}]})
        with self.assertRaises(balance.BalanceError):
            balance.amounts({"balance_infos": [
                {"currency": "USD", "total_balance": "1"},
                {"currency": "USD", "total_balance": "2"},
            ]})

    def test_first_snapshot_becomes_explicit_baseline(self):
        payload = {"is_available": True, "balance_infos": [
            {"currency": "USD", "total_balance": "12.34"},
        ]}
        with mock.patch.object(balance, "api_key", return_value="sk-test"), \
             mock.patch.object(balance, "fetch_balance", return_value=payload), \
             mock.patch("builtins.print") as print_mock:
            self.assertEqual(balance.main(["--json"]), 0)
        result = json.loads(print_mock.call_args.args[0])
        self.assertEqual(result["balances"][0]["remaining_percent_of_baseline"], "100.00")
        self.assertEqual(balance.read_baseline(), {"USD": Decimal("12.34")})


if __name__ == "__main__":
    unittest.main()
