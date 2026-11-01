"""Contract smoke test for our MP adapter without credentials or network.

These are mock API objects, not verification against the live MP service.
"""
import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from mp_backend import fetch_mp_phases


class FakeComp:
    def __init__(self, comp, name):
        self.comp, self.reduced_formula = comp, name

    def get_reduced_composition_and_factor(self):
        return self, 1

    def get_el_amt_dict(self):
        return self.comp


class FakeEntry:
    def __init__(self, comp, name, formation_energy, material_id):
        self.composition = FakeComp(comp, name)
        self.form = formation_energy
        self.energy_per_atom = -2.0 + formation_energy
        self.entry_id = material_id
        self.data = {"material_id": material_id}


class FakePhaseDiagram:
    def __init__(self, entries):
        self.entries = entries

    def get_form_energy_per_atom(self, entry):
        return entry.form


class FakeMPRester:
    last_call = None
    def __init__(self, api_key):
        assert api_key == "dummy-for-test-only"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get_entries_in_chemsys(self, elements, **kwargs):
        FakeMPRester.last_call = (elements, kwargs)
        return [FakeEntry({"Li": 1}, "Li", 0., "mp-1"),
                FakeEntry({"F": 1}, "F", 0., "mp-2"),
                FakeEntry({"Li": 1, "F": 1}, "LiF", -0.7, "mp-3")]


class TestMPBackend(unittest.TestCase):
    def test_adapter_selected_thermo_compatible_only(self):
        api_pkg = types.ModuleType("mp_api")
        api_client = types.ModuleType("mp_api.client")
        api_client.MPRester = FakeMPRester
        pymatgen_pkg = types.ModuleType("pymatgen")
        pymatgen_analysis = types.ModuleType("pymatgen.analysis")
        pymatgen_pd = types.ModuleType("pymatgen.analysis.phase_diagram")
        pymatgen_pd.PhaseDiagram = FakePhaseDiagram
        mock_mods = {
            "mp_api": api_pkg, "mp_api.client": api_client,
            "pymatgen": pymatgen_pkg,
            "pymatgen.analysis": pymatgen_analysis,
            "pymatgen.analysis.phase_diagram": pymatgen_pd,
        }
        with patch.dict(sys.modules, mock_mods):
            phases, meta = fetch_mp_phases("dummy-for-test-only", ["Li", "F"], "GGA_GGA+U")
        elems, opts = FakeMPRester.last_call
        self.assertEqual(elems, ["F", "Li"])
        self.assertEqual(opts["additional_criteria"], {"thermo_types": ["GGA_GGA+U"]})
        self.assertTrue(opts["compatible_only"])
        self.assertEqual(len(phases), 3)
        self.assertEqual(phases[-1].formation_energy_per_atom, -0.7)
        self.assertEqual(meta["elements"], ["F", "Li"])

if __name__ == "__main__":
    unittest.main()
