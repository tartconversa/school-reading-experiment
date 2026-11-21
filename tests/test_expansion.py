"""扩围机制测试：构造证据达标的合成资料，走通确认、容量与暂停路径。"""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from readingtrial import expansion, stats
from readingtrial.cli import main
from readingtrial.ledger import Store
from readingtrial.materials import load_materials

ROOT = Path(__file__).resolve().parents[1]


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


def build_materials(dest):
    """构造一套效果明确达标的合成资料（4 所试验校 + 1 所已排课校）。"""
    dest = Path(dest)
    shutil.copy(ROOT / "materials" / "contract.json", dest / "contract.json")
    schools = [
        {"id": "S1", "area": "城区", "devices": 10},
        {"id": "S2", "area": "城区", "devices": 10},
        {"id": "S3", "area": "城区", "devices": 10},
        {"id": "S4", "area": "城区", "devices": 10},
        {"id": "S5", "area": "城区", "devices": 10},
    ]
    people = []
    for i in range(24):
        sid = f"S{i // 6 + 1}"
        grade = 6 if sid == "S4" else 4
        people.append({
            "id": f"P{i + 1:03d}", "school_id": sid, "household": f"H{i:03d}",
            "grade": grade, "access_need": "text", "sample_weight": 1.0,
        })
    for i in range(24, 26):
        people.append({
            "id": f"P{i + 1:03d}", "school_id": "S5", "household": f"H{i:03d}",
            "grade": 4, "access_need": "text", "sample_weight": 1.0,
        })
    observations = []
    oid = 0
    for i in range(24):
        pid = f"P{i + 1:03d}"
        sid = f"S{i // 6 + 1}"
        base = 40.0 + (i % 6)
        gain = 10.0 if sid in ("S1", "S2") else 1.0
        jitter = ((i % 3) - 1) * 0.4
        oid += 1
        observations.append({
            "id": f"O{oid}", "person_id": pid, "on": "2026-02-20",
            "score": base, "reason": None, "received_on": "2026-02-20",
            "actually_attended": 8,
        })
        oid += 1
        observations.append({
            "id": f"O{oid}", "person_id": pid, "on": "2026-06-15",
            "score": round(base + gain + jitter, 2), "reason": None,
            "received_on": "2026-06-15", "actually_attended": 8,
        })
    data = {
        "schools": schools,
        "people": people,
        "protocols": [{
            "id": "X1", "registered_on": "2026-02-01", "unit": "school",
            "primary": "understanding", "minimum_gain": 3.0, "alpha": 0.05,
            "formal_looks": 1, "look_dates": ["2026-06-30"], "resource_hours": 20,
        }],
        "allocations": [
            {"id": f"A{k}", "school_id": s, "trial_id": "X1", "arm": arm,
             "assigned_on": "2026-02-15", "start": "2026-03-01", "end": "2026-06-15"}
            for k, (s, arm) in enumerate(
                [("S1", "reading"), ("S2", "reading"), ("S3", "usual"), ("S4", "usual")], 1)
        ],
        "observations": observations,
        "teachers": [
            {"id": "T1", "hours": 10, "grade_low": 3, "grade_high": 6},
            {"id": "T2", "hours": 10, "grade_low": 3, "grade_high": 6},
            {"id": "T3", "hours": 10, "grade_low": 3, "grade_high": 6},
            {"id": "T4", "hours": 10, "grade_low": 3, "grade_high": 6},
            {"id": "T5", "hours": 4, "grade_low": 3, "grade_high": 6},
            {"id": "T6", "hours": 100, "grade_low": 3, "grade_high": 6},
        ],
        "teaching_links": [
            {"id": "J1", "teacher_id": "T1", "school_id": "S1", "from_on": "2026-03-01",
             "hours": 3, "received_on": "2026-03-01"},
            {"id": "J2", "teacher_id": "T2", "school_id": "S2", "from_on": "2026-03-01",
             "hours": 3, "received_on": "2026-03-01"},
            {"id": "J3", "teacher_id": "T3", "school_id": "S3", "from_on": "2026-03-01",
             "hours": 3, "received_on": "2026-03-01"},
            {"id": "J4", "teacher_id": "T3", "school_id": "S4", "from_on": "2026-03-01",
             "hours": 3, "received_on": "2026-03-01"},
            {"id": "J5", "teacher_id": "T4", "school_id": "S5", "from_on": "2026-03-01",
             "hours": 3, "received_on": "2026-03-01"},
        ],
        "formal_history": [{
            "id": "H1", "trial_id": "X1", "issued_on": "2026-07-01",
            "cutoff": "2026-06-30", "look_number": 1, "decision_reference": "测试纪要",
        }],
        "rollout": [{
            "id": "R1", "school_id": "S5", "teacher_id": "T4", "weekly_hours": 2,
            "confirmed_on": "2026-07-02", "start": "2026-08-01", "started": False,
        }],
    }
    (dest / "data.json").write_text(json.dumps(data), encoding="utf-8")


class ExpansionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.materials = root / "materials"
        self.materials.mkdir()
        build_materials(self.materials)
        self.state = str(root / "state")
        run(["--state", self.state, "register", "--materials", str(self.materials)])

    def tearDown(self):
        self.tmp.cleanup()

    def advance_to_confirmable(self):
        run(["--state", self.state, "analyze", "--look", "1",
             "--cutoff", "2026-06-30", "--issued", "2026-07-01", "--ref", "测试纪要"])
        st = Store(self.state).state()
        self.assertEqual(st.release_by_look(1).result["decision"]["code"], stats.MEETS_MCID)
        run(["--state", self.state, "release-controls", "--by", "负责人", "--on", "2026-07-03"])

    def confirm_s3(self):
        run(["--state", self.state, "propose", "--item", "S3:T5:3"])
        run(["--state", self.state, "confirm", "--proposal", "P1",
             "--school", "S3", "--on", "2026-07-10", "--start", "2026-08-01"])

    def test_confirm_path_when_evidence_meets(self):
        self.advance_to_confirmable()
        self.confirm_s3()
        st = Store(self.state).state()
        self.assertEqual(len(st.confirmations), 2)     # R1 + 新确认
        new = st.confirmations[-1]
        self.assertEqual(new["school_id"], "S3")
        self.assertEqual(new["teacher_id"], "T5")
        table = expansion.teacher_table(load_materials(self.materials), st)
        self.assertEqual(table["T5"]["remaining"], 1)  # 4 - 3

    def test_duplicate_confirm_rejected(self):
        self.advance_to_confirmable()
        self.confirm_s3()
        run_blocked(["--state", self.state, "confirm", "--proposal", "P1",
                     "--school", "S3", "--on", "2026-07-11", "--start", "2026-08-01"])

    def test_teacher_capacity_shrinks_proposal(self):
        self.advance_to_confirmable()
        self.confirm_s3()
        out = run(["--state", self.state, "propose", "--item", "S4:T5:3"])
        self.assertIn(expansion.DROPPED_RESOURCE, out)  # T5 仅剩 1h
        st = Store(self.state).state()
        item = st.proposals["P2"]["items"][0]
        self.assertEqual(item["status"], expansion.DROPPED_RESOURCE)
        self.assertTrue(any("年级" in n for n in item["notes"]))  # 年级外推提示
        run_blocked(["--state", self.state, "confirm", "--proposal", "P2",
                     "--school", "S4", "--on", "2026-07-12", "--start", "2026-08-01"])

    def test_budget_shrinks_proposal(self):
        self.advance_to_confirmable()
        self.confirm_s3()
        # 预算 20，已用 R1 2h + B2 3h，剩余 15h；T6 课时充足但预算不足
        out = run(["--state", self.state, "propose", "--item", "S4:T6:25"])
        self.assertIn(expansion.DROPPED_RESOURCE, out)

    def test_pause_blocks_proposal(self):
        self.advance_to_confirmable()
        run(["--state", self.state, "pause", "--school", "S4",
             "--reason", "待核", "--by", "负责人", "--on", "2026-07-05"])
        out = run(["--state", self.state, "propose", "--item", "S4:T3:3"])
        self.assertIn("rejected", out)
        self.assertIn("暂停", out)

    def test_confirm_blocked_before_controls_released(self):
        run(["--state", self.state, "analyze", "--look", "1",
             "--cutoff", "2026-06-30", "--issued", "2026-07-01", "--ref", "测试纪要"])
        out = run(["--state", self.state, "propose", "--item", "S3:T5:3"])
        self.assertIn("rejected", out)                 # S3 仍属保留对照


if __name__ == "__main__":
    unittest.main()
