"""Numerical engine for competing-phase equilibrium at a specified composition.

Only formation energies per atom, already aligned to ONE set of elemental
references, may be combined in a single convex-hull linear program.

This module deliberately does not require pymatgen or network access.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
import re
from typing import Mapping, Sequence

import numpy as np
from scipy.optimize import linprog

# Validate chemical element symbols rather than silently accepting typos.
ELEMENTS = set((
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
    "Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba "
    "La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl "
    "Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg "
    "Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og"
).split())
_TOKEN_RE = re.compile(r"[A-Z][a-z]?|\(|\)|(?:\d+(?:\.\d*)?|\.\d+)")
_NUMBER_RE = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)\Z")


class CompositionError(ValueError):
    pass


class HullError(ValueError):
    pass


def parse_formula(formula: str) -> dict[str, float]:
    """Accept element symbols, decimal stoichiometries, and parenthesized groups.

    Examples: Mo5SiB2; Mo4.5Ti0.5SiB2; (Mo0.8Ti0.2)5SiB2.
    """
    text = re.sub(r"\s+", "", formula)
    if not text:
        raise CompositionError("化学式不能为空。")
    tokens = _TOKEN_RE.findall(text)
    if "".join(tokens) != text:
        raise CompositionError("化学式包含无法识别的字符；请用 Mo4.5Ti0.5SiB2 等格式。")
    stack: list[dict[str, float]] = [{}]
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "(":
            stack.append({})
            i += 1
            continue
        if token == ")":
            if len(stack) == 1 or not stack[-1]:
                raise CompositionError("化学式括号不匹配或包含空括号。")
            sub = stack.pop()
            i += 1
            factor = 1.0
            if i < len(tokens) and _NUMBER_RE.fullmatch(tokens[i]):
                factor = float(tokens[i]); i += 1
            if not isfinite(factor) or factor <= 0:
                raise CompositionError("原子个数必须是正数。")
            for el, n in sub.items():
                stack[-1][el] = stack[-1].get(el, 0.0) + factor * n
            continue
        if _NUMBER_RE.fullmatch(token):
            raise CompositionError("化学式中出现未跟随元素或括号的数字。")
        if token not in ELEMENTS:
            raise CompositionError(f"不合法的元素符号：{token}。")
        i += 1
        amount = 1.0
        if i < len(tokens) and _NUMBER_RE.fullmatch(tokens[i]):
            amount = float(tokens[i]); i += 1
        if not isfinite(amount) or amount <= 0:
            raise CompositionError("原子个数必须是正数。")
        stack[-1][token] = stack[-1].get(token, 0.0) + amount
    if len(stack) != 1 or not stack[0]:
        raise CompositionError("化学式缺少右括号或有效元素。")
    return stack[0]


def atom_fractions(comp: Mapping[str, float]) -> dict[str, float]:
    if not comp or any(not isfinite(v) or v <= 0 for v in comp.values()):
        raise CompositionError("所有元素的原子个数必须是正数。")
    total = sum(comp.values())
    return {el: v / total for el, v in comp.items()}


def same_stoichiometry(a: Mapping[str, float], b: Mapping[str, float], tol: float = 1e-7) -> bool:
    if set(a) != set(b):
        return False
    xa, xb = atom_fractions(a), atom_fractions(b)
    return all(abs(xa[el] - xb[el]) < tol for el in xa)


def format_formula(comp: Mapping[str, float]) -> str:
    # Display a fractional stoichiometry unchanged (without forced integer rounding).
    return "".join(el + ("" if abs(v - 1) < 1e-10 else f"{v:g}") for el, v in comp.items())


@dataclass(frozen=True)
class Phase:
    formula: str
    composition: dict[str, float]  # atoms per displayed phase formula, not cell
    formation_energy_per_atom: float  # compatible MP phase diagram, eV/atom
    mp_id: str
    mp_energy_per_atom: float | None = None  # corrected MP energy, never used with user raw energies

    def __post_init__(self) -> None:
        atom_fractions(self.composition)
        if not isfinite(self.formation_energy_per_atom):
            raise ValueError("非有限形成能。")
        if self.mp_energy_per_atom is not None and not isfinite(self.mp_energy_per_atom):
            raise ValueError("非有限 MP 总能。")


@dataclass(frozen=True)
class Product:
    formula: str
    mp_id: str
    formation_energy_per_atom: float
    atomic_fraction: float  # of all atoms in target formula
    formula_coefficient: float  # formula units per ONE user-input target formula


@dataclass(frozen=True)
class Equilibrium:
    formation_energy_per_atom: float
    products: list[Product]
    max_composition_residual: float


@dataclass(frozen=True)
class Analysis:
    target_formula: str
    target_comp: dict[str, float]
    target_formation_energy_per_atom: float
    global_hull: Equilibrium
    alternative_hull: Equilibrium | None
    delta_global_eV_per_atom: float  # signed: E_DFT(form) - E_hull_MP(form)
    delta_alternative_eV_per_atom: float | None
    same_composition_count: int
    n_phases: int


def solve_mixture(target: Mapping[str, float], phases: Sequence[Phase]) -> Equilibrium:
    """Minimize sum_j y_j * Hf_j subject to sum_j y_j*x_ij = x_i(target).

    y_j: fraction of total atoms contributed by phase j.
    x_ij: atomic fraction of element i in phase j.
    """
    if not phases:
        raise HullError("没有可用于求解的候选相。")
    elements = sorted(target)
    tx = atom_fractions(target)
    valid = [p for p in phases if set(p.composition).issubset(set(elements))]
    if not valid:
        raise HullError("候选相没有覆盖目标元素体系。")
    a = np.array([[atom_fractions(p.composition).get(el, 0.0) for p in valid] for el in elements], dtype=float)
    b = np.array([tx[el] for el in elements], dtype=float)
    # Atom-fraction constraints already imply sum(y)==1; an explicit row is
    # redundant and is avoided to improve HiGHS matrix rank.
    c = np.array([p.formation_energy_per_atom for p in valid], dtype=float)
    result = linprog(c, A_eq=a, b_eq=b, bounds=(0, None), method="highs")
    if not result.success:
        raise HullError(f"无法获得该组成的竞争相平衡：{result.message}")
    weights = np.maximum(result.x, 0)
    residual = float(np.max(np.abs(a @ weights - b)))
    if residual > 1e-6:
        raise HullError(f"求解的原子比例残差过大：{residual:.3g}")
    ntarget = sum(target.values())
    products = [
        Product(
            formula=p.formula,
            mp_id=p.mp_id,
            formation_energy_per_atom=p.formation_energy_per_atom,
            atomic_fraction=float(weights[j]),
            formula_coefficient=float(weights[j] * ntarget / sum(p.composition.values())),
        )
        for j, p in enumerate(valid)
        if weights[j] > 1e-7
    ]
    return Equilibrium(float(c @ weights), products, residual)


def analyze(target_formula: str, target_hf_eV_per_atom: float, phases: Sequence[Phase]) -> Analysis:
    target = parse_formula(target_formula)
    if not isfinite(target_hf_eV_per_atom):
        raise ValueError("目标形成能必须是有限数字。")
    filtered = [p for p in phases if set(p.composition).issubset(set(target))]
    global_hull = solve_mixture(target, filtered)
    other = [p for p in filtered if not same_stoichiometry(target, p.composition)]
    same_n = len(filtered) - len(other)
    try:
        alternative = solve_mixture(target, other)
    except HullError:
        alternative = None
    delta = target_hf_eV_per_atom - global_hull.formation_energy_per_atom
    return Analysis(
        target_formula=target_formula,
        target_comp=target,
        target_formation_energy_per_atom=target_hf_eV_per_atom,
        global_hull=global_hull,
        alternative_hull=alternative,
        delta_global_eV_per_atom=delta,
        delta_alternative_eV_per_atom=(
            target_hf_eV_per_atom - alternative.formation_energy_per_atom
            if alternative is not None else None
        ),
        same_composition_count=same_n,
        n_phases=len(filtered),
    )


def formation_energy_from_total(
    formula: str,
    dft_total_eV: float,
    cell_atom_count: int,
    elemental_dft_eV_per_atom: Mapping[str, float],
) -> float:
    """Compute Hf/atom using user's OWN elemental calculations, not MP raw energies."""
    comp = parse_formula(formula)
    if not isinstance(cell_atom_count, int) or cell_atom_count <= 0:
        raise ValueError("计算胞原子数必须是正整数。")
    if not isfinite(dft_total_eV):
        raise ValueError("DFT 总能必须为有限数值。")
    nformula = sum(comp.values())
    copies = cell_atom_count / nformula
    # Formula is an integer or decimal multiple of the simulated cell composition.
    if not np.isclose(copies, round(copies), atol=1e-7, rtol=1e-7):
        raise ValueError(
            "计算胞原子数与输入化学式不成整数倍。请使用实际计算胞化学式，"
            "或输入能表示其整数倍的化学计量式。"
        )
    for element, count in comp.items():
        atoms_in_cell = count * copies
        if not np.isclose(atoms_in_cell, round(atoms_in_cell), atol=1e-6, rtol=1e-8):
            raise ValueError(f"{element} 在所填计算胞中对应 {atoms_in_cell:g} 个原子，不是整数；请核对原子比与晶胞原子数。")
    missing = set(comp) - set(elemental_dft_eV_per_atom)
    if missing:
        raise ValueError("缺少同一计算方法下的单质参考能：" + ", ".join(sorted(missing)))
    vals = [elemental_dft_eV_per_atom[el] for el in comp]
    if any(not isfinite(v) for v in vals):
        raise ValueError("单质参考能必须是有限数值。")
    baseline = sum(x * elemental_dft_eV_per_atom[el] for el, x in atom_fractions(comp).items())
    return dft_total_eV / cell_atom_count - baseline


def aligned_energy_per_atom(
    formation_energy_per_atom: float,
    comp: Mapping[str, float],
    elemental_dft_eV_per_atom: Mapping[str, float],
) -> float:
    """MP ΔHf transplanted onto user's elemental DFT reference; approximate only."""
    return formation_energy_per_atom + sum(
        frac * elemental_dft_eV_per_atom[el] for el, frac in atom_fractions(comp).items()
    )


def dump_phases(phases: Sequence[Phase]) -> list[dict]:
    return [asdict(p) for p in phases]


def load_phases(data: list[dict]) -> list[Phase]:
    if not isinstance(data, list) or not data:
        raise ValueError("相库 JSON 不包含有效的相数据。")
    return [Phase(**d) for d in data]
