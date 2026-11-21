"""资料装载、结构核对与按资料截止时间的知识视图。

read_materials 是结构核对的唯一实现（inspect_materials.py 亦委托至此）。
Materials 提供分析所需的只读视图；所有“某时点可知”的判断都通过
received_on / confirmed_on 与截止时间比较完成，绝不事后改写原始记录。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def read_materials(directory):
    """读取并核对资料包，返回 (数据字典, 回执)。结构与口径见 资料契约.md。"""
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
    return data, {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "rows": {n: len(r) for n, r in data.items()},
    }


class Materials:
    """资料包的只读视图与索引。"""

    def __init__(self, data, receipt):
        self.data = data
        self.receipt = receipt
        self.schools = {r["id"]: r for r in data["schools"]}
        self.people = {r["id"]: r for r in data["people"]}
        self.teachers = {r["id"]: r for r in data["teachers"]}
        self.protocols = {r["id"]: r for r in data["protocols"]}
        self.allocations = list(data["allocations"])
        self.observations = list(data["observations"])
        self.links = list(data["teaching_links"])
        self.formal_history = list(data["formal_history"])
        self.rollout = list(data["rollout"])

    # ---------------------------------------------------------- 基础索引

    def trial_ids(self):
        return sorted(self.protocols)

    def trial_allocations(self, trial_id):
        return [a for a in self.allocations if a["trial_id"] == trial_id]

    def arm_of(self, school_id, trial_id):
        for a in self.trial_allocations(trial_id):
            if a["school_id"] == school_id:
                return a["arm"]
        return None

    def school_of(self, person_id):
        return self.people[person_id]["school_id"]

    def waves(self):
        return sorted({o["on"] for o in self.observations})

    def window(self, trial_id):
        """主要观测窗口（各分配一致时返回 (start, end)）。"""
        allocs = self.trial_allocations(trial_id)
        starts = {a["start"] for a in allocs}
        ends = {a["end"] for a in allocs}
        if len(starts) != 1 or len(ends) != 1:
            raise ValueError("各校观测窗口不一致，需按校分别处理")
        return starts.pop(), ends.pop()

    def baseline_wave(self, trial_id):
        start, _ = self.window(trial_id)
        earlier = [w for w in self.waves() if w <= start]
        if not earlier:
            raise ValueError("缺少观测开始前的基线波次")
        return earlier[-1]

    def endline_wave(self, trial_id):
        _, end = self.window(trial_id)
        return end

    def followup_waves(self, trial_id):
        _, end = self.window(trial_id)
        return [w for w in self.waves() if w > end]

    # ---------------------------------------------------------- 时点知识视图

    def observations_asof(self, cutoff):
        """截止 cutoff（含）已收到的观测；score 为 null 表示未回收。"""
        return [o for o in self.observations if o["received_on"] <= cutoff]

    def links_asof(self, cutoff):
        """截止 cutoff（含）已到达的任职记录。"""
        return [l for l in self.links if l["received_on"] <= cutoff]

    def latest_receipt(self):
        return max(
            [o["received_on"] for o in self.observations]
            + [l["received_on"] for l in self.links]
        )

    def wave_scores(self, wave, cutoff):
        """某波次在 cutoff 前已收到且有分数的 {person_id: observation}。"""
        out = {}
        for o in self.observations_asof(cutoff):
            if o["on"] == wave and o["score"] is not None:
                out[o["person_id"]] = o
        return out

    def teacher_schools(self, teacher_id, cutoff=None):
        """教师任职学校（按到达时间过滤）；返回 [(school_id, link)]。"""
        links = self.links if cutoff is None else self.links_asof(cutoff)
        return [(l["school_id"], l) for l in links if l["teacher_id"] == teacher_id]

    def school_teachers(self, school_id, cutoff=None):
        links = self.links if cutoff is None else self.links_asof(cutoff)
        return [(l["teacher_id"], l) for l in links if l["school_id"] == school_id]


def load_materials(directory):
    data, receipt = read_materials(directory)
    return Materials(data, receipt)
