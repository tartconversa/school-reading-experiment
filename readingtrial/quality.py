"""质量检查：回收率、分组比例、教师共享关系与数据核对概览。

这些检查只描述数据质量，不计算效果估计，不消耗、也不能被当作
正式结论。所有输出带非正式标识，与正式发布严格区分。
"""
from __future__ import annotations

QC_BANNER = "质量检查（非正式结论：不消耗正式查看机会，不构成效果结论）"


def run_qc(materials, trial_id, as_of):
    """在 as_of 时点可见的资料上做质量检查，返回可 JSON 序列化的字典。"""
    allocs = materials.trial_allocations(trial_id)
    arms = {a["school_id"]: a["arm"] for a in allocs}
    schools_by_arm = {}
    for sid, arm in arms.items():
        schools_by_arm.setdefault(arm, []).append(sid)

    # 回收率：按波次 × 组（仅统计 as_of 前已收到的记录）
    waves = materials.waves()
    recovery = {}
    for w in waves:
        row = {}
        for arm, sids in schools_by_arm.items():
            persons = [p for p in materials.people.values() if p["school_id"] in sids]
            got = 0
            for p in persons:
                for o in materials.observations:
                    if (
                        o["person_id"] == p["id"]
                        and o["on"] == w
                        and o["received_on"] <= as_of
                        and o["score"] is not None
                    ):
                        got += 1
                        break
            row[arm] = {"returned": got, "roster": len(persons)}
        recovery[w] = row

    # 分组比例：学校数与学生数
    sizes = {}
    for arm, sids in schools_by_arm.items():
        sizes[arm] = {
            "schools": len(sids),
            "students": sum(1 for p in materials.people.values() if p["school_id"] in sids),
        }

    # 教师共享：as_of 前已到达的任职记录
    links = materials.links_asof(as_of)
    by_teacher = {}
    for l in links:
        by_teacher.setdefault(l["teacher_id"], []).append(l["school_id"])
    cross_arm = []
    for tid, sids in sorted(by_teacher.items()):
        armset = {arms.get(s) for s in sids if s in arms}
        if len(armset) > 1:
            cross_arm.append({"teacher_id": tid, "schools": sorted(set(sids))})

    # 跨校家庭：同一家庭编号出现在多所学校
    by_household = {}
    for p in materials.people.values():
        by_household.setdefault(p["household"], set()).add(p["school_id"])
    cross_school_households = sum(1 for v in by_household.values() if len(v) > 1)

    # 学校层特征与分配的混杂检查
    confounds = []
    for field in ("area",):
        by_arm_values = {}
        for sid, arm in arms.items():
            by_arm_values.setdefault(arm, set()).add(materials.schools[sid][field])
        disjoint = True
        seen = set()
        for vals in by_arm_values.values():
            if seen & vals:
                disjoint = False
            seen |= vals
        if disjoint and len(by_arm_values) > 1:
            confounds.append(
                f"分配与{field}完全混杂："
                + "，".join(f"{a} 组为 {sorted(v)}" for a, v in sorted(by_arm_values.items()))
            )
    # 年级构成
    grade_by_arm = {}
    for sid, arm in arms.items():
        grades = {p["grade"] for p in materials.people.values() if p["school_id"] == sid}
        grade_by_arm.setdefault(arm, set()).update(grades)
    if len(grade_by_arm) > 1 and not set.intersection(*grade_by_arm.values()):
        confounds.append(
            "分配与年级完全混杂："
            + "，".join(f"{a} 组覆盖年级 {sorted(v)}" for a, v in sorted(grade_by_arm.items()))
        )

    # 设备条件按组均值（服务条件，不是能力指标）
    devices = {
        arm: sum(materials.schools[s]["devices"] for s in sids) / len(sids)
        for arm, sids in schools_by_arm.items()
    }

    return {
        "banner": QC_BANNER,
        "trial_id": trial_id,
        "as_of": as_of,
        "group_sizes": sizes,
        "recovery_by_wave": recovery,
        "teacher_links_known": len(links),
        "cross_arm_teachers": cross_arm,
        "cross_school_households": cross_school_households,
        "confound_warnings": confounds,
        "devices_mean_by_arm": devices,
    }


def format_qc(report):
    """把质量检查结果排成纯文本，供命令行展示。"""
    lines = [report["banner"], f"试验 {report['trial_id']}，资料时点 {report['as_of']}", ""]
    lines.append("分组比例（学校是分配单位，学生行数不是独立样本）：")
    for arm, s in sorted(report["group_sizes"].items()):
        lines.append(f"  {arm}: {s['schools']} 所学校 / {s['students']} 名学生")
    lines.append("回收率（按波次）：")
    for w, row in sorted(report["recovery_by_wave"].items()):
        parts = []
        for arm, r in sorted(row.items()):
            rate = r["returned"] / r["roster"] if r["roster"] else 0.0
            parts.append(f"{arm} {r['returned']}/{r['roster']}（{rate:.0%}）")
        lines.append(f"  {w}: " + "，".join(parts))
    lines.append(f"教师共享（已知任职 {report['teacher_links_known']} 条）：")
    if report["cross_arm_teachers"]:
        for c in report["cross_arm_teachers"]:
            lines.append(f"  跨组任职：{c['teacher_id']} -> {', '.join(c['schools'])}")
    else:
        lines.append("  未发现跨组任职")
    lines.append(f"跨校家庭：{report['cross_school_households']} 户（非独立观测提示）")
    for w in report["confound_warnings"]:
        lines.append("混杂警示：" + w)
    dev = "，".join(f"{a} 组均值 {v:.1f}" for a, v in sorted(report["devices_mean_by_arm"].items()))
    lines.append("设备条件（服务条件）：" + dev)
    return "\n".join(lines)
