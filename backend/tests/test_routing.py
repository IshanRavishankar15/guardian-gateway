from app.db.models import Route
from app.services.routing import select_route


def test_longest_prefix_and_segment_boundary_matching():
    root = Route(path_prefix="/")
    api = Route(path_prefix="/api")
    nested = Route(path_prefix="/api/v2")

    assert select_route([root, api, nested], "/api/v2/items") is nested
    assert select_route([root, api, nested], "/api/users") is api
    assert select_route([root, api], "/apix") is root
