# Competing Phases V5 — Materials Project ID 核对修正版

## 这次修复了什么

Materials Project 在 **2026-04-13** 更新后将默认 API ID 改成 AlphaID（字母编号），MP 网页则可能依照账户偏好显示数字编号。例如 `mp-149`、`mp-ft` 与 `mp-aaaaaaft` 表示 **同一个材料结构**。同时，一个材料 Material ID 可以对应多个 Task ID（每次 DFT 计算有独立 Task ID），不能混淆。

- **MP Number（数字材料编号）**：统一显示 `mp-<number>`，用于核对 Materials Explorer。
- **MP API Material ID**：额外保存 MP API 原始返回的字母/数字编号，不丢失来源。
- **Task Number / Task API ID**：单独显示实际计算任务的数字编号和原始 ID。
- **跨接口 ID 归一化**：Summary、Core、Thermo 三个接口即使一个返回字母、另一个返回数字，也能正确将结构与能量关联起来。
- **任务 ID 补全**：优先读取 `entry.data.task_id`，如缺失则使用 `ComputedEntry.entry_id`。
- **V2–V4 相库 JSON 自动迁移**：旧 JSON 中字母 ID 自动映射为数字 ID，保留原始 ID。
- **原网站核验面板**：展开“MP 编号核验”，可输入 `mp-149` 或 `mp-aaaaaaft`，实时查询 MP 官方 Summary，返回结构/空间群/星标/详情链接。
- **相能量表、竞争相组合及分解产物链接**：统一使用数字 Material ID，不把 Task ID 作为材料编号。
- **MP 数据版本**：记录从 API 获取时的数据库版本（若后端提供）。

0 K 能量模型和 UI 的 **全部 MP 相 / 仅 MP ★ 实验相** 两种筛选模式保持不变，继续输出最低竞争相组合、化学计量系数、eV/atom 竞争相能量和 ΔE。

## V4 网站升级到 V5（无需更换 Streamlit 网址）

1. 下载 **V5 快速修复包** 并解压。
2. 打开 GitHub 仓库 `qhyunc1128-sjtu/Competing-Phases` 的根目录，更新：
   - `app.py`（覆盖）
   - `mp_backend.py`（覆盖）
   - `phase_core.py`（覆盖）
   - `result_display.py`（覆盖）
   - `mp_identifiers.py`（**新增，必须**）
3. 不要把外层文件夹直接上传到仓库；保证这些文件和 `formula_utils.py`、`requirements.txt` 位于同一级根目录。
4. 点击 `Commit changes` 提交至 `main`，Streamlit 会自动更新。入口仍然是 `app.py`。
5. 回到网站，重新点击 **从 Materials Project 获取竞争相**。或者直接导入旧版相库 JSON，V5 会自动转换 ID。
6. 展开 **⑤ MP 编号核验**，输入 `mp-149` 进行在线核验。

## 关键区分

- **Material ID**：某个结构/多晶型的身份；链接 `/materials/mp-149`。
- **Task ID**：某次 GGA/PBEsol/r2SCAN 等计算的身份，与 Material ID 即使看起来相似也不能当成同一个实体。
- **同化学式不等于同结构**：不同结构应各自保留独立 Material ID。
- **原始 DFT 能量不等于 MP 修正能量**：不同能量数据体系仍单独计算，不互相混合。

### 验证边界

已通过 25 项离线单元/模拟 API 测试，包括 ID 迁移及混合 API ID 映射。因没有在本会话完成真实用户 API 在线调用，也未直接读取你的已部署 GitHub 仓库，**尚不能声称已联调确认你网站上的每个实际 MP ID**。请用网页新增的在线编号核验工具检查具体条目。

官方资料：
- https://matsci.org/t/updates-to-identifier-systems-in-the-materials-project/67442
- https://matsci.org/t/task-id-returned-from-the-api-has-changed/67291
- https://docs.materialsproject.org/frequently-asked-questions
