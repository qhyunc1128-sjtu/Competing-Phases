"""UI-independent, testable display logic for the zero-K competition results."""
from __future__ import annotations
from math import isfinite
from phase_core import Mixture
from formula_utils import parse_formula


def verdict(delta_eV_atom: float) -> tuple[str, str]:
    """Sign convention deliberately specified by the user; zero is a boundary.

    'stable' means lower than the selected *finite candidate set*, not a proof
    of complete thermodynamic stability or experimental synthesizability.
    """
    if not isfinite(delta_eV_atom):
        raise ValueError('能量差必须是有限数字')
    if delta_eV_atom < 0:
        return 'stable', '预测稳定（目标相能量低于最低竞争相组合）'
    if delta_eV_atom > 0:
        return 'unstable', '预测不稳定（目标相能量高于最低竞争相组合）'
    return 'boundary', '临界状态（ΔE = 0，不判定为稳定）'


def format_number(x: float) -> str:
    """Show small coefficients without rounding them to zero."""
    if abs(x - round(x)) < 1e-9:
        return str(round(x))
    return f'{x:.8g}'


def reaction_text(formula: str, mixture: Mixture) -> str:
    if not mixture.products:
        return f'{formula} → （没有竞争相）'
    right = ' + '.join(f'{format_number(p.coefficient_per_target_formula)} {p.formula}'
                       for p in mixture.products)
    return f'{formula} → {right}'


def product_breakdown(formula: str, mixture: Mixture) -> list[dict]:
    """Per-product energy contribution; sum equals the optimized mix energy."""
    N = float(sum(parse_formula(formula).values()))
    out = []
    for p in mixture.products:
        n = float(sum(parse_formula(p.formula).values()))
        out.append({
            'phase': p.formula,
            'coefficient': p.coefficient_per_target_formula,
            'coefficient_label': format_number(p.coefficient_per_target_formula),
            'mp_id': p.mp_id,
            'mp_id_api': p.mp_id_api,
            'task_id_api': p.task_id_api,
            'evidence': p.evidence,
            'energy_eV_atom': p.energy_per_atom,
            'energy_contribution_eV_atom': p.coefficient_per_target_formula * n / N * p.energy_per_atom,
            'atom_fraction': p.atom_fraction,
            'task_id': p.task_id,
        })
    return out
