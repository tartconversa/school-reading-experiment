"""事件账本：所有业务动作以追加事件记录，状态由重放得到。

账本写入指定的状态目录（ledger.jsonl），原始资料只读。
事件种类：
  REGISTER        登记（冻结事前声明，导入历史发布与已确认排课）
  QC              质量检查（非正式）
  RELEASE         正式发布（消耗一次正式查看机会，含完整结果与数据指纹）
  PROPOSE         研究员提出扩围方案（草稿，含逐项校验结论）
  CONFIRM         校方确认方案中的某所学校（占用课时）
  PAUSE           试验负责人暂停某所学校的新确认
  RELEASE_CONTROLS 最终查看后负责人解除对照保留
  RESOLVE         负责人办结一条复议事项
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .registry import Registration, Release


class LedgerError(Exception):
    """违反台账规则（如重复消耗正式机会、改写历史）。"""


@dataclass
class State:
    registration: Registration | None = None
    materials_path: str = ""
    materials_sha: str = ""
    releases: list = field(default_factory=list)        # Release
    qc_runs: list = field(default_factory=list)
    proposals: dict = field(default_factory=dict)       # id -> payload
    confirmations: list = field(default_factory=list)   # payload dict
    paused: dict = field(default_factory=dict)          # school_id -> reason
    controls_released: bool = False
    resolutions: dict = field(default_factory=dict)     # review key -> payload
    notes: list = field(default_factory=list)

    def release_by_look(self, look_number):
        for r in self.releases:
            if r.look_number == look_number:
                return r
        return None

    def latest_result_release(self):
        done = [r for r in self.releases if r.result is not None]
        return done[-1] if done else None


class Store:
    """追加式事件存储。"""

    def __init__(self, directory):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "ledger.jsonl"

    def append(self, kind, payload):
        event = {"kind": kind, "payload": payload}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return event

    def events(self):
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def state(self):
        return replay(self.events())


def replay(events):
    st = State()
    for ev in events:
        kind, p = ev["kind"], ev["payload"]
        if kind == "REGISTER":
            if st.registration is not None:
                raise LedgerError("试验已登记，登记内容不可修改或重复登记")
            st.registration = Registration(
                trial_id=p["trial_id"],
                registered_on=p["registered_on"],
                unit=p["unit"],
                primary=p["primary"],
                minimum_gain=p["minimum_gain"],
                alpha=p["alpha"],
                formal_looks=p["formal_looks"],
                look_dates=tuple(p["look_dates"]),
                resource_hours=p["resource_hours"],
                nominal_alphas=tuple(p["nominal_alphas"]),
            )
            st.materials_path = p["materials_path"]
            st.materials_sha = p["materials_sha"]
            for h in p.get("imported_releases", []):
                st.releases.append(Release(
                    release_id=h["id"],
                    look_number=h["look_number"],
                    cutoff=h["cutoff"],
                    issued_on=h["issued_on"],
                    decision_reference=h["decision_reference"],
                    source="imported",
                    result=None,
                ))
            for r in p.get("imported_confirmations", []):
                st.confirmations.append(dict(r, source="imported"))
        elif kind == "QC":
            st.qc_runs.append(p)
        elif kind == "RELEASE":
            existing = st.release_by_look(p["look_number"])
            if existing is not None and existing.result is not None:
                raise LedgerError(f"正式查看 {p['look_number']} 已有发布结果，不得改写")
            if existing is None:
                st.releases.append(Release(
                    release_id=p["release_id"],
                    look_number=p["look_number"],
                    cutoff=p["cutoff"],
                    issued_on=p["issued_on"],
                    decision_reference=p["decision_reference"],
                    source="computed",
                    result=p["result"],
                ))
            else:
                if existing.cutoff != p["cutoff"]:
                    raise LedgerError("发布截止与历史登记不一致")
                existing.result = p["result"]
                existing.source = "computed+bound"
        elif kind == "PROPOSE":
            st.proposals[p["proposal_id"]] = p
        elif kind == "CONFIRM":
            st.confirmations.append(p)
        elif kind == "PAUSE":
            st.paused[p["school_id"]] = p["reason"]
        elif kind == "RELEASE_CONTROLS":
            st.controls_released = True
        elif kind == "RESOLVE":
            st.resolutions[p["key"]] = p
        elif kind == "NOTE":
            st.notes.append(p)
        else:
            raise LedgerError("未知事件种类：" + kind)
    st.releases.sort(key=lambda r: r.look_number)
    return st
