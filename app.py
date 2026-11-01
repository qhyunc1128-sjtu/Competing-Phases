"""Competing Phases v4 — intuitive MP ★ vs All, zero-K energy comparison."""
from __future__ import annotations

from io import StringIO
import json

import pandas as pd
import streamlit as st

from formula_utils import parse_formula
from phase_core import (
    EnergyRow, analyze_scenarios, check_cell_stoichiometry,
    rows_from_json, rows_to_json, target_eV_per_atom,
)
from mp_backend import fetch_all_mp, fetch_task_audit, verify_material_id
from mp_identifiers import material_url
from result_display import product_breakdown, reaction_text, verdict

st.set_page_config(page_title='Competing Phases · 0 K', page_icon='⚛️', layout='wide')

SCOPES = {
    'all': '全部 MP 收录相',
    'experimental-linked': '仅 MP ★ 实验观测相',
}
SOURCES = {
    'core_raw': '原始 DFT 总能（raw）',
    'thermo_corrected': 'MP 修正能量（corrected）',
    'user_custom': '用户数据（参考，不进入两个 MP 官方集合）',
}


def display_rows(rows: list[EnergyRow]) -> pd.DataFrame:
    return pd.DataFrame([{
        'MP Number（数字材料编号）': r.mp_id,
        'MP API 原始 Material ID': r.mp_id_api or r.mp_id,
        '相': r.formula,
        '空间群': r.spacegroup,
        '★': '★' if r.energy_source != 'user_custom' and r.experimental_flag is True else '',
        '结构来源': r.evidence,
        '能量来源': SOURCES.get(r.energy_source, r.energy_source),
        '方法': r.method,
        'eV/atom': r.energy_per_atom,
        '原始计算胞总能 eV': r.dft_total_energy_eV,
        '计算胞原子数': r.dft_cell_atoms,
        '修正量 eV/atom': r.correction_per_atom,
        'Task Number（计算任务）': r.task_id,
        'Task ID（API 原始）': r.task_id_api or r.task_id,
        'POTCAR': r.potcar,
        'Hubbard U': r.hubbards,
        'MP URL': material_url(r.mp_id),
        '备注': r.note,
    } for r in rows])


def demo_data() -> list[EnergyRow]:
    # Deliberately synthetic, not an MP lookup or reported material property.
    samples = [
        ('Mo', {'Mo':1}, -6., True),
        ('Si', {'Si':1}, -4., True),
        ('B', {'B':1}, -5., True),
        ('Mo3Si', {'Mo':3, 'Si':1}, -10., False),
        ('MoB', {'Mo':1, 'B':1}, -8., True),
        ('Mo5Si3', {'Mo':5, 'Si':3}, -8.1, False),
        ('Mo5SiB2', {'Mo':5, 'Si':1, 'B':2}, -8.9, False),
    ]
    return [EnergyRow(formula=f, composition=comp, energy_per_atom=e,
                      mp_id=f'demo-{idx:02d}', energy_source='core_raw',
                      method='GGA', evidence=('experimental-linked' if starred else 'theoretical'),
                      experimental_flag=starred, note='演示数据，非 MP 数据')
            for idx, (f, comp, e, starred) in enumerate(samples, start=1)]


def reset_results() -> None:
    st.session_state.pop('tasks_audit', None)


def show_scenario(s, target_formula: str, target_e_atom: float, num_atoms: int,
                  *, prominent: bool = True) -> None:
    if s.status != 'ok' or s.mixture is None or s.delta_eV_per_atom is None:
        st.warning('当前选择无法得出最低能竞争相组合。')
        st.caption(f'原因：{s.error or s.status}')
        return

    condition, label = verdict(s.delta_eV_per_atom)
    if condition == 'stable':
        st.success('✅ ' + label)
    elif condition == 'unstable':
        st.error('❌ ' + label)
    else:
        st.warning('⚖️ ' + label)

    st.caption('判定范围：仅针对所选 MP 相集合及当前能量方法；并非实验合成保证。')
    a, b, c, d = st.columns(4)
    a.metric('目标相能量', f'{target_e_atom:.6f} eV/atom')
    b.metric('最低竞争相能量', f'{s.mixture.energy_per_atom:.6f} eV/atom')
    c.metric('ΔE = 目标 − 竞争相', f'{s.delta_meV_per_atom:+.3f} meV/atom')
    d.metric('ΔE（当前计算胞）', (f'{s.delta_eV_per_cell:+.6f} eV/cell'
                               if s.delta_eV_per_cell is not None else '不适用'))

    st.markdown('**最低能竞争相组合及配平反应**')
    st.code(reaction_text(target_formula, s.mixture), language=None)
    products = product_breakdown(target_formula, s.mixture)
    for index, row in enumerate(products, start=1):
        with st.container(border=True):
            name, coeff, energy, src = st.columns([2.7, 1.6, 2.1, 2.3])
            name.markdown(f'**{index}. {row["phase"]}**')
            coeff.markdown(f'**组合系数：{row["coefficient_label"]}**')
            energy.write(f'{row["energy_eV_atom"]:.6f} eV/atom')
            star = '★ 实验结构' if row['evidence'] == 'experimental-linked' else '理论/未标记结构'
            if material_url(row['mp_id']):
                src.markdown(f'[{row["mp_id"]}]({material_url(row["mp_id"])}) · {star}')
            else:
                src.caption(f'{row["mp_id"]} · {star}')

    if prominent:
        exported = pd.DataFrame([{
            'target_formula': target_formula,
            'mode': SCOPES[s.evidence_filter],
            'energy_source': s.energy_source, 'method': s.method,
            'target_eV_atom': target_e_atom,
            'competitor_min_eV_atom': s.mixture.energy_per_atom,
            'delta_meV_atom': s.delta_meV_per_atom,
            'delta_eV_cell': s.delta_eV_per_cell,
            'prediction': label,
            'balanced_reaction': reaction_text(target_formula, s.mixture),
        }])
        st.download_button('⬇️ 一键下载本次稳定性判断与配平反应 CSV',
                           exported.to_csv(index=False).encode('utf-8-sig'),
                           file_name='selected_stability_result.csv', mime='text/csv')
        with st.expander('查看能量加权、原子守恒残差和分解贡献（用于论文核查）'):
            contributions = pd.DataFrame([{
                '竞争相': p['phase'], 'MP Number': p['mp_id'],
                'MP API Material ID': p['mp_id_api'],
                'Task Number': p['task_id'], 'Task API ID': p['task_id_api'],
                '反应系数': p['coefficient'], '原子占比': p['atom_fraction'],
                '单相能量 (eV/atom)': p['energy_eV_atom'],
                '组合贡献 (eV/atom)': p['energy_contribution_eV_atom'],
            } for p in products])
            st.dataframe(contributions, hide_index=True, use_container_width=True)
            st.caption(f'能量贡献总和 = {sum(p["energy_contribution_eV_atom"] for p in products):.9f} eV/atom；'
                       f'元素守恒最大残差 = {s.mixture.max_residual:.2e}。'
                       '系数以目标输入化学式为 1 化学式单位计算，非相的原子占比。')
            st.download_button('下载当前分解组合 CSV', contributions.to_csv(index=False).encode('utf-8-sig'),
                               file_name='selected_competitor_reaction.csv', mime='text/csv')


def add_user_csv(file) -> list[EnergyRow]:
    df = pd.read_csv(file)
    mandatory = {'formula', 'energy_per_atom', 'method'}
    if not mandatory.issubset(df.columns):
        raise ValueError(f'CSV 缺少列：{", ".join(sorted(mandatory - set(df.columns)))}')
    added = []
    for i, r in df.iterrows():
        def optional(field: str, default: str = '') -> str:
            value = r.get(field, default)
            return default if pd.isna(value) else str(value)
        f = str(r['formula']).strip()
        evidence = optional('evidence', 'unknown')
        added.append(EnergyRow(
            formula=f, composition=parse_formula(f), energy_per_atom=float(r['energy_per_atom']),
            mp_id=optional('mp_id', f'custom-{i}'), energy_source='user_custom',
            method=str(r['method']), evidence=evidence if evidence in ('experimental-linked', 'theoretical', 'unknown') else 'unknown',
            spacegroup=optional('spacegroup'), potcar=optional('potcar'),
            note=optional('note', 'User-provided DFT'),
        ))
    return added


st.title('⚛️ Competing Phases · 竞争相稳定性计算')
st.caption('从 Materials Project 获取 0 K 能量，自动配平最低竞争相；选择 ★ 实验相或全部 MP 相，立即查看能量差与稳定性预测。')

with st.sidebar:
    st.header('Materials Project 数据')
    api_key = st.text_input('你的 MP API Key', type='password', placeholder='每位访问者填写自己的密钥')
    fetch_raw = st.checkbox('获取原始 DFT 能量', value=True)
    fetch_corrected = st.checkbox('同时获取 MP 修正能量', value=True)
    include_gnome = st.checkbox('扩展 GNoMe 候选库', value=False)
    st.caption('不同泛函、POTCAR 和 MP 修正方案不能直接混用。密钥不写入文件。')
    if st.button('清空已加载的相库', use_container_width=True):
        st.session_state.pop('phase_records', None)
        st.session_state.pop('phase_meta', None)
        reset_results()
        st.rerun()

st.subheader('① 输入目标相能量')
c1, c2, c3, c4 = st.columns([2.2, 1.3, 1.7, 1.3])
with c1:
    formula = st.text_input('目标相化学式', value='Mo5SiB2', help='如 Mo4.5Ti0.5SiB2 或 (Mo0.8Ti0.2)5SiB2')
with c2:
    unit = st.selectbox('能量输入单位', ['eV/cell', 'eV/atom'])
with c3:
    target_energy = st.number_input('DFT 总能量', value=-280.0, format='%.9f')
with c4:
    cell_atoms = st.number_input('计算胞原子数', min_value=1, value=32, step=1)

valid = False
try:
    target_comp = parse_formula(formula)
    # Every arbitrary composition works in eV/atom mode; a physical cell
    # is only required to contain integral atom counts when using eV/cell.
    valid_cell = True
    try:
        check_cell_stoichiometry(formula, int(cell_atoms))
    except ValueError:
        valid_cell = False
    if unit == 'eV/cell' and not valid_cell:
        raise ValueError('DFT 计算胞必须由整数个各元素原子组成；或切换至 eV/atom 模式。')
    target_atom = target_eV_per_atom(target_energy, unit, int(cell_atoms) if unit == 'eV/cell' else None)
    valid = True
    st.caption(f'原子比例：{target_comp} ｜ 目标能量：{target_atom:.8f} eV/atom。默认输入的是演示值，请替换为真实 DFT 数据。')
    if not valid_cell:
        st.info('输入的计算胞原子数不符合该化学式的整数原子数；仍可计算 eV/atom，'
                '但 ΔE(eV/cell) 将不提供。')
except ValueError as exc:
    st.error(f'输入错误：{exc}')

st.subheader('② 加载竞争相数据')
x1, x2 = st.columns(2)
with x1:
    if st.button('🔎 从 Materials Project 获取竞争相', type='primary', disabled=not valid,
                 use_container_width=True):
        try:
            if not api_key:
                raise ValueError('请在左侧输入 API Key')
            with st.spinner('正在读取 MP 收录的材料结构与能量…'):
                pulled, meta = fetch_all_mp(api_key, list(target_comp), include_gnome=include_gnome,
                                            fetch_raw=fetch_raw, fetch_corrected=fetch_corrected)
            st.session_state['phase_records'] = pulled
            st.session_state['phase_meta'] = meta
            reset_results()
            st.success(f'已读取 {meta["n_materials"]} 个 MP 结构、{len(pulled)} 条能量记录。')
        except Exception as exc:
            st.error(f'数据检索失败：{type(exc).__name__}: {exc}')
with x2:
    if st.button('🧪 加载演示相库（无需 API）', use_container_width=True):
        st.session_state['phase_records'] = demo_data()
        st.session_state['phase_meta'] = {'source':'SYNTHETIC DEMONSTRATION',
                                            'elements':['Mo','Si','B'], 'n_materials':7}
        reset_results()
        st.warning('演示能量是虚构数字，绝不能用于真实相稳定性判断或论文。')

with st.expander('已有相库？从 JSON 导入；或上传自己的竞争相 CSV'):
    saved_json = st.file_uploader('加载程序导出的相库 JSON', type=['json'], key='saved_json')
    if saved_json is not None and st.button('导入 JSON'):
        try:
            new_rows, meta = rows_from_json(saved_json.getvalue())
            st.session_state['phase_records'] = new_rows
            st.session_state['phase_meta'] = meta
            reset_results()
            st.success(f'已导入 {len(new_rows)} 条记录')
        except Exception as exc:
            st.error(f'JSON 读取失败：{exc}')
    uploaded_csv = st.file_uploader('追加用户竞争相 CSV（仅在详细相库保留，不影响两个 MP 官方集合）',
                                    type=['csv'], key='custom_csv')
    if uploaded_csv is not None and st.button('追加 CSV'):
        try:
            extra = add_user_csv(uploaded_csv)
            st.session_state['phase_records'] = st.session_state.get('phase_records', []) + extra
            st.success(f'已追加 {len(extra)} 条用户数据；不会冒充 MP 官方 ★ 结构')
        except Exception as exc:
            st.error(f'CSV 读取失败：{exc}')

rows: list[EnergyRow] = st.session_state.get('phase_records', [])
meta = st.session_state.get('phase_meta', {})
if not rows:
    st.info('请先获取 MP 数据、导入相库 JSON，或点击“加载演示相库”查看结果界面。')
    st.stop()

if meta.get('source') == 'SYNTHETIC DEMONSTRATION':
    st.warning('🧪 当前为合成演示数据，以下数值不是真实材料的性质。')

if valid and 'elements' in meta and not set(target_comp).issubset(set(meta.get('elements', []))):
    st.error('当前目标相与已下载相库的元素不匹配。请按新的目标元素体系重新从 MP 下载。')
    st.stop()

st.divider()
st.subheader('③ 直接查看最低能竞争相和稳定性预测')
mp_options = sorted({(r.energy_source, r.method) for r in rows
                     if r.energy_source in ('core_raw','thermo_corrected')},
                    key=lambda k: (0 if k[0] == 'core_raw' else 1, k[1]))
if not mp_options:
    st.warning('当前相库中没有 MP 数据，无法计算官方 ★ / 全部 MP 两组。')
    st.stop()

left, mid = st.columns([1.3, 2])
with left:
    scope = st.radio('选择竞争相范围', options=['all','experimental-linked'],
                     format_func=lambda s: SCOPES[s], horizontal=True,
                     help='实验相由 MP 单个结构的 theoretical=False 判断。')
with mid:
    selected_pair = st.selectbox('选择能量方法（不同方法分开计算）', options=mp_options,
        format_func=lambda k: f'{SOURCES.get(k[0], k[0])}  /  {k[1]}')

with st.expander('高级选项：POTCAR 相容性与目标相排除设置', expanded=False):
    exclude_same = st.checkbox('排除所有与目标相相同化学计量比的 MP 条目', value=True,
                               help='避免以目标自身或同组成其他晶型作为分解产物。')
    strict_potcar = st.checkbox('严格检测 MP raw 数据中同一元素的 POTCAR 冲突', value=True)
    st.caption('原始 MP 计算与个人 VASP 计算不保证使用相同 POTCAR/泛函/U/磁性设置。'
               'MP 修正能量也不能直接视为与个人原始总能兼容。若需论文定量结论，应统一计算设置。')

if valid:
    if selected_pair[0] == 'thermo_corrected':
        st.warning('当前选的是 MP 经过修正的热力学能量；与个人 VASP 原始总能直接相减并不保证物理兼容。'
                   '请将结果视为探索性筛选，不能直接作为论文最终定量结论。')
    else:
        st.caption('采用 MP 原始 0 K DFT 能量；仍须核对目标相与 MP 条目的泛函、POTCAR、U 和磁态设置。')
    scenarios = analyze_scenarios(formula, target_atom, rows,
                                  [selected_pair], ['experimental-linked','all'],
                                  cell_atoms=int(cell_atoms) if valid_cell else None,
                                  exclude_same_composition=exclude_same,
                                  require_potcar_consistency=strict_potcar)
    by_group = {scenario.evidence_filter: scenario for scenario in scenarios}
    chosen = by_group[scope]
    with st.container(border=True):
        st.markdown(f'### {SCOPES[scope]} · {selected_pair[1]}')
        st.caption(f'候选能量记录 {chosen.phase_count} 条；目标材料 {formula}。切换上方选项会自动更新。')
        show_scenario(chosen, formula, target_atom, int(cell_atoms))

    with st.expander('对比：★ 实验相与全部 MP 相的计算结果', expanded=False):
        ca, cb = st.columns(2)
        for col, group in ((ca, 'experimental-linked'), (cb, 'all')):
            s = by_group[group]
            with col:
                st.markdown(f'**{SCOPES[group]}**')
                if s.mixture is not None:
                    v, _ = verdict(s.delta_eV_per_atom)
                    st.write('✅ 预测稳定' if v == 'stable' else '❌ 预测不稳定' if v == 'unstable' else '⚖️ 临界状态')
                    st.metric('最低竞争相 eV/atom', f'{s.mixture.energy_per_atom:.6f}')
                    st.metric('ΔE meV/atom', f'{s.delta_meV_per_atom:+.3f}')
                    st.code(reaction_text(formula, s.mixture), language=None)
                else:
                    st.warning(s.error or '无法求解')
        s_star, s_all = by_group['experimental-linked'], by_group['all']
        if s_star.mixture and s_all.mixture:
            lowering = (s_star.mixture.energy_per_atom - s_all.mixture.energy_per_atom) * 1000
            st.caption(f'纳入全部 MP 相后，竞争相最低能量相对 ★ 实验相降低 {lowering:.4f} meV/atom。'
                       '只有能量方法相同、两组都可行时才有此对比意义。')

st.divider()
with st.expander('④ 展开完整 MP 晶型与多泛函能量表（用于核查/下载）', expanded=False):
    st.caption('MP Number = 数字格式 material_id（结构编号）；MP API Material ID = 原始字母或数字结构编号；Task ID = 某一次 DFT 计算任务编号。两种 ID 不应混淆。')
    full = display_rows(rows)
    preview_method = st.multiselect('过滤方法（只影响表格，不影响上方计算）',
        options=sorted(set(full['方法'].dropna())), default=sorted(set(full['方法'].dropna())))
    st.dataframe(full[full['方法'].isin(preview_method)], use_container_width=True,
                 hide_index=True, height=400,
                 column_config={'MP URL': st.column_config.LinkColumn('MP 材料详情')})
    st.download_button('下载完整相能量 CSV', full.to_csv(index=False).encode('utf-8-sig'),
                       file_name='mp_all_structure_energies.csv', mime='text/csv')
    st.download_button('保存相库 JSON（下次免 API 重查）', rows_to_json(rows, meta),
                       file_name='mp_phase_database.json', mime='application/json')
    st.caption('★ = MP summary.theoretical=False；MP 结构有实验观测证据，但所列能量仍然是 DFT 值。')

with st.expander('⑤ MP 编号核验：输入 MP 官网的数字编号，在线核对结构', expanded=False):
    st.caption('可输入 mp-149 或 mp-aaaaaaft。此核验从 MP summary 实时读取材料身份，不会用 Task ID 冒充 Material ID。')
    check_id = st.text_input('需要核对的 Material ID', placeholder='mp-149', key='check_mpid')
    if st.button('查询 MP 官网对应的材料', disabled=not (api_key and check_id)):
        try:
            checked_id = verify_material_id(api_key, check_id)
            st.write(f'**MP Number：{checked_id["material_id"]}** ｜ API ID：{checked_id["api_material_id"]}')
            st.write(f'化学式：{checked_id["formula"]}；空间群：{checked_id["spacegroup"]}')
            if checked_id['starred'] is True:
                st.caption('★ 实验观测结构（theoretical=False）')
            elif checked_id['starred'] is False:
                st.caption('理论结构（theoretical=True）')
            if checked_id['url']:
                st.link_button('打开该 MP 材料详情页', checked_id['url'])
        except Exception as exc:
            st.error(f'编号核验失败：{type(exc).__name__}: {exc}')

with st.expander('⑥ 高级核查：查看 MP 同一结构的全部 VASP 计算任务', expanded=False):
    material_ids = sorted({r.mp_id for r in rows if material_url(r.mp_id)})
    selected_ids = st.multiselect('MP IDs（一次最多 20 个）', material_ids, max_selections=20)
    if st.button('查询 VASP task 数据', disabled=not(api_key and selected_ids)):
        try:
            with st.spinner('读取结构优化及静态计算记录…'):
                st.session_state['tasks_audit'] = fetch_task_audit(api_key, selected_ids)
            st.success(f'找到 {len(st.session_state["tasks_audit"])} 条计算任务')
        except Exception as exc:
            st.error(f'无法读取 MP task：{exc}')
    if st.session_state.get('tasks_audit'):
        audit = pd.DataFrame(st.session_state['tasks_audit'])
        st.dataframe(audit, use_container_width=True, hide_index=True)
        st.download_button('导出计算任务 CSV', audit.to_csv(index=False).encode('utf-8-sig'),
                           file_name='mp_vasp_tasks.csv', mime='text/csv')

st.caption('V5 修正 MP 2026 AlphaID / 数字 ID 显示与材料—计算任务关联。ΔE = E(目标 DFT)/atom − E(最低竞争相组合)/atom。ΔE < 0 ⇒ 在已选择 MP 候选相内预测稳定；'
           'ΔE > 0 ⇒ 预测不稳定；ΔE = 0 ⇒ 临界。此判定为 0 K 的相对能量判定，'
           '并未证明动力学可合成性，且跨数据集总能可能不兼容。')
