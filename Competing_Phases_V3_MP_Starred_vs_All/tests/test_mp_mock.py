import sys
import types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mp_backend import fetch_all_mp


class FakeSummary:
    def search(self, **kwargs):
        assert kwargs['include_gnome'] is True
        return [
            {'material_id': 'mp-1', 'formula_pretty': 'Mo', 'composition': {'Mo': 1},
             'theoretical': False, 'symmetry': {'symbol': 'Im-3m'}},
            {'material_id': 'mp-2', 'formula_pretty': 'Si', 'composition': {'Si': 1},
             'theoretical': False, 'symmetry': {'symbol': 'Fd-3m'}},
            {'material_id': 'mp-3', 'formula_pretty': 'MoSi', 'composition': {'Mo': 1,'Si':1},
             'theoretical': True, 'symmetry': {'symbol': 'P4/mmm'}},
        ]


class FakeThermo:
    def search(self, **kwargs):
        return [
            {'material_id':'mp-1', 'thermo_type':'GGA_GGA+U', 'energy_per_atom': -11.1,
             'uncorrected_energy_per_atom': -11.0, 'energy_type':'GGA'},
            {'material_id':'mp-2', 'thermo_type':'GGA_GGA+U', 'energy_per_atom': -6.1,
             'uncorrected_energy_per_atom': -6.0, 'energy_type':'GGA'},
            {'material_id':'mp-3', 'thermo_type':'GGA_GGA+U', 'energy_per_atom': -10.2,
             'uncorrected_energy_per_atom': -10.0, 'energy_type':'GGA'},
        ]


class FakeMaterials:
    def __init__(self):
        self.summary = FakeSummary()
        self.thermo = FakeThermo()

    def search(self, **kwargs):
        energies = {'mp-1': ('Mo', -11.0), 'mp-2': ('Si', -6.0), 'mp-3': ('MoSi', -20.0)}
        rows = []
        for mid in kwargs['material_ids']:
            f, energy = energies[mid]
            comp = {'Mo':1,'Si':1} if f=='MoSi' else {f:1}
            rows.append({'material_id':mid, 'entries':{'GGA':{
                'energy':energy, 'correction':0, 'composition':comp,
                'parameters':{'run_type':'GGA', 'hubbards':{},
                    'potcar_spec':[{'symbol': 'Mo_pv'}]},
                'data':{'task_id':mid+'-task'}}}})
        return rows


class FakeMPRester:
    def __init__(self, **kwargs):
        assert kwargs.get('use_document_model') is False
        self.materials = FakeMaterials()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


def test_online_adapter_using_mock_client(monkeypatch):
    pkg = types.ModuleType('mp_api')
    client = types.ModuleType('mp_api.client')
    client.MPRester = FakeMPRester
    monkeypatch.setitem(sys.modules, 'mp_api', pkg)
    monkeypatch.setitem(sys.modules, 'mp_api.client', client)
    rows, meta = fetch_all_mp('fake-key', ['Mo','Si'])
    assert meta['n_materials'] == 3
    assert meta['n_mp_starred'] == 2
    assert meta['n_mp_nonstarred'] == 1
    assert meta['n_mp_flag_unknown'] == 0
    assert len(rows) == 6
    assert sum(r.energy_source == 'core_raw' for r in rows) == 3
    assert sum(r.energy_source == 'thermo_corrected' for r in rows) == 3
    assert {r.evidence for r in rows} == {'experimental-linked', 'theoretical'}
    r = next(r for r in rows if r.mp_id == 'mp-3' and r.energy_source == 'core_raw')
    assert r.energy_per_atom == -10.0
    assert r.task_id == 'mp-3-task'
    assert r.potcar == 'Mo_pv'
    assert 'fake-key' not in str(meta)
