import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from products.models import SyncRun

logger = logging.getLogger("products.sync")


def is_sync_stale():
    hours = int(getattr(settings, "SYNC_STALE_HOURS", 26))
    last = (
        SyncRun.objects.filter(status=SyncRun.STATUS_SUCCESS)
        .exclude(finished_at__isnull=True)
        .order_by("-finished_at")
        .first()
    )
    if last is None:
        return True
    return last.finished_at < timezone.now() - timedelta(hours=hours)


def record_sync_run(sync_id, started_at, status, success_count, error_count, message=""):
    try:
        SyncRun.objects.create(
            sync_id=sync_id,
            started_at=started_at,
            finished_at=timezone.now(),
            success_count=success_count,
            error_count=error_count,
            status=status,
            message=message[:1000],
        )
    except Exception:
        logger.exception("sync_run_log_failed sync_id=%s", sync_id)
