"""End-to-end smoke test for auth + projects + persistence."""
import urllib.request
import json
import sys
import time

BASE = "http://127.0.0.1:8055"


def api(method, path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read()), e.code


def main():
    # Wait for server
    for i in range(10):
        try:
            urllib.request.urlopen(f"{BASE}/login")
            break
        except Exception:
            time.sleep(1)
    else:
        print("FAIL: Server not reachable")
        sys.exit(1)

    # 1. Register
    r, s = api("POST", "/api/auth/register", {"username": "analyst1", "password": "pass1234"})
    assert s == 200, f"Register failed: {r}"
    print(f"1. Register OK: {r}")

    # 2. Login
    r, s = api("POST", "/api/auth/login", {"username": "analyst1", "password": "pass1234"})
    assert s == 200 and "token" in r, f"Login failed: {r}"
    token = r["token"]
    print(f"2. Login OK, token length={len(token)}")

    # 3. Create project
    r, s = api("POST", "/api/projects", {"name": "Op Meridian", "description": "Test"}, token)
    assert s == 200 and "id" in r, f"Create project failed: {r}"
    pid = r["id"]
    print(f"3. Project created: id={pid}")

    # 4. List projects
    r, s = api("GET", "/api/projects", token=token)
    assert len(r["projects"]) == 1
    print(f"4. List projects: {len(r['projects'])} found")

    # 5. Load demo
    r, s = api("POST", "/api/demo", {"project_id": pid}, token)
    assert r.get("success"), f"Demo failed: {r}"
    print(f"5. Demo loaded: {r['entity_count']} entities, {r['relationship_count']} rels")

    # 6. Reload project - graph should persist
    r, s = api("GET", f"/api/projects/{pid}?project_id={pid}", token=token)
    assert r["entity_count"] > 0, "Graph not persisted!"
    print(f"6. Persisted: {r['entity_count']} entities, {r['relationship_count']} rels")

    # 7. Second user sees same project
    api("POST", "/api/auth/register", {"username": "analyst2", "password": "pass5678"})
    r2, _ = api("POST", "/api/auth/login", {"username": "analyst2", "password": "pass5678"})
    token2 = r2["token"]
    r, s = api("GET", f"/api/projects/{pid}?project_id={pid}", token=token2)
    assert r["entity_count"] > 0
    print(f"7. User2 sees same project: {r['entity_count']} entities")

    # 8. Create node
    r, s = api("POST", "/api/node/create", {"project_id": pid, "name": "Test Entity", "type": "Person"}, token)
    assert r.get("success")
    new_count = r["entity_count"]
    print(f"8. Node created, entities now: {new_count}")

    # 9. Undo
    r, s = api("POST", "/api/undo", {"project_id": pid}, token)
    assert r.get("success") and r["entity_count"] == new_count - 1
    print(f"9. Undo OK, entities back to: {r['entity_count']}")

    # 10. Unauthorized access
    _, s = api("GET", "/api/projects")
    assert s == 401 or s == 403
    print(f"10. No-auth blocked: status={s}")

    print("\n=== ALL E2E TESTS PASSED ===")


if __name__ == "__main__":
    main()
