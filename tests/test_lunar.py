"""``studio.lunar``: the LunarCrush trend-freshness client and curve (task 18; research 2026-10-08 section 3).

No network: the hosted MCP endpoint is an ``httpx.MockTransport``, the clock and the sleep are fakes, and the Markdown answers
are fixtures in ``tests/fixtures/lunarcrush`` (SYNTHETIC: shaped on the 8 Oct capture, see their generator note in the task
report; only the anchor points are real). The key used here is a made-up string, never a real one.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from studio import lunar
from studio.lunar import LunarCrush, LunarError, LunarParseError, Row, TrendGate, parse_keyword_series, trend_curve, trend_key

FIX = Path(__file__).resolve().parent / "fixtures" / "lunarcrush"
KEY = "lc-test-key-0123456789"
D0 = date(2026, 9, 8)


def fixture(name: str) -> str:
    return (FIX / f"{name}.md").read_text(encoding="utf-8")


def series(values: list[int | None], *, start: date = D0, total: bool = False) -> list[Row]:
    """Daily rows from ``start``; ``total`` puts the numbers in the summed column only (no TikTok column)."""
    return [Row(start + timedelta(days=i), None if total else v, v if total else None) for i, v in enumerate(values)]


# ---- parsing the Markdown table ---------------------------------------------------------------------------------------------------


def test_the_30_daily_rows_of_the_capture_shape_are_parsed_by_column_name():
    rows = parse_keyword_series(fixture("keyword_time_series_single_ladies"))
    assert len(rows) == 30 and rows[0].day == date(2026, 9, 8) and rows[-1].day == date(2026, 10, 7)
    assert rows[0].tiktok == 62_000 and rows[25].tiktok == 1_156_085 and rows[-1].tiktok == 289_927
    assert rows[-1].total == 289_927 + 900 + 37 * (29 % 5) + int(289_927 * 0.08) + int(289_927 * 0.03)  # the `interactions` column


def test_columns_are_found_by_name_in_any_order_and_the_total_is_the_sum_of_networks_when_there_is_no_total_column():
    text = (
        "| instagram_interactions | tiktok_interactions | date | x_interactions |\n|---|---|---|---|\n"
        "| 10 | 1,200 | 2026-10-01 | 5 |\n| 20 | 2,400 | 2026-10-02 | N/A |\n"
    )
    rows = parse_keyword_series(text)
    assert [(r.day, r.tiktok, r.total) for r in rows] == [(date(2026, 10, 1), 1200, 1215), (date(2026, 10, 2), 2400, 2420)]


@pytest.mark.parametrize("stamp, expected", [
    ("2026-10-01T00:00:00Z", date(2026, 10, 1)), ("2026-10-01 00:00:00", date(2026, 10, 1)), ("1790812800", date(2026, 10, 1)),
    ("1790812800000", date(2026, 10, 1)),
])  # fmt: skip
def test_a_day_may_be_an_iso_date_a_datetime_or_unix_seconds_or_milliseconds(stamp, expected):
    rows = parse_keyword_series(f"| time | tiktok_interactions |\n|---|---|\n| {stamp} | 7 |\n")
    assert [r.day for r in rows] == [expected]


def test_hourly_rows_of_one_day_are_added_up_and_n_a_stays_unknown():
    text = "| time | tiktok_interactions |\n|---|---|\n| 2026-10-01 01:00 | 5 |\n| 2026-10-01 02:00 | N/A |\n| 2026-10-02 | N/A |\n"
    rows = parse_keyword_series(text)
    assert [(r.day, r.tiktok) for r in rows] == [(date(2026, 10, 1), 5), (date(2026, 10, 2), None)]


@pytest.mark.parametrize("answer", [
    "", "Limited data mode: nothing here", "| a | b |\n|---|---|\n| 1 | 2 |\n",  # no day column, no numbers
    "| time | likes |\n|---|---|\n| 2026-10-01 | 5 |\n",  # no interactions column at all
    "| time | tiktok_interactions |\n|---|---|\n| soon | many |\n",  # no readable row
])  # fmt: skip
def test_an_answer_that_is_not_the_table_is_a_parse_error_that_keeps_its_first_300_characters(answer):
    with pytest.raises(LunarParseError) as e:
        parse_keyword_series(answer)
    assert e.value.head == answer[:300]


def test_the_error_head_is_cut_at_300_characters():
    with pytest.raises(LunarParseError) as e:
        parse_keyword_series("x" * 1000)
    assert e.value.head == "x" * 300


# ---- the curve ----------------------------------------------------------------------------------------------------------------------


def test_single_ladies_on_7_oct_is_fading_four_days_past_its_peak():
    curve = trend_curve(parse_keyword_series(fixture("keyword_time_series_single_ladies")))
    assert curve.stage == "fading" and curve.days_since_peak == 4 and curve.peak_day == date(2026, 10, 3)
    assert curve.source == "tiktok" and 0.2 < curve.ratio < 0.4  # about a quarter to a third of the 3-day-smoothed peak


def test_patient_zero_on_7_oct_is_dead_nine_days_past_a_peak_it_is_a_tenth_of():
    curve = trend_curve(parse_keyword_series(fixture("keyword_time_series_patient_zero")))
    assert curve.stage == "dead" and curve.days_since_peak == 9 and curve.peak_day == date(2026, 9, 28) and curve.ratio < 0.2


def test_a_trend_still_climbing_at_its_peak_is_rising():
    curve = trend_curve(series([1000, 1100, 1200, 1500, 2500, 4000, 7000, 11_000, 16_000, 24_000]))
    assert (curve.stage, curve.days_since_peak, curve.peak_day) == ("rising", 0, D0 + timedelta(days=9))


def test_a_peak_a_day_ago_that_is_no_longer_climbing_is_a_peak():
    curve = trend_curve(series([1000, 1200, 2000, 5000, 10_000, 40_000, 45_000, 30_000]))
    assert (curve.stage, curve.days_since_peak) == ("peak", 1)


def test_the_peak_within_seven_days_is_fading_even_when_the_day_has_fallen_far():
    curve = trend_curve(series([100] * 8 + [50_000, 90_000, 100_000, 60_000, 20_000, 9000, 4000, 1000]))
    assert curve.stage == "fading" and curve.days_since_peak == 5 and curve.ratio < 0.5


def test_a_latest_day_at_half_of_a_peak_over_a_week_old_is_still_fading():
    curve = trend_curve(series([1000, 3000, 50_000, 100_000, 60_000] + [58_000] * 12))
    assert curve.days_since_peak > 7 and curve.ratio >= 0.5 and curve.stage == "fading"


def test_a_peak_over_a_week_old_and_under_half_is_dead():
    curve = trend_curve(series([1000, 3000, 50_000, 100_000, 60_000, 30_000] + [20_000] * 11))
    assert curve.days_since_peak > 7 and curve.ratio < 0.5 and curve.stage == "dead"


def test_a_small_climb_far_below_an_old_peak_is_not_rising():
    values = [10_000, 100_000, 500_000, 400_000, 300_000, 200_000, 150_000, 100_000, 60_000, 30_000, 20_000, 22_000, 25_000, 29_000]
    assert trend_curve(series(values)).stage == "dead"  # climbing, but not near the peak and the peak is 11 days old


def test_gaps_in_the_days_count_as_nothing_posted():
    rows = [Row(D0, 100, None), Row(D0 + timedelta(days=1), 100, None), Row(D0 + timedelta(days=10), 90_000, None)]
    curve = trend_curve(rows)
    assert curve.peak_day == D0 + timedelta(days=10) and len(curve.smoothed) == 11


def test_a_series_that_stops_long_before_yesterday_is_read_as_of_yesterday_so_a_dead_small_trend_is_not_a_peak():
    rows = series([100, 200, 5000, 30_000, 12_000, 6000])  # 8 to 13 Sep, the peak on 11 and 12 Sep; nothing sampled since
    assert (trend_curve(rows).stage, trend_curve(rows).days_since_peak) == ("peak", 1)  # as of its last row: the old reading
    curve = trend_curve(rows, as_of=date(2026, 10, 6))  # read on 7 Oct: yesterday is 6 Oct
    assert curve.stage == "dead" and curve.days_since_peak == 24 and curve.peak_day == date(2026, 9, 12) and curve.ratio < 0.01
    assert curve.smoothed[-1][0] == date(2026, 10, 6)  # padded with days of nothing up to yesterday
    assert curve.padded == 23 and trend_curve(rows).padded == 0  # the 23 days from 13 Sep to 6 Oct are not real rows


def test_a_part_day_dated_after_as_of_is_left_out_so_it_cannot_turn_rising_into_fading():
    values = [1000, 1100, 1200, 1500, 2500, 4000, 7000, 11_000, 16_000, 24_000]
    yesterday = D0 + timedelta(days=len(values) - 1)
    full = series(values)
    with_today = [*full, Row(yesterday + timedelta(days=1), 400, None), Row(yesterday + timedelta(days=2), 9, None)]  # today's part day and a later one
    assert trend_curve(full, as_of=yesterday).stage == "rising"
    assert trend_curve(with_today, as_of=yesterday) == trend_curve(full, as_of=yesterday)  # the rows after as_of are not in it
    assert trend_curve(with_today).stage != "rising"  # without as_of the rows are read as they come, as before


def test_a_lag_of_two_days_is_not_stale_but_three_days_is():
    values = [1000, 1100, 1200, 1500, 2500, 4000, 7000, 11_000, 16_000, 24_000]
    assert D0 + timedelta(days=len(values) - 1) == date(2026, 9, 17)  # the last row
    assert trend_curve(series(values), as_of=date(2026, 9, 19)) == trend_curve(series(values))  # two days behind: LunarCrush's usual lag
    assert trend_curve(series(values), as_of=date(2026, 9, 20)).stage != "rising"  # three days: the trend has stopped being sampled
    assert trend_curve(series(values), as_of=date(2026, 9, 1)) is None  # every row is dated after as_of: nothing to read


def test_the_summed_total_stands_in_when_the_answer_has_no_tiktok_column():
    curve = trend_curve(series([1000, 1100, 1200, 1500, 2500, 4000, 7000, 11_000, 16_000, 24_000], total=True))
    assert curve.source == "total" and curve.stage == "rising"


def test_no_signal_or_too_few_days_is_no_curve_at_all():
    assert trend_curve(series([0] * 20)) is None  # nothing tracked is not a dead trend: unknown
    assert trend_curve(series([5, 900])) is None
    assert trend_curve([]) is None
    assert trend_curve(series([None] * 10)) is None


def test_the_curve_is_the_same_whatever_the_order_the_rows_came_in():
    rows = series([100, 100, 100, 400, 900, 2500, 6000, 9000])
    assert trend_curve(list(reversed(rows))) == trend_curve(rows)


# ---- the trend key ------------------------------------------------------------------------------------------------------------------


NAMES = ["dog dance", "dachshund", "halloween"]


def test_the_sound_is_the_key_unless_it_is_generic():
    assert trend_key("Patient Zero", "caption #fyp", NAMES) == ("patient zero", "sound")
    assert trend_key("  Single   Ladies (Put a Ring on It) ", None, NAMES) == ("single ladies (put a ring on it)", "sound")


@pytest.mark.parametrize("generic", [
    "original sound - dancer1", "Original Sound", "original audio", "Original audio", "son original - maria", "", None, "   ",
])  # fmt: skip
def test_a_generic_sound_falls_back_to_a_trend_name_in_the_caption(generic):
    assert trend_key(generic, "my dachshund doing the thing", NAMES) == ("dachshund", "caption")


def test_a_hashtag_counts_as_the_trend_name_and_the_first_name_in_the_list_wins():
    assert trend_key("original sound - x", "so cute #dogdance #halloween", NAMES) == ("dog dance", "caption")
    assert trend_key(None, "Halloween dachshund", NAMES) == ("dachshund", "caption")  # the list's order, not the caption's


def test_a_name_must_be_a_whole_word_and_no_key_is_none():
    assert trend_key(None, "the dachshunds are back", ["dachshund"]) is None
    assert trend_key(None, "nothing here", NAMES) is None
    assert trend_key(None, None, NAMES) is None
    assert trend_key("Patient Zero", "x", []) == ("patient zero", "sound")


def test_the_events_file_is_optional_and_read_as_plain_list_lines(tmp_path):
    assert lunar.event_names(tmp_path / "events.yaml") == []
    path = tmp_path / "events.yaml"
    path.write_text("# events\n- halloween\n- name: paris fashion week\n  from: 2026-10-01\nfinals: nba finals\n- 'black friday'\n", encoding="utf-8")
    assert lunar.event_names(path) == ["halloween", "paris fashion week", "black friday"]


# ---- the client: the hosted MCP endpoint over streamable HTTP ---------------------------------------------------------------------------


class Clock:
    """A fake monotonic clock whose sleep moves it; ``slept`` records every wait."""

    def __init__(self) -> None:
        self.now, self.slept = 1000.0, []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


TABLE = "| time | tiktok_interactions |\n|---|---|\n| 2026-10-01 | 5 |\n"


def rpc_text(text: str, id_: int = 1, *, is_error: bool = False) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": {"content": [{"type": "text", "text": text}], "isError": is_error}}


class McpServer:
    """The endpoint as an ``httpx.MockTransport``: initialize (with a session id), the initialized notification, then ``tools/call``
    answered from a queue (a dict, an int HTTP status, an ``httpx.Response`` or a callable)."""

    def __init__(self, clock: Clock | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict] = []
        self.answers: list = []
        self.call_times: list[float] = []
        self.init_answers: list = []  # answers for `initialize`, first come first served (an int HTTP status, an httpx.Response)
        self.init_times: list[float] = []
        self.delay = 0.0  # seconds an answer takes on the fake clock
        self.clock = clock

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        self.bodies.append(body)
        method = body.get("method")
        if method == "initialize":
            if self.clock is not None:
                self.init_times.append(self.clock.now)
                self.clock.now += self.delay
            if self.init_answers:
                answer = self.init_answers.pop(0)
                return httpx.Response(answer, json={"error": "nope"}) if isinstance(answer, int) else answer
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "lunar", "version": "1"}}
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result}, headers={"Mcp-Session-Id": "sess-1"})
        if method == "notifications/initialized":
            return httpx.Response(202)
        assert method == "tools/call", method
        if self.clock is not None:
            self.call_times.append(self.clock.now)
            self.clock.now += self.delay
        answer = self.answers.pop(0) if self.answers else rpc_text(TABLE)
        if callable(answer):
            answer = answer(request)
        if isinstance(answer, httpx.Response):
            return answer
        if isinstance(answer, int):
            return httpx.Response(answer, json={"error": "nope"})
        return httpx.Response(200, json={**answer, "id": body["id"]})

    def client(self, clock: Clock | None = None, **kw) -> LunarCrush:
        clock = clock or self.clock or Clock()
        return LunarCrush(KEY, http=httpx.Client(transport=httpx.MockTransport(self)), clock=clock, sleep=clock.sleep, **kw)

    def tool_calls(self) -> list[dict]:
        return [b for b in self.bodies if b.get("method") == "tools/call"]


def test_the_client_shakes_hands_once_then_calls_the_tool_with_the_key_and_the_session():
    server = McpServer()
    client = server.client()
    assert client.keyword_time_series("single ladies") == TABLE
    assert client.keyword_time_series("patient zero") == TABLE
    assert [b["method"] for b in server.bodies] == ["initialize", "notifications/initialized", "tools/call", "tools/call"]
    init, ready, first, second = server.requests[0], server.requests[1], server.requests[2], server.requests[3]
    assert {r.url for r in server.requests} == {httpx.URL("https://lunarcrush.ai/mcp")} and init.method == "POST"
    for r in server.requests:
        assert r.headers["authorization"] == f"Bearer {KEY}"
        assert "application/json" in r.headers["accept"] and "text/event-stream" in r.headers["accept"]
    assert "mcp-session-id" not in init.headers and ready.headers["mcp-session-id"] == "sess-1"
    assert first.headers["mcp-session-id"] == second.headers["mcp-session-id"] == "sess-1"
    assert server.bodies[0]["params"]["protocolVersion"] and server.bodies[0]["params"]["clientInfo"]["name"]
    assert server.tool_calls()[0]["params"] == {
        "name": "keyword_time_series", "arguments": {"keyword": "single ladies", "interval": "1m", "network": "tiktok"},
    }
    assert server.tool_calls()[0]["id"] != server.tool_calls()[1]["id"] and client.calls == 2


def test_an_event_stream_answer_is_read_like_a_json_one():
    server = McpServer()
    stream = f"event: message\ndata: {json.dumps(rpc_text(TABLE, 2))}\n\n"
    server.answers.append(httpx.Response(200, text=stream, headers={"content-type": "text/event-stream"}))
    assert server.client().keyword_time_series("x") == TABLE


def test_calls_are_16_seconds_apart_so_that_four_make_a_minute():
    clock = Clock()
    server = McpServer(clock)
    client = server.client(clock)
    for word in ("a", "b", "c", "d"):
        client.keyword_time_series(word)
    gaps = [b - a for a, b in zip(server.call_times, server.call_times[1:])]
    assert gaps == [16.0, 16.0, 16.0] and clock.slept == [16.0] * 4  # the handshake went first, so even the first call waits 16 s
    clock.now += 100  # a long pause between two calls needs no extra wait
    client.keyword_time_series("e")
    assert clock.slept == [16.0] * 4


def test_the_spacing_is_measured_from_the_end_of_the_previous_request_so_a_slow_answer_cannot_bunch_the_next_ones():
    clock = Clock()
    server = McpServer(clock)
    server.delay = 7.0  # every answer takes 7 s
    client = server.client(clock)
    for word in ("a", "b", "c"):
        client.keyword_time_series(word)
    gaps = [b - a for a, b in zip(server.call_times, server.call_times[1:])]
    assert gaps == [23.0, 23.0]  # 7 s of answer, then the 16 s: start to start would have been 16


def test_the_handshake_is_paced_like_a_call_and_the_first_call_waits_for_it():
    clock = Clock()
    server = McpServer(clock)
    server.delay = 3.0
    client = server.client(clock)
    client.keyword_time_series("a")
    assert server.call_times[0] - (server.init_times[0] + 3.0) == 16.0  # 16 s after the handshake's answer
    assert client.calls == 1  # the handshake itself is not a counted call


def test_a_second_handshake_after_a_failed_one_waits_the_spacing_too():
    clock = Clock()
    server = McpServer(clock)
    server.init_answers.append(503)  # not a refusal: only the spacing applies
    client = server.client(clock)
    with pytest.raises(LunarError):
        client.keyword_time_series("a")
    client.keyword_time_series("a")
    assert server.init_times[1] - server.init_times[0] == 16.0


def test_the_daily_cap_stops_the_calls_before_the_endpoint_is_asked_again():
    server = McpServer()
    client = server.client(cap=2)
    client.keyword_time_series("a")
    client.keyword_time_series("b")
    with pytest.raises(LunarError) as e:
        client.keyword_time_series("c")
    assert "cap" in str(e.value) and len(server.tool_calls()) == 2 and client.calls == 2


@pytest.mark.parametrize("refusal", [
    429, rpc_text("Rate limit exceeded: 4 calls a minute", is_error=True),
    {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "rate limit reached for this key"}},
])  # fmt: skip
def test_a_refused_call_still_counts_is_not_retried_and_the_next_call_waits_out_the_minute(refusal):
    clock = Clock()
    server = McpServer(clock)
    server.answers.append(refusal)
    client = server.client(clock)
    with pytest.raises(LunarError) as e:
        client.keyword_time_series("a")
    assert e.value.refused is True and client.calls == 1 and len(server.tool_calls()) == 1  # no retry in the same minute
    client.keyword_time_series("b")
    assert server.call_times[1] - server.call_times[0] == 60.0  # the next call is a minute on, not 16 s


def test_a_rate_limit_that_arrives_as_an_ordinary_answer_is_a_refusal_too():
    clock = Clock()
    server = McpServer(clock)
    server.answers.append(rpc_text("Rate limit exceeded. Please wait a minute before asking again."))  # a 200, not isError, no table
    client = server.client(clock)
    with pytest.raises(LunarError) as e:
        client.keyword_time_series("a")
    assert e.value.refused is True and client.calls == 1
    client.keyword_time_series("b")
    assert server.call_times[1] - server.call_times[0] == 60.0  # the minute is waited out, as for any refusal


def test_two_such_answers_in_a_row_stop_the_client_and_the_gate_says_unknown():
    server = McpServer()
    server.answers += [rpc_text("Too many requests, slow down"), rpc_text("Rate limit exceeded")]
    gate = gate_for(server)
    assert gate.read("a").stage == "unknown" and gate.read("b").stage == "unknown" and gate.read("c").stage == "unknown"
    assert len(server.tool_calls()) == 2 and "stopped" in gate.read("d").reason  # the third key is not even asked


def test_an_answer_with_a_table_that_mentions_the_rate_limit_is_not_a_refusal():
    server = McpServer()
    server.answers.append(rpc_text("Rate Limit Minute: 3/4\nRate Limit Day: 12/100\n\n" + TABLE))
    client = server.client()
    assert "Rate Limit Day" in client.keyword_time_series("a") and client._refusals == 0


@pytest.mark.parametrize("header, waited", [("120", 120.0), ("5", 60.0), ("99999", 300.0), ("soon", 60.0), (None, 60.0)])
def test_a_429_with_retry_after_waits_that_long_never_less_than_a_minute_and_never_more_than_five(header, waited):
    clock = Clock()
    server = McpServer(clock)
    server.answers.append(httpx.Response(429, json={"error": "slow"}, headers={"Retry-After": header} if header else {}))
    client = server.client(clock)
    with pytest.raises(LunarError):
        client.keyword_time_series("a")
    client.keyword_time_series("b")
    assert server.call_times[1] - server.call_times[0] == waited


def test_two_refusals_in_a_row_stop_the_client_for_the_run():
    server = McpServer()
    server.answers += [429, 429]
    client = server.client()
    for word in ("a", "b"):
        with pytest.raises(LunarError):
            client.keyword_time_series(word)
    with pytest.raises(LunarError) as e:
        client.keyword_time_series("c")
    assert "stopped" in str(e.value) and len(server.tool_calls()) == 2 and client.calls == 2


def test_a_refused_key_stops_the_client_at_once():
    server = McpServer()
    server.answers.append(401)
    client = server.client()
    with pytest.raises(LunarError) as e:
        client.keyword_time_series("a")
    assert e.value.status == 401
    with pytest.raises(LunarError):
        client.keyword_time_series("b")
    assert len(server.tool_calls()) == 1


def test_a_refused_handshake_is_accounted_like_a_refused_call_and_the_next_try_waits_the_minute():
    clock = Clock()
    server = McpServer(clock)
    server.init_answers.append(429)
    client = server.client(clock)
    with pytest.raises(LunarError) as e:
        client.keyword_time_series("a")
    assert e.value.refused is True and client.calls == 0 and client._refusals == 1 and server.tool_calls() == []
    client.keyword_time_series("a")  # a new handshake, a minute after the refusal, then the call
    assert server.init_times[1] - server.init_times[0] == 60.0 and len(server.tool_calls()) == 1


def test_a_handshake_that_says_rate_limit_counts_and_two_in_a_row_stop_the_client():
    limit = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "Rate limit exceeded"}}
    server = McpServer()
    server.init_answers += [httpx.Response(200, json=limit), httpx.Response(200, json={**limit, "id": 2})]
    client = server.client()
    for word in ("a", "b"):
        with pytest.raises(LunarError):
            client.keyword_time_series(word)
    with pytest.raises(LunarError) as e:
        client.keyword_time_series("c")
    assert "stopped" in str(e.value) and [b["method"] for b in server.bodies] == ["initialize", "initialize"]


def test_a_server_error_on_the_handshake_is_an_error_but_not_a_refusal():
    server = McpServer()
    server.init_answers.append(503)
    client = server.client()
    with pytest.raises(LunarError) as e:
        client.keyword_time_series("a")
    assert e.value.status == 503 and e.value.refused is False and client._refusals == 0


def test_a_failed_handshake_is_an_error_and_not_a_counted_call():
    def refuse(request):
        return httpx.Response(403, text=f"bad key {KEY}")

    client = LunarCrush(KEY, http=httpx.Client(transport=httpx.MockTransport(refuse)), clock=Clock(), sleep=lambda s: None)
    with pytest.raises(LunarError) as e:
        client.keyword_time_series("a")
    assert e.value.status == 403 and client.calls == 0 and KEY not in str(e.value)


def test_a_dropped_connection_is_an_error_without_the_key():
    def boom(request):
        raise httpx.ConnectError(f"cannot reach with {KEY}")

    client = LunarCrush(KEY, http=httpx.Client(transport=httpx.MockTransport(boom)), clock=Clock(), sleep=lambda s: None)
    with pytest.raises(LunarError) as e:
        client.keyword_time_series("a")
    assert KEY not in str(e.value) and "ConnectError" in str(e.value)


def test_the_key_is_never_in_the_repr_or_an_error():
    server = McpServer()
    server.answers.append(rpc_text(f"the key {KEY} was refused", is_error=True))
    client = server.client()
    assert KEY not in repr(client)
    with pytest.raises(LunarError) as e:
        client.keyword_time_series("a")
    assert KEY not in str(e.value)


def test_the_key_comes_from_the_environment_only():
    assert LunarCrush.from_env({}) is None and LunarCrush.from_env({"LUNARCRUSH_API_KEY": "  "}) is None
    assert isinstance(LunarCrush.from_env({"LUNARCRUSH_API_KEY": KEY}), LunarCrush)
    with pytest.raises(ValueError):
        LunarCrush("")


# ---- the gate: one check per key, and every failure is "unknown" ---------------------------------------------------------------------


def gate_for(server: McpServer, **kw) -> TrendGate:
    return TrendGate(server.client(**kw))


def test_a_gate_without_a_key_answers_unknown_and_calls_nothing():
    gate = TrendGate(None)
    reading = gate.read("single ladies")
    assert gate.enabled is False and reading.stage == "unknown" and reading.days_since_peak is None and "LUNARCRUSH_API_KEY" in reading.reason


def test_the_gate_reads_the_curve_and_asks_once_per_key():
    server = McpServer()
    server.answers.append(rpc_text(fixture("keyword_time_series_single_ladies")))
    gate = gate_for(server)
    first = gate.read("Single  Ladies")
    again = gate.read("single ladies")
    assert (first.stage, first.days_since_peak) == ("fading", 4) and again == first
    assert len(server.tool_calls()) == 1 and gate.summary()["keys"] == 1


def test_the_gate_says_unknown_for_a_refusal_a_cap_and_an_answer_it_cannot_read_and_remembers_it():
    server = McpServer()
    server.answers += [429, rpc_text("no table today")]
    gate = gate_for(server, cap=2)
    assert gate.read("a").stage == "unknown" and gate.read("b").stage == "unknown" and gate.read("c").stage == "unknown"
    assert gate.read("a").stage == "unknown" and len(server.tool_calls()) == 2  # "c" hit the cap; "a" is cached
    assert gate.summary()["stages"] == {"unknown": 3}


def test_an_unreadable_answer_is_logged_with_its_first_300_characters_and_never_the_key(caplog):
    server = McpServer()
    server.answers.append(rpc_text("Y" * 500 + KEY))
    with caplog.at_level(logging.WARNING, logger="studio.lunar"):
        reading = gate_for(server).read("a")
    assert reading.stage == "unknown"
    assert ("Y" * 300) in caplog.text and ("Y" * 301) not in caplog.text and KEY not in caplog.text


def test_a_refusal_is_logged_without_the_key(caplog):
    server = McpServer()
    server.answers.append(rpc_text(f"nope {KEY}", is_error=True))
    with caplog.at_level(logging.WARNING, logger="studio.lunar"):
        gate_for(server).read("a")
    assert "nope" in caplog.text and KEY not in caplog.text


def test_a_day_cell_the_clock_cannot_hold_is_unknown_not_an_exception(caplog):
    server = McpServer()
    server.answers.append(rpc_text("| time | tiktok_interactions |\n|---|---|\n| 99999999999999999999 | 5 |\n"))  # OSError in fromtimestamp
    with caplog.at_level(logging.WARNING, logger="studio.lunar"):
        reading = gate_for(server).read("a")
    assert reading.stage == "unknown" and "could not be read" in reading.reason
    assert "99999999999999999999" not in caplog.text  # the type of the error, never the answer


def test_whatever_goes_wrong_while_reading_an_answer_is_unknown(monkeypatch):
    server = McpServer()
    monkeypatch.setattr(lunar, "trend_curve", lambda rows, as_of=None: (_ for _ in ()).throw(RuntimeError("boom")))
    assert gate_for(server).read("a").stage == "unknown"


def test_a_series_that_stopped_is_unknown_never_dead_because_missing_rows_may_be_a_data_lag():
    server = McpServer()
    stopped = "| time | tiktok_interactions |\n|---|---|\n" + "".join(
        f"| 2026-09-{8 + i:02d} | {v} |\n" for i, v in enumerate([100, 200, 5000, 30_000, 12_000, 6000])
    )  # 8 to 13 Sep: padded to 6 Oct it would read dead
    server.answers += [rpc_text(stopped), rpc_text(fixture("keyword_time_series_patient_zero"))]
    gate = gate_for(server)
    stale = gate.read("small dance", as_of=date(2026, 10, 6))
    assert stale.stage == "unknown" and stale.ratio is None and "stopped" in stale.reason and "23 days" in stale.reason
    real = gate.read("patient zero", as_of=date(2026, 10, 7))  # the series ends on 7 Oct: nothing padded, a real dead trend
    assert (real.stage, real.days_since_peak) == ("dead", 9) and real.ratio < 0.2
    assert gate.summary()["stages"] == {"unknown": 1, "dead": 1}


def test_the_summary_counts_stages_and_calls():
    server = McpServer()
    server.answers += [rpc_text(fixture("keyword_time_series_single_ladies")), rpc_text(fixture("keyword_time_series_patient_zero"))]
    gate = gate_for(server)
    gate.read("single ladies")
    gate.read("patient zero")
    assert gate.summary() == {"enabled": True, "keys": 2, "calls": 2, "stages": {"dead": 1, "fading": 1}}
    assert TrendGate(None).summary() == {"enabled": False, "keys": 0, "calls": 0, "stages": {}}
