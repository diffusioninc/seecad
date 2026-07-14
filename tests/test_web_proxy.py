from __future__ import annotations

import re
from pathlib import Path

from seecad.api import API_REQUEST_LIMIT_BYTES


def test_nginx_request_limit_matches_api_transport_contract() -> None:
    config = (Path(__file__).resolve().parents[1] / "web" / "nginx.conf").read_text()
    match = re.search(r"\bclient_max_body_size\s+(\d+)m;", config)

    assert match is not None, "nginx must explicitly bound proxied request bodies"
    assert int(match.group(1)) * 1024 * 1024 == API_REQUEST_LIMIT_BYTES


def test_nginx_proxy_window_exceeds_browser_and_backend_planner_budgets() -> None:
    config = (Path(__file__).resolve().parents[1] / "web" / "nginx.conf").read_text()
    read_timeout = re.search(r"\bproxy_read_timeout\s+(\d+)s;", config)
    send_timeout = re.search(r"\bproxy_send_timeout\s+(\d+)s;", config)

    assert read_timeout is not None
    assert send_timeout is not None
    assert int(read_timeout.group(1)) >= 600
    assert int(send_timeout.group(1)) >= 600
