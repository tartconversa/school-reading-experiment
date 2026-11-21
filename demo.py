"""端到端演练：用合成资料完整走一遍登记到扩围的流程。

运行：python3 demo.py [状态目录]（默认 demo_state/，已存在时先清空重建）。
每一步对应一类业务动作；被规则阻断的动作也会展示，以验证口径。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from readingtrial.cli import main

STATE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo_state")


def run(title, argv, expect_block=False):
    print("\n" + "=" * 72)
    print("【" + title + "】")
    print("$ readingtrial " + " ".join(argv))
    print("-" * 72)
    try:
        main(["--state", str(STATE)] + argv)
    except SystemExit as exc:
        if expect_block and exc.code == 2:
            print("（按预期被规则阻断）")
            return
        raise
    if expect_block:
        raise AssertionError("该动作应被阻断却通过了：" + title)


def main_demo():
    if STATE.exists():
        shutil.rmtree(STATE)
    STATE.mkdir(parents=True)

    run("1. 登记：冻结事前声明，导入历史发布与已确认排课",
        ["register", "--materials", "materials"])

    run("2. 质量检查（非正式）：回收率、分组比例、教师共享，不消耗正式机会",
        ["qc", "--as-of", "2026-06-30"])

    run("3. 第 1 次正式查看：绑定历史发布 H1，计算并冻结结论",
        ["analyze", "--look", "1", "--cutoff", "2026-06-30",
         "--issued", "2026-07-01", "--ref", "研究会纪要A"])

    run("4. 任职更正到达后的质量检查（仍是非正式）",
        ["qc", "--as-of", "2026-07-10"])

    run("5. 第 2 次正式查看：截止 2026-09-30，含后续期描述",
        ["analyze", "--look", "2", "--cutoff", "2026-09-30",
         "--issued", "2026-10-05", "--ref", "研究会纪要B"])

    run("6. 试图进行登记外的第 3 次正式查看",
        ["analyze", "--look", "3", "--cutoff", "2026-10-31", "--issued", "2026-11-01"],
        expect_block=True)

    run("7. 全部正式查看完成，负责人解除对照保留",
        ["release-controls", "--by", "试验负责人", "--on", "2026-10-06"])

    run("8. 研究员提出下一批扩围方案（草稿）：含超资源与不合规项",
        ["propose", "--item", "C2:T2:3", "--item", "C4:T4:3", "--item", "C6:T6:3",
         "--item", "C8:T2:3", "--item", "C10:T3:3", "--item", "C9:T3:3",
         "--note", "下一批城区校"])

    run("9. 证据不足且有待复议事项时试图确认",
        ["confirm", "--proposal", "P1", "--school", "C2",
         "--on", "2026-10-15", "--start", "2026-11-01"],
        expect_block=True)

    run("10. 负责人暂停有疑问学校；已开始教学不回退",
        ["pause", "--school", "C4", "--reason", "家长投诉待核",
         "--by", "试验负责人", "--on", "2026-10-07"])

    run("11. 办结部分复议事项（其余保留）",
        ["resolve", "--key", "OVERBOOK:T1", "--by", "试验负责人",
         "--note", "J13 更正后 T1 超占 1h；R1 未开始，拟改派或缩减，另行登记"])

    run("12. 再次试图确认（仍有未办结复议且证据不足）",
        ["confirm", "--proposal", "P1", "--school", "C2",
         "--on", "2026-10-15", "--start", "2026-11-01"],
        expect_block=True)

    run("13. 完整追踪：结论链、每校可扩围依据、课时占用、待复议",
        ["trace"])

    run("14. 复核：统计可复现 + 业务联动一致",
        ["verify"])

    print("\n演练完成。状态与报告位于 " + str(STATE.resolve()))


if __name__ == "__main__":
    main_demo()
