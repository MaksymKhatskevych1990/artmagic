from django.core.management.base import BaseCommand

from carts.checkout import (
    expire_pending_reservations,
    retry_pending_notifications,
)


class Command(BaseCommand):
    help = "Знімає прострочені резерви LiqPay і переводить такі замовлення в expired."

    def handle(self, *args, **options):
        expired = expire_pending_reservations()
        notification_batches = retry_pending_notifications()
        self.stdout.write(
            self.style.SUCCESS(
                f"expired_orders={expired} "
                f"notification_batches={notification_batches}"
            )
        )
