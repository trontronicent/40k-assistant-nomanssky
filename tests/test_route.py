"""Tests for the route planner, its form and the plan_route action."""

import asyncio

from nms_connector import create_plugin, planets_view, route
from nms_connector.history import PlanetHistory
from test_connector import FakeCtx


def key(x, y, z, system=1, galaxy_index=0):
    return (x & 0xFFF) | (z & 0xFFF) << 12 | (y & 0xFF) << 24 | galaxy_index << 32 | system << 40


ORIGIN, TARGET = key(0, 0, 0), key(10, 0, 0)


def test_portal_addresses_become_system_keys():
    """A portal address (12 hex glyphs, spaces or dashes allowed) names a system in your galaxy; anything else
    is refused."""
    assert route.portal_to_key("006202925E80", 0) == 0x620002925E80
    assert route.portal_to_key("0062 0292-5E80", 1) == 0x620002925E80 | 1 << 32
    assert route.portal_to_key("XYZ", 0) is None and route.portal_to_key("0062029", 0) is None


def test_jumps_round_up_and_never_drop_below_one():
    """A leg needs ceil(distance / range) jumps, at least one (even inside one region)."""
    assert route.jumps_for(0, 1000) == 1 and route.jumps_for(1000, 1000) == 1 and route.jumps_for(1001, 1000) == 2
    assert route.jumps_for(None, 1000) is None


def test_known_systems_are_used_when_they_cost_no_extra_jump():
    """With known systems in reach the route hops between them (no jump into unknown space); without them the
    same number of jumps crosses unknown space with the regions to aim for."""
    via = route.plan_route([key(4, 0, 0, 5), key(7, 0, 0, 6)], ORIGIN, TARGET, 1600)
    assert via["ok"] and via["jumps"] == 3 and via["unknown_jumps"] == 0 and len(via["legs"]) == 3
    alone = route.plan_route([], ORIGIN, TARGET, 1600)
    assert alone["jumps"] == 3 and alone["unknown_jumps"] == 2 and alone["legs"][0]["waypoints"] == [(3, 0, 0), (7, 0, 0)]
    assert alone["direct_jumps"] == 3 and alone["direct_distance"] == 4000


def test_a_detour_that_costs_an_extra_jump_is_not_taken():
    """A known system off the straight line that would need one more jump is skipped."""
    plan = route.plan_route([key(5, 0, 8, 3)], ORIGIN, TARGET, 4000)
    assert plan["jumps"] == 1 and [leg["to"] for leg in plan["legs"]] == [TARGET]


def test_impossible_routes_explain_why():
    """Same system, another galaxy and a non-positive range each give a reason instead of a route."""
    assert "already in that system" in route.plan_route([], ORIGIN, ORIGIN, 1000)["reason"]
    assert "another galaxy" in route.plan_route([], ORIGIN, key(1, 0, 0, galaxy_index=2), 1000)["reason"]
    assert "positive" in route.plan_route([], ORIGIN, TARGET, 0)["reason"]


class Live:
    status, error, current, current_source = "ok", None, None, "planets"
    current_system = ORIGIN


class Texts:
    def lookup(self, item_id):
        return None

    def icon_name(self, item_id):
        return None

    def text(self, key):
        return None


def test_route_tab_shows_the_form_and_the_planned_route(tmp_path):
    """The Route tab offers a form (target from your known systems, portal address, jump range - prefilled with
    the last request) and, after planning, a summary, the legs and the route on a map."""
    visits = {TARGET: {"name": "Far Away", "planets": {}}, key(4, 0, 0, 5): {"name": "Stop A", "planets": {}}}
    ctx = planets_view.Context(Live(), PlanetHistory(tmp_path / "h.json"), visits, Texts(), None)
    plan = route.plan_route(planets_view.route_nodes(ctx), ORIGIN, TARGET, 1600)
    state = {"request": {"target": f"{TARGET:x}", "portal": "", "range": 1600}, "result": plan}
    form, summary, legs, routemap = planets_view.route_sections(ctx, state)
    assert form["type"] == "form" and form["action"] == planets_view.PLAN_ROUTE
    fields = {f["id"]: f for f in form["fields"]}
    assert fields["target"]["value"] == f"{TARGET:x}" and fields["range"]["value"] == 1600
    assert {o["value"] for o in fields["target"]["options"]} >= {f"{TARGET:x}", f"{key(4, 0, 0, 5):x}"}
    items = {i["label"]: i["value"] for i in summary["items"]}
    assert summary["id"] == planets_view.ROUTE_RESULT_ID and items["Jumps"].startswith("3")
    assert legs["rows"][0][1] == "System 000000000000" or legs["rows"][0][2] == "Stop A"
    assert routemap["type"] == "starmap" and routemap["lines"][0]["label"] == "Route"
    assert any(p.get("marker") == "target" for p in routemap["points"])
    failed = planets_view.route_sections(ctx, {"request": {}, "result": {"ok": False, "reason": "choose a target system"}})
    assert failed[-1]["type"] == "notice" and "choose a target system" in failed[-1]["text"]


def test_plan_route_action_checks_its_input_and_remembers_the_route(tmp_path, monkeypatch):
    """The action treats form values as untrusted: a bad range or portal address is refused with a reason, a
    valid request plans the route, asks the page to show it and is kept for the next start."""
    monkeypatch.setenv("NMS_SAVE_DIR", str(tmp_path / "missing"))

    async def scenario():
        plugin = create_plugin(FakeCtx(tmp_path / "data"))
        no_origin = await plugin.action("plan_route", {"target": f"{TARGET:x}", "range": 1000})
        plugin.save_system = ORIGIN
        bad_range = await plugin.action("plan_route", {"target": f"{TARGET:x}", "range": "lots"})
        bad_portal = await plugin.action("plan_route", {"portal": "nope", "range": 1000})
        good = await plugin.action("plan_route", {"portal": "00000000000A", "range": 1600})
        return plugin, no_origin, bad_range, bad_portal, good

    plugin, no_origin, bad_range, bad_portal, good = asyncio.run(scenario())
    assert no_origin["ok"] is False and "not known" in no_origin["message"]
    assert bad_range["ok"] is False and "between 50 and 20,000" in bad_range["message"]
    assert bad_portal["ok"] is False and "12 hex digits" in bad_portal["message"]
    assert good["ok"] is True and good["focus"] == planets_view.ROUTE_RESULT_ID and "3 jump" in good["message"]
    again = create_plugin(FakeCtx(tmp_path / "data"))
    assert again.route_state["request"]["portal"] == "00000000000A" and again.route_state["result"]["jumps"] == 3
