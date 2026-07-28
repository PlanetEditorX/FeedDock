"""Value objects returned by the notification service."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class NotificationResult:
    """Summarize a multi-channel notification delivery attempt."""

    ok: bool
    sent: int = 0
    skipped: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        if self.skipped:
            return "通知未启用或事件未勾选"
        if self.ok:
            return f"通知发送成功，共 {self.sent} 个渠道"
        return "；".join(self.errors) or "通知发送失败"
