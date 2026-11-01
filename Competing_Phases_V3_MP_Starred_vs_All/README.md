# Competing Phases V3 — MP ★ vs All (0 K DFT)

本项目是 **Streamlit 在线竞争相能量计算程序**。每位用户在网页内输入自己的 Materials Project（MP）API Key、目标组成和 0 K DFT 总能；无需自行安装 Python 环境。数据和任务记录可以导出 CSV / JSON。

## 本版关键修改：只做两套 MP 候选集

| 自动计算的候选集 | MP 规则 | 数据范围 |
|---|---|---|
| **A. MP ★ 实验观测结构** | `summary.theoretical is False` | Materials Explorer 中带星号（★）的 MP 结构（逐个 Material ID 判断） |
| **B. 全部 MP 结构** | 不根据 `theoretical` 过滤 | MP 检索到的全部结构，包括 ★、理论预测与来源未标明结构 |

**两组使用同一批 MP 检索结果、相同的目标 DFT 能量、元素守恒公式及相同的能量数据集。** 对每个可用的能量来源/方法（例如 core_raw/GGA、core_raw/r2SCAN、thermo_corrected/GGA_GGA+U），分别求出两套最低能竞争相组合及目标相与其的能量差。不同泛函与能量修正方案**不混合**。

⚠️ **星号含义：** 根据 MP 官方社区，Materials Explorer 的星号代表 *Experimentally Observed*，API `theoretical=False`；它说明该 MP 晶体结构与实验数据库结构相匹配，**不是说 MP 中的 DFT 能量是实验测量结果**。`theoretical=True` 和未知标记不会进入 A 组。不能仅凭一个化学式判断所有晶型都属于实验组。

⚠️ **覆盖范围：** “全部 MP”是本次选定 MP 数据源中可检索到的全部材料条目，不意味着包括自然界/理论上一切可能相。可选勾选 `include_gnome` 以扩大 MP 搜索范围；勾选与否对 A、B 两组使用同一设置。默认关闭 GNoMe 扩展，以便和常规 MP Materials Explorer 对齐。

## 直接更新你已有的 Streamlit 网站

仓库地址（以实际 GitHub 仓库为准）：`qhyunc1128-sjtu/Competing-Phases`。

1. 解压 `Competing_Phases_V3_MP_Starred_vs_All.zip`。
2. 把**解压目录内部的文件**上传/更新到已有 GitHub 仓库的 `main` 分支。务必替换旧版 `app.py`、`phase_core.py`、`mp_backend.py`、`README.md` 和测试文件；保留 `formula_utils.py` 与 `requirements.txt`，上传 `.streamlit/config.toml` 以保留界面设置。
3. GitHub 提交变更后 Streamlit Community Cloud 会重新部署；若未自动更新可从应用管理面板选择 Reboot。
4. 部署入口仍是 **`app.py`**，不要修改为 `streamlit_app.py`。
5. 打开网站，在左侧输入个人 MP API Key，填入化学式、DFT 能量和胞内原子数，然后点击 **从 MP 下载当前元素体系**。
6. 在 **4 · 自动对比两组最低能竞争相（★ vs 全部 MP）** 选择各数据体系，点击 **计算所有选定情景**。网页会同时显示 A/B 两组的竞争相、配平结果及能量差。

## 能量计算（严格按用户定义）

针对目标化学式中各元素的原子分数 \(x_i^0\)，各竞争相 \(j\) 的每原子 **0 K DFT 总能** \(e_j=E_j^{cell}/N_j\)。用线性规划求：

\[
E_{\mathrm{comp}}^{\min}=\min_{w_j\ge0}\sum_jw_je_j,\qquad
\sum_jw_jx_{ij}=x_i^0.
\]

所有元素的约束同时保证 \(\sum_jw_j=1\)。**不先把竞争相能量转为相对于单质的形成能**。

目标相输入可以是每计算胞总能（eV/cell）或每原子能量（eV/atom）；计算胞总能除以其真实原子数 \(N_{target}\) 归一化。定义：

\[
\Delta e_{\mathrm{A}}=e_{\mathrm{target}}-E_{\mathrm{comp,A}}^{\min},\quad
\Delta e_{\mathrm{B}}=e_{\mathrm{target}}-E_{\mathrm{comp,B}}^{\min}.
\]

输出 eV/atom、meV/atom、eV/cell（使用目标实际计算胞原子数）。正值表示目标相相对于该组最低竞争相**能量更高**，负值表示更低；这是有符号竞争相能量差，不等于 MP 网站上非负 `energy above hull` 的通常定义。

**额外的 A/B 对比量**：

\[
\Delta E_{\mathrm{lowering}}=E_{\mathrm{comp,A}}^{\min}-E_{\mathrm{comp,B}}^{\min}\ge0
\]

两组都可配平、采用同一能量体系并成功求解时，全部 MP 集合包含实验 ★ 集合，故该值理论上不小于 0；它反映额外引入理论/未知结构导致的最低竞争相能量降低。

## 多种 DFT 计算与记录

- `MP core raw`：保留每个 MP 材料、每种可用 `run_type` 的代表原始计算能量，不采用 MP 兼容性修正；尽可能展示计算胞原子数、eV/cell、eV/atom、POTCAR、Hubbard U、任务 ID。
- `MP thermo corrected`：保留官方热力学方案的兼容性修正能量，**分开计算**、不与 raw 混用。
- **全部 tasks 审计**：对选中的少量 MP IDs 查询相关优化/静态任务，列出不同任务的能量与方法（仅用于审计，不直接加入最低能优化，以免混入不可比任务）。
- 默认同组检测 POTCAR 冲突；发现相同元素不同 POTCAR 时阻止该情景运行，可自主关闭严格校验以进行探索性比较。

MP 原始 DFT 数据与用户自己 VASP 目标相可能使用不同 PAW 赝势、泛函、U、磁有序设置。即使都属于 GGA，**直接相减也可能产生不可忽略的系统误差**，应在科研论文中核对一致性。MP `thermo_corrected` 是另一能量体系，与未经相同兼容性校正的个人原始 VASP 总能不能视为严格同尺度。

## 自定义 CSV 与安全

保留导入自算竞争相能量的 CSV 和下载 JSON 功能。但为了保证本版 **MP ★** 和 **全部 MP** 的统计定义，`user_custom` 条目不会自动并入上述两组；自定义数据需单独核算，不能伪装成 MP ★ 条目。用户的密钥不会写入代码、版本库、导出文件或持久缓存。

CSV 示例（能量仅作格式示意，**非真实 MP 数据**）：

```csv
formula,energy_per_atom,method,mp_id,evidence,spacegroup,potcar,note
Mo3Si,-9.0,PBE-custom,custom-001,unknown,Pm-3n,PAW_PBE,DEMO ONLY
MoB,-8.0,PBE-custom,custom-002,unknown,Cmcm,PAW_PBE,DEMO ONLY
```

## 本地开发（网站用户不用操作）

```bash
pip install -r requirements.txt
streamlit run app.py
pytest -q
```

本次版本经过 **17 项离线 / 模拟 MP 客户端测试**，验证星号分类、未知标记排除、同化学式不同 MP ID、线性规划配平与能量归一化。**没有使用真人 API Key 进行真实在线联调**，最终端点和响应字段需在已部署的 Streamlit Cloud 上测试。

## MP 官方来源

- [Obtain star materials — MP 开发人员说明](https://matsci.org/t/obtain-star-materials/51386)
- [Experimental materials availability since 2016 — Star 对应实验观测结构](https://matsci.org/t/experimental-materials-availability-since-2016/54006)
- [MP Summary API：theoretical 字段](https://materialsproject.github.io/api/_modules/mp_api/client/routes/materials/summary.html)
