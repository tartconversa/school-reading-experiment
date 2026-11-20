"""资料完整性检查，不检验尚未开发的业务能力。"""
from pathlib import Path
import json, tempfile, unittest
from inspect_materials import read_materials

class MaterialsTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(__file__).resolve().parents[1] / "materials"

    def test_load_and_digest(self):
        data, receipt = read_materials(self.directory)
        self.assertEqual(len(receipt["sha256"]), 64)
        self.assertEqual(set(data), set(receipt["rows"]))

    def test_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)
            data=json.loads((self.directory/"data.json").read_text(encoding="utf-8"))
            key=next(iter(data)); data[key].append(data[key][0])
            (dest/"data.json").write_text(json.dumps(data),encoding="utf-8")
            (dest/"contract.json").write_bytes((self.directory/"contract.json").read_bytes())
            with self.assertRaisesRegex(ValueError,"重复"):
                read_materials(dest)

    def test_missing_reference_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)
            data=json.loads((self.directory/"data.json").read_text(encoding="utf-8"))
            meta=json.loads((self.directory/"contract.json").read_text(encoding="utf-8"))
            name=next(k for k,v in meta["tables"].items() if v["references"])
            column=next(iter(meta["tables"][name]["references"]))
            data[name][0][column]="NO-SUCH-RECORD"
            (dest/"data.json").write_text(json.dumps(data),encoding="utf-8")
            (dest/"contract.json").write_text(json.dumps(meta),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"关联资料不存在"):
                read_materials(dest)

    def test_source_facts_1(self):
        data, _ = read_materials(self.directory)
        self.assertTrue(len(data['allocations'])==12 and len(data['observations'])==576)

    def test_source_facts_2(self):
        data, _ = read_materials(self.directory)
        self.assertTrue(any(x['received_on']>x['from_on'] for x in data['teaching_links']))

if __name__ == "__main__":
    unittest.main()
