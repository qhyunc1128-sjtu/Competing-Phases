import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from phase_core import (Phase, analyze, atom_fractions, formation_energy_from_total,
                        parse_formula, same_stoichiometry, solve_mixture, HullError)


class TestCore(unittest.TestCase):
    def setUp(self):
        # Synthetic A-B system with elemental energy = 0 and stable AB = -1 eV/atom.
        self.phases = [
            Phase("Li", {"Li": 1}, 0., "mp-Li"),
            Phase("F", {"F": 1}, 0., "mp-F"),
            Phase("LiF", {"Li": 1, "F": 1}, -1., "mp-LiF"),
            Phase("Li2F", {"Li": 2, "F": 1}, -0.4, "mp-Li2F"),
        ]

    def test_parser_and_group(self):
        a = parse_formula("(Mo0.8Ti0.2)5SiB2")
        self.assertAlmostEqual(a["Mo"], 4)
        self.assertAlmostEqual(a["Ti"], 1)
        self.assertEqual(a["B"], 2)
        self.assertTrue(same_stoichiometry(a, parse_formula("Mo4TiSiB2")))
        for broken in ["CiSi2", "Mo-5SiB2", "(Mo2Si", "Mo0Si2", "Mo2.3.2Si"]:
            with self.assertRaises(ValueError):
                parse_formula(broken)

    def test_full_and_excluding_target_stoichiometry(self):
        r = analyze("LiF", -0.8, self.phases)
        self.assertAlmostEqual(r.global_hull.formation_energy_per_atom, -1.0)
        self.assertAlmostEqual(r.delta_global_eV_per_atom, 0.2)
        self.assertAlmostEqual(r.alternative_hull.formation_energy_per_atom, -0.3)
        self.assertAlmostEqual(r.delta_alternative_eV_per_atom, -0.5)
        # Li2F and pure F: 0.75 of atoms from Li2F, 0.25 from F
        pd = {p.formula: p for p in r.alternative_hull.products}
        self.assertAlmostEqual(pd["Li2F"].formula_coefficient, 0.5)
        self.assertAlmostEqual(pd["F"].formula_coefficient, 0.5)
        self.assertAlmostEqual(sum(p.atomic_fraction for p in r.alternative_hull.products), 1.0)

    def test_fractional_composition(self):
        r = analyze("Li0.5F0.5", -0.5, self.phases)
        self.assertAlmostEqual(r.global_hull.formation_energy_per_atom, -1)
        self.assertAlmostEqual(r.global_hull.products[0].formula_coefficient, 0.5)

    def test_dft_total_referenced_to_own_elements(self):
        # 4 atoms of Li2F2; user elemental energies: Li=-2, F=-1
        # E_ref = -6 eV, cell is -9.2 => Hf/atom = -0.8
        hf = formation_energy_from_total("LiF", -9.2, 4, {"Li": -2., "F": -1.})
        self.assertAlmostEqual(hf, -0.8)
        with self.assertRaises(ValueError):
            formation_energy_from_total("LiF", -9.2, 3, {"Li": -2., "F": -1.})
        with self.assertRaises(ValueError):
            formation_energy_from_total("LiF", -9.2, 4, {"Li": -2.})
        with self.assertRaises(ValueError):
            formation_energy_from_total("Mo4.4Ti0.6SiB2", -100.0, 32,
                                        {"Mo": -10., "Ti": -8., "Si": -5., "B": -6.})

    def test_only_elements(self):
        phases = [self.phases[0], self.phases[1]]
        r = analyze("LiF", -0.12, phases)
        self.assertAlmostEqual(r.global_hull.formation_energy_per_atom, 0)
        self.assertEqual(r.same_composition_count, 0)
        self.assertAlmostEqual(r.alternative_hull.formation_energy_per_atom, 0)

    def test_no_cover(self):
        with self.assertRaises(HullError):
            solve_mixture({"Li": 1, "F": 1}, self.phases[:1])


if __name__ == "__main__":
    unittest.main()
