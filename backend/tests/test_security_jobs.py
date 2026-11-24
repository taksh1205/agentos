import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient

from agentos.security import authenticate, validate_configuration


@pytest.fixture
def oidc(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    for k, v in {
        "AUTH_MODE": "oidc",
        "DEPLOYMENT": "shared",
        "OIDC_ISSUER": "https://issuer.example.test",
        "OIDC_AUDIENCE": "agentos",
        "OIDC_PUBLIC_KEY": public,
    }.items():
        monkeypatch.setenv(k, v)

    def token(**overrides):
        claims = dict(
            sub="user-1",
            workspace="tenant",
            role="editor",
            iss="https://issuer.example.test",
            aud="agentos",
            iat=int(time.time()),
            exp=int(time.time()) + 300,
        )
        claims.update(overrides)
        return jwt.encode(claims, private, algorithm="RS256")

    return token


def test_oidc_validated_and_scope_intersection(oidc):
    user = authenticate("Bearer " + oidc(scope="data:read superuser"))
    assert user["workspace"] == "tenant" and user["scopes"] == ["data:read"]
    assert authenticate("Bearer " + oidc())["role"] == "editor"


@pytest.mark.parametrize(
    "claims", [{"exp": 0}, {"aud": "other"}, {"iss": "https://wrong.test"}, {"role": "superuser"}]
)
def test_oidc_rejects_invalid_claims(oidc, claims):
    with pytest.raises(HTTPException):
        authenticate("Bearer " + oidc(**claims))


def test_demo_forbidden_in_shared_deployment(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT", "shared")
    monkeypatch.setenv("AUTH_MODE", "demo")
    with pytest.raises(RuntimeError):
        validate_configuration()


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "db"))
    monkeypatch.setenv("CHECKPOINT_PATH", str(tmp_path / "cp"))
    from agentos.api import app

    return app


H = {"Authorization": "Bearer local-demo-token"}


def wait_run(client, ident):
    for _ in range(400):
        out = client.get("/runs/" + ident, headers=H).json()
        if out["status"] != "running":
            return out
        time.sleep(0.01)
    raise AssertionError("API job did not finish")


def test_durable_job_recovered_after_restart(api):
    # Simulate a persisted queued job at shutdown, before a dispatcher can claim it.
    with TestClient(api) as c:
        c.post("/demo/seed", headers=H)
        initial = dict(
            goal="Analyze revenue",
            workspace="demo",
            run_id="recovered",
            mode="demo",
            workflow="auto",
            results=[],
            events=[],
            scopes=["data:read", "action:write"],
        )
        api.state.store.execute(
            "INSERT INTO runs VALUES(:id,:w,:s,:t)",
            dict(
                id="recovered",
                w="demo",
                s=json.dumps({**initial, "status": "running"}),
                t=time.time(),
            ),
        )
        # A running job is deliberately stale as if the old worker crashed.
        api.state.store.execute(
            "INSERT INTO jobs VALUES('stale','demo',:input,'running',0,1)",
            {"input": json.dumps({"kind": "start", "run_id": "recovered", "state": initial})},
        )
    with TestClient(api) as c:
        out = wait_run(c, "recovered")
        assert out["status"] == "completed"
        assert (
            api.state.store.execute("SELECT status FROM jobs WHERE id='stale'")[0]["status"]
            == "done"
        )


def test_rate_limit_and_scope_tenant(api, monkeypatch):
    monkeypatch.setenv("REQUESTS_PER_MINUTE", "2")
    with TestClient(api) as c:
        assert c.get("/config", headers=H).status_code == 200
        assert c.get("/config", headers=H).status_code == 200
        assert c.get("/config", headers=H).status_code == 429


def test_approval_trace_and_cancel_pending(api):
    with TestClient(api) as c:
        c.post("/demo/seed", headers=H)
        ident = c.post("/runs", json={"goal": "Export revenue CSV"}, headers=H).json()["id"]
        assert wait_run(c, ident)["status"] == "awaiting_approval"
        trace = c.get("/runs/" + ident + "/traces", headers=H).json()
        assert any(t["kind"] == "plan" for t in trace)
        assert (
            c.post(
                "/runs/" + ident + "/approval",
                json={"approve": True, "proposal_id": "stale"},
                headers=H,
            ).status_code
            == 409
        )
        assert c.post("/runs/" + ident + "/cancel", headers=H).json()["status"] == "cancelled"
        assert (
            c.post("/runs/" + ident + "/approval", json={"approve": True}, headers=H).status_code
            == 409
        )
        assert c.post("/runs/" + ident + "/resume", headers=H).status_code == 409
        assert c.get("/inbox", headers=H).json() == []


def test_cross_tenant_read_and_ingestion_errors(api, monkeypatch):
    monkeypatch.setenv(
        "API_KEYS",
        json.dumps(
            {
                "local-demo-token": {"workspace": "demo", "role": "admin"},
                "other": {"workspace": "other", "role": "viewer"},
            }
        ),
    )
    with TestClient(api) as c:
        ident = c.post("/runs", json={"goal": "Analyze revenue"}, headers=H).json()["id"]
        assert c.get("/runs/" + ident, headers={"Authorization": "Bearer other"}).status_code == 404
        assert (
            c.post(
                "/documents/upload", files={"file": ("bad.pdf", b"not PDF")}, headers=H
            ).status_code
            == 422
        )


def test_stale_queued_decision_cannot_approve_current_proposal(api):
    with TestClient(api) as c:
        ident = c.post("/runs", json={"goal": "Create a local notification"}, headers=H).json()[
            "id"
        ]
        assert wait_run(c, ident)["status"] == "awaiting_approval"
        api.state.store.execute(
            "INSERT INTO jobs VALUES('replayed','demo',:p,'queued',0,0)",
            {
                "p": json.dumps(
                    {
                        "run_id": ident,
                        "kind": "approval",
                        "approve": True,
                        "proposal_id": "prior-proposal",
                    }
                )
            },
        )
        for _ in range(200):
            if (
                api.state.store.execute("SELECT status FROM jobs WHERE id='replayed'")[0]["status"]
                == "done"
            ):
                break
            time.sleep(0.02)
        assert (
            api.state.store.execute("SELECT status FROM jobs WHERE id='replayed'")[0]["status"]
            == "done"
        )
        assert c.get("/runs/" + ident, headers=H).json()["status"] == "awaiting_approval"
        assert c.get("/inbox", headers=H).json() == []
