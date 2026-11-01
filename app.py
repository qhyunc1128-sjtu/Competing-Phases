"""PhaseMatch: shareable Materials Project competitive phase energy web app.

Deployment: Streamlit Community Cloud, with each visitor supplying their own key.
"""
from __future__ import annotations

import json
import pandas as pd
import streamlit as st

from phase_core import (
    aligned_energy_per_atom, analyze,
    dump_phases, formation_energy_from_total, load_phases,
    parse_formula, same_stoichiometry,
)
from mp_backend import THERMO_TYPES, fetch_mp_phases

st.set_page_config(page_title="PhaseMatch | 竞争相能量在线计算", page_icon="🧪", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 2rem; max-width: 1260px; }
.subtitle { color:#536780; font-size:1.06rem; margin-top:-0.6rem; }
.steps { padding: 0.75rem 1rem; border: 1px solid #dce7f2; border-radius: 12px;
         background: #f7fbff; margin-bottom:1rem; }
@media(max-width:700px) { .block-container {padding-top: 1.2rem;} }
</style>
""", unsafe_allow_html=True)

st.title("🧪 PhaseMatch · 竞争相能量计算")
st.markdown('<div class="subtitle">Materials Project API · 最低能竞争相组合 · 线性规划 · Convex Hull · 科研数据导出</div>',
            unsafe_allow_html=True)
st.markdown('<div class="steps"><b>① 输入目标组成与 DFT 能量</b>　 →　<b>② 输入个人 MP Key 并检索</b>　 →　<b>③ 自动计算、配平、导出</b><br>所有计算在网站服务器完成；访问者无需安装 Python。每位访问者使用自己的 API Key。</div>',
            unsafe_allow_html=True)
with st.sidebar:
    st.markdown("### PhaseMatch")
    st.markdown("**在线科研工具**\n\n- 任意有效化学计量比\n- 全子体系竞争相检索\n- MP 热力学兼容方案\n- 分解系数与能量差\n- CSV/JSON 导出")
    st.markdown("[获取个人 MP API Key](https://materialsproject.org/api)  ·  [API 官方文档](https://docs.materialsproject.org/downloading-data/using-the-api)")
    st.divider()
    st.caption("密钥用于本次请求，不写入源代码、数据库或结果导出文件。密钥会经本网站服务器发送至 MP；请仅在可信站点输入。")

with st.expander("计算定义与边界（建议先阅读）", expanded=False):
    st.markdown(r"""
**能量差定义**：\(\Delta E_{\mathrm{hull}}=\Delta H^{\mathrm{DFT}}_{f,\mathrm{target}}-\Delta H^{\mathrm{MP}}_{f,\mathrm{hull}}\)，单位 eV/atom。
该差为 **有符号的跨数据集比较**：正值表示目标相高于所选 MP 参照凸包，负值表示其低于 MP 参照凸包。

**排除同化学计量比**：将 MP 中与目标相原子比例完全相同的条目全部移除，求其他组成竞争相的最低能混合物。
这适合研究相对于异组成分解产物的驱动力，但**忽略同组成多晶型竞争**，因此不是标准的凸包距离。

**DFT 输入**：若提供的是计算胞原始总能，必须同时输入**同一 DFT 设置**下的每种单质参考能（eV/atom），
才能换算为形成能。直接将用户的 VASP 总能与 MP 原始总能相减无效。
此外，MP 对不同泛函和部分化学体系采用兼容性修正；即使转换为形成能，与个人计算也仅是近似比较。
严格定量研究建议对竞争相、单质与目标相进行统一设置的 DFT 计算及兼容性处理。

**适用范围**：0 K、给定组成的固相能量极小化；不包含振动/构型熵、气体化学势、动力学或有限温度相变。
只考虑 MP 相库中已收录的结构；未收录的相可能改变结果。
""")

left, right = st.columns([1.1, 0.9], gap="large")
with left:
    st.subheader("1. 目标材料")
    formula = st.text_input("化学式 / 实际原子计量比", value="Mo5SiB2",
                            help="示例：Mo5SiB2、Mo4.5Ti0.5SiB2、(Mo0.8Ti0.2)5SiB2")
    try:
        target_comp = parse_formula(formula)
        st.caption("识别的组成：" + ", ".join(f"{el}: {v:g}" for el, v in target_comp.items()))
    except ValueError as e:
        st.error(str(e))
        st.stop()

    energy_kind = st.radio("DFT 能量输入方式", ["形成能 ΔHf (eV/atom)", "原始 DFT 计算胞总能 (eV)"],
                           horizontal=True)
    user_eles = sorted(target_comp)
    n_formula = sum(target_comp.values())
    if energy_kind.startswith("形成能"):
        target_hf = st.number_input("目标相形成能 ΔHf (eV/atom)", value=-0.50, format="%.8f")
        cell_atoms = None
        refs = None
        original_total = None
    else:
        default_n = max(1, int(round(n_formula)))
        cell_atoms = int(st.number_input("实际 DFT 计算胞原子总数", min_value=1,
                                         value=default_n, step=1))
        original_total = st.number_input("实际 DFT 计算胞总能 (eV)",
                                         value=-100.0, format="%.8f")
        st.markdown("**同一 DFT 参数计算得到的单质参考能（eV/atom）**")
        refs = {}
        ref_cols = st.columns(min(3, len(user_eles)))
        for i, el in enumerate(user_eles):
            val = ref_cols[i % len(ref_cols)].text_input(f"{el} 单质", key=f"ref_{el}",
                                                         placeholder="如 -10.123456")
            if val.strip():
                try:
                    refs[el] = float(val)
                except ValueError:
                    pass
        try:
            target_hf = formation_energy_from_total(formula, float(original_total), cell_atoms, refs)
            st.info(f"已换算目标形成能：**{target_hf:.8f} eV/atom**")
        except ValueError as e:
            target_hf = None
            st.warning(f"能量换算尚未完成：{e}")

with right:
    st.subheader("2. Materials Project 相库")
    thermo = st.selectbox("MP 热力学数据体系", THERMO_TYPES, index=0,
                          help="尽量与个人 DFT 泛函匹配。GGA_GGA+U_R2SCAN 是兼容的混合相图。")
    st.caption("当前化学体系：" + "-".join(user_eles))
    key = st.text_input(
        "Materials Project API Key（各用户自行输入）",
        value="", type="password", key="visitor_api_key",
        placeholder="在这里输入你的 MP API Key",
        help="通过部署服务器调用 Materials Project；不会写入程序源码、共享缓存、日志或结果导出文件。",
    )
    st.caption("🔒 不在网页地址栏、公开代码、下载的 CSV/JSON 中记录 API Key；请只在信任的网站使用个人密钥。")
    if len(user_eles) > 9:
        st.error("MP 该接口最多允许 9 种元素。请缩小目标化学体系。")
    if st.button("从 Materials Project 检索全部竞争相", type="primary",
                 disabled=not bool(key.strip()) or len(user_eles) > 9, use_container_width=True):
        try:
            with st.spinner("正在读取 MP thermo 相库并统一形成能基准……"):
                phases, meta = fetch_mp_phases(key, user_eles, thermo)
            st.session_state["mp_database"] = {"phases": dump_phases(phases), "metadata": meta}
            st.success(f"已获得 {len(phases)} 条兼容相记录。")
        except Exception as e:
            # Do not display raw third-party error messages: they can contain
            # request URLs/headers, and some libraries include credentials.
            st.error("MP 检索失败。请检查 API Key 是否有效、网络是否可用、所选热力学体系是否有数据，"
                     "以及是否触发了 API 访问限制。")
            st.caption(f"故障类别：{type(e).__name__}（为保护用户密钥，故意隐藏原始异常信息）")

    with st.expander("导入之前保存的离线相库 JSON"):
        upload = st.file_uploader("选择从本程序导出的 JSON", type=["json"])
        if st.button("加载离线相库", disabled=upload is None):
            try:
                data = json.load(upload)
                load_phases(data["phases"])
                if not isinstance(data["metadata"], dict):
                    raise ValueError("相库元信息损坏。")
                st.session_state["mp_database"] = data
                st.success("已载入本地相库。")
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
                st.error(f"无法读取 JSON：{e}")

    def clear_visitor_session() -> None:
        # Do not persist user-provided credentials; clear the widget value as well.
        for name in ("mp_database", "visitor_api_key"):
            st.session_state.pop(name, None)

    st.button("清除当前会话的相库和 Key", on_click=clear_visitor_session,
              help="清空本次浏览器会话中保存的数据。")
    db = st.session_state.get("mp_database")
    if db:
        meta = db["metadata"]
        st.markdown(f"当前相库：**{len(db['phases'])} 条相**；热力学体系 **{meta.get('thermo_type','未知')}**")
        st.caption(f"检索时间（UTC）：{meta.get('retrieved_utc','未知')}")
        st.download_button(
            "保存相库 JSON（下次可离线使用）",
            data=json.dumps(db, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=f"MP_phases_{'-'.join(meta.get('elements', []))}_{meta.get('thermo_type','unknown')}.json",
            mime="application/json", use_container_width=True,
        )

if not db:
    st.info("输入 API Key 检索相库，或者上传以前保存的相库 JSON，随后将在下方显示计算结果。")
    st.stop()

metadata = db["metadata"]
if not set(user_eles).issubset(set(metadata.get("elements", []))):
    st.warning("当前化学式包含相库中未检索的元素，请重新检索相库。")
    st.stop()
if metadata.get("thermo_type") != thermo:
    st.warning("当前相库的 MP 热力学体系和上方选择不一致。请切回相库原体系或重新检索。")
    st.stop()
if target_hf is None:
    st.warning("请完成 DFT 总能与单质参考能输入后再计算。")
    st.stop()

try:
    phases = load_phases(db["phases"])
    result = analyze(formula, float(target_hf), phases)
except (ValueError, TypeError) as exc:
    st.error(f"无法求解：{exc}")
    st.stop()

st.divider()
st.subheader("3. 最低能竞争相与能量差")
mp_hull = result.global_hull.formation_energy_per_atom
mp_alt = result.alternative_hull.formation_energy_per_atom if result.alternative_hull else None
metrics = st.columns(4)
metrics[0].metric("目标相 ΔHf", f"{target_hf:.5f} eV/atom")
metrics[1].metric("MP 凸包 ΔHf", f"{mp_hull:.5f} eV/atom")
metrics[2].metric("目标 − MP 凸包", f"{result.delta_global_eV_per_atom:+.5f} eV/atom")
metrics[3].metric("目标 − 异组成竞争相", f"{result.delta_alternative_eV_per_atom:+.5f} eV/atom"
                  if result.delta_alternative_eV_per_atom is not None else "无法求解")

if result.delta_global_eV_per_atom > 1e-5:
    st.info("目标相形成能高于 MP 参照凸包：在该近似比较下，相对于所示竞争相存在正的分解能差。")
elif result.delta_global_eV_per_atom < -1e-5:
    st.info("目标相形成能低于 MP 参照凸包：可能形成新的低能相，但跨计算体系的结果不能直接证明其稳定性。")
else:
    st.info("目标相形成能接近 MP 参照凸包；需考虑计算误差和能量兼容性。")

st.warning("科学边界：这里比较的是个人 DFT 与 MP 兼容形成能；若赝势、泛函、U 值或兼容修正不同，"
           "能量差仅供初步筛选，不等同于统一计算条件下的严格相稳定性结论。")

with st.expander("能量差详解（eV/atom / meV/atom）"):
    st.latex(
        r"E_{\mathrm{comp}}=\min_{y_j\geq 0}\sum_j y_j\,\Delta H_{f,j},"
        r"\qquad \sum_j y_j x_{ij}=x_{i,\mathrm{target}}"
    )
    st.latex(r"\Delta E = \Delta H_{f,\mathrm{target}}^{\mathrm{own}} - E_{\mathrm{comp}}")
    st.markdown("**正值**：目标高于 MP 参照竞争相组合；**负值**：目标低于原有 MP 参照。"
                "“排除同组成”仅用于考察异组成分解通道，不能视为标准的 E above hull。")


def equilibrium_table(eq):
    return pd.DataFrame([{
        "竞争相": p.formula,
        "MP ID": p.mp_id,
        "系数（按输入目标化学式）": p.formula_coefficient,
        "所占原子比例": p.atomic_fraction,
        "MP 形成能 (eV/atom)": p.formation_energy_per_atom,
    } for p in eq.products])


def display_eq(title: str, eq):
    st.markdown(f"#### {title}")
    if eq is None:
        st.warning("排除目标组成后未找到覆盖目标原子比例的相组合；这不代表目标相一定稳定。")
        return
    tab = equilibrium_table(eq)
    st.dataframe(tab, hide_index=True, use_container_width=True,
                 column_config={
                     "系数（按输入目标化学式）": st.column_config.NumberColumn(format="%.6f"),
                     "所占原子比例": st.column_config.NumberColumn(format="%.6f"),
                     "MP 形成能 (eV/atom)": st.column_config.NumberColumn(format="%.6f"),
                 })
    rxn = " + ".join(f"{p.formula_coefficient:.5g} {p.formula}"
                     for p in eq.products)
    st.code(f"{formula} → {rxn}", language=None)
    n_target = sum(target_comp.values())
    st.markdown(f"**竞争相组合形成能：{eq.formation_energy_per_atom:.7f} eV/atom**"
                f"，约 **{eq.formation_energy_per_atom * n_target:.7f} eV / 输入化学式**。")
    st.caption(f"最低混合形成能 = {eq.formation_energy_per_atom:.8f} eV/atom；"
               f"元素守恒最大残差 = {eq.max_composition_residual:.2e}")
    return tab

st.caption(f"MP 候选记录：{result.n_phases}；其中同目标原子比例的记录：{result.same_composition_count}。")
tab1, tab2, tab3 = st.tabs(["完整 MP 凸包", "排除相同化学计量比", "所有 MP 候选相"])
with tab1:
    table_full = display_eq("包含 MP 同组成结构的最低能组合", result.global_hull)
with tab2:
    table_alt = display_eq("仅允许不同组成的相参与分解", result.alternative_hull)
    st.caption("注意：这里排除同组成的 MP 相及其多晶型。此能量差不是标准 E_above_hull。")
with tab3:
    rows = [{
        "公式": p.formula,
        "MP ID": p.mp_id,
        "形成能 (eV/atom)": p.formation_energy_per_atom,
        "MP 校正总能 (eV/atom)": p.mp_energy_per_atom,
        "是否与目标相同计量比": same_stoichiometry(result.target_comp, p.composition),
    } for p in phases if set(p.composition).issubset(set(result.target_comp))]
    entries_table = pd.DataFrame(rows).sort_values("形成能 (eV/atom)").reset_index(drop=True)
    st.dataframe(entries_table, hide_index=True, use_container_width=True)
    st.caption("MP 校正总能只用于数据库内部核验，不能直接与用户的 DFT 总能相减。")
    st.download_button("导出全部候选相 CSV", entries_table.to_csv(index=False).encode("utf-8-sig"),
                       file_name="MP_all_competing_phases.csv", mime="text/csv")

competition_rows = []
for label, eq in [("全凸包", result.global_hull), ("排除同组成", result.alternative_hull)]:
    if eq is not None:
        for p in eq.products:
            competition_rows.append({
                "分类": label,
                "竞争相": p.formula,
                "MP ID": p.mp_id,
                "相计量系数/目标化学式": p.formula_coefficient,
                "原子比例": p.atomic_fraction,
                "形成能 eV/atom": p.formation_energy_per_atom,
                "组合形成能 eV/atom": eq.formation_energy_per_atom,
            })
if competition_rows:
    st.download_button("导出最优竞争相组合 CSV", pd.DataFrame(competition_rows).to_csv(index=False).encode("utf-8-sig"),
                       file_name="MP_optimal_competing_mixtures.csv", mime="text/csv")

st.divider()
st.subheader("4. 按 DFT 计算胞换算（可选）")
num_scale = cell_atoms if cell_atoms is not None else sum(target_comp.values())
st.caption(f"采用 N = {num_scale:g} 个原子的归一化单位；若上面输入的是形成能，"
           "这里默认按输入化学式的原子总数换算。")
info = {
    "目标化学式": formula,
    "MP 热力学体系": metadata.get("thermo_type"),
    "相库时间 UTC": metadata.get("retrieved_utc"),
    "归一化原子数": num_scale,
    "目标形成能 eV/atom": target_hf,
    "MP 全凸包形成能 eV/atom": mp_hull,
    "目标减全凸包 eV/atom": result.delta_global_eV_per_atom,
    "目标减全凸包 meV/atom": 1000 * result.delta_global_eV_per_atom,
    "目标减全凸包 eV/归一化单位": num_scale * result.delta_global_eV_per_atom,
    "排除同组成竞争相形成能 eV/atom": mp_alt,
    "目标减异组成竞争相 eV/atom": result.delta_alternative_eV_per_atom,
    "目标减异组成竞争相 meV/atom": (
        1000 * result.delta_alternative_eV_per_atom if result.delta_alternative_eV_per_atom is not None else None
    ),
    "目标减异组成竞争相 eV/归一化单位": (
        num_scale * result.delta_alternative_eV_per_atom if result.delta_alternative_eV_per_atom is not None else None
    ),
}
if refs is not None and len(refs) == len(target_comp):
    aligned_global = aligned_energy_per_atom(mp_hull, target_comp, refs)
    info["MP 凸包映射到用户单质参考能 eV/atom (近似)"] = aligned_global
    info["MP 凸包映射到用户单质参考能 eV/计算胞 (近似)"] = aligned_global * num_scale
    st.caption(f"基于用户单质能，将 MP 竞争相形成能映射到相同元素参考基准："
               f"{aligned_global * num_scale:.6f} eV / {num_scale:g} 原子。"
               "该值仍含 DFT 泛函与 MP 兼容性修正差异，并非直接计算得到的竞争相 VASP 总能。")

summary_df = pd.DataFrame([{"指标": k, "结果": v} for k, v in info.items()])
st.dataframe(summary_df, hide_index=True, use_container_width=True)
st.download_button("导出计算摘要 CSV", summary_df.to_csv(index=False).encode("utf-8-sig"),
                   file_name=f"MP_hull_{formula.replace('(','').replace(')','')}.csv", mime="text/csv")
