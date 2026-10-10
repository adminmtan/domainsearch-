"""全局 pytest 配置：禁用真实网络，避免测试时连真实服务。

- wechat_pusher: 全部 mock 成"未配置"，测试覆盖业务逻辑
- checker.time.sleep: 跳过 1s/3s 退避（真实重试仍会发生，但快速通过）
- dmcheck.app:   真实外网依赖，测试必须自己 mock `app.check_domains_with_errors`
                  或 `app.retry_unknown_domains` 之一
"""
import pytest


@pytest.fixture(autouse=True)
def _disable_real_network(monkeypatch):
    """所有测试自动禁用真实外网调用。"""
    # ── 1) wechat_pusher：未配置，所有推送都是 skipped ──
    import wechat_pusher

    monkeypatch.setattr(wechat_pusher, "is_configured", lambda: False)
    monkeypatch.setattr(
        wechat_pusher, "push_new_domain",
        lambda *a, **kw: {"configured": False, "ok": False, "skipped": True},
    )
    monkeypatch.setattr(
        wechat_pusher, "push_report",
        lambda *a, **kw: {"configured": False, "ok": False, "skipped": True},
    )
    monkeypatch.setattr(
        wechat_pusher, "push_stopped",
        lambda *a, **kw: {"configured": False, "ok": False, "skipped": True},
    )
    monkeypatch.setattr(
        wechat_pusher, "push_test",
        lambda *a, **kw: {"configured": False, "ok": False, "skipped": True},
    )
    monkeypatch.setattr(
        wechat_pusher, "send_message",
        lambda *a, **kw: {"configured": False, "ok": False, "skipped": True},
    )
    monkeypatch.setattr(
        wechat_pusher, "get_status",
        lambda: {"bot_reachable": False, "logged_in": False},
    )

    # ── 2) checker 内部 time.sleep：避免 1s/3s 退避拖慢测试 ──
    import checker
    monkeypatch.setattr(checker.time, "sleep", lambda *_a, **_kw: None)
    # 注：retry_unknown_domains 不再需要 fallback mock — 它内部已调
    # check_domains_with_errors，测试 mock 它就能覆盖全部 dmcheck 调用。

    yield

