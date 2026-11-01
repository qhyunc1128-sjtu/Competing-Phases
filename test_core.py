import json
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest

from formula_utils import parse_formula, same_stoichiometry
from phase_core import (EnergyRow, solve_minimum, analyze_scenarios,
                        check_cell_stoichiometry, rows_from_json, rows_to_json, target_eV_per_atom,
                        CompetingPhaseError)
from mp_backend import _entry_to_record, enumerate_subsystems


def row(formula, energy, evidence='theoretical', source='core_raw', method='GGA', mid=None):
    return EnergyRow(formula, parse_formula(formula), energy, mid or f'test-{formula}', source,
                     method, evidence, experimental_flag=(evidence == 'experimental-linked') if source != 'user_custom' else None)


def test_fractional_parsing_and_normalization():
    assert parse_formula('(Mo0.8Ti0.2)5SiB2') == {'Mo': 4, 'Ti': 1, 'Si': 1, 'B': 2}
    assert same_stoichiometry(parse_formula('Mo5SiB2'), parse_formula('Mo10Si2B4'))
    assert target_eV_per_atom(-320, 'eV/cell', 32) == -10


def test_reference_mo5sib2_algebra():
    rows = [row('Mo3Si', -9.0), row('MoB', -8.0)]
    sol = solve_minimum(parse_formula('Mo5SiB2'), rows)
    assert sol.energy_per_atom == pytest.approx(-8.5)
    coef = {p.formula: p.coefficient_per_target_formula for p in sol.products}
    assert coef == pytest.approx({'Mo3Si': 1, 'MoB': 2})
    assert sol.max_residual < 1e-10


def test_lower_energy_competing_chooses_minimum():
    # Mo3Si + 2MoB = Mo5SiB2 ; 5Mo + Si + 2B also balanced, but higher E.
    rows = [row('Mo', -6), row('Si', -4), row('B', -5),
            row('Mo3Si', -9), row('MoB', -8)]
    sol = solve_minimum(parse_formula('Mo5SiB2'), rows)
    assert sol.energy_per_atom == pytest.approx(-8.5)
    assert len(sol.products) == 2


def test_excluding_same_composition():
    rows = [row('Mo3Si', -9), row('MoB', -8), row('Mo5SiB2', -100)]
    assert solve_minimum(parse_formula('Mo5SiB2'), rows).energy_per_atom == pytest.approx(-8.5)
    assert solve_minimum(parse_formula('Mo5SiB2'), rows, exclude_same_composition=False).energy_per_atom == pytest.approx(-100)


def test_two_scopes_mp_starred_and_all():
    rows = [row('Mo', -6, 'experimental-linked'), row('Si', -4, 'experimental-linked'),
            row('B', -5, 'experimental-linked'), row('Mo3Si', -9, 'theoretical'),
            row('MoB', -8, 'theoretical')]
    results = analyze_scenarios('Mo5SiB2', -8.75, rows, [('core_raw','GGA')],
                                ['experimental-linked','all'], cell_atoms=32)
    assert all(s.status == 'ok' for s in results)
    starred, full = results
    assert starred.phase_count == 3
    assert full.phase_count == 5
    assert full.mixture.energy_per_atom == pytest.approx(-8.5)
    assert starred.mixture.energy_per_atom == pytest.approx((-6*5 - 4 - 5*2)/8)
    assert full.delta_meV_per_atom == pytest.approx(-250)
    assert full.delta_eV_per_cell == pytest.approx(-8)
    assert starred.mixture.energy_per_atom >= full.mixture.energy_per_atom


def test_no_theory_only_or_non_theory_mode():
    with pytest.raises(ValueError):
        analyze_scenarios('Mo5SiB2', -8.75, [], [('core_raw', 'GGA')], ['theoretical-only'])


def test_unknown_and_user_supplied_never_claim_mp_star():
    from phase_core import filter_by_evidence
    mp_star = row('Mo', -10, 'experimental-linked', mid='mp-1')
    unknown = row('Si', -6, 'unknown', mid='mp-2')
    prediction = row('B', -7, 'theoretical', mid='mp-3')
    user_claim = row('MoB', -8, 'experimental-linked', source='user_custom', mid='my-1')
    rows = [mp_star, unknown, prediction, user_claim]
    assert [r.mp_id for r in filter_by_evidence(rows, 'experimental-linked')] == ['mp-1']
    assert [r.mp_id for r in filter_by_evidence(rows, 'all')] == ['mp-1', 'mp-2', 'mp-3']


def test_same_formula_different_mp_ids_different_star():
    from phase_core import filter_by_evidence
    a = row('MoSi', -9, 'experimental-linked', mid='mp-10')
    b = row('MoSi', -9.5, 'theoretical', mid='mp-11')
    assert [r.mp_id for r in filter_by_evidence([a,b], 'experimental-linked')] == ['mp-10']
    assert [r.mp_id for r in filter_by_evidence([a,b], 'all')] == ['mp-10', 'mp-11']

def test_methods_not_mixed():
    rows = [row('Mo3Si', -9, method='GGA'), row('MoB', -8, method='GGA'),
            row('Mo3Si', -90, method='r2SCAN'), row('MoB', -80, method='r2SCAN')]
    res = analyze_scenarios('Mo5SiB2', -10, rows,
                            [('core_raw','GGA'), ('core_raw','r2SCAN')], ['all'])
    assert res[0].mixture.energy_per_atom == pytest.approx(-8.5)
    assert res[1].mixture.energy_per_atom == pytest.approx(-85)


def test_infeasible_phase_balancing():
    with pytest.raises(CompetingPhaseError):
        solve_minimum(parse_formula('Mo5SiB2'), [row('MoB', -3)])


def test_cell_integrality():
    check_cell_stoichiometry('Mo5SiB2', 32)
    with pytest.raises(ValueError):
        check_cell_stoichiometry('Mo5SiB2', 30)


def test_json_roundtrip():
    rec = [row('MoB', -8.2)]
    s = rows_to_json(rec, {'source': 'test'})
    rows, meta = rows_from_json(s)
    assert rows[0].energy_per_atom == -8.2
    assert meta == {'source': 'test'}


def test_subsystem_enumeration():
    assert set(enumerate_subsystems(['Mo','Si','B'])) == {
        'Mo', 'Si', 'B', 'Mo-Si', 'B-Mo', 'B-Si', 'B-Mo-Si',
    }


def test_entry_conversion_raw_and_provenance():
    s = {'formula': 'MoB', 'composition': {'Mo': 1, 'B': 1},
         'evidence': 'theoretical', 'experimental_flag': False, 'spacegroup':'P6/mmm'}
    d = {'energy': -32.0, 'correction': 0,
         'composition': {'Mo': 1,'B': 1},
         'parameters': {'run_type': 'GGA', 'potcar_spec': [{'symbol': 'Mo_pv', 'hash': 'hash1'}, {'symbol': 'B'}],
                        'hubbards': {'Mo': 3}}, 'data': {'task_id': 'mp-100'}}
    result = _entry_to_record('mp-88', 'GGA', d, s)
    assert result.energy_per_atom == pytest.approx(-16)
    assert result.dft_total_energy_eV == pytest.approx(-32)
    assert result.dft_cell_atoms == pytest.approx(2)
    assert 'Mo_pv' in result.potcar
    assert result.hubbards == 'Mo:3'


def test_security_no_key_in_json():
    assert 'secret-api-key' not in rows_to_json([row('MoB', -8)], {'source': 'mp'})


def test_potcar_conflicts_prevent_mixed_pseudo():
    from phase_core import potcar_conflicts
    a = row('Mo3Si', -9); a.potcar = 'Mo_pv [hash1]; Si [hashSi]'
    b = row('MoB', -8); b.potcar = 'Mo [hash2]; B [hashB]'
    assert list(potcar_conflicts([a,b])) == ['Mo']
    strict = analyze_scenarios('Mo5SiB2', -8.75, [a,b], [('core_raw','GGA')], ['all'])
    assert strict[0].status == 'not solvable'
    relaxed = analyze_scenarios('Mo5SiB2', -8.75, [a,b], [('core_raw','GGA')], ['all'],
                                require_potcar_consistency=False)
    assert relaxed[0].status == 'ok'


def test_v4_simple_verdict_and_reaction_text():
    from result_display import verdict, reaction_text, product_breakdown
    assert verdict(-1e-8)[0] == 'stable'
    assert verdict(1e-8)[0] == 'unstable'
    assert verdict(0.0)[0] == 'boundary'
    mix = solve_minimum(parse_formula('Mo5SiB2'), [row('Mo3Si', -9), row('MoB', -8)])
    assert reaction_text('Mo5SiB2', mix) == 'Mo5SiB2 → 1 Mo3Si + 2 MoB'
    details = product_breakdown('Mo5SiB2', mix)
    assert sum(d['energy_contribution_eV_atom'] for d in details) == pytest.approx(mix.energy_per_atom)
    assert [d['coefficient_label'] for d in details] == ['1', '2']


def test_v4_sign_rule_applies_to_both_mp_scenarios():
    from result_display import verdict
    rows = [row('Mo', -6, 'experimental-linked'), row('Si', -4, 'experimental-linked'),
            row('B', -5, 'experimental-linked'), row('Mo3Si', -9, 'theoretical'), row('MoB', -8, 'theoretical')]
    results = analyze_scenarios('Mo5SiB2', -8.0, rows, [('core_raw','GGA')],
                                ['experimental-linked','all'])
    assert verdict(results[0].delta_eV_per_atom)[0] == 'stable'
    assert verdict(results[1].delta_eV_per_atom)[0] == 'unstable'
