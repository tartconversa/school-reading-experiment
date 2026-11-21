"""检查演练资料的结构、编号及外键，不作分析或业务裁决。

结构核对的唯一实现位于 readingtrial.materials.read_materials，
本脚本保留原有命令行入口与输出格式。
"""
from pathlib import Path
import json

from readingtrial.materials import read_materials

__all__ = ["read_materials"]

if __name__ == "__main__":
    _, receipt = read_materials(Path(__file__).resolve().parent / "materials")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
