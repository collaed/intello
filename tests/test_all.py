"""Test suite for L'Intello — blackbox + whitebox tests."""
import json
import os
import sys
import tempfile

# Ensure intello package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_models():
    """Whitebox: verify all providers load."""
    from intello.research import get_providers
    providers = get_providers()
    assert len(providers) >= 25, f"Expected 25+ providers, got {len(providers)}"
    free = [p for p in providers if p.tier.value == "free"]
    assert len(free) >= 15, f"Expected 15+ free providers, got {len(free)}"
    print(f"✅ Models: {len(providers)} providers ({len(free)} free)")


def test_task_classifier():
    """Whitebox: verify task classification."""
    from intello.router import classify_task, TaskType
    cases = [
        ("write a python function", TaskType.CODE),
        ("solve the integral of x^2", TaskType.MATH),
        ("write me a short story", TaskType.CREATIVE),
        ("analyze the pros and cons", TaskType.ANALYSIS),
        ("what is the capital of France", TaskType.GENERAL),
    ]
    for prompt, expected in cases:
        result = classify_task(prompt)
        assert result == expected, f"'{prompt}' → {result}, expected {expected}"
    print(f"✅ Classifier: {len(cases)} cases passed")


def test_guardrails():
    """Whitebox: verify confidence scoring."""
    from intello.guardrails import check_confidence, check_word_count, count_words
    # Confident
    r = check_confidence("The capital of France is Paris.")
    assert r["confidence"] >= 0.7, f"Expected high confidence, got {r['confidence']}"
    # Hedging
    r = check_confidence("I'm not sure but I think maybe it could be Paris probably.")
    assert r["confidence"] < 0.9, f"Expected lower confidence for hedging"
    # Word count
    assert count_words("hello world test") == 3
    wc = check_word_count("word " * 800, 1000)
    assert not wc["within_tolerance"], "800/1000 should be outside 15% tolerance"
    wc = check_word_count("word " * 900, 1000)
    assert wc["within_tolerance"], "900/1000 should be within 15% tolerance"
    print("✅ Guardrails: confidence + word count passed")


def test_cache():
    """Whitebox: verify semantic cache."""
    from intello.cache import store, get_cached, _hash
    # Store
    store("test query for cache", "general", "test response", "test", "test-model", 0.0)
    # Exact match
    r = get_cached("test query for cache", "general")
    assert r is not None, "Exact cache match failed"
    assert r["response"] == "test response"
    # Different query
    r = get_cached("completely unrelated question about bananas", "general")
    # May or may not match depending on embeddings — just verify no crash
    print("✅ Cache: store + retrieve passed")


def test_literary_ingest():
    """Whitebox: verify document ingestion."""
    from intello.literary import ingest_document, get_document_info, get_structure, get_pacing_data

    text = """Chapter 1: The Chase

Rain hammered the windows. Elena ran through the dark alley.
"Stop!" she screamed. But nobody listened.
The shadow grew larger behind her.

Chapter 2: Morning

Sunlight streamed through curtains. Birds sang.
Elena sat at the kitchen table with cold tea."""

    r = ingest_document("test_doc_1", text, "Test Doc")
    assert r["chapters"] == 2, f"Expected 2 chapters, got {r['chapters']}"
    assert r["lines"] > 5, f"Expected >5 lines"

    info = get_document_info("test_doc_1")
    assert info is not None

    struct = get_structure("test_doc_1")
    assert len(struct) == 2

    pacing = get_pacing_data("test_doc_1", window=3)
    assert len(pacing) > 0
    print(f"✅ Literary: ingested {r['lines']} lines, {r['chapters']} chapters")


def test_craft():
    """Whitebox: verify craft reference engine."""
    from intello.craft import get_relevant_techniques, build_craft_prompt
    t = get_relevant_techniques("fiction", ["slow pacing"])
    assert len(t) > 0, "Expected techniques for slow pacing"
    p = build_craft_prompt("fiction", ["slow"], "Hemingway")
    assert "CRAFT REFERENCE" in p
    assert "Hemingway" in p
    print(f"✅ Craft: {len(t)} techniques returned")


def test_writing_tools():
    """Whitebox: verify prompt generation."""
    from intello.writing_tools import show_not_tell, describe_senses, brainstorm, shrink_ray
    assert "SHOW" in show_not_tell("She was angry.")
    assert "SIGHT" in describe_senses("an old library")
    assert "plot" in brainstorm("detective in Paris", "plot").lower()
    assert "blurb" in shrink_ray("Some text", "blurb").lower()
    print("✅ Writing tools: all prompt generators work")


def test_scheduler():
    """Whitebox: verify scheduler CRUD."""
    from intello.scheduler import create_task, get_task, list_tasks, delete_task
    t = create_task("test_sched_1", "Test Task", "Say hello", "daily")
    assert t["name"] == "Test Task"
    assert get_task("test_sched_1") is not None
    assert len(list_tasks()) >= 1
    delete_task("test_sched_1")
    assert get_task("test_sched_1") is None
    print("✅ Scheduler: CRUD passed")


def test_webhooks():
    """Whitebox: verify webhook CRUD."""
    from intello.webhooks import create_webhook, get_webhook, list_webhooks, delete_webhook
    w = create_webhook("test_hook_1", "Test Hook", "chat", {"key": "val"})
    assert w["name"] == "Test Hook"
    assert w["config"]["key"] == "val"
    assert len(list_webhooks()) >= 1
    delete_webhook("test_hook_1")
    assert get_webhook("test_hook_1") is None
    print("✅ Webhooks: CRUD passed")


def test_user_filtering():
    """Whitebox: verify premium model filtering."""
    from intello.research import get_providers
    from intello.web import filter_providers_for_user, PREMIUM_MODELS
    providers = get_providers()
    # Admin sees all
    admin = filter_providers_for_user(providers, "ecb")
    assert len(admin) == len(providers)
    # Non-admin gets filtered
    guest = filter_providers_for_user(providers, "guest")
    assert len(guest) < len(providers), "Guest should see fewer models"
    premium_in_guest = [p for p in guest if any(pm in p.model_id for pm in PREMIUM_MODELS)]
    assert len(premium_in_guest) == 0, "Guest should not see premium models"
    print(f"✅ User filtering: admin={len(admin)}, guest={len(guest)}")


def test_ocr_module():
    """Whitebox: verify OCR module loads."""
    from intello.ocr import get_languages
    langs = get_languages()
    assert "eng" in langs, "English should be available"
    print(f"✅ OCR: {len(langs)} languages available")


def test_web_app():
    """Blackbox: verify all routes exist."""
    from intello.web import app
    routes = {r.path for r in app.routes if hasattr(r, 'path')}
    required = [
        "/", "/literary", "/corkboard", "/login",
        "/api/prompt", "/api/providers", "/api/v1/status",
        "/v1/chat/completions", "/v1/models",
        "/api/v1/ocr", "/api/v1/ocr/pdf",
        "/api/scheduler/tasks", "/api/webhooks",
        "/api/literary/ingest", "/api/literary/projects",
        "/api/tools/transform", "/api/tools/beta-read",
        "/api/v1/image/generate", "/api/v1/voice/transcribe",
        "/api/literary/compare",
        "/v1/chat/completions/stream",
    ]
    missing = [r for r in required if r not in routes]
    assert not missing, f"Missing routes: {missing}"
    print(f"✅ Web app: all {len(required)} required routes present")


if __name__ == "__main__":
    tests = [
        test_models, test_task_classifier, test_guardrails, test_cache,
        test_literary_ingest, test_craft, test_writing_tools,
        test_scheduler, test_webhooks, test_user_filtering,
        test_ocr_module, test_web_app,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    if failed:
        sys.exit(1)
