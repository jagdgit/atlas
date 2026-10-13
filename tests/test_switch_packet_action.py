"""A switch recommendation is recorded as SELL only when it can execute now (2026-10-13 01:32 IST noise)."""

from atlas.workers.paper_trading import switch_packet_action


def test_session_closed_switch_is_recorded_as_hold_with_reason():
    sell, why = switch_packet_action("switch", session_open=False, execute=True, switched=0, max_switches=1)
    assert sell is False and why == ["switch_not_executed:session_closed"]


def test_executable_switch_is_sell():
    assert switch_packet_action("switch", session_open=True, execute=True, switched=0, max_switches=1) == (True, [])


def test_tick_cap_and_disabled_execution_are_holds():
    sell, why = switch_packet_action("switch", session_open=True, execute=False, switched=1, max_switches=1)
    assert sell is False
    assert why == ["switch_not_executed:execute_disabled", "switch_not_executed:max_switches_per_tick"]


def test_non_switch_decision_is_plain_hold():
    assert switch_packet_action("hold", session_open=False, execute=True, switched=0, max_switches=1) == (False, [])
