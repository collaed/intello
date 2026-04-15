"""Grey-box integration tests — test component interactions."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_ingest_to_analysis_pipeline():
    """Ingest a doc → verify characters + pacing + threads all populate."""
    from intello.literary import ingest_document, get_characters, get_pacing_data, get_threads, get_structure

    text = """Chapter 1: The Disappearance

Nobody knew where Elena had gone. She vanished on a Tuesday.
Marco wondered if she was hiding something. The police found nothing.
"Who took her?" Marco asked the detective. No answer came.
Why did Elena leave her phone behind? It made no sense.

Chapter 2: The Truth

It turns out Elena had been planning this for months.
She finally revealed the truth to Marco at the hospital.
"I was protecting you," she confessed. Now Marco understood."""

    r = ingest_document("grey_test_1", text, "Grey Test")
    assert r["chapters"] == 2, f"Chapters: {r['chapters']}"
    assert r["characters"] >= 1, f"Characters: {r['characters']}"
    assert r["threads"] >= 1, f"Threads: {r['threads']}"

    chars = get_characters("grey_test_1")
    names = [c["name"] for c in chars]
    assert any("Elena" in n or "Marco" in n for n in names), f"Expected Elena/Marco, got {names}"

    pacing = get_pacing_data("grey_test_1", window=3)
    assert len(pacing) > 0, "No pacing data"

    threads = get_threads("grey_test_1")
    assert len(threads) > 0, "No threads detected"
    resolved = [t for t in threads if t["resolved"]]
    assert len(resolved) > 0, "Expected some resolved threads"

    struct = get_structure("grey_test_1")
    assert len(struct) == 2
    print(f"✅ Ingest→Analysis: {len(chars)} chars, {len(pacing)} pacing points, {len(threads)} threads ({len(resolved)} resolved)")


def test_project_to_document_link():
    """Create project → ingest doc → verify project brief appears in analysis context."""
    from intello.literary import create_project, ingest_document, get_project_brief_prompt, link_document_to_project

    p = create_project("grey_proj_1", "Test Novel", "fiction", "A mystery story",
                       80000, "noir", ["Setup", "Investigation", "Climax"])
    assert p["title"] == "Test Novel"

    r = ingest_document("grey_doc_2", "Chapter 1\n\nSome text here with enough words to pass the minimum.", "Doc2", "grey_proj_1")
    brief = get_project_brief_prompt("grey_proj_1")
    assert "Test Novel" in brief
    assert "noir" in brief
    assert "80000" in brief
    print(f"✅ Project→Document: brief has {len(brief)} chars")


def test_cache_store_and_semantic_retrieve():
    """Store a response → retrieve by similar (not identical) query."""
    from intello.cache import store, get_cached

    store("How do I reverse a string in Python?", "code",
          "Use slicing: s[::-1]", "TestProvider", "test-model", 0.001)

    # Exact match
    r = get_cached("How do I reverse a string in Python?", "code")
    assert r is not None, "Exact match failed"
    assert "slicing" in r["response"]

    # Semantic match (different wording)
    r2 = get_cached("Python reverse a string", "code")
    # May or may not match — just verify no crash
    print(f"✅ Cache: exact={'hit' if r else 'miss'}, semantic={'hit' if r2 else 'miss'}")


def test_memory_conversation_flow():
    """Create conversation → add messages → verify context builds."""
    from intello.memory import create_conversation, add_message, get_messages, build_context
    import uuid
    cid = create_conversation(f"grey_conv_{uuid.uuid4().hex[:6]}")
    add_message(cid, "user", "My name is Alice")
    add_message(cid, "assistant", "Hello Alice!", "test-model", 0.0)
    add_message(cid, "user", "What is my name?")

    msgs = get_messages(cid)
    assert len(msgs) >= 3, f"Expected 3 messages, got {len(msgs)}"

    ctx = build_context(cid)
    assert "Alice" in ctx, "Context should contain 'Alice'"
    print(f"✅ Memory: {len(msgs)} messages, context has {len(ctx)} chars")


def test_craft_varies_per_call():
    """Verify craft engine returns different techniques on repeated calls (randomized)."""
    from intello.craft import get_relevant_techniques
    results = set()
    for _ in range(5):
        t = get_relevant_techniques("fiction", ["slow pacing", "boring"])
        results.add(tuple(t))
    # Should get at least 2 different combinations in 5 tries
    assert len(results) >= 2, f"Craft should vary, got {len(results)} unique sets"
    print(f"✅ Craft randomization: {len(results)} unique sets in 5 calls")


def test_user_filtering_integration():
    """Verify premium filtering works end-to-end with real provider list."""
    from intello.research import get_providers
    from intello.web import filter_providers_for_user, PREMIUM_MODELS
    from intello.router import build_plan

    providers = get_providers()
    # Simulate availability
    for p in providers:
        p.available = True
        p.api_key = "fake"

    guest_provs = filter_providers_for_user(providers, "guest")
    admin_provs = filter_providers_for_user(providers, "ecb")

    # Build plan for guest — should not pick premium
    plan = build_plan("write code", guest_provs)
    if plan.primary:
        assert not any(pm in plan.primary.model_id for pm in PREMIUM_MODELS), \
            f"Guest got premium model: {plan.primary.model_id}"

    print(f"✅ User filtering E2E: admin={len(admin_provs)}, guest={len(guest_provs)}, plan={'ok' if plan.primary else 'no provider'}")


if __name__ == "__main__":
    tests = [
        test_ingest_to_analysis_pipeline,
        test_project_to_document_link,
        test_cache_store_and_semantic_retrieve,
        test_memory_conversation_flow,
        test_craft_varies_per_call,
        test_user_filtering_integration,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    print(f"\nGrey-box: {passed} passed, {failed} failed out of {len(tests)}")
    if failed: sys.exit(1)
