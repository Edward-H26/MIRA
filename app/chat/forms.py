from django import forms
from app.services.ocr import validate_uploaded_image


class DocumentUploadForm(forms.Form):
    file = forms.FileField(
        label="Upload document",
        help_text="Supported: JPEG, PNG, TIFF, BMP, WebP, PDF. Max 10 MB.",
        widget=forms.ClearableFileInput(attrs={
            "accept": "image/jpeg,image/png,image/tiff,image/bmp,image/webp,application/pdf",
            "class": "upload-input",
        }),
    )

    def clean_file(self):
        uploadedFile = self.cleaned_data.get("file")
        isValid, errorMessage = validate_uploaded_image(uploadedFile)
        if not isValid:
            raise forms.ValidationError(errorMessage)
        return uploadedFile
