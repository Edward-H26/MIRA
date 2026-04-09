from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from app.chat.models import Document


class Command(BaseCommand):
    help = "Delete documents that have exceeded their TTL"

    def handle(self, *args, **options):
        now = timezone.now()
        expired = Document.objects.filter(ttl_days__isnull=False).exclude(ttl_days=0)
        deleted = 0
        for doc in expired:
            expiresAt = doc.created_at + timedelta(days=doc.ttl_days)
            if now >= expiresAt:
                if doc.file:
                    doc.file.delete(save=False)
                doc.delete()
                deleted += 1
        self.stdout.write(f"Deleted {deleted} expired document(s).")
