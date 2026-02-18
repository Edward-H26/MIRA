from pathlib import Path
from uuid import uuid4

from django.db import models

def avatar_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    if not extension:
        extension = ".jpg"
    return f"avatars/users/{instance.uuid}/{uuid4().hex}{extension}"

# Create your models here.
class User(models.Model):
    """
    Real-world entity: Application user profile linked to Django auth user
    Why it exists: Store profile-specific fields not in auth.User
    """
    # Link to the Django auth user record this profile extends; cascade to remove profile if auth user is deleted
    user = models.OneToOneField("auth.User", on_delete=models.CASCADE, related_name='profile')
    # Opaque identifier for URL routing.
    uuid = models.UUIDField(default=uuid4, unique=True, editable=False, db_index=True)
    # Profile avatar image for the user
    profile_img = models.ImageField(null=True, blank=True, upload_to=avatar_upload_to)

    class Meta:
        ordering = ["user_id"]

    def __str__(self):
        return self.user.username
