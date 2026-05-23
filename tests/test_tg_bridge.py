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
