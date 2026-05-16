"""
tests/unit/test_template_engine.py — Unit tests for TemplateEngine.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.template_engine import TemplateEngine, ALLOWED_VARIABLES


@pytest.fixture
def engine(mock_db, mock_redis):
    return TemplateEngine(db=mock_db, redis=mock_redis)


class TestRenderBody:
    def test_renders_all_variables(self, engine):
        template = "Привет, {{client_name}}! Запись на {{appointment_date}} в {{appointment_time}}."
        context = {
            "client_name": "Иван",
            "appointment_date": "15.01.2024",
            "appointment_time": "14:00",
        }
        result = engine.render_body(template, context)
        assert "Иван" in result
        assert "15.01.2024" in result
        assert "14:00" in result

    def test_missing_variable_replaced_with_empty_string(self, engine):
        template = "Привет, {{client_name}}! Мастер: {{master_name}}."
        context = {"client_name": "Иван"}
        result = engine.render_body(template, context)
        assert "Иван" in result
        assert "{{master_name}}" not in result

    def test_emoji_preserved(self, engine):
        template = "🎉 Привет, {{client_name}}!"
        context = {"client_name": "Мария"}
        result = engine.render_body(template, context)
        assert "🎉" in result
        assert "Мария" in result

    def test_html_tags_preserved(self, engine):
        template = "<b>{{client_name}}</b>"
        context = {"client_name": "Тест"}
        result = engine.render_body(template, context)
        assert "<b>Тест</b>" == result

    def test_empty_context_returns_template_with_empty_vars(self, engine):
        template = "{{client_name}} — {{master_name}}"
        result = engine.render_body(template, {})
        assert "{{" not in result


class TestValidateTemplate:
    def test_valid_template_returns_empty_list(self, engine):
        template = "Привет, {{client_name}}! Запись у {{master_name}}."
        invalid = engine.validate_template(template)
        assert invalid == []

    def test_invalid_variable_detected(self, engine):
        template = "Привет, {{unknown_var}}!"
        invalid = engine.validate_template(template)
        assert "unknown_var" in invalid

    def test_all_allowed_variables_valid(self, engine):
        template = " ".join(f"{{{{{v}}}}}" for v in ALLOWED_VARIABLES)
        invalid = engine.validate_template(template)
        assert invalid == []

    def test_syntax_error_detected(self, engine):
        template = "{% if %} broken"
        invalid = engine.validate_template(template)
        assert any("syntax_error" in v for v in invalid)

    def test_mixed_valid_invalid(self, engine):
        template = "{{client_name}} {{bad_var}}"
        invalid = engine.validate_template(template)
        assert "bad_var" in invalid
        assert "client_name" not in invalid


class TestGetTemplateBody:
    @pytest.mark.asyncio
    async def test_returns_from_local_cache(self, engine):
        engine._local_cache["template:new_appointment:telegram:ru"] = "cached body"
        result = await engine.get_template_body("new_appointment", "telegram")
        assert result == "cached body"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, engine, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await engine.get_template_body("nonexistent_type", "telegram")
        assert result is None

    @pytest.mark.asyncio
    async def test_caches_result_locally(self, engine, mock_db):
        mock_template = MagicMock()
        mock_template.body_template = "test body"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_template
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await engine.get_template_body("new_appointment", "telegram")
        assert result == "test body"
        assert "template:new_appointment:telegram:ru" in engine._local_cache
