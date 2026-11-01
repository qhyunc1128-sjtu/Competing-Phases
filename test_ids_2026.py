"""Regression tests for MP's 2026-04-13 numeric/AlphaID migration."""
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mp_identifiers import material_id_legacy, task_id_legacy, material_url
from mp_backend import fetch_all_mp, fetch_task_audit, verify_material_id
from phase_core import rows_from_json


def test_official_silicon_id_all_spelling():
    for x in ('mp-149', 'mp-ft', 'mp-aaaaaaft'):
        assert material_id_legacy(x) == 'mp-149'
    assert material_url('mp-aaaaaaft').endswith('/materials/mp-149')


def test_task_ids_without_mp_prefix():
    assert task_id_legacy('ft') == 'mp-149'
    assert task_id_legacy('aaaaaaft') == 'mp-149'
    assert task_id_legacy('mp-ft') == 'mp-149'
    assert task_id_legacy('mp-149') == 'mp-149'
    assert task_id_legacy('mvc-16068') == 'mvc-16068'
    assert material_id_legacy('custom-001') == 'custom-001'


class Summary:
    def search(self, **kwargs):
        if 'material_ids' in kwargs:
            return [{'material_id':'mp-aaaaaaft','formula_pretty':'Si', 'theoretical':False,
                     'symmetry':{'symbol':'Fd-3m'}}]
        return [{'material_id':'mp-aaaaaaft','formula_pretty':'Si',
                 'composition':{'Si':1}, 'theoretical':False,
                 'symmetry':{'symbol':'Fd-3m'}}]


class Thermo:
    def search(self, **kwargs):
        return [{'material_id':'mp-149', 'thermo_type':'GGA_GGA+U',
                 'energy_per_atom':-5.5, 'uncorrected_energy_per_atom':-5.4,
                 'energy_type':'GGA'}]


class Tasks:
    def search(self, **kwargs):
        # Mimic the real MP API: disallow the nonexistent `state` field.
        supported = {'nsites', 'elements', 'nelements', 'composition',
                     'composition_reduced', 'formula_pretty', 'formula_anonymous',
                     'chemsys', 'volume', 'density', 'density_atomic', 'symmetry',
                     'batch_id', 'calc_type', 'completed_at', 'dir_name',
                     'icsd_id', 'input', 'last_updated', 'orig_inputs', 'output',
                     'run_type', 'structure', 'tags', 'task_id', 'task_type',
                     'transformations', 'vasp_objects', 'vasp_version'}
        unexpected = set(kwargs['fields']) - supported
        if unexpected:
            raise ValueError(f"invalid fields requested: {sorted(unexpected)}")
        assert 'mp-149' in kwargs['task_ids']
        return [{'task_id':'aaaaaaft', 'run_type':'GGA', 'task_type':'Static',
                 'calc_type':'GGA Static', 'completed_at':'2026-10-01T00:00:00',
                 'input':{}, 'output':{'energy_per_atom':-5.4}}]


class Mat:
    summary=Summary()
    thermo=Thermo()
    tasks=Tasks()

    def search(self, **kwargs):
        if kwargs.get('fields') == ['material_id','task_ids']:
            return [{'material_id':'mp-aaaaaaft', 'task_ids':['aaaaaaft']}]
        return [{'material_id':'mp-149','entries':{'GGA':{
            'energy':-10.8,'correction':0, 'composition':{'Si':2},
            'parameters':{'run_type':'GGA'},
            # Older V4 would drop this ID because it only read data.task_id.
            'entry_id':'aaaaaaft', 'data':{},
        }}}]


class MP:
    def __init__(self, **kwargs):
        assert kwargs.get('use_document_model') is False
        self.materials=Mat()
        self.db_version='2026.09.28'
    def __enter__(self): return self
    def __exit__(self, *args): pass


def install_fake(monkeypatch):
    pkg=types.ModuleType('mp_api')
    cli=types.ModuleType('mp_api.client')
    cli.MPRester=MP
    monkeypatch.setitem(sys.modules,'mp_api',pkg)
    monkeypatch.setitem(sys.modules,'mp_api.client',cli)


def test_summary_core_thermo_use_different_id_forms(monkeypatch):
    install_fake(monkeypatch)
    rows, meta=fetch_all_mp('TEST-NOT-A-REAL-KEY',['Si'],include_gnome=False)
    assert meta['n_materials']==1
    assert meta['mp_database_version']=='2026.09.28'
    assert len(rows)==2  # both fetched despite ID string discrepancy
    assert {r.mp_id for r in rows}=={'mp-149'}
    assert {r.mp_id_api for r in rows}=={'mp-aaaaaaft'}
    raw=next(r for r in rows if r.energy_source=='core_raw')
    assert raw.task_id=='mp-149'
    assert raw.task_id_api=='aaaaaaft'
    assert raw.energy_per_atom==-5.4


def test_task_audit_joins_new_format_to_legacy(monkeypatch):
    install_fake(monkeypatch)
    audit=fetch_task_audit('TEST-NOT-A-REAL-KEY',['mp-aaaaaaft'])
    assert audit[0]['material_id']=='mp-149'
    assert audit[0]['task_id']=='mp-149'
    assert audit[0]['task_id_api']=='aaaaaaft'
    assert audit[0]['calc_type']=='GGA Static'
    assert audit[0]['completed_at']=='2026-10-01T00:00:00'
    assert 'state' not in audit[0]


def test_verify_material_id_api(monkeypatch):
    install_fake(monkeypatch)
    result=verify_material_id('TEST-NOT-A-REAL-KEY','mp-149')
    assert result['material_id']=='mp-149'
    assert result['api_material_id']=='mp-aaaaaaft'
    assert result['formula']=='Si'


def test_migrate_saved_v4_json():
    blob=json.dumps({'records':[{
        'formula':'Si','composition':{'Si':1},'energy_per_atom':-5.4,
        'mp_id':'mp-aaaaaaft','energy_source':'core_raw','method':'GGA',
        'task_id':'aaaaaaft',
    }], 'metadata':{'source':'old'}})
    rows,meta=rows_from_json(blob)
    assert rows[0].mp_id=='mp-149'
    assert rows[0].mp_id_api=='mp-aaaaaaft'
    assert rows[0].task_id=='mp-149'
    assert rows[0].task_id_api=='aaaaaaft'
    assert meta['source']=='old'
