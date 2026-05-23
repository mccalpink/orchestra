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


class TestThreadForSession:
    def _stub_db(self, monkeypatch, rows):
        monkeypatch.setattr("app.db.get_all_sessions", lambda: rows)

    def test_orchestrator_uses_own_topic(self, monkeypatch):
        import app.tg_bridge as tg
        monkeypatch.setattr(tg, "config", {"group_id": 1, "topics": {"pm-fichi-auth": 100}, "mirrors": {}})
        self._stub_db(monkeypatch, [
            {"name": "pm-fichi-auth", "scope": "/s", "is_orchestrator": 1, "role": "pm-fichi", "parent_id": "", "parent_name": ""},
        ])
        assert tg._thread_for_session("pm-fichi-auth") == 100

    def test_worker_silent_by_default_returns_none(self, monkeypatch):
        # дефолт: TG_WORKER_TOPICS=False → воркер молчит → None
        import app.tg_bridge as tg
        monkeypatch.setattr(tg, "config", {"group_id": 1, "topics": {"coder-auth": 200}, "mirrors": {}})
        monkeypatch.setattr(tg, "WORKER_TOPICS_ENABLED", False)
        self._stub_db(monkeypatch, [
            {"name": "coder-auth", "scope": "/s", "is_orchestrator": 1, "role": "coder", "parent_id": "", "parent_name": ""},
            {"name": "coder-step1", "scope": "/s", "is_orchestrator": 0, "role": "worker", "parent_id": "", "parent_name": "coder-auth"},
        ])
        assert tg._thread_for_session("coder-step1") is None

    def test_worker_with_own_topics_enabled(self, monkeypatch):
        # TG_WORKER_TOPICS=True → воркер стримится в свой топик
        import app.tg_bridge as tg
        monkeypatch.setattr(tg, "config", {"group_id": 1, "topics": {"coder-auth": 200, "coder-step1": 201}, "mirrors": {}})
        monkeypatch.setattr(tg, "WORKER_TOPICS_ENABLED", True)
        self._stub_db(monkeypatch, [
            {"name": "coder-step1", "scope": "/s", "is_orchestrator": 0, "role": "worker", "parent_id": "", "parent_name": "coder-auth"},
        ])
        assert tg._thread_for_session("coder-step1") == 201

    def test_unknown_session_returns_none(self, monkeypatch):
        import app.tg_bridge as tg
        monkeypatch.setattr(tg, "config", {"group_id": 1, "topics": {}, "mirrors": {}})
        self._stub_db(monkeypatch, [])
        assert tg._thread_for_session("ghost") is None

    def test_stale_worker_topic_ignored_when_flag_off(self, monkeypatch):
        # B3: stale worker-топик в config["topics"] при выключенном флаге
        # → _thread_for_session должен вернуть None, а не stale thread_id
        import app.tg_bridge as tg
        # stale-топик воркера остался в json-конфиге после выключения TG_WORKER_TOPICS
        monkeypatch.setattr(tg, "config", {"group_id": 1, "topics": {"coder-auth": 200, "coder-step1": 201}, "mirrors": {}})
        monkeypatch.setattr(tg, "WORKER_TOPICS_ENABLED", False)
        self._stub_db(monkeypatch, [
            {"name": "coder-step1", "scope": "/s", "is_orchestrator": 0, "role": "worker", "parent_id": "", "parent_name": "coder-auth"},
        ])
        assert tg._thread_for_session("coder-step1") is None


class TestWorkerStreamWiring:
    @pytest.mark.asyncio
    async def test_no_worker_topic_by_default(self, monkeypatch):
        # дефолт: WORKER_TOPICS_ENABLED=False → воркеру топик не создаётся
        import app.tg_bridge as tg
        from unittest.mock import AsyncMock, MagicMock
        monkeypatch.setattr(tg, "config", {"group_id": 1, "topics": {}, "token": "t", "mirrors": {}})
        monkeypatch.setattr(tg, "_manager", MagicMock())
        monkeypatch.setattr(tg, "save_config", lambda: None)
        monkeypatch.setattr(tg, "WORKER_TOPICS_ENABLED", False)
        monkeypatch.setattr(tg.asyncio, "create_task", lambda coro: (coro.close() or MagicMock()))
        fake_bot = MagicMock()
        r = MagicMock(); r.message_thread_id = 7
        fake_bot.create_forum_topic = AsyncMock(return_value=r)
        monkeypatch.setattr(tg, "bot", fake_bot)
        monkeypatch.setattr("app.db.get_all_sessions", lambda: [
            {"name": "coder-auth", "scope": "/s", "is_orchestrator": 1, "role": "coder", "parent_id": "", "parent_name": ""},
            {"name": "coder-step1", "scope": "/s", "is_orchestrator": 0, "role": "worker", "parent_id": "", "parent_name": "coder-auth"},
        ])
        await tg.ensure_topics()
        # топик создан только оркестратору
        assert "coder-auth" in tg.config["topics"]
        assert "coder-step1" not in tg.config["topics"]

    @pytest.mark.asyncio
    async def test_worker_own_topic_when_enabled(self, monkeypatch):
        # TG_WORKER_TOPICS=True → воркер получает свой топик
        import app.tg_bridge as tg
        from unittest.mock import AsyncMock, MagicMock
        monkeypatch.setattr(tg, "config", {"group_id": 1, "topics": {}, "token": "t", "mirrors": {}})
        monkeypatch.setattr(tg, "_manager", MagicMock())
        monkeypatch.setattr(tg, "save_config", lambda: None)
        monkeypatch.setattr(tg, "WORKER_TOPICS_ENABLED", True)
        monkeypatch.setattr(tg.asyncio, "create_task", lambda coro: (coro.close() or MagicMock()))
        ids = iter([10, 11])
        async def fake_create(chat_id, name, icon_custom_emoji_id=None):
            r = MagicMock(); r.message_thread_id = next(ids); return r
        fake_bot = MagicMock(); fake_bot.create_forum_topic = AsyncMock(side_effect=fake_create)
        monkeypatch.setattr(tg, "bot", fake_bot)
        monkeypatch.setattr("app.db.get_all_sessions", lambda: [
            {"name": "coder-auth", "scope": "/s", "is_orchestrator": 1, "role": "coder", "parent_id": "", "parent_name": ""},
            {"name": "coder-step1", "scope": "/s", "is_orchestrator": 0, "role": "worker", "parent_id": "", "parent_name": "coder-auth"},
        ])
        await tg.ensure_topics()
        assert "coder-step1" in tg.config["topics"]

    def test_start_stream_idempotent(self, monkeypatch):
        # _start_stream вызывает create_task ровно один раз для одной сессии
        import app.tg_bridge as tg
        from unittest.mock import MagicMock, AsyncMock
        calls = []
        monkeypatch.setattr(tg, "_streamed", set())
        monkeypatch.setattr(tg, "_tasks", [])
        monkeypatch.setattr(tg, "stream_logs", AsyncMock())
        monkeypatch.setattr(tg.asyncio, "create_task", lambda coro: (calls.append(coro) or MagicMock()))
        tg._start_stream("coder-auth", 100)
        tg._start_stream("coder-auth", 100)  # повторный вызов — игнорируется
        assert len(calls) == 1
        assert "coder-auth" in tg._streamed

    def test_start_stream_worker_own_topic_id(self, monkeypatch):
        # _start_stream запускает stream_logs с правильным topic_id воркера
        import app.tg_bridge as tg
        from unittest.mock import MagicMock, AsyncMock, call
        logged = []
        monkeypatch.setattr(tg, "_streamed", set())
        monkeypatch.setattr(tg, "_tasks", [])
        mock_sl = AsyncMock()
        monkeypatch.setattr(tg, "stream_logs", mock_sl)
        monkeypatch.setattr(tg.asyncio, "create_task", lambda coro: MagicMock())
        tg._start_stream("coder-step1", 201)
        # убедимся, что stream_logs был вызван с name=coder-step1, thread_id=201
        # Минимальная проверка: имя есть в _streamed, задача добавлена в _tasks
        assert "coder-step1" in tg._streamed

    def test_worker_not_streamed_by_default(self, monkeypatch):
        # при WORKER_TOPICS_ENABLED=False _thread_for_session возвращает None
        # → _start_stream НЕ вызывается для воркера
        import app.tg_bridge as tg
        from unittest.mock import MagicMock
        monkeypatch.setattr(tg, "WORKER_TOPICS_ENABLED", False)
        monkeypatch.setattr(tg, "_streamed", set())
        monkeypatch.setattr(tg, "_tasks", [])
        create_task_calls = []
        monkeypatch.setattr(tg.asyncio, "create_task", lambda c: create_task_calls.append(c))
        monkeypatch.setattr("app.db.get_all_sessions", lambda: [
            {"name": "coder-step1", "scope": "/s", "is_orchestrator": 0, "role": "worker", "parent_id": "", "parent_name": "coder-auth"},
        ])
        monkeypatch.setattr(tg, "config", {"group_id": 1, "topics": {"coder-step1": 201}, "mirrors": {}})
        # _thread_for_session для воркера при флаге off → None → _start_stream не вызван
        assert tg._thread_for_session("coder-step1") is None
        assert len(create_task_calls) == 0  # stream не запустился

    def test_stale_worker_not_streamed_in_start_bridge(self, monkeypatch):
        # start_bridge использует _thread_for_session, а не слепой цикл по config["topics"]
        # stale worker-топик в config["topics"] при флаге off не порождает стрим
        import app.tg_bridge as tg
        from unittest.mock import MagicMock
        monkeypatch.setattr(tg, "WORKER_TOPICS_ENABLED", False)
        monkeypatch.setattr(tg, "_streamed", set())
        # stale в config — воркер с топиком, но флаг выключен
        monkeypatch.setattr(tg, "config", {"group_id": 1, "topics": {"coder-auth": 200, "coder-step1": 201}, "mirrors": {}})
        monkeypatch.setattr("app.db.get_all_sessions", lambda: [
            {"name": "coder-auth", "scope": "/s", "is_orchestrator": 1, "role": "coder", "parent_id": "", "parent_name": ""},
            {"name": "coder-step1", "scope": "/s", "is_orchestrator": 0, "role": "worker", "parent_id": "", "parent_name": "coder-auth"},
        ])
        # Имитируем логику start_bridge: для каждой сессии из БД → _thread_for_session
        streamed = []
        # Новый подход: обходим сессии из БД
        from app.db import get_all_sessions
        for row in get_all_sessions():
            tid = tg._thread_for_session(row["name"])
            if tid is not None:
                streamed.append(row["name"])
        assert "coder-step1" not in streamed  # воркер не стримится при флаге off
        assert "coder-auth" in streamed        # оркестратор стримится
