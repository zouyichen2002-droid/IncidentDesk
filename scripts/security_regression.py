"""Application negative tests against a running, isolated local K8s environment."""

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx
from smoke import login, wait, BASE, SOURCE


def main():
    out = []

    def check(name, yes):
        out.append({"test": name, "pass": bool(yes)})
        assert yes, name

    headers = login("alice")
    admin = login("admin")
    with httpx.Client(base_url=BASE, headers=headers, timeout=15) as c:
        end = datetime.now(timezone.utc)
        body = {
            "service": "svc-17",
            "symptom": "Negative authorization regression",
            "start": (end - timedelta(days=1)).isoformat(),
            "end": end.isoformat(),
            "timezone": "UTC",
        }
        r = c.post(
            "/api/v1/investigations",
            json={**body, "service": "svc-23"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        check("cross_team_create", r.status_code == 403)
        r = httpx.get(
            BASE + "/api/v1/services", headers={"Authorization": "Bearer invalid"}
        )
        check("invalid_jwt", r.status_code == 401)
        r = httpx.post(
            BASE + "/internal/v1/claim",
            headers={"X-Worker-Key": "local-worker-key", "X-Protocol-Version": "2"},
            json={"owner": "test"},
        )
        check("protocol_mismatch", r.status_code == 409)
        r = httpx.post(
            BASE + "/internal/v1/claim",
            headers={"X-Worker-Key": "invalid", "X-Protocol-Version": "1"},
            json={"owner": "test"},
        )
        check("service_identity", r.status_code == 401)
        r = c.post(
            "/api/v1/investigations",
            json=body,
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        r.raise_for_status()
        id = r.json()["id"]
        i = wait(c, id)
        # K8s's demo may not have generated logs yet. Its partial state is still inspectable.
        if i["status"] == "waiting_information":
            httpx.get(SOURCE + "/business")
            c.post(
                "/api/v1/investigations/" + id + "/resume",
                json={"information": "new logs generated"},
            ).raise_for_status()
            i = wait(c, id)
        r = c.put(
            "/api/v1/investigations/" + id + "/action",
            json={
                "version": 0,
                "title": "Draft security test",
                "body": "No write without approval",
            },
        )
        check("draft_without_approval", r.status_code == 200)
        # Editing increments version and prevents approval of an older draft.
        r = c.put(
            "/api/v1/investigations/" + id + "/action",
            json={
                "version": 1,
                "title": "Edited security test",
                "body": "Changed content requires new approval",
            },
        )
        check(
            "edit_version_increment",
            r.status_code == 200 and r.json()["action"]["version"] == 2,
        )
        r = c.post(
            "/api/v1/investigations/" + id + "/action/approve", json={"version": 1}
        )
        check("old_approval_rejected", r.status_code == 409)
        check(
            "unapproved_no_external_result",
            c.get("/api/v1/investigations/" + id).json()["action"]["result"] is None,
        )
        # Revoke the current account while its token remains valid.
        httpx.put(
            BASE + "/api/v1/admin/members",
            headers=admin,
            json={"subject": "alice", "team": "orders", "role": ""},
        ).raise_for_status()
        try:
            for endpoint in [
                f"/investigations/{id}",
                f"/investigations/{id}/replay",
                f"/investigations/{id}/events",
            ]:
                check(
                    "revoked_" + endpoint.split("/")[-1],
                    c.get("/api/v1" + endpoint).status_code == 403,
                )
            check("revoked_memories_empty", c.get("/api/v1/memories").json() == [])
        finally:
            httpx.put(
                BASE + "/api/v1/admin/members",
                headers=admin,
                json={"subject": "alice", "team": "orders", "role": "approver"},
            ).raise_for_status()
        # Cancel and ensure approval cannot be dispatched.
        c.post("/api/v1/investigations/" + id + "/cancel", json={}).raise_for_status()
        check(
            "cancel_blocks_approval",
            c.post(
                "/api/v1/investigations/" + id + "/action/approve", json={"version": 2}
            ).status_code
            == 409,
        )
        i = c.get("/api/v1/investigations/" + id).json()
        check(
            "cancelled_action_invalidated",
            i["status"] == "cancelled" and i["action"]["state"] == "invalidated",
        )
        # Source deletion makes existing exports unavailable, including memory.
        httpx.post(
            BASE + "/api/v1/admin/services/svc-17/invalidate",
            headers=admin,
            json={"delete": True},
        ).raise_for_status()
        check(
            "deleted_report_hidden",
            c.get("/api/v1/investigations/" + id).json()["report"] is None,
        )
        check(
            "deleted_replay_denied",
            c.get("/api/v1/investigations/" + id + "/replay").status_code == 410,
        )
    Path("docs/evidence/security-regression.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
