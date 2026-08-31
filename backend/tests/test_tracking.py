"""Testes unitários básicos do endpoint de tracking."""

from api.tracking import router


def test_tracking_router_exposes_go_endpoint():
    paths = {route.path for route in router.routes}
    assert "/go/{deal_id}" in paths


def test_tracking_route_is_get():
    route = next(route for route in router.routes if route.path == "/go/{deal_id}")
    assert "GET" in route.methods
