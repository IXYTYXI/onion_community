"""Exercise real startup/failure/shutdown, including both listening sockets."""
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def unused_ports():
    with socket.socket() as one, socket.socket() as two:
        one.bind(("127.0.0.1", 0))
        two.bind(("127.0.0.1", 0))
        return one.getsockname()[1], two.getsockname()[1]


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def start(api_port, frontend_port, environment="test"):
    env = {**os.environ, "OWS_COMMUNITY_ENVIRONMENT": environment, "OWS_COMMUNITY_STORE_BACKEND": "memory",
           "OWS_COMMUNITY_ASSISTANT_ENABLED": "false",
           "OWS_COMMUNITY_NEWS_SYNC_ENABLED": "false", "OWS_COMMUNITY_DEV_LOGIN_ENABLED": "false", "OWS_COMMUNITY_HOST": "127.0.0.1",
           "OWS_COMMUNITY_PORT": str(api_port), "OWS_COMMUNITY_FRONTEND_PORT": str(frontend_port)}
    return subprocess.Popen([sys.executable, "-m", "app"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_ready(process, urls):
    deadline = time.monotonic() + 12
    with httpx.Client(timeout=0.5, trust_env=False) as client:
        while time.monotonic() < deadline:
            assert process.poll() is None, "launcher exited before readiness"
            try:
                if all(client.get(url).status_code == 200 for url in urls):
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
    raise AssertionError("services did not start")


@pytest.mark.parametrize("environment", ["test", "development"])
def test_one_command_starts_both_and_ctrl_c_stops_both(environment):
    api_port, frontend_port = unused_ports()
    process = start(api_port, frontend_port, environment)
    api, web = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{frontend_port}"
    try:
        wait_ready(process, [api + "/health/live", web + "/login.html"])
        with httpx.Client(trust_env=False) as client:
            assert client.get(api + "/api/v1/me").status_code == 401
            assert client.get(web + "/index.html").status_code == 303
            assert "OWS Community" in client.get(web + "/login.html").text
            assert client.get(web + "/api/v1/auth/options").status_code == 200
            assert client.get(web + "/assets/icons/lucide.svg").status_code == 200
            for path in ("/.env", "/app/core/config.py", "/%2e%2e/.env", "/assets/"):
                assert client.get(web + path).status_code == 404
        process.send_signal(signal.SIGINT)
        assert process.wait(timeout=12) == 0
        assert not listening(api_port) and not listening(frontend_port)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=12)


@pytest.mark.parametrize("occupied", ["api", "frontend"])
def test_busy_port_stops_sibling_without_stopping_existing_service(occupied):
    api_port, frontend_port = unused_ports()
    busy = api_port if occupied == "api" else frontend_port
    other = frontend_port if occupied == "api" else api_port
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", busy))
        listener.listen()
        process = start(api_port, frontend_port)
        try:
            assert process.wait(timeout=12) != 0
            assert not listening(other)
            assert listening(busy)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=12)
