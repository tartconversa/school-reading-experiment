"""命令行入口：登记、质量检查、正式分析、扩围与复核追踪。

用法概览（Linux 用 python3，Windows 用 python）：
  python3 -m readingtrial register --materials materials --state state
  python3 -m readingtrial qc --state state [--as-of 2026-06-30]
  python3 -m readingtrial analyze --state state --look 1 --cutoff 2026-06-30 --issued 2026-07-01 --ref 研究会纪要A
  python3 -m readingtrial propose --state state --item C8:T2:3 ...
  python3 -m readingtrial confirm --state state --proposal P1 --school C8 --on 2026-10-15 --start 2026-11-01
  python3 -m readingtrial reviews|resolve|pause|release-controls|status|trace|verify ...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import analysis, expansion, quality, report as report_mod
from .ledger import LedgerError, Store
from .materials import load_materials
from .registry import Registration


class CliError(Exception):
    pass


def _store(args):
    return Store(args.state)


def _materials(st):
    if not st.materials_path:
        raise CliError("尚未登记，请先运行 register")
    return load_materials(st.materials_path)


def _require_registration(st):
    if st.registration is None:
        raise CliError("尚未登记，请先运行 register")


# ---------------------------------------------------------------- 登记


def cmd_register(args):
    store = _store(args)
    if store.events():
        raise CliError("状态目录已有账本，不能重复登记；如需重来请更换状态目录")
    materials = load_materials(args.materials)
    if len(materials.protocols) != 1:
        raise CliError("本应用一次登记一项试验")
    protocol = next(iter(materials.protocols.values()))
    reg = Registration.from_protocol(protocol)
    imported_releases = [
        h for h in materials.formal_history if h["trial_id"] == reg.trial_id
    ]
    for h in imported_releases:
        if not 1 <= h["look_number"] <= reg.formal_looks:
            raise CliError(f"历史发布 {h['id']} 的查看编号超出登记计划")
        if h["cutoff"] > reg.look_dates[h["look_number"] - 1]:
            raise CliError(f"历史发布 {h['id']} 的截止晚于事前声明查看日")
    imported_confirmations = [dict(r) for r in materials.rollout]
    payload = {
        "trial_id": reg.trial_id,
        "registered_on": reg.registered_on,
        "unit": reg.unit,
        "primary": reg.primary,
        "minimum_gain": reg.minimum_gain,
        "alpha": reg.alpha,
        "formal_looks": reg.formal_looks,
        "look_dates": list(reg.look_dates),
        "resource_hours": reg.resource_hours,
        "nominal_alphas": list(reg.nominal_alphas),
        "materials_path": str(Path(args.materials).resolve()),
        "materials_sha": materials.receipt["sha256"],
        "imported_releases": imported_releases,
        "imported_confirmations": imported_confirmations,
    }
    store.append("REGISTER", payload)
    st = store.state()
    print(f"已登记试验 {reg.trial_id}：单位 {reg.unit}，主结果 {reg.primary}，"
          f"最小有意义改善 {reg.minimum_gain}，整体风险 {reg.alpha}")
    print("逐次名义风险（冻结）："
          + "，".join(f"第{i+1} 次 {a:.4f}" for i, a in enumerate(reg.nominal_alphas)))
    print(f"导入历史发布 {len(imported_releases)} 条、已确认排课 {len(imported_confirmations)} 条")
    reviews = expansion.open_reviews(materials, st)
    print(f"登记即发现待复议事项 {len(reviews)} 条（详见 reviews 命令）")
    for item in reviews:
        print(f"  [{item['kind']}] {item['message']}")


# ---------------------------------------------------------------- 质量检查


def cmd_qc(args):
    store = _store(args)
    st = store.state()
    _require_registration(st)
    materials = _materials(st)
    as_of = args.as_of or materials.latest_receipt()
    result = quality.run_qc(materials, st.registration.trial_id, as_of)
    store.append("QC", {"as_of": as_of, "summary": {"recovery": result["recovery_by_wave"]}})
    print(quality.format_qc(result))
    print(f"\n（本次为第 {len(st.qc_runs) + 1} 次质量检查；正式查看机会未受影响，"
          f"已用 {sum(1 for r in st.releases if r.result)}/{st.registration.formal_looks} 次）")


# ---------------------------------------------------------------- 正式分析


def cmd_analyze(args):
    store = _store(args)
    st = store.state()
    _require_registration(st)
    reg = st.registration
    materials = _materials(st)
    existing = st.release_by_look(args.look)
    if existing is not None and existing.result is not None:
        raise CliError(f"第 {args.look} 次正式查看已有发布结果，不得改写；可用 verify 复核")
    if existing is not None and existing.cutoff != args.cutoff:
        raise CliError(
            f"历史发布 {existing.release_id} 登记的截止为 {existing.cutoff}，"
            f"与请求 {args.cutoff} 不一致"
        )
    consumed = [r for r in st.releases if r.result is not None]
    reg.check_look(args.look, args.cutoff, [
        {"look_number": r.look_number, "cutoff": r.cutoff} for r in consumed
    ])
    if args.issued < args.cutoff:
        raise CliError("发布日不得早于资料截止日")
    result = analysis.run_formal(materials, reg, args.look, args.cutoff)
    release_id = existing.release_id if existing else f"F{args.look}"
    ref = args.ref or (existing.decision_reference if existing else "")
    store.append("RELEASE", {
        "release_id": release_id,
        "look_number": args.look,
        "cutoff": args.cutoff,
        "issued_on": args.issued,
        "decision_reference": ref,
        "result": result,
    })
    st = store.state()
    release = st.release_by_look(args.look)
    text = report_mod.render_report(reg, release)
    report_path = Path(args.state) / f"report_{release_id}.md"
    report_path.write_text(text, encoding="utf-8")
    dec = result["decision"]
    print(f"正式发布 {release_id}：第 {args.look} 次查看，截止 {args.cutoff}")
    print(f"ITT 估计 {result['itt']['estimate']:.3f}（SE {result['itt']['se']:.3f}），"
          f"区间 [{dec['ci_lo']:.3f}, {dec['ci_hi']:.3f}]，判定 {dec['code']}")
    print(f"报告已写入 {report_path}")
    reviews = expansion.open_reviews(materials, st)
    if reviews:
        print(f"当前待复议事项 {len(reviews)} 条：")
        for item in reviews:
            print(f"  [{item['kind']}] {item['message']}")


# ---------------------------------------------------------------- 扩围


def _parse_items(items):
    out = []
    for raw in items or []:
        try:
            school, teacher, hours = raw.split(":")
            out.append((school, teacher, float(hours)))
        except ValueError:
            raise CliError(f"方案项格式应为 学校:教师:小时，收到 {raw}")
    return out


def cmd_propose(args):
    store = _store(args)
    st = store.state()
    _require_registration(st)
    materials = _materials(st)
    items = _parse_items(args.item)
    if not items:
        raise CliError("方案至少包含一项 学校:教师:小时")
    pid = args.id or f"P{len(st.proposals) + 1}"
    if pid in st.proposals:
        raise CliError(f"方案编号 {pid} 已存在")
    proposal = expansion.make_proposal(materials, st, pid, items, note=args.note or "")
    store.append("PROPOSE", proposal)
    print(f"方案 {pid} 已登记（草稿，不代表已确认）：")
    for i in proposal["items"]:
        line = f"  {i['school_id']} + {i['teacher_id']} {i['weekly_hours']}h -> {i['status']}"
        for p in i.get("problems", []):
            line += f"\n    阻断：{p}"
        for n in i.get("notes", []):
            line += f"\n    提示：{n}"
        print(line)
    print(f"本方案拟占课时 {proposal['placed_hours']:.1f}h")
    gate = expansion.check_confirmable(materials, store.state())
    if gate:
        print("注意：当前不具备确认条件——" + "；".join(gate))


def cmd_confirm(args):
    store = _store(args)
    st = store.state()
    _require_registration(st)
    materials = _materials(st)
    proposal = st.proposals.get(args.proposal)
    if proposal is None:
        raise CliError(f"方案 {args.proposal} 不存在")
    try:
        confirmation = expansion.confirm(
            materials, st, proposal, args.school, args.on, args.start
        )
    except expansion.ConfirmBlocked as exc:
        raise CliError(f"确认被阻断：{exc}")
    store.append("CONFIRM", confirmation)
    print(f"已确认 {confirmation['id']}：{args.school} 由 {confirmation['teacher_id']} "
          f"每周 {confirmation['weekly_hours']}h，{confirmation['start']} 起接管")


def cmd_pause(args):
    store = _store(args)
    st = store.state()
    _require_registration(st)
    store.append("PAUSE", {
        "school_id": args.school, "reason": args.reason,
        "by": args.by, "on": args.on,
    })
    started = [
        c for c in st.confirmations
        if c["school_id"] == args.school and c.get("started")
    ]
    print(f"已暂停 {args.school} 的新确认：{args.reason}")
    if started:
        print("该校已有实际开始的教学，暂停不回退既有教学，仅阻断新的确认")


def cmd_release_controls(args):
    store = _store(args)
    st = store.state()
    _require_registration(st)
    reg = st.registration
    done = sum(1 for r in st.releases if r.result)
    if done < reg.formal_looks:
        raise CliError(
            f"正式查看仅完成 {done}/{reg.formal_looks} 次，对照保留不能解除"
        )
    store.append("RELEASE_CONTROLS", {"by": args.by, "on": args.on})
    print("对照保留已解除，相关学校可进入扩围候选评估")


# ---------------------------------------------------------------- 复议


def cmd_reviews(args):
    store = _store(args)
    st = store.state()
    _require_registration(st)
    materials = _materials(st)
    items = expansion.open_reviews(materials, st)
    if not items:
        print("无待复议事项")
        return
    print(f"待复议事项 {len(items)} 条：")
    for i in items:
        print(f"  {expansion.review_key(i)}  {i['message']}")


def cmd_resolve(args):
    store = _store(args)
    st = store.state()
    _require_registration(st)
    materials = _materials(st)
    keys = {expansion.review_key(i) for i in expansion.compute_reviews(materials, st)}
    if args.key not in keys:
        raise CliError(f"复议事项 {args.key} 不存在（当前推导出的清单见 reviews）")
    if args.key in st.resolutions:
        raise CliError(f"复议事项 {args.key} 已办结，不得重复办结")
    store.append("RESOLVE", {"key": args.key, "by": args.by, "note": args.note})
    print(f"已办结 {args.key}：{args.note}")


# ---------------------------------------------------------------- 状态与追踪


def cmd_status(args):
    store = _store(args)
    st = store.state()
    _require_registration(st)
    materials = _materials(st)
    reg = st.registration
    done = [r for r in st.releases if r.result]
    print(f"试验 {reg.trial_id}：正式查看已用 {len(done)}/{reg.formal_looks} 次")
    for r in st.releases:
        if r.result:
            d = r.result["decision"]
            print(f"  {r.release_id}：第 {r.look_number} 次，截止 {r.cutoff}，判定 {d['code']}")
        else:
            print(f"  {r.release_id}：第 {r.look_number} 次，截止 {r.cutoff}（历史导入，结果待计算）")
    budget = expansion.budget_table(st)
    print(f"扩围课时预算：{budget['used']:.1f}/{budget['total']:.1f}h 已用")
    reviews = expansion.open_reviews(materials, st)
    print(f"待复议事项 {len(reviews)} 条；暂停学校 {len(st.paused)} 所；"
          f"对照保留{'已解除' if st.controls_released else '生效中'}")


def cmd_trace(args):
    store = _store(args)
    st = store.state()
    _require_registration(st)
    materials = _materials(st)
    reg = st.registration
    print(f"== 试验 {reg.trial_id} 追踪 ==")
    print(f"登记 {reg.registered_on}：单位 {reg.unit}，主结果 {reg.primary}，"
          f"MCID {reg.minimum_gain}，风险 {reg.alpha}，查看 {reg.formal_looks} 次")
    print("\n-- 正式结论链 --")
    for r in st.releases:
        if r.result:
            d = r.result["decision"]
            fp = r.result["dataset"]["dataset_fingerprint"][:12]
            print(f"  {r.release_id}（第 {r.look_number} 次，截止 {r.cutoff}，发布 {r.issued_on}）："
                  f"{d['code']}，区间 [{d['ci_lo']:.2f}, {d['ci_hi']:.2f}]，指纹 {fp}…")
        else:
            print(f"  {r.release_id}（第 {r.look_number} 次，截止 {r.cutoff}）：历史导入，结果待计算")
    print(f"  质量检查 {len(st.qc_runs)} 次（非正式，不计入上链）")
    print("\n-- 每所学校的可扩围依据 --")
    kept = expansion.kept_control_schools(materials, st)
    for sid in sorted(materials.schools):
        arm = materials.arm_of(sid, reg.trial_id)
        marks = []
        if arm == "reading":
            marks.append("干预组")
        elif sid in kept:
            marks.append("保留对照")
        if any(c["school_id"] == sid for c in st.confirmations):
            c = next(c for c in st.confirmations if c["school_id"] == sid)
            marks.append(f"已确认扩围 {c['id']}（{'已开始' if c.get('started') else '未开始'}）")
        if sid in st.paused:
            marks.append(f"已暂停：{st.paused[sid]}")
        blocks, notes = expansion.evaluate_candidate(materials, st, sid)
        if not blocks and not notes:
            marks.append("可作为候选")
        for b in blocks:
            marks.append("阻断-" + b)
        for n in notes:
            marks.append("提示-" + n)
        print(f"  {sid}：" + "；".join(dict.fromkeys(marks)))
    print("\n-- 实际占用课时 --")
    for tid, row in expansion.teacher_table(materials, st).items():
        print(f"  {tid}：可用 {row['hours']}h，任职 {row['links']}h，"
              f"扩围 {row['rollout']}h，剩余 {row['remaining']}h")
    budget = expansion.budget_table(st)
    print(f"  预算：{budget['used']:.1f}/{budget['total']:.1f}h")
    print("\n-- 待复议事项 --")
    reviews = expansion.open_reviews(materials, st)
    if not reviews:
        print("  无")
    for i in reviews:
        print(f"  {expansion.review_key(i)}  {i['message']}")
    dropped = [
        (pid, i) for pid, p in st.proposals.items() for i in p["items"]
        if i["status"] == expansion.DROPPED_RESOURCE
    ]
    if dropped:
        print("\n-- 资源不足未纳入（不是试验失败）--")
        for pid, i in dropped:
            print(f"  方案 {pid}：{i['school_id']}（{i['teacher_id']} {i['weekly_hours']}h）")


# ---------------------------------------------------------------- 复核


def cmd_verify(args):
    store = _store(args)
    st = store.state()
    _require_registration(st)
    failures = []

    def check(ok, label):
        print(("PASS " if ok else "FAIL ") + label)
        if not ok:
            failures.append(label)

    materials = _materials(st)
    check(materials.receipt["sha256"] == st.materials_sha, "原始资料指纹与登记时一致")

    reg = st.registration
    done = [r for r in st.releases if r.result]
    check(len(done) <= reg.formal_looks, "正式查看次数未超登记上限")
    looks = sorted(r.look_number for r in done)
    check(looks == list(range(1, len(looks) + 1)), "正式查看按序消耗")
    cutoffs = [r.cutoff for r in sorted(done, key=lambda r: r.look_number)]
    check(cutoffs == sorted(cutoffs) and len(set(cutoffs)) == len(cutoffs), "资料截止严格递增")

    for r in done:
        again = analysis.run_formal(materials, reg, r.look_number, r.cutoff)
        same_fp = again["dataset"]["dataset_fingerprint"] == r.result["dataset"]["dataset_fingerprint"]
        same_est = abs(again["itt"]["estimate"] - r.result["itt"]["estimate"]) < 1e-9
        same_dec = again["decision"]["code"] == r.result["decision"]["code"]
        check(same_fp and same_est and same_dec,
              f"发布 {r.release_id} 可由原始资料与截止日复现")

    seen = set()
    dup = [c["school_id"] for c in st.confirmations if c["school_id"] in seen or seen.add(c["school_id"])]
    check(not dup, "无学校被重复确认扩围")
    over = [
        tid for tid, row in expansion.teacher_table(materials, st).items()
        if row["committed"] > row["hours"]
    ]
    explained = {
        k.split(":", 1)[1] for k in list(st.resolutions)
        if k.startswith(expansion.OVERBOOK + ":")
    }
    open_over = expansion.open_reviews(materials, st)
    open_over_t = {i["target"] for i in open_over if i["kind"] == expansion.OVERBOOK}
    check(all(t in explained or t in open_over_t for t in over),
          "课时超占均有复议事项跟踪")
    check(all(i["status"] != "failed" for p in st.proposals.values() for i in p["items"]),
          "方案中不存在被记为失败的学校（资源不足只记为未纳入）")

    if failures:
        print(f"\n复核未通过：{len(failures)} 项")
        raise SystemExit(1)
    print("\n复核通过：统计可复现，业务联动一致")


# ---------------------------------------------------------------- 入口


def build_parser():
    p = argparse.ArgumentParser(prog="readingtrial", description=__doc__)
    p.add_argument("--state", default="state", help="状态目录（默认 state/）")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("register", help="登记试验并冻结事前声明")
    s.add_argument("--materials", required=True)
    s.set_defaults(fn=cmd_register)

    s = sub.add_parser("qc", help="质量检查（非正式）")
    s.add_argument("--as-of", default=None)
    s.set_defaults(fn=cmd_qc)

    s = sub.add_parser("analyze", help="执行一次正式查看并发布")
    s.add_argument("--look", type=int, required=True)
    s.add_argument("--cutoff", required=True)
    s.add_argument("--issued", required=True)
    s.add_argument("--ref", default="")
    s.set_defaults(fn=cmd_analyze)

    s = sub.add_parser("propose", help="研究员提出扩围方案（草稿）")
    s.add_argument("--id", default=None)
    s.add_argument("--item", action="append", help="学校:教师:小时，可重复")
    s.add_argument("--note", default="")
    s.set_defaults(fn=cmd_propose)

    s = sub.add_parser("confirm", help="校方确认方案中的一所学校")
    s.add_argument("--proposal", required=True)
    s.add_argument("--school", required=True)
    s.add_argument("--on", required=True, help="确认日")
    s.add_argument("--start", required=True, help="接管起日")
    s.set_defaults(fn=cmd_confirm)

    s = sub.add_parser("pause", help="试验负责人暂停某校新确认")
    s.add_argument("--school", required=True)
    s.add_argument("--reason", required=True)
    s.add_argument("--by", required=True)
    s.add_argument("--on", required=True)
    s.set_defaults(fn=cmd_pause)

    s = sub.add_parser("release-controls", help="解除对照保留（须完成全部正式查看）")
    s.add_argument("--by", required=True)
    s.add_argument("--on", required=True)
    s.set_defaults(fn=cmd_release_controls)

    s = sub.add_parser("reviews", help="列出待复议事项")
    s.set_defaults(fn=cmd_reviews)

    s = sub.add_parser("resolve", help="办结一条复议事项")
    s.add_argument("--key", required=True)
    s.add_argument("--by", required=True)
    s.add_argument("--note", required=True)
    s.set_defaults(fn=cmd_resolve)

    s = sub.add_parser("status", help="当前状态概览")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("trace", help="从试验到结论、扩围依据、课时与复议的完整追踪")
    s.set_defaults(fn=cmd_trace)

    s = sub.add_parser("verify", help="重新运行统计与业务联动验证")
    s.set_defaults(fn=cmd_verify)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.fn(args)
    except (CliError, LedgerError, ValueError) as exc:
        print("错误：" + str(exc), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
