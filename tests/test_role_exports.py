"""Six-role delivery contract, independent from richer analytical roles."""
import io
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1] / 'money_graph'
sys.path.insert(0, str(ROOT))
from mg.export import contract_roles, role_csv_bytes


def test_export_preserves_detail_without_mutating_internal_roles():
    original = pd.DataFrame({'gid': ['001', '999999999999999999'],
                             'role': ['truncated', 'terminal'],
                             'priority_score': [0.1234, 0.9]})
    result = contract_roles(original)
    assert result.role.tolist() == ['peripheral', 'terminal']
    assert result.role_detail.tolist() == ['truncated', 'terminal']
    assert result.is_truncated.tolist() == [True, False]
    assert result.role_base.equals(result.role)
    assert original.role.tolist() == ['truncated', 'terminal']
    assert result.priority_score.equals(original.priority_score)
    pd.testing.assert_frame_equal(contract_roles(result), result)


@pytest.mark.parametrize('role', ['unexpected', None])
def test_unknown_roles_fail_closed(role):
    with pytest.raises(ValueError):
        contract_roles(pd.DataFrame({'role': [role]}))


def test_cached_download_preserves_identifiers_and_exact_number_strings(tmp_path):
    frame = pd.DataFrame({'gid': ['001', '999999999999999999'],
                          'role': ['truncated', 'transit'],
                          'in_kzt': ['1.1234567890123456789', ''],
                          'block_impact': ['-0.04065772088227928', '0.25'],
                          'evidence': ["'=1+1", '2 senders']})
    path = tmp_path / 'nodes_roles.csv'
    frame.to_csv(path, index=False)
    result = pd.read_csv(io.BytesIO(role_csv_bytes(path)), dtype=str, keep_default_na=False)
    assert result.gid.tolist() == frame.gid.tolist()
    assert result.in_kzt.tolist() == frame.in_kzt.tolist()
    assert result.block_impact.tolist() == frame.block_impact.tolist()
    assert result.role.tolist() == ['peripheral', 'transit']
    assert result.evidence.iloc[0] == "'=1+1"


def test_all_http_csv_paths_normalize_legacy_roles(tmp_path, monkeypatch):
    from api import main
    internal = pd.DataFrame({'gid': ['001'], 'role': ['truncated'],
                             'priority_score': [0.25]}).set_index('gid')
    for name in ['nodes_roles.csv', 'top_nodes.csv']:
        internal.reset_index().to_csv(tmp_path / name, index=False)
    for name in ['clusters.csv', 'requests.csv', 'resilience.csv']:
        (tmp_path / name).write_text('value\n1\n', encoding='utf-8')
    (tmp_path / 'summary.json').write_text('{}', encoding='utf-8')
    monkeypatch.setattr(main.s, 'folder', lambda pid: tmp_path)
    monkeypatch.setattr(main.s, 'result_dir', lambda path: tmp_path)
    monkeypatch.setattr(main, 'context', lambda pid: (internal,))
    with TestClient(main.app) as client:
        prefix = '/api/projects/' + 'a' * 32 + '/export/'
        downloads = [client.get(prefix + name) for name in ['nodes_roles.csv', 'top_nodes.csv']]
        downloads.append(client.post(prefix + 'selection.csv', json={'ids': ['001']}))
        for response in downloads:
            assert response.status_code == 200
            frame = pd.read_csv(io.BytesIO(response.content), dtype={'gid': str})
            assert frame.gid.tolist() == ['001']
            assert frame.role.tolist() == ['peripheral']
            assert frame.role_detail.tolist() == ['truncated']
            assert frame.is_truncated.tolist() == [True]
        response = client.get(prefix + 'all.zip')
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for name in ['nodes_roles.csv', 'top_nodes.csv']:
                frame = pd.read_csv(io.BytesIO(archive.read(name)), dtype={'gid': str})
                assert frame.role.tolist() == ['peripheral']
                assert frame.gid.tolist() == ['001']
    assert internal.role.tolist() == ['truncated']
