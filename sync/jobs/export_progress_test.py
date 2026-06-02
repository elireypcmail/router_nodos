from sync.jobs.export_progress import should_tick_export_loop


def test_tick_first_and_last():
    ticks = [
        i
        for i in range(1, 101)
        if should_tick_export_loop(written=i, total=100)
    ]
    assert ticks[0] == 1
    assert ticks[-1] == 100
    assert 50 in ticks
    assert 51 not in ticks


def test_tick_every_50_mid():
    assert should_tick_export_loop(written=50, total=200)
    assert not should_tick_export_loop(written=49, total=200)
