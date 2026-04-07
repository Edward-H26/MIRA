from django import forms
from app.services.ocr import validate_uploaded_image


class DocumentUploadForm(forms.Form):
    image = forms.ImageField(
        label="Upload document image",
        help_text="Supported: JPEG, PNG, TIFF, BMP, WebP. Max 10 MB.",
        widget=forms.ClearableFileInput(attrs={
            "accept": "image/jpeg,image/png,image/tiff,image/bmp,image/webp",
            "class": "upload-input",
        }),
    )

    def clean_image(self):
        imageFile = self.cleaned_data.get("image")
        isValid, errorMessage = validate_uploaded_image(imageFile)
        if not isValid:
            raise forms.ValidationError(errorMessage)
        return imageFile
