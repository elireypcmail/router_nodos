from sync.jobs.ingest_event_ids import bounded_event_id, HUB_INGEST_EVENT_ID_MAX


def test_bounded_event_id_short_unchanged():
    assert bounded_event_id("sale-kardex", "123") == "sale-kardex-123"


def test_bounded_event_id_long_is_deterministic_and_within_limit():
    long_codigo = "X" * 40
    job_tag = f"sale-{'a' * 36}"
    raw = f"stock-snap-{job_tag}-{long_codigo}"
    assert len(raw) > HUB_INGEST_EVENT_ID_MAX
    out = bounded_event_id("stock-snap", job_tag, long_codigo)
    assert len(out) <= HUB_INGEST_EVENT_ID_MAX
    assert out == bounded_event_id("stock-snap", job_tag, long_codigo)
