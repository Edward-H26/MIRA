from django.db import models

def avatar_upload_to(instance, filename):
    """"""
    return f"avatars/users/{instance.user_id}"

# Create your models here.
class User(models.Model):
    """
    Real-world entity: Application user profile linked to Django auth user
    Why it exists: Store profile-specific fields not in auth.User
    """
    # Link to the Django auth user record this profile extends
    user = models.OneToOneField("auth.User", on_delete=models.CASCADE, related_name='profile')
    # Profile avatar image for the user
    profile_img = models.ImageField(null=True, blank=True, upload_to=avatar_upload_to)

    def __str__(self):
        return self.user.username
