# 最小 Stage A 本地工具：交接

本轮只有实现与零求解测试。CP-SAT Solve / Oracle Solve / benchmark / Stage A 均未执行。
真实运行仍等待用户代码审查与单独批准；`--execute` 是手动操作开关，不是授权凭据。
旧门禁和研究成果保留；此入口不依赖签名、Journal、冻结 Manifest，也不继承旧框架全部保证。

## 新增文件与复用

| 文件 | 必要性 |
| --- | --- |
| `run.py` | 顺序执行、保存与验收；已有执行器强制依赖旧审批框架。 |
| `config.json` | 唯一可读任务计划、参数和候选资源限制。 |
| `analyze.py` | 生成 8 组对照表及可选 CSV；无需新统计平台。 |
| `test_run.py` | 验证新接线，复用已有 ZeroSolveGuard 和 Mock reader。 |
| `README.md` | 本份命令、证据与限制说明。 |

复用 `baseline_common.load_instance` 的完整输入验证、`research.symmetry_integration`
的模型准备/统计/解提取、原 `research.tiny_oracle.solve`、`validate_solution` 的独立物理验证，
以及已有 `_supervise` / `DummyStage` / Windows Job Object。没有重写算法或监管器。
所有既有 tracked 文件与基线 `5a95af6e7326278f2b3c61b8cec24918fa5b3141` 相同。

## 命令

在仓库根目录，使用 Windows、Python 3.12.11 / OR-Tools 9.14.6206 环境（本轮验证版本）：

```powershell
python -B -m research.simple_experiment.run                     # 默认只显示计划
python -B -m research.simple_experiment.test_run                # 零求解测试
# 仅在用户完成审查、另行明确批准之后：
python -B -m research.simple_experiment.run --execute
python -B -m research.simple_experiment.analyze <run-directory>  # 可加 --csv <新文件.csv>
```

每次新建 `results/simple-experiment/<UTC>_<随机ID>`，拒绝覆盖。
第一个失败、非 OPTIMAL、物理解/资源验收失败或 Oracle 分歧即停止，退出码非零；不重试、不续跑。

## 固定 32 项计划

每行依次 ORACLE → M0（无手工 Prefix）→ M1（Forward）→ M2（Reverse）；编号从 0 开始。

| 实例 | volume 编号 | count 编号 |
| --- | --- | --- |
| T00 | 0–3 | 4–7 |
| T01 | 8–11 | 12–15 |
| T02 | 16–19 | 20–23 |
| T03 | 24–27 | 28–31 |

合计 8 Oracle + 24 CP-SAT。workers=1、seed=0、LP=2、symmetry_level=2、原索引顺序、
无 hints、无额外 volume bound。CP 内部 2s；Oracle 200000 节点。
复用现有 helper 的 presolve/probing 设置，保存实际完整参数。
候选外部停止阈值：单项 4.5s、整体 170s、累计子进程 CPU 110s、Job commit 256MiB；
轮询 10ms、清理宽限 1s。只为本研究进程及子进程设置数值库线程为 1。
这些阈值尚未证明真实任务能完成，轮询与清理可能产生超出阈值的时间。

每项保存输入、配置/任务、worker 原始结果、OS 资源/清理记录、独立验证结果；CP 另存原始
response protobuf 与可用日志。记录 Git SHA/dirty、Python/OR-Tools 版本、目标/模型/seed、
状态、incumbent、可用 bound、Solve 调用时间、分支/冲突/LP、有限轨迹、见证和失败原因。
外部 wall/CPU/commit peak 单独记录；不可用 LP/presolve 统计保持不可用，不推断为 0。
UNKNOWN 没有可用目标/bound/见证；FEASIBLE 保留但不能通过精确最优比较；Oracle 耗尽记
INCOMPLETE，没有 CP bound。真正 OPTIMAL 的空见证 0 可以通过。独立重算目标并核查
M1/M2 标签，再与只接收原始输入、不接收 CP 解或 Prefix 规则的 Oracle 比较。

## 验证与剩余问题

2026-10-28：8 项测试通过（unittest 1.712s），语法与 32 项计划校验通过。
Guard 在模型/测试导入前启用：blocked `{cpsat_api:0,native_factory:0,oracle:0}`；
executed CP/Oracle 均为 0。全部 worker 启动被 Mock；没有实验或 Dummy 子进程。
覆盖 4×2×3 Proto（仅去掉 Prefix 后与生产构造器一致）、同输入、目标单位、物理解拒绝、
空解/UNKNOWN、Oracle 耗尽、资源/清理拒绝、新目录、完整模拟 32 项和首次分歧停止。
模拟回复不是计算得到的 fixture 最优值。Oracle 仍为 7432 bytes，SHA-256：
`8dcb6fac0ea7ec29a622b4400ef51d0520ded4f5f3d709962ccb224bbd0d93b8`。

待解决：用户审查/运行批准，以及新接线的首次真实 Windows 运行。Mock 通过不证明 OS 行为、
4.5s 启动余量或 256MiB 余量。强制终止/崩溃可能没有保存 incumbent，记 null 并停止；
解释器异常崩溃可能只有 OS 退出/缺文件诊断。每文件 1MiB 上限超出即失败，不静默截断。
复用回调尚无 A/A 开销校准；Stage A 只做正确性交叉验证，不用于 Stage B 机制结论。
不新增 Issue/PR，不实现 Stage B。
