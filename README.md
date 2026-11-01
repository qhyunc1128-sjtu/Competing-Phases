# Competing Phases V4 — 直观稳定性结果版

V4 优化了 **V3 的结果展示**，不改变“0 K DFT 总能 + 原子守恒 + 最低能竞争相组合”的计算定义。

## 现在的使用流程

1. 在网页填写目标相化学式、VASP 总能和计算胞原子数；或选择输入 eV/atom。
2. 输入个人 Materials Project API Key 并获取数据；也可以导入此前保存的 JSON。
3. 在结果区域直接选择**全部 MP 收录相**或**仅 MP ★ 实验观测相**。
4. 选择一个能量来源和方法（例如 `core_raw / GGA`）。页面会**立刻自动更新**，不需要再按计算按钮。
5. 第一屏立即显示：**稳定性判断、目标相能量、最低竞争相能量、ΔE（meV/atom 和 eV/cell）、配平反应、每一竞争相的化学式、组合系数、MP ID 和单相能量**。
6. 可一键导出当前分析结果 CSV；完整相结构数据、计算方法、POTCAR、任务记录均折叠到页面下方，只有需要核查时才展开。

### 稳定性判断规则

\[
\Delta e = E_{\mathrm{target}}/N - E^{\min}_{\mathrm{competitors}}\quad (\mathrm{eV/atom})
\]

- **ΔE < 0：预测稳定**（相对于已选竞争相集合）
- **ΔE > 0：预测不稳定**
- **ΔE = 0：临界状态**，不简单判定为严格稳定。

**重要**：上述预测只针对本次 MP 候选集合、所选能量方法和 0 K 总能。不是包含所有可能晶体相的严格结论，不代表实验合成一定成功。目标相自行计算的总能，与 MP DFT 结果若使用不同 PAW、泛函、U 或磁性设置，不应直接当作完全兼容的严格量化判断。MP `thermo_corrected` 与个人原始总能也不一定兼容；网页会提示。

组合系数是相对于**输入目标化学式 1 个公式单位**的原子守恒化学计量系数。例如 `Mo5SiB2 → 1 Mo3Si + 2 MoB`，不是质量比，也不是原子分数。软件保留未经四舍五入的系数参与能量计算；页面只对显示进行格式化。

## 公开网站（Streamlit）更新步骤

当前 GitHub 仓库：`qhyunc1128-sjtu/Competing-Phases`；默认分支 `main`，入口 `app.py`。

**最省事的更新方式（基于 V3）**：

1. 从这个 V4 压缩包中仅提取 `app.py` 和**新增**的 `result_display.py`。
2. 将这 **2 个文件上传到 GitHub 仓库根目录**，覆盖 `app.py`，增加 `result_display.py`。不要把外层目录作为子文件夹上传。
3. `phase_core.py`、`formula_utils.py`、`mp_backend.py`、`requirements.txt` 沿用 V3，无需重新修改。旧版测试文件也不影响运行。
4. Commit 到 `main` 分支；Streamlit Cloud 会自动部署更新。入口路径仍是 `app.py`。

**如果仓库仍然是 V1/V2：** 将 V4 压缩包内所有源文件上传到**仓库根目录**，不要上传外层文件夹。项目包含：

```text
Competing-Phases/
├── app.py
├── result_display.py        ← V4 新增
├── phase_core.py
├── formula_utils.py
├── mp_backend.py
├── requirements.txt
├── README.md
├── LICENSE
├── .streamlit/config.toml
└── tests/
```

网页用户无需自行安装环境。

## 自动演示 / 数据来源

网页中的“加载演示相库”不使用 MP API；所有能量为**虚构测试值**，仅用于展示两套模式的不同判断，绝不可用于论文。真实计算请填写 API Key 下载 MP 数据。

- MP `summary.theoretical=False` 对应 ★ 实验观测结构；在结构 MP ID 层面判断，而非以化学式统一归类。
- 全部 MP 相不筛选 `theoretical`，但其范围仍限于本次实际检索的 MP 已收录结构。
- DFT 原始数据与 MP 修正数据分开；不同计算方法不混算。
- 如果某组欠缺满足元素守恒的相、或 POTCAR 冲突，会显示具体错误，而不会伪造结果。
- 额外保留每个材料可能存在的多种任务记录，仅作核查，不直接作为未经筛选的可混用能量输入。

## 核心计算与测试

求 \(\min_{w_j\ge 0}\sum_j w_j e_j\)，满足每个元素原子分数守恒 \(\sum_jw_jx_{ij}=x_i^0\)；\(e_j=E_j^{DFT}/N_j\)。并计算：\(\Delta e=e_{target}-e_{comp,min}\)。没有经过“先计算各竞争相相对于单质的形成能”的步骤。

本项目通过 **19 项离线单元测试**（包含数值求解、两套 MP 范围、能量差符号、配平反应、MP 元数据模拟），但未使用真实 API Key 测试全部在线 MP 端点或部署平台。在线联调需要在使用者账户中完成。

```bash
pip install -r requirements.txt
streamlit run app.py
pytest -q
```
