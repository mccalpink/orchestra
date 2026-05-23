import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_spawn_sends_orchestrator_role_parent(monkeypatch):
    import app.mcp_stdio as m
    monkeypatch.setattr(m, "SCOPE", "/s")
    monkeypatch.setattr(m, "WORKER_NAME", "pm-fichi-auth")
    captured = {}
    async def fake_api(method, path, **kw):
        if path == "/api/sessions":
            captured.update(kw.get("json", {}))
        return {"ok": True}
    with patch.object(m, "_api", side_effect=fake_api):
        await m.spawn_worker(name="coder-auth", task="do it", repo_path="/s",
                             model="claude-opus-4-6[1m]", is_orchestrator=True, role="coder")
    assert captured["is_orchestrator"] is True
    assert captured["role"] == "coder"
    assert captured["parent_name"] == "pm-fichi-auth"
    assert captured["use_worktree"] is False  # оркестратор без worktree
