"""Additional unit tests for modules added after the initial test suite."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_costs_ledger():
    """Whitebox: cost tracking and budget enforcement."""
    from intello.costs import record_cost, get_spending, set_budget, check_budget, estimate_tts_cost

    # Record some costs
    record_cost("tts", "voxtral", 1000, "characters", 0.016, "test", "proj1", "user1")
    record_cost("tts", "voxtral", 2000, "characters", 0.032, "test", "proj1", "user1")
    record_cost("llm", "openai", 500, "tokens", 0.005, "test", "proj2", "user1")

    # Check spending
    s = get_spending("global", "", "today")
    assert s["total_usd"] > 0, "Should have spending"
    assert "tts" in s["by_service"]
    assert s["transactions"] >= 3

    # Per-project
    s2 = get_spending("project", "proj1", "all")
    assert s2["total_usd"] >= 0.048

    # Budget enforcement
    set_budget("global", "", daily=0.10, monthly=1.00)
    check = check_budget(0.01, "global")
    assert check["allowed"], "Should be within budget"

    check2 = check_budget(999.0, "global")
    assert not check2["allowed"], "Should exceed budget"

    # TTS cost estimation
    assert estimate_tts_cost("hello", "voxtral") > 0
    assert estimate_tts_cost("hello", "piper") == 0
    assert estimate_tts_cost("hello", "groq") == 0

    print("✅ Costs: ledger + budget + estimation passed")


def test_jobs_system():
    """Whitebox: async job lifecycle."""
    from intello.jobs import create_job, get_job, list_jobs, update_job

    jid = create_job("test", "Test job")
    assert get_job(jid) is not None
    assert get_job(jid)["status"] == "queued"

    update_job(jid, status="processing", progress=50)
    assert get_job(jid)["status"] == "processing"
    assert get_job(jid)["progress"] == 50

    jobs = list_jobs()
    assert any(j["job_id"] == jid for j in jobs)

    print("✅ Jobs: create + update + list passed")


def test_speech_module():
    """Whitebox: speech module loads and functions exist."""
    from intello.speech import (
        get_available_voices, tts_available, synthesize,
        synthesize_groq, synthesize_voxtral, transcribe_groq,
        VOICE_MAP, GROQ_VOICES,
    )

    assert len(VOICE_MAP) >= 4, "Should have EN + FR voice mappings"
    assert len(GROQ_VOICES) >= 5, "Should have Groq voices"
    assert callable(synthesize)
    assert callable(synthesize_groq)
    assert callable(synthesize_voxtral)
    assert callable(transcribe_groq)

    voices = get_available_voices()
    # May be empty if Piper not installed locally
    assert isinstance(voices, list)

    print(f"✅ Speech: module loaded, {len(GROQ_VOICES)} Groq voices, {len(voices)} Piper voices")


def test_ocr_rotation():
    """Whitebox: rotation detection function exists and handles missing files."""
    from intello.ocr import _auto_rotate, MAX_UPLOAD_MB

    # Should return None for non-existent file (not crash)
    result = _auto_rotate("/nonexistent/file.png")
    assert result is None

    assert MAX_UPLOAD_MB > 0, "Upload limit should be set"
    print(f"✅ OCR: rotation handler OK, max upload {MAX_UPLOAD_MB}MB")


def test_reconstruct_parsing():
    """Whitebox: version reference detection."""
    from intello.reconstruct import find_references, extract_version_num, parse_sections

    # Version number extraction
    assert extract_version_num("project_v21.md") == 21
    assert extract_version_num("version 3 draft") == 3
    assert extract_version_num("no version here") is None

    # Reference detection
    refs = find_references("This section unchanged since v21\nSee v3 for details\n(v15)")
    assert len(refs) >= 3, f"Expected 3+ refs, got {len(refs)}"
    versions_found = {r["referenced_version"] for r in refs}
    assert 21 in versions_found
    assert 3 in versions_found
    assert 15 in versions_found

    # Section parsing
    sections = parse_sections("# Intro\nSome text\n# Methods\nMore text")
    assert len(sections) == 2

    print(f"✅ Reconstruct: version parsing + refs + sections passed")


def test_craft_coverage():
    """Whitebox: all craft categories have techniques."""
    from intello.craft import FICTION_TECHNIQUES, NONFICTION_TECHNIQUES

    assert len(FICTION_TECHNIQUES) >= 6, f"Fiction categories: {len(FICTION_TECHNIQUES)}"
    assert len(NONFICTION_TECHNIQUES) >= 4, f"Non-fiction categories: {len(NONFICTION_TECHNIQUES)}"

    for cat, techniques in FICTION_TECHNIQUES.items():
        assert len(techniques) >= 2, f"Fiction/{cat} has only {len(techniques)} techniques"

    for cat, techniques in NONFICTION_TECHNIQUES.items():
        assert len(techniques) >= 2, f"Non-fiction/{cat} has only {len(techniques)} techniques"

    print(f"✅ Craft: {sum(len(t) for t in FICTION_TECHNIQUES.values())} fiction + "
          f"{sum(len(t) for t in NONFICTION_TECHNIQUES.values())} non-fiction techniques")


def test_guardrails_edge_cases():
    """Whitebox: guardrails handle edge cases."""
    from intello.guardrails import check_confidence, check_word_count, count_words

    # Empty string
    r = check_confidence("")
    assert r["confidence"] >= 0

    # Very long string
    r = check_confidence("word " * 10000)
    assert r["confidence"] >= 0

    # Word count with code blocks
    assert count_words("hello ```python\nprint('hi')\n``` world") == 2

    # Zero target
    wc = check_word_count("some text", 0)
    assert "verdict" in wc

    print("✅ Guardrails: edge cases passed")


def test_workflow_phases():
    """Whitebox: workflow phase transitions."""
    from intello.literary import create_project, update_project
    from intello.workflow import get_workflow_state

    # Empty project → outline
    create_project("wf_test_2", "Test", "fiction")
    s = get_workflow_state("wf_test_2")
    assert s["phase"] == "outline"

    # Add structure → enrich
    update_project("wf_test_2", steps=["A", "B", "C"],
                   character_arcs=[{"name": "X", "arc": "Y"}], themes=["Z"])
    s = get_workflow_state("wf_test_2")
    assert s["phase"] == "enrich"

    # Rich structure → expand
    update_project("wf_test_2",
                   steps=["A", "B", "C", "D", "E"],
                   character_arcs=[{"name": "X", "arc": "Y"}, {"name": "Z", "arc": "W"}])
    s = get_workflow_state("wf_test_2")
    assert s["phase"] == "expand"

    print(f"✅ Workflow: phase transitions outline→enrich→expand passed")


def test_provider_count():
    """Whitebox: verify provider catalog is complete."""
    from intello.research import get_providers, BASELINE_PROVIDERS
    from intello.backends import _BACKENDS
    from intello.keys import _VALIDATORS

    providers = get_providers()
    provider_types = {p.provider for p in providers}
    backend_types = set(_BACKENDS.keys())
    validator_types = set(_VALIDATORS.keys())

    # Every provider type should have a backend
    missing_backends = provider_types - backend_types
    assert not missing_backends, f"Providers without backends: {missing_backends}"

    # Every provider type should have a validator
    missing_validators = provider_types - validator_types
    assert not missing_validators, f"Providers without validators: {missing_validators}"

    print(f"✅ Providers: {len(providers)} providers, {len(backend_types)} backends, {len(validator_types)} validators — all matched")


if __name__ == "__main__":
    tests = [
        test_costs_ledger, test_jobs_system, test_speech_module,
        test_ocr_rotation, test_reconstruct_parsing, test_craft_coverage,
        test_guardrails_edge_cases, test_workflow_phases, test_provider_count,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    print(f"\nAdditional tests: {passed} passed, {failed} failed out of {len(tests)}")
    if failed:
        sys.exit(1)
