"""检查演练资料的结构、编号及外键，不作分析或业务裁决。"""
from pathlib import Path
import hashlib, json

def read_materials(directory):
    directory = Path(directory)
    raw = (directory / "data.json").read_bytes()
    data = json.loads(raw)
    contract = json.loads((directory / "contract.json").read_text(encoding="utf-8"))
    if set(data) != set(contract["tables"]):
        raise ValueError("资料表与契约不一致")
    for name, meta in contract["tables"].items():
        rows = data[name]
        ids = [r["id"] for r in rows]
        if not rows or len(ids) != len(set(ids)):
            raise ValueError("资料编号为空或重复：" + name)
        for row in rows:
            if set(row) != set(meta["fields"]):
                raise ValueError("字段与契约不一致：" + name)
        for column, target in meta["references"].items():
            valid = {r["id"] for r in data[target]}
            if any(row[column] not in valid for row in rows):
                raise ValueError("关联资料不存在：" + name + "." + column)
    return data, {"sha256": hashlib.sha256(raw).hexdigest(), "rows": {n: len(r) for n,r in data.items()}}

if __name__ == "__main__":
    _, receipt = read_materials(Path(__file__).resolve().parent / "materials")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
