"""#43 price watch -testit: luokittelu, monotonia, suunta-konsistenssi,
sanity-gate, loader-fail-safe, endpoint-smoke. Hermeettinen (ei verkkoa)."""
from __future__ import annotations

import json

from scripts.build_fpl_price_watch import (
    MIN_THRESHOLD, build_payload, classify, sanity_gate,
)
from src.models.fpl_price_watch import empty_price_watch, load_price_watch


def _element(pid, net_in, net_out, pct, cce=0, cost=50):
    return {"id": pid, "web_name": f"P{pid}", "team": 1, "now_cost": cost,
            "transfers_in_event": net_in, "transfers_out_event": net_out,
            "selected_by_percent": str(pct), "cost_change_event": cce,
            "element_type": 3}


TOTAL = 10_000_000  # 10 % omistus → 1 000 000 omistajaa; rise-kynnys 50 000


def test_classify_statuses():
    owners = 1_000_000
    assert classify(0, owners, 0) == ("stable", 0.0, 0.0)
    # rise-kynnys = 0.05 × 1 000 000 = 50 000
    s, c, p = classify(50_000, owners, 0)
    assert s == "rising_soon" and c == 1.0 and p == 100.0
    s, _, p = classify(30_000, owners, 0)
    assert s == "rising_watch" and 50 <= p < 90
    s, _, _ = classify(10_000, owners, 0)
    assert s == "stable"
    # fall-kynnys korkeampi (0.075) → sama |net| antaa matalamman progressin
    s_fall, _, p_fall = classify(-30_000, owners, 0)
    _, _, p_rise = classify(30_000, owners, 0)
    assert p_fall < p_rise
    s, _, _ = classify(-75_000, owners, 0)
    assert s == "falling_soon"


def test_min_threshold_floor_protects_small_ownership():
    # 0 omistajaa → lattia MIN_THRESHOLD estää kohina-triggauksen
    s, _, p = classify(int(MIN_THRESHOLD * 0.4), 0, 0)
    assert s == "stable" and p < 50


def test_confidence_monotonic_in_net_event_same_ownership():
    owners = 1_000_000
    prev = -1.0
    for net in range(0, 60_000, 5_000):
        _, conf, _ = classify(net, owners, 0)
        assert conf >= prev
        prev = conf


def test_direction_consistency_clamp():
    owners = 1_000_000
    # Laski jo tänään mutta net-virta nousuun → rising sallittu; nousi tänään
    # mutta net-virta alas → falling EI sallittu (clamp stable)
    s, _, _ = classify(-75_000, owners, cost_change_event=1)
    assert not s.startswith("falling")
    s, _, _ = classify(75_000, owners, cost_change_event=-1)
    assert not s.startswith("rising")


def test_build_payload_and_sanity_gate_pass():
    bootstrap = {
        "total_players": TOTAL,
        "elements": [
            _element(1, 60_000, 5_000, 10.0),          # rising_soon
            _element(2, 32_000, 2_000, 10.0),          # rising_watch
            _element(3, 0, 80_000, 10.0),              # falling_soon
            _element(4, 0, 0, 5.0),                    # stable
            _element(5, 55_000, 0, 10.0, cce=1),       # nousi jo tänään
        ],
    }
    payload = build_payload(bootstrap)
    assert sanity_gate(payload) == []
    risers = {r["id"]: r for r in payload["risers"]}
    fallers = {r["id"]: r for r in payload["fallers"]}
    assert 1 in risers and risers[1]["status"] == "rising_soon"
    assert 2 in risers and risers[2]["status"] == "rising_watch"
    assert 3 in fallers and fallers[3]["status"] == "falling_soon"
    assert 4 not in risers and 4 not in fallers
    assert risers[5]["already_changed_today"] is True
    assert payload["meta"]["available"] is True
    assert "estimated" in payload["meta"]["disclaimer"].lower() or \
        "Estimated" in payload["meta"]["disclaimer"]


def test_build_payload_preseason_all_zero():
    bootstrap = {"total_players": TOTAL,
                 "elements": [_element(i, 0, 0, 5.0) for i in range(1, 6)]}
    payload = build_payload(bootstrap)
    assert payload["risers"] == [] and payload["fallers"] == []
    assert "note" in payload["meta"]
    assert sanity_gate(payload) == []


def test_sanity_gate_catches_bad_rows():
    payload = empty_price_watch()
    payload["meta"]["available"] = True
    payload["risers"] = [{"web_name": "X", "status": "falling_soon",
                          "net_event": -1, "confidence": 0.5, "progress_pct": 50.0}]
    assert sanity_gate(payload)


def test_loader_missing_and_broken_file(tmp_path):
    assert load_price_watch(tmp_path / "nope.json")["meta"]["available"] is False
    bad = tmp_path / "bad.json"
    bad.write_text("{roska", encoding="utf-8")
    assert load_price_watch(bad)["meta"]["available"] is False
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"meta": {"available": True}}), encoding="utf-8")
    out = load_price_watch(ok)
    assert out["meta"]["available"] is True and out["risers"] == []


def test_endpoint_smoke(client, monkeypatch):
    import src.models.fpl_price_watch as pw
    r = client.get("/api/fantasy/price-watch")
    assert r.status_code == 200
    b = r.json()
    assert "meta" in b and "risers" in b and "fallers" in b
    assert r.headers["cache-control"] == "no-store"
