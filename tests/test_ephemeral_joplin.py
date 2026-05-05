import os
import requests


def test_joplin_is_running(ephemeral_joplin):
    resp = requests.get("http://localhost:22300/api/ping", headers={"Host": "joplin:22300"}, timeout=30)
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"


def test_admin_login(ephemeral_joplin):
    resp = requests.post("http://localhost:22300/api/sessions", headers={"Host": "joplin:22300"}, json={
        "email": "admin@localhost",
        "password": os.environ["JOPLIN_ADMIN_PASSWORD"]
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
