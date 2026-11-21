"""正式发布报告渲染（中文 Markdown）。

判定措辞固定，遵守两条护栏：不显著不得说成“没有效果”，
区间尚宽不得说成“已证实有效”。
"""
from __future__ import annotations

from . import stats

DECISION_TEXT = {
    stats.MEETS_MCID: "区间下限达到事前声明的最小有意义改善，判定：达到最小有意义改善。",
    stats.BELOW_MCID: "区间上限低于最小有意义改善，判定：现有证据排除了最小有意义改善。",
    stats.INCONCLUSIVE: "区间跨过最小有意义改善，判定：证据不足，无法判定是否达到最小有意义改善。",
}


def _decision_paragraph(d):
    base = DECISION_TEXT[d["code"]]
    if d["code"] == stats.MEETS_MCID:
        extra = "该判定仅针对事前声明的主结果与最小有意义改善，不意味着所有学校、所有条件下均有同等效果。"
    elif d["code"] == stats.BELOW_MCID:
        if d["includes_zero"]:
            extra = (
                "区间包含零：不能表述为“没有效果”，也不能表述为“已证实有效”；"
                "其含义是在当前风险预算下，达到最小有意义改善的可能性被排除。"
            )
        elif d["ci_lo"] > 0:
            extra = "区间整体位于零以上：存在改善迹象，但未达事前声明的有意义水平，不得按此宣称达标。"
        else:
            extra = "区间整体位于零以下：证据指向不利方向，应按风险预案处理并暂停相关扩围。"
    else:
        extra = "证据不足不等于无效，也不等于有效；不得据此作双向宣称。"
    return base + extra


def render_report(registration, release):
    """registration 为 Registration，release 为 registry.Release（含 result）。"""
    r = release.result
    dec = r["decision"]
    itt = r["itt"]
    lines = []
    lines.append(f"# 正式发布报告 {release.release_id}（试验 {registration.trial_id}）")
    lines.append("")
    lines.append(
        f"第 {release.look_number} 次正式查看（共 {registration.formal_looks} 次）；"
        f"资料截止 {release.cutoff}；发布日 {release.issued_on}；"
        f"人工决定引用：{release.decision_reference}"
    )
    lines.append(
        f"本次消耗名义风险 {r['nominal_alpha']:.4f}（整体预算 {registration.alpha}，"
        "OB 形消耗，登记时冻结）"
    )
    lines.append(
        f"数据指纹 {r['dataset']['dataset_fingerprint'][:16]}…；"
        f"代码版本 {r['code_version']}；可用 `verify` 复现"
    )
    lines.append("")
    lines.append("## 事前声明摘要")
    lines.append(
        f"分配单位：{registration.unit}；主结果：{registration.primary}；"
        f"最小有意义改善：{registration.minimum_gain}；"
        f"正式查看日：{', '.join(registration.look_dates)}"
    )
    lines.append("")
    lines.append("## 数据核对（截止时点）")
    ds = r["dataset"]
    lines.append(
        f"名册 {ds['roster']} 人；进入主分析 {ds['analyzed']} 人；"
        f"期末未回收 {ds['missing_endline']} 人；基线缺失 {ds['missing_baseline']} 人；"
        f"截止后到达未纳入 {len(ds['late_after_cutoff'])} 条"
    )
    att = r["attrition"]
    ztxt = f"，失访差异 z={att['z']}" + ("（达到诊断阈值）" if att["differential"] else "")
    lines.append(
        "回收率："
        + "，".join(
            f"{a} 组 {v['returned']}/{v['roster']}" for a, v in sorted(att["by_arm"].items())
        )
        + ztxt
    )
    lines.append("")
    lines.append("## 主分析（按分配，ITT）")
    lines.append(
        f"ANCOVA（期末 ~ 分组 + 基线），学校层 CR1 聚类稳健标准误，t({itt['df']})："
    )
    lines.append(
        f"估计 {itt['estimate']:.3f}，标准误 {itt['se']:.3f}，"
        f"{1 - r['nominal_alpha']:.1%} 区间 [{dec['ci_lo']:.3f}, {dec['ci_hi']:.3f}]，"
        f"学校数 {itt['clusters']}，学生数 {itt['n']}"
    )
    lines.append(
        f"置换检验（学校层精确置换 {r['permutation']['permutations']} 次）："
        f"p={r['permutation']['p']:.4f}（稳健性参考）"
    )
    lines.append("")
    lines.append("## 判定")
    lines.append(_decision_paragraph(dec))
    lines.append("")
    lines.append("## 描述性补充（非因果）")
    d = r["descriptive"]

    def _fmt(v, n):
        return "—（无观测）" if n == 0 else f"{v}（n={n}）"

    lines.append(
        f"实际参加者（干预组）平均变化 {_fmt(d['reading_attended_mean_change'], d['reading_attended_n'])}；"
        f"干预组未参加者平均变化 {_fmt(d['reading_not_attended_mean_change'], d['reading_not_attended_n'])}；"
        f"对照组平均变化 {_fmt(d['usual_mean_change'], d['usual_n'])}。"
        "参加者自选择，以上仅为描述。"
    )
    for f in r["followups"]:
        lines.append(
            f"后续期 {f['wave']}：均值 {f['means']}（n={f['n']}）；{f['note']}"
        )
    lines.append("")
    lines.append("## 适用条件与解释限制")
    for w in r["limitations"]:
        lines.append(f"- {w}")
    lines.append("")
    lines.append("## 对扩围的含义")
    if dec["code"] == stats.MEETS_MCID:
        lines.append(
            "结论达到事前声明标准，可作为下一批扩围的证据之一；"
            "逐校是否纳入仍须通过证据覆盖、共享教师与课时校验。"
        )
    else:
        lines.append(
            "当前证据不支持新的扩围确认；已有承诺如与本结论口径冲突，应进入复议清单。"
        )
    lines.append("")
    return "\n".join(lines)
