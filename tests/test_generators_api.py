"""Integration test for FastAPI Generators and Email Worker API endpoints."""

import os
from fastapi.testclient import TestClient
from liftassistant.api.app import create_app
from liftassistant.db.connection import init_db

# Configure environment to test
os.environ["ENVIRONMENT"] = "test"

def test_api_endpoints():
    init_db()
    app = create_app()
    # Disable device auth middleware for test client by header or env
    client = TestClient(app, headers={"X-Device-Token": "test"})

    # 1. Test worker status
    res = client.get("/api/v1/generators/email/worker")
    assert res.status_code == 200, res.text
    status_data = res.json()
    assert "interval_seconds" in status_data
    print("PASS: /api/v1/generators/email/worker returned status:", status_data)

    # 2. Test runs list
    res = client.get("/api/v1/generators/email/runs")
    assert res.status_code == 200, res.text
    runs = res.json()
    assert isinstance(runs, list)
    print(f"PASS: /api/v1/generators/email/runs returned {len(runs)} past runs.")

    # 3. Test generated events feedback list
    res = client.get("/api/v1/generators/email/events")
    assert res.status_code == 200, res.text
    events = res.json()
    assert isinstance(events, list)
    print(f"PASS: /api/v1/generators/email/events returned {len(events)} events.")

    # 4. Test prompt rules list
    res = client.get("/api/v1/generators/email/rules")
    assert res.status_code == 200, res.text
    rules = res.json()
    assert isinstance(rules, list)
    print(f"PASS: /api/v1/generators/email/rules returned {len(rules)} prompt rules.")

    # 5. Test create custom prompt rule
    res = client.post(
        "/api/v1/generators/email/rules",
        json={
            "user_feedback": "Ignore promotional streaming offers",
            "prompt_instruction": "USER CORRECTION: Promotional subscription offers are SKIP.",
            "rule_type": "NEGATIVE",
        },
    )
    assert res.status_code == 201, res.text
    rule_data = res.json()
    rule_id = rule_data["id"]
    print("PASS: /api/v1/generators/email/rules created rule:", rule_id)

    # 6. Test effective prompt endpoint
    res = client.get("/api/v1/generators/email/prompt")
    assert res.status_code == 200, res.text
    prompt_data = res.json()
    assert "effective_prompt" in prompt_data
    assert "Ignore promotional streaming offers" in prompt_data["effective_prompt"] or "Promotional subscription offers are SKIP" in prompt_data["effective_prompt"]
    print("PASS: /api/v1/generators/email/prompt correctly shows dynamically injected rule!")

    # 7. Test delete rule
    res = client.delete(f"/api/v1/generators/email/rules/{rule_id}")
    assert res.status_code == 200, res.text
    print("PASS: /api/v1/generators/email/rules DELETE successfully cleaned up rule.")

    # 8. Test Depletion Worker Run
    res = client.post("/api/v1/generators/depletion/run")
    assert res.status_code == 200, res.text
    dep_data = res.json()
    assert "summary_message" in dep_data
    assert dep_data["run"]["generator_type"] == "DEPLETION_WORKER"
    print("PASS: /api/v1/generators/depletion/run returned summary:", dep_data["summary_message"])

    # 9. Test Facility Worker Run
    res = client.post("/api/v1/generators/facility/run")
    assert res.status_code == 200, res.text
    fac_data = res.json()
    assert "summary_message" in fac_data
    assert fac_data["run"]["generator_type"] == "FACILITY_WORKER"
    print("PASS: /api/v1/generators/facility/run returned summary:", fac_data["summary_message"])

    # 10. Test Run Details endpoint
    run_id = dep_data["run"]["id"]
    res = client.get(f"/api/v1/generators/runs/{run_id}")
    assert res.status_code == 200, res.text
    run_result = res.json()
    assert run_result["run"]["id"] == run_id
    assert "summary_message" in run_result
    assert isinstance(run_result["events"], list)
    print("PASS: /api/v1/generators/runs/{run_id} correctly returned run summary & events list!")

    print("\n==============================================")
    print("ALL REST API ROUTE INTEGRATION TESTS PASSED!")
    print("==============================================\n")


if __name__ == "__main__":
    test_api_endpoints()
