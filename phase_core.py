"""0 K signed competition energy with elemental atom conservation.

Objective: minimize SUM_j a_j * E_j(eV/atom), where a_j is fraction of
all atoms supplied by phase j, subject to the target atomic fractions.
No elemental reference state / formation enthalpy is required.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
import re
from typing import Any, Mapping, Sequence
import json
import numpy as np
from scipy.optimize import linprog

# Reuse original project's explicitly validated fractional formula parser.
from formula_utils import parse_formula, atom_fractions, same_stoichiometry


class CompetingPhaseError(ValueError):
    pass


@dataclass
class EnergyRow:
    formula: str
    composition: dict[str, float]
    energy_per_atom: float
    mp_id: str
    energy_source: str  # core_raw / thermo_corrected / user_custom
    method: str         # GGA | GGA+U | r2SCAN | GGA_GGA+U etc
    evidence: str = "unknown"  # experimental-linked / theoretical / unknown
    experimental_flag: bool | None = None
    spacegroup: str = ""
    task_id: str = ""
    potcar: str = ""
    hubbards: str = ""
    correction_per_atom: float | None = None
    dft_cell_atoms: float | None = None
    dft_total_energy_eV: float | None = None
    note: str = ""

    def __post_init__(self):
        if not isinstance(self.composition, dict) or not self.composition:
            raise ValueError('Missing composition')
        atom_fractions(self.composition)
        self.energy_per_atom = float(self.energy_per_atom)
        if not isfinite(self.energy_per_atom):
            raise ValueError('Non-finite energy')
        if self.energy_source not in ('core_raw', 'thermo_corrected', 'user_custom'):
            raise ValueError('Unknown energy source')
        if self.evidence not in ('experimental-linked', 'theoretical', 'unknown'):
            raise ValueError('Unknown evidence class')


@dataclass
class Product:
    formula: str
    mp_id: str
    task_id: str
    method: str
    evidence: str
    energy_per_atom: float
    atom_fraction: float
    coefficient_per_target_formula: float


@dataclass
class Mixture:
    energy_per_atom: float
    products: list[Product]
    max_residual: float


@dataclass
class Scenario:
    label: str
    energy_source: str
    method: str
    evidence_filter: str
    phase_count: int
    status: str
    mixture: Mixture | None
    delta_eV_per_atom: float | None
    delta_meV_per_atom: float | None
    delta_eV_per_cell: float | None
    error: str = ""


def atom_count(comp: Mapping[str, float]) -> float:
    return float(sum(comp.values()))


def target_eV_per_atom(energy: float, unit: str, num_atoms: int | None = None) -> float:
    energy = float(energy)
    if not isfinite(energy):
        raise ValueError('目标总能量不是有限数字')
    if unit == 'eV/atom':
        return energy
    if unit == 'eV/cell':
        if num_atoms is None or int(num_atoms) <= 0:
            raise ValueError('请输入有效的计算胞总原子数')
        return energy / int(num_atoms)
    raise ValueError('Invalid unit')


def check_cell_stoichiometry(target_formula: str, num_atoms: int) -> None:
    """Actual periodic cell must contain integer element counts for given formula ratios."""
    comp = parse_formula(target_formula)
    if num_atoms < 1:
        raise ValueError('原子数必须 >=1')
    frac = atom_fractions(comp)
    for el, x in frac.items():
        k = x * num_atoms
        if not np.isclose(k, round(k), atol=1e-6, rtol=1e-8):
            raise ValueError(f'{el}: 该原子比例与 {num_atoms} 原子计算胞不匹配（{k:g} 非整数）')


def filter_by_evidence(rows: Sequence[EnergyRow], group: str) -> list[EnergyRow]:
    """The TWO MP Materials Explorer scopes, by individual material/structure ID.

    MP star (experimentally observed): summary.theoretical is exactly False.
    An absent/unknown flag is *not* evidence of an experimental structure.
    User-supplied CSV entries cannot independently claim an MP star even if their
    user-entered `evidence` text says 'experimental-linked'.
    """
    mp_rows = [x for x in rows if x.energy_source in ('core_raw', 'thermo_corrected')]
    if group == 'all':
        return mp_rows
    if group == 'experimental-linked':
        return [x for x in mp_rows if x.experimental_flag is True]
    raise ValueError('仅支持两种 MP 范围：all、experimental-linked')


def potcar_conflicts(rows: Sequence[EnergyRow]) -> dict[str, list[str]]:
    """Flag differing POTCAR names/hashes for the SAME chemical element.

    POTCAR metadata is often missing. An empty map DOES NOT prove consistency.
    This is a conservative heuristic for common MP potcar_spec spellings, not a
    replacement for detailed comparison of POTCAR ENMAX, hashes and PAW family.
    """
    found: dict[str, set[str]] = {}
    for r in rows:
        for part in r.potcar.split(';'):
            part = part.strip()
            if not part:
                continue
            prefix = part.split(' [', 1)[0]
            matches = re.findall(r'(?<![A-Za-z])([A-Z][a-z]?)(?=_|\s|$)', prefix)
            if not matches:
                continue
            elem = matches[-1]
            if elem not in r.composition:
                continue
            found.setdefault(elem, set()).add(part)
    return {el: sorted(specs) for el, specs in found.items() if len(specs) > 1}


def solve_minimum(target_comp: Mapping[str, float], candidates: Sequence[EnergyRow],
                  *, exclude_same_composition: bool = True) -> Mixture:
    els = sorted(target_comp)
    tfrac = atom_fractions(target_comp)
    eligible = [r for r in candidates if set(r.composition).issubset(set(els)) and
                (not exclude_same_composition or not same_stoichiometry(target_comp, r.composition))]
    if not eligible:
        raise CompetingPhaseError('筛选后没有竞争相；可能是排除了所有同组成相')
    a = np.array([[atom_fractions(r.composition).get(el, 0.0) for r in eligible] for el in els], float)
    b = np.array([tfrac[el] for el in els], float)
    c = np.array([r.energy_per_atom for r in eligible], float)
    # All atom balances imply sum_j a_j = 1.
    ans = linprog(c, A_eq=a, b_eq=b, bounds=(0, None), method='highs')
    if not ans.success:
        raise CompetingPhaseError('无法配平原子比并求得竞争相能量：' + ans.message)
    residual = float(np.max(np.abs(a @ ans.x - b)))
    if residual > 1e-6:
        raise CompetingPhaseError('元素守恒残差过大')
    denom = atom_count(target_comp)
    products = []
    for idx, w in enumerate(ans.x):
        if w > 1e-7:
            r = eligible[idx]
            products.append(Product(
                formula=r.formula, mp_id=r.mp_id, task_id=r.task_id,
                method=r.method, evidence=r.evidence,
                energy_per_atom=r.energy_per_atom,
                atom_fraction=float(w),
                coefficient_per_target_formula=float(w * denom / atom_count(r.composition)),
            ))
    return Mixture(energy_per_atom=float(c @ ans.x), products=products, max_residual=residual)


def analyze_scenarios(target_formula: str, target_energy: float, rows: Sequence[EnergyRow],
                      methods: Sequence[tuple[str, str]], evidence_groups: Sequence[str],
                      *, cell_atoms: int | None = None, exclude_same_composition: bool = True,
                      require_potcar_consistency: bool = True) -> list[Scenario]:
    if any(g not in ('all', 'experimental-linked') for g in evidence_groups):
        raise ValueError('只能选择 MP ★ 实验结构与全部 MP 结构这两种范围')
    target = parse_formula(target_formula)
    target_energy = float(target_energy)
    if not isfinite(target_energy):
        raise ValueError('Invalid target energy')
    result = []
    for source, method in methods:
        method_rows = [r for r in rows if r.energy_source == source and r.method == method]
        for group in evidence_groups:
            eligible = filter_by_evidence(method_rows, group)
            # Duplicate chemical polymorphs / different MP IDs are intentionally retained.
            label = f'{source} / {method} / {group}'
            try:
                if require_potcar_consistency and source in ('core_raw', 'user_custom'):
                    checked = [r for r in eligible if
                               (not exclude_same_composition or not same_stoichiometry(target, r.composition))]
                    conflicts = potcar_conflicts(checked)
                    if conflicts:
                        summary = '; '.join(f'{el}: {" vs ".join(labels)}' for el, labels in conflicts.items())
                        raise CompetingPhaseError('同一元素的 POTCAR 不一致；默认阻止混算。'
                                                  '请筛选相或取消严格校验后仅作探索性计算。' + summary)
                mix = solve_minimum(target, eligible, exclude_same_composition=exclude_same_composition)
                delta = target_energy - mix.energy_per_atom
                result.append(Scenario(label, source, method, group, len(eligible), 'ok', mix,
                                       delta, delta * 1000,
                                       delta * cell_atoms if cell_atoms is not None else None))
            except CompetingPhaseError as exc:
                result.append(Scenario(label, source, method, group, len(eligible), 'not solvable',
                                       None, None, None, None, str(exc)))
    return result


def rows_to_json(rows: Sequence[EnergyRow], metadata: dict[str, Any] | None = None) -> str:
    return json.dumps({'metadata': metadata or {}, 'records': [asdict(r) for r in rows]},
                      indent=2, ensure_ascii=False)


def rows_from_json(blob: bytes | str) -> tuple[list[EnergyRow], dict[str, Any]]:
    data = json.loads(blob)
    if not isinstance(data, dict) or not isinstance(data.get('records'), list):
        raise ValueError('Invalid saved phase JSON')
    return [EnergyRow(**r) for r in data['records']], data.get('metadata') or {}
