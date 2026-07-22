def test_index_empty_db_returns_200(client):
    resp = client.get('/')
    assert resp.status_code == 200
