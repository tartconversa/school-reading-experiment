"""正式分析装配：按登记口径与资料截止构造分析集，输出可复现结果。

主分析为按分配（ITT）的 ANCOVA：期末成绩 ~ 分组 + 基线成绩，
学校层 CR1 聚类稳健标准误，t(G-1) 参考分布，该次查看的名义风险
来自登记时冻结的 OB 形消耗。实际参加者的变化只作描述，不作因果解释。
"""
from __future__ import annotations

import hashlib
import json

from . import stats
from .quality import run_qc

CODE_VERSION = "readingtrial-0.1.0"


def build_analysis_rows(materials, trial_id, cutoff):
    """构造主分析数据集并给出核对计数。

    返回 (rows, meta)。rows 为 (arm01, baseline, endline, school) 四元组，
    仅含基线与期末均回收的学生；meta 记录排除原因，供报告与核对。
    """
    arms = {a["school_id"]: a["arm"] for a in materials.trial_allocations(trial_id)}
    base_wave = materials.baseline_wave(trial_id)
    end_wave = materials.endline_wave(trial_id)
    base = materials.wave_scores(base_wave, cutoff)
    end = materials.wave_scores(end_wave, cutoff)

    roster = [p for p in materials.people.values() if p["school_id"] in arms]
    late = [
        o for o in materials.observations
        if o["on"] == end_wave and o["received_on"] > cutoff
    ]
    rows = []
    missing_end = 0
    missing_base = 0
    for p in roster:
        pid = p["id"]
        if pid not in end:
            missing_end += 1
            continue
        if pid not in base:
            missing_base += 1
            continue
        sid = p["school_id"]
        rows.append((1 if arms[sid] == "reading" else 0, base[pid]["score"], end[pid]["score"], sid))

    meta = {
        "baseline_wave": base_wave,
        "endline_wave": end_wave,
        "roster": len(roster),
        "missing_endline": missing_end,
        "missing_baseline": missing_base,
        "late_after_cutoff": sorted({o["id"] for o in late}),
        "analyzed": len(rows),
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            {"trial": trial_id, "cutoff": cutoff, "rows": sorted(map(list, rows))},
            ensure_ascii=False, sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    meta["dataset_fingerprint"] = fingerprint
    return rows, meta


def run_formal(materials, registration, look_number, cutoff):
    """执行一次正式分析，返回完整结果字典（可 JSON 序列化）。"""
    trial_id = registration.trial_id
    rows, meta = build_analysis_rows(materials, trial_id, cutoff)
    arms = {a["school_id"]: a["arm"] for a in materials.trial_allocations(trial_id)}

    itt = stats.ancova_itt(rows)
    alpha = registration.nominal_alpha(look_number)
    decision = stats.decide(itt.estimate, itt.se, itt.df, alpha, registration.minimum_gain)

    gains = stats.school_gains(rows)
    arm01 = {s: (1 if a == "reading" else 0) for s, a in arms.items()}
    perm_p, perm_total, perm_stat = stats.permutation_pvalue(gains, arm01)

    # 描述性：实际参加者的变化（非因果，明确标注）
    people = materials.people
    base_map = materials.wave_scores(meta["baseline_wave"], cutoff)
    end_map = materials.wave_scores(meta["endline_wave"], cutoff)
    att_desc = {"reading": {"attended": [], "not_attended": []}, "usual": {"all": []}}
    for pid, eo in end_map.items():
        if pid not in base_map:
            continue
        sid = people[pid]["school_id"]
        if sid not in arms:
            continue
        change = eo["score"] - base_map[pid]["score"]
        if arms[sid] == "reading":
            key = "attended" if eo["actually_attended"] > 0 else "not_attended"
            att_desc["reading"][key].append(change)
        else:
            att_desc["usual"]["all"].append(change)

    def mean(xs):
        return sum(xs) / len(xs) if xs else None

    descriptive = {
        "note": "描述性统计，不构成因果结论",
        "reading_attended_mean_change": _round(mean(att_desc["reading"]["attended"])),
        "reading_attended_n": len(att_desc["reading"]["attended"]),
        "reading_not_attended_mean_change": _round(mean(att_desc["reading"]["not_attended"])),
        "reading_not_attended_n": len(att_desc["reading"]["not_attended"]),
        "usual_mean_change": _round(mean(att_desc["usual"]["all"])),
        "usual_n": len(att_desc["usual"]["all"]),
    }

    # 失访诊断
    rec = {}
    for arm_name in ("reading", "usual"):
        sids = [s for s, a in arms.items() if a == arm_name]
        persons = [p for p in people.values() if p["school_id"] in sids]
        got = sum(1 for p in persons if p["id"] in end_map)
        rec[arm_name] = {"returned": got, "roster": len(persons)}
    z = stats.two_proportion_z(
        rec["reading"]["returned"], rec["reading"]["roster"],
        rec["usual"]["returned"], rec["usual"]["roster"],
    )
    attrition = {"by_arm": rec, "z": _round(z), "differential": abs(z) >= 1.96}

    # 后续期波次描述（排除截止前已确认扩围的学校）
    followups = []
    confirmed = [
        r for r in materials.rollout
        if r["confirmed_on"] <= cutoff
    ]
    for w in materials.followup_waves(trial_id):
        scores = materials.wave_scores(w, cutoff)
        if not scores:
            continue
        affected = sorted({r["school_id"] for r in confirmed if r["start"] <= w})
        by_arm = {}
        for pid, o in scores.items():
            sid = people[pid]["school_id"]
            if sid not in arms or sid in affected:
                continue
            by_arm.setdefault(arms[sid], []).append(o["score"])
        followups.append({
            "wave": w,
            "note": "后续期描述，已排除截止前确认扩围的学校：" + ("、".join(affected) if affected else "无"),
            "excluded_schools": affected,
            "means": {a: _round(mean(v)) for a, v in by_arm.items()},
            "n": {a: len(v) for a, v in by_arm.items()},
        })

    # 质量检查快照（同一截止时点）
    qc = run_qc(materials, trial_id, cutoff)

    limitations = _limitations(materials, registration, qc, attrition, itt, meta, confirmed, cutoff)

    return {
        "code_version": CODE_VERSION,
        "trial_id": trial_id,
        "look_number": look_number,
        "cutoff": cutoff,
        "nominal_alpha": alpha,
        "primary": registration.primary,
        "dataset": meta,
        "itt": {
            "estimate": itt.estimate,
            "se": itt.se,
            "df": itt.df,
            "n": itt.n,
            "clusters": itt.clusters,
            "baseline_coef": itt.beta[2],
        },
        "decision": {
            "code": decision.code,
            "ci_lo": decision.lo,
            "ci_hi": decision.hi,
            "mcid": decision.mcid,
            "includes_zero": decision.includes_zero,
            "significant": decision.significant,
        },
        "permutation": {"p": perm_p, "permutations": perm_total, "statistic": perm_stat},
        "descriptive": descriptive,
        "attrition": attrition,
        "followups": followups,
        "qc": qc,
        "limitations": limitations,
    }


def _round(x, nd=4):
    return None if x is None else round(x, nd)


def _limitations(materials, registration, qc, attrition, itt, meta, confirmed, cutoff):
    out = []
    if itt.clusters < 30:
        out.append(
            f"聚类数较少（{itt.clusters} 所学校），采用 CR1 小样本修正与 t(G-1) 近似，"
            "区间较宽属预期；结论对学校层异常值敏感。"
        )
    out.extend(qc["confound_warnings"])
    if attrition["differential"]:
        out.append(
            "两组回收率差异达到诊断阈值（|z|≥1.96），完整病例分析可能受失访偏倚影响；"
            "本方案不做事后插补，结论按完整病例口径解释。"
        )
    if qc["cross_arm_teachers"]:
        who = "、".join(c["teacher_id"] for c in qc["cross_arm_teachers"])
        out.append(
            f"存在跨组任职教师（{who}），对照组可能部分暴露于干预，"
            "估计偏向稀释真实效果，解释时按下限情景对待。"
        )
    if qc["cross_school_households"]:
        out.append(
            f"发现 {qc['cross_school_households']} 户跨校家庭，学校层聚类未覆盖该层非独立性，"
            "标准误可能略偏乐观。"
        )
    if meta["late_after_cutoff"]:
        out.append(
            "存在截止后到达的记录（" + "、".join(meta["late_after_cutoff"]) +
            "），本次正式分析未纳入；其影响须通过复议或后续正式机会处理，不得静默改数。"
        )
    if confirmed:
        out.append(
            "截止前已有扩围确认（" + "、".join(r["id"] for r in confirmed) +
            "），相关学校退出对照，后续期描述性对照范围相应缩小。"
        )
    out.append(
        "抽样基础权重未用于主分析（登记口径为未加权估计）；如需加权结论须另行登记敏感性分析。"
    )
    return out
