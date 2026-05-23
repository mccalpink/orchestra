import pytest


class TestTopicLabel:
    def test_hub_default_orchestrator(self):
        # role пустой + is_orchestrator → Хаб: 🧭 <проект>
        from app.tg_bridge import _topic_label
        assert _topic_label("", True, "myproj-orchestrator", "/home/user/projects/myproj") == "🧭 myproj"

    def test_pm_glava(self):
        from app.tg_bridge import _topic_label
        # 🎯 PM-глава: 🎯 <проект>·спринт
        assert _topic_label("pm-glava", True, "pm-glava-q2", "/home/user/projects/myproj") == "🎯 myproj·спринт"

    def test_pm_fichi(self):
        from app.tg_bridge import _topic_label
        # 📋 PM-фичи: 📋 <фича> (фича = имя сессии без role-префикса)
        assert _topic_label("pm-fichi", True, "pm-fichi-auth", "/s") == "📋 auth"

    def test_analyst(self):
        from app.tg_bridge import _topic_label
        assert _topic_label("analyst", True, "analyst-auth", "/s") == "🔬 auth·анализ"

    def test_coder(self):
        from app.tg_bridge import _topic_label
        assert _topic_label("coder", True, "coder-auth", "/s") == "🛠 auth·код"

    def test_worker_own_topic(self):
        from app.tg_bridge import _topic_label
        # 🔨 воркер (когда у воркеров включены свои топики): 🔨 <имя>
        assert _topic_label("worker", False, "auth-step1", "/s") == "🔨 auth-step1"

    def test_unknown_role_orchestrator_falls_back_to_hub_emoji(self):
        from app.tg_bridge import _topic_label
        # неизвестная роль + оркестратор → 🧭 + имя (безопасный фолбэк)
        assert _topic_label("weird", True, "x-orchestrator", "/s").startswith("🧭 ")


class TestEnsureTopicsNaming:
    @pytest.mark.asyncio
    async def test_topic_created_with_role_label(self, monkeypatch):
        import app.tg_bridge as tg
        from unittest.mock import AsyncMock, MagicMock

        # стейт моста: чистый config, мок-бот, мок-manager
        monkeypatch.setattr(tg, "config", {"group_id": 123, "topics": {}, "token": "t", "mirrors": {}})
        monkeypatch.setattr(tg, "_manager", MagicMock())
        monkeypatch.setattr(tg, "save_config", lambda: None)
        # stream_logs не запускаем по-настоящему
        monkeypatch.setattr(tg, "stream_logs", AsyncMock())

        created = {}
        async def fake_create(chat_id, name, icon_custom_emoji_id=None):
            created["name"] = name
            r = MagicMock(); r.message_thread_id = 555
            return r
        fake_bot = MagicMock()
        fake_bot.create_forum_topic = AsyncMock(side_effect=fake_create)
        monkeypatch.setattr(tg, "bot", fake_bot)

        # БД отдаёт одного pm-fichi оркестратора
        monkeypatch.setattr("app.db.get_all_sessions", lambda: [
            {"name": "pm-fichi-auth", "scope": "/home/user/projects/myproj",
             "is_orchestrator": 1, "role": "pm-fichi", "parent_id": "", "parent_name": ""},
        ])
        # asyncio.create_task(stream_logs(...)) — замокаем create_task, чтобы не плодить задачи
        monkeypatch.setattr(tg.asyncio, "create_task", lambda coro: (coro.close() or MagicMock()))

        await tg.ensure_topics()
        assert created["name"] == "📋 auth"
        assert tg.config["topics"]["pm-fichi-auth"] == 555
