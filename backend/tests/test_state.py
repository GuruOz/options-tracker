from app.core.state import GatewayStatus, SessionState


def test_update_reports_change():
    s = SessionState()
    changed = s.update(status=GatewayStatus.AUTHENTICATED, message="Connected.")
    assert changed is True
    assert s.status is GatewayStatus.AUTHENTICATED
    assert s.last_checked is not None


def test_update_noop_when_unchanged():
    s = SessionState(status=GatewayStatus.AUTHENTICATED, message="Connected.")
    s.update()  # sets last_checked but nothing user-visible
    changed = s.update(status=GatewayStatus.AUTHENTICATED, message="Connected.")
    assert changed is False


def test_to_dict_serialises_status_as_string():
    s = SessionState(status=GatewayStatus.DISCONNECTED)
    d = s.to_dict()
    assert d["status"] == "disconnected"
    assert "authenticated" in d
