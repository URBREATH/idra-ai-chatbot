import pytest
from unittest.mock import patch, AsyncMock


class TestSemanticEnricher:
    @pytest.mark.asyncio
    async def test_enrich_returns_concepts_synonyms_related_terms(self):
        from app.ingestion.semantic_enricher import enrich

        mock_llm_response = '["occupazione", "lavoro", "mercato del lavoro", "disoccupazione", "forza lavoro"]'

        with patch("app.ingestion.semantic_enricher.generate_completion", new=AsyncMock(return_value=mock_llm_response)):
            result = await enrich("occupazione giovanile")

        assert isinstance(result, list)
        assert len(result) >= 3
        assert "occupazione" in result
        assert "lavoro" in result
        assert "mercato del lavoro" in result

    @pytest.mark.asyncio
    async def test_enrich_handles_empty_input(self):
        from app.ingestion.semantic_enricher import enrich

        with patch("app.ingestion.semantic_enricher.generate_completion", new=AsyncMock(return_value="[]")):
            result = await enrich("")

        assert result == []

    @pytest.mark.asyncio
    async def test_enrich_handles_invalid_json_from_llm(self):
        from app.ingestion.semantic_enricher import enrich

        with patch("app.ingestion.semantic_enricher.generate_completion", new=AsyncMock(return_value="invalid json")):
            result = await enrich("test")

        assert result == []

    @pytest.mark.asyncio
    async def test_enrich_uses_correct_model_and_temperature(self):
        from app.ingestion.semantic_enricher import enrich

        captured = {}

        async def capture_completion(prompt, model, temperature):
            captured["model"] = model
            captured["temperature"] = temperature
            return '["term1", "term2"]'

        with patch("app.ingestion.semantic_enricher.generate_completion", new=capture_completion):
            await enrich("test query")

        assert captured["model"] == "enggpt-2-16b-a3b"
        assert captured["temperature"] == 0.1

    @pytest.mark.asyncio
    async def test_enrich_prompt_contains_input_text(self):
        from app.ingestion.semantic_enricher import enrich

        captured_prompt = {}

        async def capture_completion(prompt, model, temperature):
            captured_prompt["prompt"] = prompt
            return '["term1"]'

        with patch("app.ingestion.semantic_enricher.generate_completion", new=capture_completion):
            await enrich("occupazione giovanile in Italia")

        assert "occupazione giovanile in Italia" in captured_prompt["prompt"]
        assert "concetti" in captured_prompt["prompt"].lower()
        assert "sinonimi" in captured_prompt["prompt"].lower()
        assert "termini correlati" in captured_prompt["prompt"].lower()

    @pytest.mark.asyncio
    async def test_enrich_returns_unique_terms(self):
        from app.ingestion.semantic_enricher import enrich

        mock_response = '["lavoro", "lavoro", "occupazione", "occupazione", "mercato del lavoro"]'

        with patch("app.ingestion.semantic_enricher.generate_completion", new=AsyncMock(return_value=mock_response)):
            result = await enrich("lavoro")

        assert len(result) == len(set(result))
        assert result.count("lavoro") == 1

    @pytest.mark.asyncio
    async def test_enrich_limits_results(self):
        from app.ingestion.semantic_enricher import enrich

        many_terms = '["term' + '", "term'.join(str(i) for i in range(50)) + '"]'

        with patch("app.ingestion.semantic_enricher.generate_completion", new=AsyncMock(return_value=many_terms)):
            result = await enrich("test")

        assert len(result) <= 20