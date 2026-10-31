from app.db.models import Route


def select_route(routes: list[Route], request_path: str) -> Route | None:
    matches = [route for route in routes if _prefix_matches(route.path_prefix, request_path)]
    return max(matches, key=lambda route: len(route.path_prefix), default=None)


def _prefix_matches(prefix: str, request_path: str) -> bool:
    if prefix == "/":
        return request_path.startswith("/")
    return request_path == prefix or request_path.startswith(prefix + "/")
