"""Validated formula parsing utilities."""
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


