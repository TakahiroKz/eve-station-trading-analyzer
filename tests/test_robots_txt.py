"""robots.txt: public read-only API routes are crawlable (renderers need them), the rest stays blocked."""
from pathlib import Path

ROBOTS = Path(__file__).resolve().parent.parent / "frontend" / "app" / "public" / "robots.txt"
PUBLIC_API = {"/api/markets", "/api/summary", "/api/categories", "/api/items"}


def _groups() -> list[dict[str, set[str]]]:
    groups: list[dict[str, set[str]]] = []
    previous_was_agent = False
    for raw in ROBOTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        field, value = (part.strip() for part in line.split(":", 1))
        field = field.lower()
        if field == "user-agent":
            if not previous_was_agent:
                groups.append({"agents": set(), "allow": set(), "disallow": set()})
            groups[-1]["agents"].add(value)
            previous_was_agent = True
            continue
        previous_was_agent = False
        if field in ("allow", "disallow") and groups:
            groups[-1][field].add(value)
    return groups


def test_every_group_opens_only_the_public_api_routes_and_keeps_the_rest_blocked():
    groups = _groups()
    assert groups, "robots.txt has no user-agent groups"
    for group in groups:
        api_allowed = {path for path in group["allow"] if path.startswith("/api")}
        assert api_allowed == PUBLIC_API, group["agents"]
        assert "/api/" in group["disallow"], group["agents"]


def test_no_allow_rule_can_reach_the_private_api():
    for group in _groups():
        for path in group["allow"]:
            assert path == "/" or not "/api/private".startswith(path.rstrip("*")), path
            assert not path.startswith("/api/private"), path
