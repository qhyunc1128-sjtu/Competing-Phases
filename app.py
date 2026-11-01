"""Competing Phases v3 — MP-starred vs all MP phase competition, 0 K LP."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from io import BytesIO, StringIO

import pandas as pd
import streamlit as st

from formula_utils import parse_formula, atom_fractions, same_stoichiometry
from phase_core import (
    EnergyRow, analyze_scenarios, check_cell_stoichiometry,
    rows_from_json, rows_to_json, target_eV_per_atom, potcar_conflicts,
)
from mp_backend import fetch_all_mp, fetch_task_audit

st.set_page_config(page_title='Competing Phases | MP ★ vs All', page_icon='⚛️', layout='wide')

LABEL = {
    'experimental-linked': 'A · 仅 MP ★ 实验观测结构（theoretical=False）',
    'all': 'B · 全部 MP 收录结构（含理论预测、实验与未知）',
}
MP_GROUPS = ['experimental-linked', 'all']  # Always compute exactly these two scopes.

SOURCE = {'core_raw': '原始 DFT（MP core）', 'thermo_corrected': 'MP 热力学修正能',
          'user_custom': '用户自定义数据'}


def display_rows(rows):
    data = []
    for r in rows:
        data.append({
            'mp_id': r.mp_id, 'formula': r.formula, 'spacegroup': r.spacegroup,
            'MP_starred': ('★' if r.energy_source != 'user_custom' and r.experimental_flag is True else ''),
            'theoretical_flag': ('False' if r.experimental_flag is True else
                                 'True' if r.experimental_flag is False else 'unknown'),
            'evidence': r.evidence,
            'dataset_key': r.energy_source,
            'dataset': SOURCE.get(r.energy_source, r.energy_source), 'method': r.method,
            'energy_eV_atom': r.energy_per_atom, 'dft_total_energy_eV':r.dft_total_energy_eV,
            'dft_cell_atoms':r.dft_cell_atoms, 'correction_eV_atom': r.correction_per_atom,
            'task_id': r.task_id, 'potcar': r.potcar, 'hubbards': r.hubbards,
            'MP_URL': f'https://materialsproject.org/materials/{r.mp_id}' if r.mp_id.startswith('mp-') else '',
            'notes': r.note,
        })
    return pd.DataFrame(data)


def test_data():
    x = [
        ('Mo', {'Mo': 1}, -10.0, 'experimental-linked'),
        ('Si', {'Si': 1}, -5.0, 'experimental-linked'),
        ('B', {'B': 1}, -6.0, 'experimental-linked'),
        ('Mo3Si', {'Mo':3,'Si':1}, -9.0, 'experimental-linked'),
        ('MoB', {'Mo':1,'B':1}, -8.0, 'experimental-linked'),
        ('Mo5SiB2', {'Mo':5,'Si':1,'B':2}, -9.1, 'theoretical'),
        ('Mo5Si3', {'Mo':5,'Si':3}, -8.0, 'theoretical'),
    ]
    return [EnergyRow(formula=f, composition=c, energy_per_atom=e, mp_id=f'demo-{i}',
                      energy_source='core_raw', method='GGA', evidence=ev,
                      experimental_flag=(ev == 'experimental-linked'),
                      note='演示数据：非真实 MP 能量') for i,(f,c,e,ev) in enumerate(x)]


st.title('⚛️ Competing Phases · MP ★ vs All')
st.caption('两种固定候选集：MP ★ 实验观测结构 / 全部 MP 收录结构 · 分泛函比较 0 K DFT 竞争相能量')
st.markdown(r'$$\Delta e=E_{\mathrm{target}}/N-\min\sum_j w_j(E_j/N_j),\quad '
            r'\sum_j w_j x_{ij}=x_i^{\mathrm{target}},\quad w_j\geq0$$')
st.info('**两套计算仅按 MP 官方星号区分**：A. ★ 实验观测结构 = Summary `theoretical=False`；'
        'B. 全部 MP 收录结构 = 不按 theoretical 过滤（含 True / False / 缺失）。'
        '★ 表示 MP 将结构匹配到实验观测来源，不表示 MP 能量来自实验测量。'
        '能量差由 0 K DFT 总能和原子守恒求得，不先计算单质参考形成能。')

with st.sidebar:
    st.header('1 · 数据源')
    api_key = st.text_input('个人 Materials Project API Key', type='password',
                            placeholder='此处输入；不写入代码或导出文件', help='密钥仅用于当前会话向 MP API 请求数据。')
    include_gnome = st.checkbox('另外纳入 MP 中可检索的 GNoMe 候选', value=False,
                                  help='关闭时统计常规 MP 数据集；开启后两组都按相同检索范围查询，但 GNoMe 主要影响全部 MP 组。')
    fetch_raw = st.checkbox('检索 MP core 原始 DFT 能量及 POTCAR', value=True)
    fetch_corr = st.checkbox('检索 MP thermo 修正能量体系', value=True)
    st.caption('raw 与 corrected 分成**不同数据集**，不会直接放入一个优化。大量元素体系请先测试低元素数。')
    if st.button('清空本会话数据', use_container_width=True):
        for key in ('phase_records', 'phase_meta', 'tasks_audit'):
            st.session_state.pop(key, None)
        st.rerun()

st.subheader('2 · 目标材料与 0 K DFT 能量')
a, b, c, d = st.columns([2.2, 1.5, 1.4, 1.3])
with a:
    formula = st.text_input('目标材料化学式（可小数/括号）', 'Mo5SiB2')
with b:
    target_unit = st.selectbox('目标能量输入单位', ['eV/cell', 'eV/atom'])
with c:
    target_energy = st.number_input('VASP 总能 / 每原子能量', value=-280.0, format='%.8f')
with d:
    cell_atoms = st.number_input('DFT 计算胞总原子数', min_value=1, value=32, step=1)

valid = True
try:
    target_comp = parse_formula(formula)
    check_cell_stoichiometry(formula, int(cell_atoms))
    dft_e_atom = target_eV_per_atom(target_energy, target_unit,
                                    int(cell_atoms) if target_unit == 'eV/cell' else None)
    st.caption(f'目标元素比：{target_comp} ｜ 目标 DFT 总能：**{dft_e_atom:.8f} eV/atom**'
               f' ｜ 输入值仅为示例，请替换为真实 VASP 结果。')
    if len(target_comp) >= 7:
        st.warning('当前输入包含 7 种或以上不同元素：完整子体系检索可能涉及数百个 MP 化学体系，'
                   '网站查询耗时或受到数据库服务限制；可改为分体系下载并合并 JSON/CSV。')
except Exception as exc:
    valid = False
    st.error(f'目标输入错误：{exc}')

q1, q2 = st.columns(2)
with q1:
    if st.button('🔍 从 MP 下载当前元素体系（包含所有子体系）', type='primary',
                 disabled=not valid, use_container_width=True):
        try:
            if not api_key:
                raise ValueError('请先在左侧输入 API Key')
            with st.spinner('从 Materials Project 拉取 summary / core / thermo 数据；大体系可能较慢…'):
                rows, meta = fetch_all_mp(api_key, list(target_comp), include_gnome=include_gnome,
                                          fetch_raw=fetch_raw, fetch_corrected=fetch_corr)
            st.session_state['phase_records'] = rows
            st.session_state['phase_meta'] = meta
            st.session_state.pop('tasks_audit', None)
            st.session_state.pop('latest_scenarios', None)
            st.success(f'获得 MP 结构 {meta["n_materials"]} 个：★ {meta["n_mp_starred"]}、'
                       f'非★ {meta["n_mp_nonstarred"]}、未标记 {meta["n_mp_flag_unknown"]}；'
                       f'能量记录 {meta["n_energy_rows"]} 条。')
        except Exception as exc:
            st.error(f'MP 检索失败（未隐藏异常类型）：{type(exc).__name__}: {exc}')
with q2:
    if st.button('🧪 加载离线演示数据（无需 API）', use_container_width=True):
        st.session_state['phase_records'] = test_data()
        st.session_state['phase_meta'] = {'source':'DEMO — SYNTHETIC, NOT MATERIALS PROJECT',
                                           'elements':['Mo','Si','B'], 'n_materials':7}
        st.session_state.pop('tasks_audit', None)
        st.session_state.pop('latest_scenarios', None)
        st.warning('已加载合成演示数据！所有演示能量均非 MP 真实值，不能用于论文。')

with st.expander('导入保存的候选库 JSON 或本人计算的 CSV', expanded=False):
    up_json = st.file_uploader('导入本程序导出的 JSON', type=['json'], key='uploadjson')
    if up_json and st.button('读取 JSON 作为候选库'):
        try:
            rows, meta = rows_from_json(up_json.getvalue())
            st.session_state['phase_records'] = rows
            st.session_state['phase_meta'] = meta
            st.session_state.pop('latest_scenarios', None)
            st.success(f'导入 {len(rows)} 条能量记录。')
        except Exception as exc:
            st.error(str(exc))
    st.caption('CSV 必填列：`formula,energy_per_atom,method`；可附 `mp_id,evidence,spacegroup,potcar,note`。'
               '用户自定义相库保留供参考/导出，但**不会混入仅 MP ★ / 全部 MP 两个官方集合**。')
    up_csv = st.file_uploader('导入自己算的竞争相 CSV（追加到现有候选库）', type=['csv'], key='uploadcsv')
    if up_csv and st.button('添加 CSV 数据'):
        try:
            table = pd.read_csv(up_csv)
            required = {'formula', 'energy_per_atom', 'method'}
            if not required.issubset(table.columns):
                raise ValueError('缺少必填列：' + str(required - set(table.columns)))
            extra = []
            for i, item in table.iterrows():
                formula_i = str(item['formula']).strip()
                comp_i = parse_formula(formula_i)
                def opt(field, fallback=''):
                    v = item.get(field, fallback)
                    return fallback if pd.isna(v) else str(v)
                evidence = opt('evidence', 'unknown')
                extra.append(EnergyRow(
                    formula=formula_i, composition=comp_i,
                    energy_per_atom=float(item['energy_per_atom']),
                    mp_id=opt('mp_id', f'custom-{i}'),
                    energy_source='user_custom', method=str(item['method']).strip(),
                    evidence=evidence, spacegroup=opt('spacegroup'),
                    potcar=opt('potcar'), note=opt('note', 'User-supplied DFT'),
                ))
            st.session_state['phase_records'] = st.session_state.get('phase_records', []) + extra
            st.session_state['phase_meta'] = {**st.session_state.get('phase_meta', {}),
                                               'custom_rows_added': len(extra)}
            st.session_state.pop('latest_scenarios', None)
            st.success(f'追加 {len(extra)} 条用户计算数据。')
        except Exception as exc:
            st.error(f'导入失败：{exc}')

rows: list[EnergyRow] = st.session_state.get('phase_records', [])
if not rows:
    st.markdown('---')
    st.markdown('**先选择下载 MP 数据、导入 JSON/CSV 或加载离线演示数据。**')
    st.stop()

meta = st.session_state.get('phase_meta', {})
with st.expander('候选数据集及检索范围信息', expanded=False):
    st.json(meta)
    st.warning('MP 仅覆盖其公开收录的相（以及所选 GNoMe 候选）；“全部理论相”没有普适完备数据库。'
               '缺失的预测结构可用 CSV 追加。')

st.subheader('3 · MP 结构 ★ 标识与每种计算方法的能量')
full_df = display_rows(rows)
dataset_methods = sorted(set((r.energy_source, r.method) for r in rows))
filter_source = st.multiselect('按能量数据类型和方法过滤预览',
    options=[f'{a} | {b}' for a,b in dataset_methods],
    default=[f'{a} | {b}' for a,b in dataset_methods])
filter_evidence = st.multiselect('按 MP 来源标记过滤预览（仅影响表格预览，不影响两组计算）',
    options=['experimental-linked', 'theoretical', 'unknown'],
    default=['experimental-linked','theoretical','unknown'])
preview_df = full_df[
    full_df.apply(lambda r: f'{r["dataset_key"]} | {r["method"]}' in filter_source,
                  axis=1) & full_df['evidence'].isin(filter_evidence)
]
st.caption('**★**：MP `theoretical=False`；空白：理论结构、未知来源或非 MP 自定义条目。'
           '同一化学式的不同 MP ID 可以有不同星号，按结构而非化学式筛选。')
st.dataframe(preview_df, use_container_width=True, height=360, hide_index=True)
st.download_button('⬇️ 导出所有能量记录 CSV', data=full_df.to_csv(index=False).encode('utf-8-sig'),
                   file_name='competing_phases_all_energy_rows.csv', mime='text/csv')
st.download_button('⬇️ 导出完整候选数据库 JSON（不含密钥）',
                   data=rows_to_json(rows, meta), file_name='competing_phases_data.json',
                   mime='application/json')

st.subheader('4 · 自动对比两组最低能竞争相（★ vs 全部 MP）')
st.caption('**严格不混用不同能量体系**：每个 `(source, method)` 单独运行一次线性规划。'
           '数据表会完整保留多晶型、多种 GGA/GGA+U/r2SCAN 计算；同一数据集可能有多个同组成结构。')
mp_dataset_methods = [(s,m) for s,m in dataset_methods if s in ('core_raw','thermo_corrected')]
method_options = [f'{s} | {m}' for s,m in mp_dataset_methods]
selected_methods = st.multiselect('选择需要参与比较的能量数据集',
                                  method_options, default=method_options)
st.markdown('**固定计算两组：** A. 仅 ★ 实验观测结构；B. 全部 MP 结构。两组均采用同一个目标相能量。')
evidence_groups = MP_GROUPS
exclude_same = st.checkbox('排除全部与目标材料原子比例完全相同的 MP 条目（避免目标相自身参与竞争）', value=True)
strict_potcar = st.checkbox('严格检查同一元素的 POTCAR：检测到不一致时阻止该 raw 计算情景', value=True,
                            help='只检测存在的 POTCAR metadata，不保证条目间计算参数完全相同')
if any(s == 'core_raw' for s,m in dataset_methods):
    st.warning('原始 GGA、GGA+U、r2SCAN 的绝对能量**不能混合比较**。即使单独对 GGA+U 求解，'
               '也要检查 U 值、POTCAR、磁态及与目标计算的兼容性。MP 修正体系也不能直接视为同设置的个人 VASP 总能。')

if st.button('▶ 计算所有选定情景', type='primary', disabled=not valid):
    methods = [m for m in dataset_methods if f'{m[0]} | {m[1]}' in selected_methods]
    if not methods:
        st.error('至少选择一种 MP 能量数据集。')
    elif not set(target_comp).issubset({el for r in rows for el in r.composition}):
        st.error('候选库缺少至少一种目标元素的条目。')
    else:
        scenarios = analyze_scenarios(formula, dft_e_atom, rows, methods, evidence_groups,
                                      cell_atoms=int(cell_atoms),
                                      exclude_same_composition=exclude_same,
                                      require_potcar_consistency=strict_potcar)
        st.session_state['latest_scenarios'] = scenarios
        st.session_state['latest_summary'] = {'formula':formula, 'DFT_energy_per_atom':dft_e_atom,
                                               'exclude_same':exclude_same, 'strict_potcar':strict_potcar, 'target_unit':target_unit}

scenarios = st.session_state.get('latest_scenarios', [])
if scenarios:
    previous = st.session_state.get('latest_summary', {})
    if previous.get('formula') != formula or previous.get('DFT_energy_per_atom') != dft_e_atom or previous.get('exclude_same') != exclude_same or previous.get('strict_potcar') != strict_potcar:
        st.warning('目标输入或选项已更改；以下是上一次计算的结果，请重新点击“计算所有选定情景”。')
    summary = []
    product_table = []
    for s in scenarios:
        summary.append({'energy_source': SOURCE.get(s.energy_source,s.energy_source),
                        'method': s.method, 'scenario': LABEL[s.evidence_filter],
                        'n_candidates': s.phase_count, 'status': s.status,
                        'competing_energy_eV_atom': s.mixture.energy_per_atom if s.mixture else None,
                        'delta_meV_atom': s.delta_meV_per_atom,
                        'delta_eV_cell': s.delta_eV_per_cell,
                        'error': s.error})
        if s.mixture:
            for p in s.mixture.products:
                product_table.append({
                    'scenario':s.label, 'formula':p.formula, 'mp_id':p.mp_id,
                    'task_id':p.task_id, 'method':p.method, 'evidence':p.evidence,
                    'formula_coefficient':p.coefficient_per_target_formula,
                    'atom_fraction':p.atom_fraction, 'phase_energy_eV_atom':p.energy_per_atom,
                })
    result_df = pd.DataFrame(summary)
    st.dataframe(result_df, use_container_width=True, hide_index=True)
    comparison = []
    for source, method in sorted({(s.energy_source, s.method) for s in scenarios}):
        pair = {s.evidence_filter: s for s in scenarios if (s.energy_source, s.method) == (source, method)}
        star = pair.get('experimental-linked')
        everything = pair.get('all')
        if not star or not everything:
            continue
        s_e = star.mixture.energy_per_atom if star.mixture else None
        a_e = everything.mixture.energy_per_atom if everything.mixture else None
        comparison.append({
            'data_source': SOURCE.get(source, source), 'method': method,
            'n_MP_star_energy_rows': star.phase_count, 'n_all_MP_energy_rows': everything.phase_count,
            'E_comp_star_eV_atom': s_e, 'E_comp_all_eV_atom': a_e,
            'all_vs_star_lowering_meV_atom': (s_e - a_e) * 1000 if s_e is not None and a_e is not None else None,
            'target_minus_star_meV_atom': star.delta_meV_per_atom,
            'target_minus_all_meV_atom': everything.delta_meV_per_atom,
            'note': '两组求解成功' if s_e is not None and a_e is not None else '其中一组缺少可行竞争相或未通过兼容性检查',
        })
    if comparison:
        st.markdown('**A / B 对比（同一能量方法）**')
        st.dataframe(pd.DataFrame(comparison), use_container_width=True, hide_index=True)
        st.caption('`all_vs_star_lowering = E_comp(★) − E_comp(全部)`；同设置且两组均可行时该值理论上 ≥ 0。'
                   '它表示加入理论/未知结构后，竞争相最低能量下降多少。')
    st.caption('ΔE = E(target DFT) – E(min. competing phases). ΔE < 0 为目标低于该竞争组合；'
               'ΔE > 0 为目标高于该组合。该值是“指定候选库的有符号差值”，'
               '不自动等于 MP 官方 energy above hull。')
    prod_df = pd.DataFrame(product_table)
    if not prod_df.empty:
        st.markdown('**最优竞争相与原子数配平系数（相对于输入目标化学式）**')
        st.dataframe(prod_df, use_container_width=True, hide_index=True)
    st.download_button('⬇️ 导出情景汇总 CSV', result_df.to_csv(index=False).encode('utf-8-sig'),
                       file_name='phase_scenarios_summary.csv', mime='text/csv')
    if not prod_df.empty:
        st.download_button('⬇️ 导出最优分解组合 CSV', prod_df.to_csv(index=False).encode('utf-8-sig'),
                           file_name='phase_decomposition_products.csv', mime='text/csv')

st.subheader('5 · 可选：检查某一结构的全部 MP 计算任务')
st.caption('MP core 的 `entries` 是每个结构/泛函的已选代表计算，**不是**所有结构优化、静态计算。'
           '如需逐条查看任务的 run_type、POTCAR、U、结构优化能量，请在这里按 MP ID 展开。'
           '这些任务记录只用于人工核查，**不会自动进入竞争相优化**。')
mids = sorted({r.mp_id for r in rows if r.mp_id.startswith('mp-')})
selected_ids = st.multiselect('选择要核查的 MP ID（最多 20 个）', mids, max_selections=20)
if st.button('查询所选 MP ID 的所有关联任务', disabled=not (api_key and selected_ids)):
    try:
        with st.spinner('正在检索所选材料关联的 VASP tasks…'):
            st.session_state['tasks_audit'] = fetch_task_audit(api_key, selected_ids)
        st.success(f'任务记录 {len(st.session_state["tasks_audit"])} 条')
    except Exception as exc:
        st.error(f'任务检索失败：{type(exc).__name__}: {exc}')
if st.session_state.get('tasks_audit'):
    task_df = pd.DataFrame(st.session_state['tasks_audit'])
    st.dataframe(task_df, use_container_width=True, height=300, hide_index=True)
    st.download_button('⬇️ 导出任务审计 CSV', task_df.to_csv(index=False).encode('utf-8-sig'),
                       file_name='mp_task_audit.csv', mime='text/csv')

st.divider()
st.caption('方法：0 K DFT 总能原子守恒线性规划。★ 来自 MP summary.theoretical=False；'
           '它代表实验观测结构来源，MP 能量仍为 DFT 结果。'
           ' 只对所查询 MP 版本和已导入结构负责，不声称覆盖所有可能材料。'
           ' API Key 仅用于本会话的查询，不包含在下载文件中。')
