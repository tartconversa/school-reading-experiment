"""扩围方案、课时资源台账与复议事项。

原则：
- 扩围不是给所有学校贴同一结论；逐校评估证据覆盖、共享教师暴露与可兑现课时。
- 质量不足或证据不足时停止新的确认；既有承诺进入复议，不自动回退。
- 资源不足可缩小方案；被缩减的学校记为“资源不足未纳入”，绝不回写为试验失败。
"""
from __future__ import annotations

from . import stats

# 复议事项种类
LATE_KNOWLEDGE = "LATE_KNOWLEDGE"      # 发布截止后到达、影响该发布口径的记录
OVERBOOK = "OVERBOOK"                  # 教师承诺课时超过可用课时
EXPOSURE = "EXPOSURE"                  # 已确认排课的共享教师仍服务保留对照校
INSUFFICIENT_BASIS = "INSUFFICIENT_BASIS"  # 确认时最近正式结论并非“达到最小有意义改善”
CONTROL_EXIT = "CONTROL_EXIT"          # 对照校在全部正式查看完成前确认退出对照

DROPPED_RESOURCE = "dropped_resource"  # 资源不足未纳入（不是试验失败）


# ---------------------------------------------------------------- 资源台账


def teacher_table(materials, state):
    """每位教师的可用、已占与剩余课时（按当前全部已知任职与已确认排课）。"""
    links_hours = {}
    for l in materials.links:
        links_hours[l["teacher_id"]] = links_hours.get(l["teacher_id"], 0) + l["hours"]
    rollout_hours = {}
    for c in state.confirmations:
        rollout_hours[c["teacher_id"]] = rollout_hours.get(c["teacher_id"], 0) + c["weekly_hours"]
    table = {}
    for tid, t in sorted(materials.teachers.items()):
        committed = links_hours.get(tid, 0) + rollout_hours.get(tid, 0)
        table[tid] = {
            "hours": t["hours"],
            "links": links_hours.get(tid, 0),
            "rollout": rollout_hours.get(tid, 0),
            "committed": committed,
            "remaining": t["hours"] - committed,
        }
    return table


def budget_table(state):
    """登记资源边界的使用情况（下一批每周可分配教师小时）。"""
    total = state.registration.resource_hours if state.registration else 0.0
    used = sum(c["weekly_hours"] for c in state.confirmations)
    return {"total": total, "used": used, "remaining": total - used}


def kept_control_schools(materials, state):
    """仍属保留对照的学校：对照组、未被确认扩围、且对照保留未解除。"""
    if state.controls_released or state.registration is None:
        return set()
    trial = state.registration.trial_id
    expanded = {c["school_id"] for c in state.confirmations}
    return {
        a["school_id"]
        for a in materials.trial_allocations(trial)
        if a["arm"] != "reading" and a["school_id"] not in expanded
    }


# ---------------------------------------------------------------- 候选评估


def evaluate_candidate(materials, state, school_id):
    """逐校评估：返回 (blocks, notes)。blocks 为阻断项，notes 为提示。"""
    blocks, notes = [], []
    if school_id not in materials.schools:
        blocks.append(f"{school_id} 不在学校名册内")
        return blocks, notes
    reg = state.registration
    trial = reg.trial_id
    arm = materials.arm_of(school_id, trial)
    if arm == "reading":
        blocks.append("该校已在干预组，无需扩围")
    if any(c["school_id"] == school_id for c in state.confirmations):
        blocks.append("该校已有确认的扩围排课，不得重复占用")
    if school_id in state.paused:
        blocks.append(f"该校已被试验负责人暂停：{state.paused[school_id]}")
    if school_id in kept_control_schools(materials, state):
        blocks.append("该校仍属保留对照，须待最终正式查看后由负责人解除保留")

    # 证据覆盖：人群与教学条件
    school = materials.schools[school_id]
    allocs = materials.trial_allocations(trial)
    reading_schools = [a["school_id"] for a in allocs if a["arm"] == "reading"]
    reading_areas = {materials.schools[s]["area"] for s in reading_schools}
    trial_areas = {materials.schools[a["school_id"]]["area"] for a in allocs}
    if school["area"] not in trial_areas:
        blocks.append(f"地区层 {school['area']} 超出试验覆盖 {sorted(trial_areas)}")
    elif school["area"] not in reading_areas:
        notes.append(
            f"干预组证据全部来自{sorted(reading_areas)}学校，该校（{school['area']}）属外推"
        )
    trial_grades = {
        p["grade"] for p in materials.people.values()
        if materials.arm_of(p["school_id"], trial) is not None
    }
    reading_grades = {
        p["grade"] for p in materials.people.values() if p["school_id"] in reading_schools
    }
    grades = {p["grade"] for p in materials.people.values() if p["school_id"] == school_id}
    if grades and not grades <= trial_grades:
        blocks.append(f"年级 {sorted(grades)} 超出试验覆盖 {sorted(trial_grades)}")
    elif grades and not grades <= reading_grades:
        notes.append(
            f"干预组证据仅覆盖年级 {sorted(reading_grades)}，该校年级 {sorted(grades)} 部分或全部属外推"
        )
    min_devices = min(materials.schools[s]["devices"] for s in reading_schools)
    if school["devices"] < min_devices:
        notes.append(
            f"该校终端 {school['devices']} 台低于干预组最低 {min_devices} 台，教学条件超出证据覆盖"
        )
    return blocks, notes


# ---------------------------------------------------------------- 方案与确认


def exposure_conflicts(materials, state, teacher_id):
    """该教师当前任职学校中仍属保留对照的学校（共享教师提前暴露风险）。"""
    kept = kept_control_schools(materials, state)
    return sorted({s for s, _ in materials.teacher_schools(teacher_id) if s in kept})


def make_proposal(materials, state, proposal_id, items, note=""):
    """校验并生成扩围方案草稿。items: [(school_id, teacher_id, weekly_hours)]。"""
    teachers = teacher_table(materials, state)
    budget = budget_table(state)
    placed_teacher = {}
    placed_total = 0.0
    out_items = []
    for school_id, teacher_id, hours in items:
        entry = {"school_id": school_id, "teacher_id": teacher_id, "weekly_hours": hours}
        problems = []
        if teacher_id not in materials.teachers:
            problems.append(f"教师 {teacher_id} 不存在")
        if hours <= 0:
            problems.append("课时须为正数")
        blocks, notes = evaluate_candidate(materials, state, school_id)
        problems.extend(blocks)
        if problems:
            entry.update(status="rejected", problems=problems)
            out_items.append(entry)
            continue
        t = materials.teachers[teacher_id]
        grades = {p["grade"] for p in materials.people.values() if p["school_id"] == school_id}
        if grades and (min(grades) < t["grade_low"] or max(grades) > t["grade_high"]):
            entry.update(
                status="rejected",
                problems=[f"教师 {teacher_id} 可服务年级 {t['grade_low']}-{t['grade_high']} 不覆盖 {sorted(grades)}"],
            )
            out_items.append(entry)
            continue
        conflicts = exposure_conflicts(materials, state, teacher_id)
        if conflicts:
            notes.append(f"共享教师暴露风险：{teacher_id} 仍服务保留对照校 {'、'.join(conflicts)}")
        remaining_teacher = teachers[teacher_id]["remaining"] - placed_teacher.get(teacher_id, 0.0)
        remaining_budget = budget["remaining"] - placed_total
        if hours <= remaining_teacher and hours <= remaining_budget:
            placed_teacher[teacher_id] = placed_teacher.get(teacher_id, 0.0) + hours
            placed_total += hours
            entry.update(status="placed", notes=notes)
        else:
            entry.update(
                status=DROPPED_RESOURCE,
                notes=notes + [
                    "资源不足未纳入本批（教师剩余 "
                    f"{remaining_teacher:.1f}h / 预算剩余 {remaining_budget:.1f}h）；"
                    "该状态不是试验失败，不得回写为失败样本"
                ],
            )
        out_items.append(entry)
    return {
        "proposal_id": proposal_id,
        "note": note,
        "items": out_items,
        "placed_hours": placed_total,
    }


class ConfirmBlocked(Exception):
    """确认被规则阻断。"""


def check_confirmable(materials, state):
    """新确认的全局门槛；返回阻断原因列表（空为可确认）。"""
    reasons = []
    open_items = open_reviews(materials, state)
    if open_items:
        reasons.append(f"存在 {len(open_items)} 条未办结复议事项")
    latest = state.latest_result_release()
    if latest is None:
        reasons.append("尚无正式结论，不能作为扩围依据")
    elif latest.result["decision"]["code"] != stats.MEETS_MCID:
        reasons.append(
            f"最近正式结论（{latest.release_id}）判定为 {latest.result['decision']['code']}，"
            "证据不足，停止新的扩围确认"
        )
    return reasons


def confirm(materials, state, proposal, school_id, confirmed_on, start):
    """校方确认方案中的一所学校；通过全部校验后返回确认记录。"""
    reasons = check_confirmable(materials, state)
    if reasons:
        raise ConfirmBlocked("；".join(reasons))
    item = next((i for i in proposal["items"] if i["school_id"] == school_id), None)
    if item is None:
        raise ConfirmBlocked(f"方案 {proposal['proposal_id']} 中不存在学校 {school_id}")
    if item["status"] != "placed":
        raise ConfirmBlocked(f"该校在方案中的状态为 {item['status']}，不能确认")
    if any(c["school_id"] == school_id for c in state.confirmations):
        raise ConfirmBlocked("该校已有确认的扩围排课，不得重复占用")
    if school_id in state.paused:
        raise ConfirmBlocked(f"该校已被暂停：{state.paused[school_id]}")
    teachers = teacher_table(materials, state)
    if item["weekly_hours"] > teachers[item["teacher_id"]]["remaining"]:
        raise ConfirmBlocked(
            f"教师 {item['teacher_id']} 剩余课时不足（"
            f"{teachers[item['teacher_id']]['remaining']:.1f}h），不得重复占用"
        )
    conflicts = exposure_conflicts(materials, state, item["teacher_id"])
    if conflicts:
        raise ConfirmBlocked(
            f"教师 {item['teacher_id']} 仍服务保留对照校 {'、'.join(conflicts)}，"
            "确认将把对照校提前暴露"
        )
    seq = len(state.confirmations) + 1
    return {
        "id": f"B{seq}",
        "proposal_id": proposal["proposal_id"],
        "school_id": school_id,
        "teacher_id": item["teacher_id"],
        "weekly_hours": item["weekly_hours"],
        "confirmed_on": confirmed_on,
        "start": start,
        "started": False,
        "source": "computed",
    }


# ---------------------------------------------------------------- 复议事项


def compute_reviews(materials, state):
    """由当前全部已知资料推导复议事项（未扣除已办结）。"""
    items = []
    reg = state.registration
    if reg is None:
        return items
    trial = reg.trial_id
    end_wave = materials.endline_wave(trial)

    # 发布截止后到达的记录
    for r in state.releases:
        if r.result is None:
            continue
        late_obs = [
            o["id"] for o in materials.observations
            if o["on"] <= end_wave and o["received_on"] > r.cutoff
        ]
        late_links = [l["id"] for l in materials.links if l["received_on"] > r.cutoff]
        if late_obs or late_links:
            looks_left = reg.formal_looks - sum(1 for x in state.releases if x.result)
            detail = []
            if late_obs:
                detail.append("观测 " + "、".join(sorted(late_obs)))
            if late_links:
                detail.append("任职 " + "、".join(sorted(late_links)))
            msg = (
                f"发布 {r.release_id}（截止 {r.cutoff}）之后到达："
                + "；".join(detail)
            )
            if looks_left <= 0:
                msg += "；正式查看机会已用尽，不能静默改结论，须经复议决定后续口径"
            items.append({"kind": LATE_KNOWLEDGE, "target": r.release_id, "message": msg})

    # 课时超占与共享教师暴露（按当前已知任职）
    table = teacher_table(materials, state)
    for tid, row in table.items():
        if row["committed"] > row["hours"]:
            items.append({
                "kind": OVERBOOK,
                "target": tid,
                "message": (
                    f"教师 {tid} 承诺 {row['committed']}h 超过可用 {row['hours']}h"
                    "（含后到任职更正），相关排课需复议"
                ),
            })
    kept = kept_control_schools(materials, state)
    for c in state.confirmations:
        exposed = sorted(
            {s for s, _ in materials.teacher_schools(c["teacher_id"])} & kept
        )
        if exposed:
            items.append({
                "kind": EXPOSURE,
                "target": c["id"],
                "message": (
                    f"排课 {c['id']} 的教师 {c['teacher_id']} 仍服务保留对照校 "
                    f"{'、'.join(exposed)}，对照可能提前暴露"
                ),
            })

    # 确认依据不足：确认时点最近的正式结论并非“达到”
    done = [r for r in state.releases if r.result is not None]
    for c in state.confirmations:
        prior = [r for r in done if r.issued_on <= c["confirmed_on"]]
        if prior and prior[-1].result["decision"]["code"] != stats.MEETS_MCID:
            items.append({
                "kind": INSUFFICIENT_BASIS,
                "target": c["id"],
                "message": (
                    f"排课 {c['id']} 确认时最近正式结论 {prior[-1].release_id} "
                    f"判定为 {prior[-1].result['decision']['code']}，依据不足"
                ),
            })

    # 对照提前退出
    all_done = len(done) >= reg.formal_looks
    if not all_done:
        exited = [
            c["id"] for c in state.confirmations
            if materials.arm_of(c["school_id"], trial) == "usual"
        ]
        if exited:
            items.append({
                "kind": CONTROL_EXIT,
                "target": trial,
                "message": (
                    "对照校在全部正式查看完成前确认扩围（" + "、".join(sorted(exited)) +
                    "），后续期对照描述范围缩小"
                ),
            })
    return items


def review_key(item):
    return f"{item['kind']}:{item['target']}"


def open_reviews(materials, state):
    return [
        i for i in compute_reviews(materials, state)
        if review_key(i) not in state.resolutions
    ]
