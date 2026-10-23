"""Judge defects: replay, held lots, bottleneck copy, free text, tardiness."""

from __future__ import annotations

from resilimes.agents.orchestrator import RecoverInput, run_recovery
from resilimes.config import HORIZON, Settings
from resilimes.domain.gantt import shared_window
from resilimes.engines.scout.engine import default_scout

SECRET = "honesty-secret"


def _report(scenario: str | None = None, incident: str | None = None) -> object:
    return run_recovery(
        Settings(mode="mock", horizon=HORIZON, scout_signing_secret=SECRET),
        RecoverInput(scenario=scenario, incident=incident),
    )


def test_litho_commit_replays_the_assigned_jobs() -> None:
    report = _report("litho_down")
    world = report.world_model  # type: ignore[attr-defined]
    assert world["events"] > world["replay_jobs"] > 0
    replayed = {row["id"]: row for row in world["replayed"]}
    assert replayed
    for row in replayed.values():
        assert row["type"] == "job"
        assert row["equipmentId"]
        assert row["step"]
    moved = next(row for row in replayed.values() if row["id"] == "LOT-1001")
    assert moved["equipmentId"] == "LITHO-01"
    assert moved["step"] == "LITHO"


def test_stockout_and_qtime_do_not_claim_a_fed_bottleneck() -> None:
    banned = ("bottleneck fed", "保住了", "ボトルネック")
    for scenario in ("material_shortage", "qtime"):
        report = _report(scenario)
        for lang in ("en", "zh", "ja"):
            brief = report.brief[lang]  # type: ignore[attr-defined]
            text = " ".join([brief["headline"], *brief["points"], brief["detail"]])
            assert not any(phrase in text for phrase in banned), text
    litho = _report("litho_down")
    assert "bottleneck fed" in litho.brief["en"]["detail"] or "bottleneck fed" in " ".join(  # type: ignore[attr-defined]
        litho.brief["en"]["points"]  # type: ignore[attr-defined]
    )


def test_held_lots_are_on_the_after_gantt_and_do_not_stretch_it() -> None:
    report = _report("material_shortage")
    after = report.gantt["after"]  # type: ignore[attr-defined]
    held = [bar for row in after["rows"] for bar in row["bars"] if bar.get("held")]
    ids = {bar["job_id"] for bar in held}
    assert ids == set(report.kpis["after"]["unscheduled_lots"])  # type: ignore[attr-defined]
    assert all(bar["end_min"] == bar["start_min"] for bar in held)
    assert all(bar["reason"] for bar in held)
    window = report.gantt["window"]  # type: ignore[attr-defined]
    assert window["end_min"] < 24 * 60
    assert window == shared_window(report.gantt["before"], after)  # type: ignore[attr-defined]
    qtime = _report("qtime")
    q_held = [
        bar["job_id"]
        for row in qtime.gantt["after"]["rows"]  # type: ignore[attr-defined]
        for bar in row["bars"]
        if bar.get("held")
    ]
    assert set(q_held) == set(qtime.kpis["after"]["unscheduled_lots"])  # type: ignore[attr-defined]


def test_held_lots_are_not_charged_a_fake_day_count() -> None:
    report = _report("material_shortage")
    before = report.kpis["before"]  # type: ignore[attr-defined]
    after = report.kpis["after"]  # type: ignore[attr-defined]
    assert after["on_time_delivery_pct"] < before["on_time_delivery_pct"]
    assert after["lots_at_risk"] > before["lots_at_risk"]
    assert after["weighted_tardiness_min"] == before["weighted_tardiness_min"]
    assert after["weighted_tardiness_min"] == 0
    text = " ".join(report.brief["en"]["points"])  # type: ignore[attr-defined]
    assert "replenished" in text
    assert "12 d" not in text
    assert "12 d" not in report.brief["en"]["detail"]  # type: ignore[attr-defined]
    qtime = _report("qtime")
    assert (
        qtime.kpis["after"]["weighted_tardiness_min"]
        == qtime.kpis["before"]["weighted_tardiness_min"]
    )  # type: ignore[attr-defined]
    q_text = " ".join(qtime.brief["en"]["points"] + [qtime.brief["en"]["detail"]])  # type: ignore[attr-defined]
    assert "4 d" not in q_text
    assert "finish time" in q_text


def test_free_text_names_the_tool_in_en_zh_ja() -> None:
    scout = default_scout(signing_secret=SECRET, clock=lambda: HORIZON)
    phrases = (
        ("ETCH-02 down, 300 min", 300),
        ("Machine ETCH-02 Down, repair ETA 300 minutes", 300),
        ("ETCH-02 is offline for 5 hours", 300),
        ("ETCH-02 宕机, 维修 300 分钟", 300),
        ("刻蚀 ETCH-02 停机 300分钟", 300),
        ("ETCH-02 が停止、修理 300分", 300),
        ("ETCH-02 ダウン 300分", 300),
    )
    for phrase, minutes in phrases:
        decision = scout.decide(
            {"prompt": phrase, "user": {"id": "u", "role": "planner"}, "surface": "mes_console"}
        )
        assert decision.intent["primary"] == "plant.machine_down", phrase
        assert decision.intent["parameters"]["equipment_id"] == "ETCH-02", phrase
        assert decision.intent["parameters"]["repair_min"] == minutes, phrase
        report = _report(incident=phrase)
        for lang in ("en", "zh", "ja"):
            headline = report.brief[lang]["headline"]  # type: ignore[attr-defined]
            assert "ETCH-02" in headline, (phrase, lang, headline)
            assert "LITHO" not in headline
        assert (
            "ETCH-02" in report.verdict["rationale"]
            or "ETCH-02"
            in (  # type: ignore[attr-defined]
                report.rejected_alternative["critique"]["violations"][0]["detail"]  # type: ignore[attr-defined]
            )
        )
        moved = report.kpis["lots_moved"]  # type: ignore[attr-defined]
        assert "LOT-1001" not in moved
        etch = [
            bar
            for row in report.gantt["after"]["rows"]  # type: ignore[attr-defined]
            for bar in row["bars"]
            if bar.get("moved") and row["area"] == "Etch"
        ]
        assert etch, phrase
        down = next(
            row
            for row in report.gantt["after"]["rows"]  # type: ignore[attr-defined]
            if row["equipment_id"] == "ETCH-02"
        )
        assert down["status"] == "DOWN"
        assert down["available_at_min"] == minutes
