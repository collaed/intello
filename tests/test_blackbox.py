"""Black-box HTTP API tests — test the running service via HTTP."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient
from intello.web import app

client = TestClient(app)
# Simulate authenticated request (Docker internal IP)
HEADERS = {"X-Auth-User": "ecb"}


def test_root_page():
    r = client.get("/", headers=HEADERS)
    assert r.status_code == 200
    assert "L'Intello" in r.text or "Intello" in r.text
    print("✅ GET / → 200")


def test_literary_page():
    r = client.get("/literary", headers=HEADERS)
    assert r.status_code == 200
    assert "Literary" in r.text
    print("✅ GET /literary → 200")


def test_corkboard_page():
    r = client.get("/corkboard", headers=HEADERS)
    assert r.status_code == 200
    assert "Corkboard" in r.text
    print("✅ GET /corkboard → 200")


def test_status_endpoint():
    r = client.get("/api/v1/status", headers=HEADERS)
    assert r.status_code == 200
    d = r.json()
    assert "available" in d
    assert "ocr" in d
    assert d["total_available"] >= 0
    print(f"✅ GET /api/v1/status → {d['total_available']} providers")


def test_models_endpoint():
    r = client.get("/v1/models", headers=HEADERS)
    assert r.status_code == 200
    d = r.json()
    assert d["object"] == "list"
    assert "data" in d
    print(f"✅ GET /v1/models → {len(d['data'])} models")


def test_providers_endpoint():
    r = client.get("/api/providers", headers=HEADERS)
    assert r.status_code == 200, f"Status {r.status_code}"
    data = r.json()
    assert isinstance(data, list), f"Expected list, got {type(data)}"
    print(f"✅ GET /api/providers → {len(data)} providers")


def test_literary_ingest():
    r = client.post("/api/literary/ingest", headers=HEADERS,
                    data={"title": "BB Test", "text": "Chapter 1\n\nThe rain fell hard. Elena ran. Marco followed. " * 5})
    assert r.status_code == 200
    d = r.json()
    assert "doc_id" in d
    assert d["chapters"] >= 1
    print(f"✅ POST /api/literary/ingest → {d['doc_id']}")
    return d["doc_id"]


def test_literary_document():
    doc_id = test_literary_ingest()
    r = client.get(f"/api/literary/{doc_id}", headers=HEADERS)
    assert r.status_code == 200
    d = r.json()
    assert "info" in d
    assert "structure" in d
    assert "pacing" in d
    assert "characters" in d
    assert "threads" in d
    print(f"✅ GET /api/literary/{doc_id} → structure+pacing+chars+threads")


def test_literary_documents_list():
    r = client.get("/api/literary/documents", headers=HEADERS)
    assert r.status_code == 200
    d = r.json()
    assert isinstance(d, list)
    print(f"✅ GET /api/literary/documents → {len(d)} docs")


def test_literary_projects_crud():
    # Create
    r = client.post("/api/literary/projects", headers=HEADERS,
                    data={"title": "BB Project", "genre": "fiction", "brief": "A test"})
    assert r.status_code == 200
    pid = r.json()["project_id"]
    # List
    r = client.get("/api/literary/projects", headers=HEADERS)
    assert r.status_code == 200
    assert any(p["project_id"] == pid for p in r.json())
    # Get
    r = client.get(f"/api/literary/projects/{pid}", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["title"] == "BB Project"
    print(f"✅ Projects CRUD → {pid}")


def test_scheduler_crud():
    r = client.post("/api/scheduler/tasks", headers=HEADERS,
                    data={"name": "BB Task", "prompt": "hello", "schedule": "daily"})
    assert r.status_code == 200
    tid = r.json()["task_id"]
    r = client.get("/api/scheduler/tasks", headers=HEADERS)
    assert r.status_code == 200
    assert any(t["task_id"] == tid for t in r.json())
    r = client.delete(f"/api/scheduler/tasks/{tid}", headers=HEADERS)
    assert r.status_code == 200
    print(f"✅ Scheduler CRUD → {tid}")


def test_webhooks_crud():
    r = client.post("/api/webhooks", headers=HEADERS,
                    data={"name": "BB Hook", "action": "chat", "config": "{}"})
    assert r.status_code == 200
    hid = r.json()["hook_id"]
    r = client.get("/api/webhooks", headers=HEADERS)
    assert r.status_code == 200
    r = client.delete(f"/api/webhooks/{hid}", headers=HEADERS)
    assert r.status_code == 200
    print(f"✅ Webhooks CRUD → {hid}")


def test_writing_tools():
    r = client.post("/api/tools/transform", headers=HEADERS,
                    data={"text": "She was angry.", "tool": "show_not_tell"})
    # May fail if no providers available, but should not 500
    assert r.status_code == 200
    d = r.json()
    assert "result" in d or "error" in d
    print(f"✅ POST /api/tools/transform → {d.get('tool', 'ok')}")


def test_cache_stats():
    r = client.get("/api/cache/stats", headers=HEADERS)
    assert r.status_code == 200
    d = r.json()
    assert "entries" in d
    print(f"✅ GET /api/cache/stats → {d['entries']} entries")


def test_conversations():
    r = client.get("/api/conversations", headers=HEADERS)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    print(f"✅ GET /api/conversations → {len(r.json())} convs")


def test_prefs():
    r = client.get("/api/prefs", headers=HEADERS)
    assert r.status_code == 200
    d = r.json()
    assert "tone" in d
    print(f"✅ GET /api/prefs → tone={d['tone']}")


def test_learning():
    r = client.get("/api/learning", headers=HEADERS)
    assert r.status_code == 200
    print(f"✅ GET /api/learning → ok")


def test_auth_rejected_without_credentials():
    """Verify unauthenticated requests are rejected."""
    r = client.get("/api/providers")  # No headers
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"
    print("✅ Auth: unauthenticated → 401")


def test_chat_completions():
    r = client.post("/v1/chat/completions", headers=HEADERS,
                    json={"messages": [{"role": "user", "content": "hi"}], "max_tokens": 10})
    # May 503 if no providers, but should not 500
    assert r.status_code in (200, 429, 503), f"Unexpected status: {r.status_code}"
    print(f"✅ POST /v1/chat/completions → {r.status_code}")


if __name__ == "__main__":
    tests = [
        test_root_page, test_literary_page, test_corkboard_page,
        test_status_endpoint, test_models_endpoint, test_providers_endpoint,
        test_literary_documents_list, test_literary_projects_crud,
        test_scheduler_crud, test_webhooks_crud,
        test_writing_tools, test_cache_stats, test_conversations,
        test_prefs, test_learning,
        test_auth_rejected_without_credentials, test_chat_completions,
        test_literary_document,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    print(f"\nBlack-box: {passed} passed, {failed} failed out of {len(tests)}")
    if failed: sys.exit(1)
