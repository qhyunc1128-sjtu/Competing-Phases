# PhaseMatch | Materials Project 竞争相能量在线计算

**开源部署版**：每位访问者通过网页输入自己的 Materials Project API Key，无需本地安装 Python 或其他软件。网站后台自动获取完整化学体系和各子体系的 MP 相图兼容条目，计算最低能竞争相分解组合、能量差、反应式配平，并提供 CSV / JSON 下载。

> 注意：本代码包是“可直接部署”的网站源代码，不是已经上线的网站。网站拥有者需要将代码发布到 GitHub，再使用 Streamlit Community Cloud 托管，才能获得可公开访问的 `https://<name>.streamlit.app` 网址。

## 1. 零安装部署：浏览器中操作即可

1. 登录 [GitHub](https://github.com/new)，新建一个仓库，例如 `phasematch`，可设为 Public。
2. 解压本 ZIP，**把压缩包最外层的文件**上传到仓库根目录（`app.py`、`phase_core.py`、`mp_backend.py`、`requirements.txt`、`tests/` 等）。不要把 ZIP 文件直接上传指望服务自动解压。仓库可以先只上传四个 Python/依赖文件，`.streamlit/config.toml` 是可选的风格配置。
3. 打开 [Streamlit Community Cloud](https://share.streamlit.io/)，用 GitHub 登录，选 **Create app**，选仓库与 `main` 分支，**Main file path** 填 `app.py`。选择适合的 Python 版本（推荐 **3.11**）。点击 Deploy。
4. 部署完成后会得到 `https://你的自定义名称.streamlit.app`。将链接分享给同事；他们打开后输入自己的 API Key，选择材料，完成计算。**每个使用者都不需要安装任何环境。**

由托管平台负责安装 `requirements.txt` 中的依赖。访问者只需浏览器，开发者无需维护自己的服务器。

部署官方教程：https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy

## 2. 网页操作

1. 输入 `Mo5SiB2`、`Mo4TiSiB2`、`Mo4.5Ti0.5SiB2`、`(Mo0.8Ti0.2)5SiB2` 等有效化学式。
2. 选择 **形成能 eV/atom**，或者 **VASP / DFT 总能 eV + 实际晶胞原子数 + 同一 DFT 设置下的单质参考能 eV/atom**。
3. 选择 MP thermo type：`GGA_GGA+U`、`GGA_GGA+U_R2SCAN` 或 `R2SCAN`。
4. 在密码框输入你自己的 [MP API Key](https://materialsproject.org/api)，点击 **从 Materials Project 检索全部竞争相**。
5. 查询完成后显示两种最小能分解组合、各相 ID/形成能/摩尔化学计量系数、能量差以及 CSV/JSON 导出。修改目标 DFT 形成能后可直接复用本次查询结果。

支持离线上传之前导出的相库 JSON。在没有连接 API 时，也能用同一批数据分析不同目标比例。

## 3. 计算原理（重要）

基于输入化学式中的元素，拉取所选 MP 热力学方案的相及其所有子体系，利用 `pymatgen.analysis.phase_diagram.PhaseDiagram` 提取基于同一组 MP 单质参考的兼容形成能，随后使用 HiGHS 线性规划求解：

\[
E_{\mathrm{comp}}^{f}=\min_{y_j\ge0}\sum_j y_j\,\Delta H_{f,j}
\quad \mathrm{s.t.}\quad \sum_j y_j x_{ij}=x_{i,\mathrm{target}}.
\]

其中 `y_j` 是第 j 个竞争相贡献的原子比例，`x_ij` 是对应竞争相中元素 i 的原子分数；结果可以换算为配平的竞争相系数。

\[
\Delta E=\Delta H_{f,\mathrm{target}}^{\mathrm{own}}-E_{\mathrm{comp}}^{f}.
\]

- **完整 MP 凸包**：保留已知同组成相/多晶型；含 MP 已知目标本身的最低能参照。
- **排除同组成**：移除所有相同原子比例的 MP 记录，评估由异组成相分解时的最低能量；**不等于标准 E above hull**。
- 正的 `ΔE` 表示输入目标能量在参照线之上，负值表示低于参照线（不自动等于热力学稳定）。
- 若采用总能模式，先计算 `ΔHf_target = E_total/N - Σ x_i E_element,i`；**不能直接减去 MP 的原始 DFT 总能**。
- 个人 VASP 形成能与 MP 修正形成能可能存在泛函、U、PAW、校正方法差异。此工具结果首先是*近似跨数据库筛选*，论文定量结论建议用相同 DFT 设置重新计算相关竞争相。
- 当前为 **0 K 固相能量模型**，不包含 Gibbs 自由能、温度、气氛氧分压、相变动力学或构型熵。

## 4. API Key 安全说明

- **每位访问者用自己的 MP Key**，不共用网站作者的 Key。
- Key 使用 Streamlit 的 `type="password"` 控件输入，**不会嵌入公开代码、URL 参数、导出 CSV/JSON 或应用自建数据库**。
- Key 在本次会话中传递到网站托管服务器，由服务器向 Materials Project 官方 API 发送请求。因此**网站运营者和托管服务处于信任边界内**，不宜在不可信网页粘贴任何密钥；密码遮挡不意味着端到端保密。
- 程序不提供磁盘日志输出用户密钥，不对密钥进行跨用户缓存；用户可点击“清除当前会话的相库和 Key”。
- **如果某个 MP API Key 已经暴露在公开对话或论坛，建议在 MP 账户里更换/重新生成，并使用新 Key。**

## 5. 管理员可选本地测试

只有网站部署者开发/排错时才需要：

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

自带数值与 MP 适配接口的脱网单元测试：

```bash
python -m unittest discover -s tests -v
```

测试只覆盖计算逻辑和模拟 API 响应；上线前仍应使用有效密钥与官方 MP 服务器做一次真实检索。

## 6. 文件布局

```text
app.py                    # Streamlit UI / 每人输入自己的 API Key
phase_core.py             # 化学式解析、线性规划、DFT 形成能和输出
mp_backend.py             # mp-api 接口及相图形成能统一处理
requirements.txt          # 托管平台自动安装依赖
.streamlit/config.toml     # 网页主题
.gitignore                # 避免提交私密文件/缓存
tests/                    # 计算与 API 适配测试
README.md                 # 本文档
LICENSE                   # MIT
```

### 官方资料

- [Materials Project API](https://docs.materialsproject.org/downloading-data/using-the-api/getting-started)
- [mp-api `get_entries_in_chemsys`](https://materialsproject.github.io/api/_autosummary/mp_api.client.mprester.MPRester.html)
- [Streamlit Community Cloud 部署](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)
