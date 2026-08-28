import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.application.notification_config import DiscordConfig
from app.application.ports import NotificationPublisher
from app.domain.enums import DeliveryStatus
from app.domain.notification_models import DeliveryReceipt, DiscordMessage


class DiscordWebhookPublisher(NotificationPublisher):
    def __init__(self, config: DiscordConfig) -> None:
        self._config = config

    def publish(self, message: DiscordMessage) -> DeliveryReceipt:
        webhook_url = os.getenv(self._config.webhook_url_env)
        if not webhook_url:
            return DeliveryReceipt(
                status=DeliveryStatus.FAILED,
                detail=f"Environment variable {self._config.webhook_url_env} is not set.",
            )

        payload = message.model_dump(mode="json", exclude_none=True)
        request = Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        max_attempts = 3
        last_error_detail = "unknown error"

        for attempt in range(max_attempts):
            try:
                with urlopen(request, timeout=self._config.timeout_seconds) as response:
                    detail = f"Discord webhook accepted request with HTTP {response.status}."
                    return DeliveryReceipt(status=DeliveryStatus.SENT, detail=detail)
            except HTTPError as error:
                if error.code == 429:
                    # Respect rate-limits with Retry-After header
                    retry_after = error.headers.get("Retry-After")
                    try:
                        sleep_seconds = float(retry_after) if retry_after else 1.0
                    except ValueError:
                        sleep_seconds = 1.0
                    # Cap sleep_seconds to avoid long hangs
                    sleep_seconds = min(10.0, max(0.1, sleep_seconds))
                    time.sleep(sleep_seconds)
                    continue
                detail = f"Discord webhook returned HTTP {error.code}: {error.reason}"
                return DeliveryReceipt(status=DeliveryStatus.FAILED, detail=detail)
            except URLError as error:
                last_error_detail = str(error.reason)
            except TimeoutError:
                last_error_detail = "Discord webhook timed out."

            if attempt < max_attempts - 1:
                time.sleep(0.5)

        return DeliveryReceipt(status=DeliveryStatus.FAILED, detail=last_error_detail)
