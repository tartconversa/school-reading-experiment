"""试验登记：事前声明的冻结与正式查看机会的台账规则。

登记后主结果、分配单位、观测窗口、风险预算与查看次数不可修改；
逐次名义风险在登记时按 OB 形消耗一次算定并冻结，之后不得按
“哪项指标显著”调整。正式查看必须落在事前声明的计划内。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import stats


@dataclass(frozen=True)
class Registration:
    """冻结的登记内容。"""

    trial_id: str
    registered_on: str
    unit: str
    primary: str
    minimum_gain: float
    alpha: float
    formal_looks: int
    look_dates: tuple
    resource_hours: float
    nominal_alphas: tuple

    @classmethod
    def from_protocol(cls, protocol):
        p = protocol
        if p["unit"] != "school":
            raise ValueError("本应用要求以学校为分配单位")
        if p["formal_looks"] != len(p["look_dates"]):
            raise ValueError("正式查看次数与查看日数量不一致")
        if not 0.0 < p["alpha"] < 1.0:
            raise ValueError("alpha 须在 (0,1) 内")
        if p["minimum_gain"] <= 0:
            raise ValueError("最小有意义改善须为正数")
        dates = tuple(sorted(p["look_dates"]))
        if any(d <= p["registered_on"] for d in dates):
            raise ValueError("正式查看日须晚于登记日")
        return cls(
            trial_id=p["id"],
            registered_on=p["registered_on"],
            unit=p["unit"],
            primary=p["primary"],
            minimum_gain=float(p["minimum_gain"]),
            alpha=float(p["alpha"]),
            formal_looks=int(p["formal_looks"]),
            look_dates=dates,
            resource_hours=float(p["resource_hours"]),
            nominal_alphas=tuple(stats.obf_nominal_alphas(p["alpha"], p["formal_looks"])),
        )

    def nominal_alpha(self, look_number):
        return self.nominal_alphas[look_number - 1]

    def check_look(self, look_number, cutoff, releases):
        """校验一次正式查看是否合规；releases 为既有发布（按查看号排序）。"""
        if not 1 <= look_number <= self.formal_looks:
            raise ValueError(
                f"正式查看编号 {look_number} 超出登记计划（共 {self.formal_looks} 次）"
            )
        if any(r["look_number"] == look_number for r in releases):
            raise ValueError(f"正式查看机会 {look_number} 已被使用，不得重复消耗")
        used = {r["look_number"] for r in releases}
        if used and look_number != max(used) + 1:
            raise ValueError("正式查看须按编号顺序消耗")
        planned = self.look_dates[look_number - 1]
        if cutoff > planned:
            raise ValueError(
                f"资料截止 {cutoff} 晚于事前声明的第 {look_number} 次查看日 {planned}"
            )
        earlier = [r["cutoff"] for r in releases if r["look_number"] < look_number]
        if earlier and cutoff <= max(earlier):
            raise ValueError("资料截止须晚于已发布的正式查看（每次查看须对应新到的资料）")


@dataclass
class Release:
    """一次正式发布（正式查看的结论记录）。"""

    release_id: str
    look_number: int
    cutoff: str
    issued_on: str
    decision_reference: str
    source: str               # imported=历史导入, computed=本系统计算
    result: dict | None = field(default=None)

    def to_dict(self):
        return {
            "release_id": self.release_id,
            "look_number": self.look_number,
            "cutoff": self.cutoff,
            "issued_on": self.issued_on,
            "decision_reference": self.decision_reference,
            "source": self.source,
            "result": self.result,
        }
