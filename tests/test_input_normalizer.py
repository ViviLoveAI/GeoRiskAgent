from src import input_normalizer


def test_english_input_passes_through_without_model_call(monkeypatch):
    def fail_if_called(text):
        raise AssertionError("English input should not call the normalization model")

    monkeypatch.setattr(input_normalizer, "_normalize_non_english_with_model", fail_if_called)

    result = input_normalizer.normalize_event_input("Red Sea Shipping Disruption")

    assert result.detected_language == "English"
    assert result.original_text == "Red Sea Shipping Disruption"
    assert result.analysis_text == "Red Sea Shipping Disruption"
    assert result.normalization_applied is False


def test_non_english_input_uses_general_normalization_path(monkeypatch):
    monkeypatch.setattr(
        input_normalizer,
        "_normalize_non_english_with_model",
        lambda text: "Black Sea port insurance restrictions delay grain shipping.",
    )

    result = input_normalizer.normalize_event_input("黑海港口保险限制导致谷物运输延迟。")

    assert result.detected_language == "Chinese"
    assert result.original_text == "黑海港口保险限制导致谷物运输延迟。"
    assert result.analysis_text == "Black Sea port insurance restrictions delay grain shipping."
    assert result.normalization_applied is True


def test_non_english_normalization_failure_preserves_original(monkeypatch):
    def fail(text):
        raise input_normalizer.InputNormalizationError("model unavailable")

    monkeypatch.setattr(input_normalizer, "_normalize_non_english_with_model", fail)

    text = "黑海港口保险限制导致谷物运输延迟。"
    result = input_normalizer.normalize_event_input(text)

    assert result.detected_language == "Chinese"
    assert result.original_text == text
    assert result.analysis_text == text
    assert result.normalization_applied is False
    assert "InputNormalizationError" in str(result.normalization_error)


def test_language_detection_does_not_depend_on_fixed_phrase_dictionary():
    assert input_normalizer.detect_language("红海航运中断") == "Chinese"
    assert input_normalizer.detect_language("黑海港口保险限制导致谷物运输延迟") == "Chinese"
