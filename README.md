# 跨校阅读干预的实验判定与扩围接管

本仓库包含两部分：

1. **合成资料与资料检查工具**（原有）：`materials/` 下的演练数据与 `inspect_materials.py` 结构核对。所有人员、学校、机构、价格和业务记录均为演练数据。
2. **实验分析应用**（`readingtrial/` 包）：从试验登记、数据核对到扩围决定的完整流程，仅使用 Python 3.11 标准库。

资料契约见 [资料契约.md](资料契约.md)；统计方案与适用条件见 [统计方案.md](统计方案.md)。

## 应用做什么

- **登记冻结**：登记时冻结分配单位、主结果、观测窗口、正式查看次数与逐次名义风险；登记后不能按“哪项指标显著”更换主结果或方法。
- **三种动作分开**：质量检查（回收率、分组比例、教师共享）不消耗也不伪装成正式结论；正式查看按编号消耗并记录资料截止；排课确认是另一套业务动作。
- **正式分析**：以学校为分配单位的 ITT 主估计（ANCOVA + 学校层聚类稳健标准误），对照事前声明的最小有意义改善与风险预算作三分类判定；失访、混杂、跨组接触自动写入解释限制。
- **扩围联动**：逐校评估证据覆盖、共享教师暴露与可兑现课时；证据不足或有未办结复议时停止新确认；资源不足只记“未纳入”，绝不回写为试验失败；已开始的教学不因复议自动回退。
- **可复现**：每次发布记录数据指纹与代码版本，`verify` 可从原始资料重算并核对业务联动。

## 快速开始

Linux 用 `python3`，Windows 用 `python`。无需第三方依赖。

```sh
python3 demo.py                 # 端到端演练（状态写入 demo_state/）
python3 inspect_materials.py    # 资料结构核对
python3 -m unittest discover -s tests -v
```

手工逐步操作（状态目录可另行指定）：

```sh
python3 -m readingtrial --state state register --materials materials
python3 -m readingtrial --state state qc --as-of 2026-06-30
python3 -m readingtrial --state state analyze --look 1 --cutoff 2026-06-30 --issued 2026-07-01 --ref 研究会纪要A
python3 -m readingtrial --state state analyze --look 2 --cutoff 2026-09-30 --issued 2026-10-05 --ref 研究会纪要B
python3 -m readingtrial --state state propose --item C2:T2:3 --item C4:T4:3
python3 -m readingtrial --state state reviews
python3 -m readingtrial --state state trace
python3 -m readingtrial --state state verify
```

全部子命令见 `python3 -m readingtrial --help`。

## 目录说明

- `readingtrial/`：应用包（stats 统计原语、materials 资料视图、registry 登记、quality 质量检查、analysis 正式分析、expansion 扩围、ledger 事件账本、report 报告、cli 入口）
- `materials/`：合成输入资料（只读；运行状态与报告写入 `--state` 指定目录）
- `tests/`：统计数值、端到端流程与扩围机制测试
- `demo.py`：端到端演练脚本

原始资料保留不变；`state/`、`demo_state/` 等运行产物不入库。
