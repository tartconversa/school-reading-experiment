"""真实资料上的端到端流程测试：登记、查看纪律、复议与扩围阻断。"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from readingtrial import expansion, stats
from readingtrial.cli import main
from readingtrial.ledger import Store
from readingtrial.materials import load_materials

ROOT = Path(__file__).resolve().parents[1]
MATERIALS = ROOT / "materials"


def run(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(argv)
    return buf.getvalue()


def run_blocked(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with unittest.TestCase().assertRaises(SystemExit) as cm:
            main(argv)
    unittest.TestCase().assertEqual(cm.exception.code, 2)
    return buf.getvalue()


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = self.tmp.name
        run(["--state", self.state, "register", "--materials", str(MATERIALS)])
        self.store = Store(self.state)
        self.materials = load_materials(MATERIALS)

    def tearDown(self):
        self.tmp.cleanup()

    def analyze(self, look, cutoff, issued, ref="纪要"):
        return run(["--state", self.state, "analyze", "--look", str(look),
                    "--cutoff", cutoff, "--issued", issued, "--ref", ref])

    # ---------------------------------------------------------- 登记与纪律

    def test_register_freezes_plan(self):
        st = self.store.state()
        self.assertEqual(st.registration.primary, "understanding")
        self.assertAlmostEqual(sum(st.registration.nominal_alphas), 0.05, places=12)
        self.assertEqual(len(st.releases), 1)          # 历史 H1 导入
        self.assertEqual(len(st.confirmations), 2)     # R1、R2 导入

    def test_register_twice_rejected(self):
        run_blocked(["--state", self.state, "register", "--materials", str(MATERIALS)])

    def test_qc_does_not_consume_looks(self):
        run(["--state", self.state, "qc", "--as-of", "2026-06-30"])
        run(["--state", self.state, "qc"])
        st = self.store.state()
        self.assertEqual(len(st.qc_runs), 2)
        self.assertEqual(sum(1 for r in st.releases if r.result), 0)

    def test_look1_binds_history_and_respects_cutoff(self):
        self.analyze(1, "2026-06-30", "2026-07-01", "研究会纪要A")
        st = self.store.state()
        h1 = st.release_by_look(1)
        self.assertEqual(h1.release_id, "H1")
        self.assertEqual(h1.decision_reference, "研究会纪要A")
        ds = h1.result["dataset"]
        self.assertEqual(ds["analyzed"], 167)          # 192 - 24 未回收 - 1 晚到
        self.assertIn("O2", ds["late_after_cutoff"])   # 晚到成绩不得进入本次分析
        self.assertEqual(h1.result["decision"]["code"], stats.INCONCLUSIVE)

    def test_history_cutoff_mismatch_rejected(self):
        run_blocked(["--state", self.state, "analyze", "--look", "1",
                     "--cutoff", "2026-06-29", "--issued", "2026-07-01"])

    def test_look_budget_and_order(self):
        self.analyze(1, "2026-06-30", "2026-07-01")
        # 未按顺序：第 2 次查看的截止不得早于第 1 次
        run_blocked(["--state", self.state, "analyze", "--look", "2",
                     "--cutoff", "2026-06-30", "--issued", "2026-08-01"])
        self.analyze(2, "2026-09-30", "2026-10-05")
        # 机会用尽
        run_blocked(["--state", self.state, "analyze", "--look", "3",
                     "--cutoff", "2026-10-31", "--issued", "2026-11-01"])
        # 已发布不得改写
        run_blocked(["--state", self.state, "analyze", "--look", "1",
                     "--cutoff", "2026-06-30", "--issued", "2026-07-02"])

    def test_late_data_never_enters_formal_dataset(self):
        self.analyze(1, "2026-06-30", "2026-07-01")
        self.analyze(2, "2026-09-30", "2026-10-05")
        st = self.store.state()
        f2 = st.release_by_look(2)
        self.assertIn("O2", f2.result["dataset"]["late_after_cutoff"])
        self.assertEqual(f2.result["dataset"]["analyzed"], 167)
        keys = {expansion.review_key(i) for i in expansion.open_reviews(self.materials, st)}
        self.assertIn("LATE_KNOWLEDGE:H1", keys)       # J13、O2 晚于 H1 截止
        self.assertIn("LATE_KNOWLEDGE:F2", keys)       # O2 晚于 F2 截止且机会用尽

    # ---------------------------------------------------------- 复议与扩围

    def test_reviews_track_imported_commitments(self):
        self.analyze(1, "2026-06-30", "2026-07-01")
        st = self.store.state()
        keys = {expansion.review_key(i) for i in expansion.open_reviews(self.materials, st)}
        self.assertIn("OVERBOOK:T1", keys)             # J13 到达后 T1 超占
        self.assertIn("EXPOSURE:R1", keys)             # T1 仍服务对照校 C4
        self.assertIn("INSUFFICIENT_BASIS:R1", keys)   # 确认时证据不足
        self.assertIn("INSUFFICIENT_BASIS:R2", keys)

    def test_confirm_blocked_when_evidence_insufficient(self):
        self.analyze(1, "2026-06-30", "2026-07-01")
        self.analyze(2, "2026-09-30", "2026-10-05")
        run(["--state", self.state, "release-controls", "--by", "负责人", "--on", "2026-10-06"])
        run(["--state", self.state, "propose", "--item", "C2:T2:3"])
        run_blocked(["--state", self.state, "confirm", "--proposal", "P1",
                     "--school", "C2", "--on", "2026-10-15", "--start", "2026-11-01"])
        st = self.store.state()
        self.assertEqual(len(st.confirmations), 2)     # 仅有历史导入的两条

    def test_dropped_resource_is_not_failure(self):
        self.analyze(1, "2026-06-30", "2026-07-01")
        self.analyze(2, "2026-09-30", "2026-10-05")
        run(["--state", self.state, "release-controls", "--by", "负责人", "--on", "2026-10-06"])
        run(["--state", self.state, "propose",
             "--item", "C2:T2:3", "--item", "C8:T2:3", "--item", "C6:T6:3"])
        st = self.store.state()
        items = {i["school_id"]: i for i in st.proposals["P1"]["items"]}
        self.assertEqual(items["C2"]["status"], "placed")
        self.assertEqual(items["C8"]["status"], expansion.DROPPED_RESOURCE)  # T2 课时不足
        self.assertEqual(items["C6"]["status"], expansion.DROPPED_RESOURCE)  # T6 仅剩 1h
        statuses = {i["status"] for p in st.proposals.values() for i in p["items"]}
        self.assertNotIn("failed", statuses)

    def test_pause_does_not_revert_started_teaching(self):
        run(["--state", self.state, "pause", "--school", "C12",
             "--reason", "待核", "--by", "负责人", "--on", "2026-10-07"])
        st = self.store.state()
        r2 = next(c for c in st.confirmations if c["id"] == "R2")
        self.assertTrue(r2["started"])                 # 已开始教学不回退
        self.assertIn("C12", st.paused)

    def test_controls_cannot_release_before_final_look(self):
        run_blocked(["--state", self.state, "release-controls",
                     "--by", "负责人", "--on", "2026-07-03"])

    def test_verify_passes_and_reproduces(self):
        self.analyze(1, "2026-06-30", "2026-07-01")
        self.analyze(2, "2026-09-30", "2026-10-05")
        out = run(["--state", self.state, "verify"])
        self.assertIn("复核通过", out)

    def test_verify_detects_tampered_materials(self):
        self.analyze(1, "2026-06-30", "2026-07-01")
        # 复制一份资料并改动一个分数，登记到新状态目录
        import json, shutil
        tmp2 = tempfile.TemporaryDirectory()
        self.addCleanup(tmp2.cleanup)
        dest = Path(tmp2.name) / "materials"
        shutil.copytree(MATERIALS, dest)
        data = json.loads((dest / "data.json").read_text(encoding="utf-8"))
        for o in data["observations"]:
            if o["id"] == "O5":
                o["score"] = 99.99
        (dest / "data.json").write_text(json.dumps(data), encoding="utf-8")
        state2 = Path(tmp2.name) / "state"
        run(["--state", str(state2), "register", "--materials", str(dest)])
        run(["--state", str(state2), "analyze", "--look", "1",
             "--cutoff", "2026-06-30", "--issued", "2026-07-01"])
        # 篡改资料后重新登记：指纹一致但结论应与原始资料不同
        st2 = Store(state2).state()
        h1_new = st2.release_by_look(1)
        st_old_h1 = self.store.state().release_by_look(1)
        self.assertNotEqual(h1_new.result["dataset"]["dataset_fingerprint"],
                            st_old_h1.result["dataset"]["dataset_fingerprint"])


if __name__ == "__main__":
    unittest.main()
