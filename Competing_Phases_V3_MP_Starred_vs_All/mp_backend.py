"""MP transport. No key ever serialized, cached globally, exported, or logged.

Data layers:
- summary: MP Materials Explorer ★ flag via `theoretical is False`, by structure ID
- core materials.entries: one selected raw DFT entry per material x run_type
- thermo: independently reported *corrected* energies by thermodynamic mixing scheme
- optional tasks: all available VASP tasks for selected material IDs (audit only)
"""
from __future__ import annotations

from datetime import datetime, timezone
from itertools import combinations
from math import isfinite
from typing import Any

from formula_utils import parse_formula
from phase_core import EnergyRow

THERMO_TYPES = ("GGA_GGA+U", "GGA_GGA+U_R2SCAN", "r2SCAN")
MAX_ELEMENTS = 9  # explicit safe upper bound; 7–9 element queries can be very slow
MAX_MATERIALS = 12000  # fail visibly, not silent truncation


def _value(doc: Any, field: str, default=None):
    if isinstance(doc, dict):
        return doc.get(field, default)
    return getattr(doc, field, default)


def _scalar(x: Any) -> str:
    return str(getattr(x, 'value', x)) if x is not None else ''


def _formula(comp: Any, fallback: str = '') -> dict[str, float]:
    if comp is None:
        return parse_formula(fallback)
    if hasattr(comp, 'get_el_amt_dict'):
        return {str(k): float(v) for k, v in comp.get_el_amt_dict().items()}
    if isinstance(comp, dict):
        if 'element_composition' in comp:
            return _formula(comp['element_composition'], fallback)
        # Common Monty serialization of Composition: {'Mo': 5, 'Si': 1, 'B': 2}
        d = {str(k): float(v) for k, v in comp.items() if not str(k).startswith('@') and isinstance(v, (float, int))}
        if d:
            return d
    return parse_formula(fallback)


def _potcar_text(spec) -> str:
    if not spec:
        return ''
    result = []
    for p in spec:
        sym = _value(p, 'symbol') or _value(p, 'titel') or _value(p, 'title') or ''
        hash_ = _value(p, 'hash') or _value(p, 'md5') or ''
        result.append(f'{sym} [{hash_}]' if hash_ else str(sym))
    return '; '.join(result)


def _hubbards_text(raw) -> str:
    if not isinstance(raw, dict):
        return str(raw) if raw else ''
    return ', '.join(f'{el}:{float(value):g}' for el, value in sorted(raw.items()))


def enumerate_subsystems(elements: list[str]) -> list[str]:
    els = sorted(set(elements))
    if not 1 <= len(els) <= MAX_ELEMENTS:
        raise ValueError(f'当前在线全子体系检索允许 1–{MAX_ELEMENTS} 种元素；更多元素建议按子体系分批导入 JSON/CSV。')
    return ['-'.join(c) for size in range(1, len(els) + 1) for c in combinations(els, size)]


def _batches(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i+size]


def _summary_map(mpr, subsystems: list[str], include_gnome: bool) -> dict[str, dict]:
    meta = {}
    for parts in _batches(subsystems, 35):
        docs = mpr.materials.summary.search(
            chemsys=parts, include_gnome=include_gnome,
            fields=['material_id', 'formula_pretty', 'composition', 'theoretical', 'symmetry'],
            chunk_size=1000,
        )
        for d in docs:
            mid = _scalar(_value(d, 'material_id'))
            sym = _value(d, 'symmetry')
            theoretical = _value(d, 'theoretical')
            if theoretical is True:
                evidence = 'theoretical'
            elif theoretical is False:
                evidence = 'experimental-linked'
            else:
                evidence = 'unknown'
            meta[mid] = {
                'formula': str(_value(d, 'formula_pretty') or ''),
                'composition': _formula(_value(d, 'composition'), str(_value(d, 'formula_pretty') or '')),
                'evidence': evidence,
                'experimental_flag': theoretical is False if isinstance(theoretical, bool) else None,
                'spacegroup': str(_value(sym, 'symbol') or ''),
            }
            if len(meta) > MAX_MATERIALS:
                raise ValueError(f'MP 返回超过 {MAX_MATERIALS} 个结构；请缩小体系或分批检索。本程序不会截断结果。')
    return meta


def _entry_to_record(mid: str, run_type: str, entry: Any, s: dict) -> EnergyRow | None:
    # Prefer official pymatgen entry model for consistent uncorrected energy handling.
    try:
        from pymatgen.entries.computed_entries import ComputedEntry, ComputedStructureEntry
        if isinstance(entry, dict):
            if entry.get('@class') == 'ComputedStructureEntry':
                obj = ComputedStructureEntry.from_dict(entry)
            else:
                obj = ComputedEntry.from_dict(entry)
        else:
            obj = entry
        energy = float(obj.uncorrected_energy_per_atom)
        raw_cell_energy = float(obj.uncorrected_energy)
        raw_cell_atoms = float(obj.composition.num_atoms)
        params = getattr(obj, 'parameters', {}) or {}
        data = getattr(obj, 'data', {}) or {}
        comp = _formula(getattr(obj, 'composition', None), s['formula'])
        task_id = _scalar(data.get('task_id', ''))
    except (ImportError, ValueError, TypeError, AttributeError, KeyError):
        # A legacy serialized representation may not round-trip through the
        # current model. Handle its numeric fields with explicit correction.
        params = _value(entry, 'parameters', {}) or {}
        data = _value(entry, 'data', {}) or {}
        comp = _formula(_value(entry, 'composition'), s['formula'])
        e = _value(entry, 'energy')
        correction = float(_value(entry, 'correction', 0) or 0)
        if e is None:
            return None
        raw_cell_energy = float(e) - correction
        raw_cell_atoms = float(sum(comp.values()))
        energy = raw_cell_energy / raw_cell_atoms
        task_id = _scalar(data.get('task_id', ''))
    if not isfinite(energy):
        return None
    actual_run = _scalar(params.get('run_type')) or run_type
    return EnergyRow(
        formula=s['formula'] or ''.join(f'{k}{v:g}' for k, v in comp.items()),
        composition=comp, energy_per_atom=energy, mp_id=mid,
        energy_source='core_raw', method=actual_run,
        evidence=s['evidence'], experimental_flag=s['experimental_flag'],
        spacegroup=s['spacegroup'], task_id=task_id,
        potcar=_potcar_text(params.get('potcar_spec')),
        hubbards=_hubbards_text(params.get('hubbards')),
        dft_cell_atoms=raw_cell_atoms, dft_total_energy_eV=raw_cell_energy,
        note='MP core preferred/selected raw entry, not every optimization task',
    )


def fetch_all_mp(api_key: str, elements: list[str], *, include_gnome: bool = True,
                 fetch_raw: bool = True, fetch_corrected: bool = True) -> tuple[list[EnergyRow], dict]:
    if not api_key or not api_key.strip():
        raise ValueError('请输入个人 Materials Project API Key')
    if not fetch_raw and not fetch_corrected:
        raise ValueError('至少检索一个能量来源')
    subsystems = enumerate_subsystems(elements)
    from mp_api.client import MPRester
    records: list[EnergyRow] = []
    with MPRester(api_key=api_key.strip(), use_document_model=False) as mpr:
        summaries = _summary_map(mpr, subsystems, include_gnome)
        mids = sorted(summaries)
        if not mids:
            raise ValueError('MP 未找到任何候选结构。')
        if fetch_raw:
            for batch in _batches(mids, 100):
                docs = mpr.materials.search(material_ids=batch,
                    fields=['material_id', 'entries'], chunk_size=100)
                for d in docs:
                    mid = _scalar(_value(d, 'material_id'))
                    if mid not in summaries:
                        continue
                    ent = _value(d, 'entries') or {}
                    if not isinstance(ent, dict):
                        ent = getattr(ent, '__dict__', {})
                    for rt, entry in ent.items():
                        if entry is not None:
                            r = _entry_to_record(mid, str(rt), entry, summaries[mid])
                            if r:
                                records.append(r)
        if fetch_corrected:
            for batch in _batches(mids, 100):
                docs = mpr.materials.thermo.search(
                    material_ids=batch,
                    thermo_types=list(THERMO_TYPES),
                    fields=['material_id', 'thermo_type', 'energy_per_atom',
                            'uncorrected_energy_per_atom', 'energy_type'],
                    chunk_size=100,
                )
                for d in docs:
                    mid = _scalar(_value(d, 'material_id'))
                    if mid not in summaries:
                        continue
                    scheme = _scalar(_value(d, 'thermo_type'))
                    e = _value(d, 'energy_per_atom')
                    u = _value(d, 'uncorrected_energy_per_atom')
                    if e is None or scheme not in THERMO_TYPES:
                        continue
                    s = summaries[mid]
                    records.append(EnergyRow(
                        formula=s['formula'], composition=s['composition'],
                        energy_per_atom=float(e), mp_id=mid,
                        energy_source='thermo_corrected', method=scheme,
                        evidence=s['evidence'], experimental_flag=s['experimental_flag'],
                        spacegroup=s['spacegroup'],
                        correction_per_atom=(float(e) - float(u)) if u is not None else None,
                        note=f'MP thermo scheme, selected energy type: {_scalar(_value(d, "energy_type"))}',
                    ))
    unique = {(r.mp_id, r.energy_source, r.method, r.task_id): r for r in records}
    return list(unique.values()), {
        'source': 'Materials Project /materials/summary + /materials/core + /materials/thermo',
        'retrieved_utc': datetime.now(timezone.utc).isoformat(),
        'elements': sorted(set(elements)),
        'subsystems_queried': subsystems,
        'n_materials': len(summaries),
        'n_mp_starred': sum(v['experimental_flag'] is True for v in summaries.values()),
        'n_mp_nonstarred': sum(v['experimental_flag'] is False for v in summaries.values()),
        'n_mp_flag_unknown': sum(v['experimental_flag'] is None for v in summaries.values()),
        'n_energy_rows': len(unique),
        'include_gnome': include_gnome,
        'fetch_raw': fetch_raw, 'fetch_corrected': fetch_corrected,
        'note': 'No API key stored. MP star (experimentally observed) = summary.theoretical is False; all = no theoretical filter. '
                'This is matched experimental structure provenance, not a measured MP DFT energy. '
                'Neither MP nor this app contains all conceivable structures.',
    }


def fetch_task_audit(api_key: str, material_ids: list[str], limit: int = 20) -> list[dict]:
    """All MP calculation task IDs for requested materials, as an AUDIT table only.

    Task energies from relaxations/statics and alternative POTCARs may not share
    a single consistent thermodynamic energy scale. Never add automatically to LP.
    """
    mids = list(dict.fromkeys(x.strip() for x in material_ids if x.strip()))
    if not mids or len(mids) > limit:
        raise ValueError(f'请选择 1–{limit} 个 MP ID 查询计算任务')
    from mp_api.client import MPRester
    rows = []
    with MPRester(api_key=api_key.strip(), use_document_model=False) as mpr:
        core = mpr.materials.search(material_ids=mids, fields=['material_id','task_ids'])
        task_to_mat = {}
        for d in core:
            for task_id in _value(d, 'task_ids', []) or []:
                task_to_mat[_scalar(task_id)] = _scalar(_value(d, 'material_id'))
        if len(task_to_mat) > 1500:
            raise ValueError('任务超过 1500 个；请缩小到更少 MP ID 查询')
        for batch in _batches(list(task_to_mat), 35):
            docs = mpr.materials.tasks.search(task_ids=batch,
                fields=['task_id', 'run_type', 'task_type', 'state', 'input', 'output'],
                chunk_size=100)
            for d in docs:
                tid = _scalar(_value(d, 'task_id'))
                inp = _value(d, 'input')
                out = _value(d, 'output')
                raw = _value(out, 'energy_per_atom')
                if raw is None and _value(out, 'energy') is not None:
                    struct = _value(out, 'structure')
                    comp = _value(struct, 'composition')
                    try:
                        raw = float(_value(out, 'energy')) / sum(_formula(comp).values())
                    except (ValueError, KeyError, TypeError):
                        pass
                rows.append({
                    'material_id': task_to_mat.get(tid, ''), 'task_id': tid,
                    'run_type': _scalar(_value(d, 'run_type')),
                    'task_type': _scalar(_value(d, 'task_type')),
                    'state': _scalar(_value(d, 'state')),
                    'energy_eV_per_atom': raw,
                    'potcar': _potcar_text(_value(inp, 'potcar_spec')),
                    'hubbards': _hubbards_text(_value(inp, 'hubbards')),
                    'use_in_lp': False,
                })
    return rows
