from __future__ import annotations

from uuid import uuid4

from django.conf import settings
from django.core.files.storage import Storage
from django.core.validators import RegexValidator
from django.db import models
from django_extensions.db.models import TimeStampedModel

from dandiapi.api.storage import DeconstructableFileField, create_s3_storage


def _get_validation_blob_storage() -> Storage:
    return create_s3_storage(settings.DANDI_DANDISETS_BUCKET_NAME)


def _get_validation_blob_prefix(instance: Validation, filename: str) -> str:
    return f'{filename}/{uuid4()}'


class Validation(TimeStampedModel):
    SHA256_REGEX = r'[0-9a-f]{64}'

    class State(models.TextChoices):
        IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
        SUCCEEDED = 'SUCCEEDED', 'Succeeded'
        FAILED = 'FAILED', 'Failed'

    class Meta:
        indexes = [models.Index(fields=['sha256'])]

    blob = DeconstructableFileField(
        blank=True,
        storage=_get_validation_blob_storage,
        upload_to=_get_validation_blob_prefix,
        max_length=256,
    )
    sha256 = models.CharField(
        max_length=64, unique=True, validators=[RegexValidator(f'^{SHA256_REGEX}$')]
    )
    state = models.CharField(max_length=20, choices=State.choices)
    error = models.TextField(null=True)

    def object_key_exists(self):
        return self.blob.field.storage.exists(self.blob.name)
