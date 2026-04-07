from django.core.management.base import BaseCommand

from app.chat.models.memory_bullet import MemoryBullet
from app.services import embedding as embeddingService


class Command(BaseCommand):
    help = "Backfill embedding vectors for MemoryBullets that have no embedding_json."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=64)
        parser.add_argument("--user-id", type=int, default=None)

    def handle(self, *args, **options):
        batchSize = options["batch_size"]
        userId = options["user_id"]

        if not embeddingService.is_available():
            self.stderr.write("Embedding model not available. Download weights first.")
            return

        qs = MemoryBullet.objects.filter(embedding_json="").exclude(content="")
        if userId:
            qs = qs.filter(memory__user_id=userId)

        total = qs.count()
        self.stdout.write(f"Found {total} bullets without embeddings.")

        processed = 0
        bullets = list(qs[:batchSize])
        while bullets:
            texts = [b.content for b in bullets]
            embeddings = embeddingService.encode_texts(texts, batch_size=batchSize)
            if embeddings is not None:
                for bullet, emb in zip(bullets, embeddings):
                    bullet.embedding_json = embeddingService.embedding_to_json(emb)
                MemoryBullet.objects.bulk_update(bullets, ["embedding_json"])
                processed += len(bullets)

            self.stdout.write(f"Processed {processed}/{total}")
            bullets = list(qs[:batchSize])

        self.stdout.write(f"Done. Embedded {processed} bullets.")
