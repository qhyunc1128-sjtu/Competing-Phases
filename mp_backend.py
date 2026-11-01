"""Materials Project API adapter. Imported only when online retrieval is requested."""
from __future__ import annotations

from datetime import datetime, timezone

from phase_core import Phase

THERMO_TYPES = (
    "GGA_GGA+U", "GGA_GGA+U_R2SCAN", "R2SCAN"
)


def fetch_mp_phases(api_key: str, elements: list[str], thermo_type: str) -> tuple[list[Phase], dict]:
    if not api_key.strip():
        raise ValueError("请提供 Materials Project API Key。")
    if thermo_type not in THERMO_TYPES:
        raise ValueError("不支持的热力学能量体系。")
    if not 1 <= len(set(elements)) <= 9:
        raise ValueError("当前 MP get_entries_in_chemsys 接口最多支持 9 种不同元素。")
    try:
        from mp_api.client import MPRester
        from pymatgen.analysis.phase_diagram import PhaseDiagram
    except ImportError as exc:
        raise RuntimeError("缺少 mp-api 或 pymatgen，请先安装 requirements.txt。") from exc

    # Critical: request exactly ONE compatible thermodynamic scheme.
    # The MP API uses a system-wide common energy scale for the mixed scheme.
    with MPRester(api_key=api_key.strip()) as mpr:
        entries = mpr.get_entries_in_chemsys(
            sorted(set(elements)),
            compatible_only=True,
            additional_criteria={"thermo_types": [thermo_type]},
        )
    if not entries:
        raise ValueError("MP 没有返回相条目，无法构造凸包。")

    pd = PhaseDiagram(entries)
    phases = []
    for entry in entries:
        comp = entry.composition.get_reduced_composition_and_factor()[0]
        frac = comp.get_el_amt_dict()
        material_id = (getattr(entry, "data", None) or {}).get("material_id") or entry.entry_id or ""
        phases.append(Phase(
            formula=comp.reduced_formula,
            composition={k: float(v) for k, v in frac.items()},
            formation_energy_per_atom=float(pd.get_form_energy_per_atom(entry)),
            mp_id=str(material_id),
            mp_energy_per_atom=float(entry.energy_per_atom),
        ))
    # Defensive, because duplicate polymorph records otherwise complicate listing.
    seen = set()
    unique = []
    for phase in phases:
        key = (phase.mp_id, phase.formula, round(phase.formation_energy_per_atom, 9))
        if key not in seen:
            unique.append(phase); seen.add(key)
    return unique, {
        "source": "Materials Project API / thermo entries",
        "elements": sorted(set(elements)),
        "thermo_type": thermo_type,
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "n_entries": len(unique),
        "disclaimer": "MP 已兼容化的每原子形成能；不得直接与独立 DFT 原始绝对总能相减。",
    }
