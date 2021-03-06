from __future__ import annotations

import datetime

from django.conf import settings
from django.contrib.postgres.indexes import HashIndex
from django.core.validators import RegexValidator
from django.db import models
from django_extensions.db.models import TimeStampedModel

from .dandiset import Dandiset


class VersionMetadata(TimeStampedModel):
    metadata = models.JSONField(default=dict)
    name = models.CharField(max_length=300)

    class Meta:
        indexes = [
            HashIndex(fields=['metadata']),
            HashIndex(fields=['name']),
        ]

    @property
    def references(self) -> int:
        return self.versions.count()

    def __str__(self) -> str:
        return self.name


def _get_default_version() -> str:
    # This cannot be a lambda, as migrations cannot serialize those
    return Version.make_version()


class Version(TimeStampedModel):
    VERSION_REGEX = r'(0\.\d{6}\.\d{4})|draft'

    dandiset = models.ForeignKey(Dandiset, related_name='versions', on_delete=models.CASCADE)
    metadata = models.ForeignKey(VersionMetadata, related_name='versions', on_delete=models.CASCADE)
    version = models.CharField(
        max_length=13,
        validators=[RegexValidator(f'^{VERSION_REGEX}$')],
        default=_get_default_version,
    )  # TODO: rename this?

    class Meta:
        unique_together = ['dandiset', 'version']

    @property
    def asset_count(self):
        return self.assets.count()

    @property
    def name(self):
        return self.metadata.name

    @property
    def size(self):
        return self.assets.aggregate(size=models.Sum('blob__size'))['size'] or 0

    @staticmethod
    def datetime_to_version(time: datetime.datetime) -> str:
        return time.strftime('0.%y%m%d.%H%M')

    @classmethod
    def make_version(cls, dandiset: Dandiset = None) -> str:
        versions: models.Manager = dandiset.versions if dandiset else cls.objects

        time = datetime.datetime.utcnow()
        # increment time until there are no collisions
        while True:
            version = cls.datetime_to_version(time)
            collision = versions.filter(version=version).exists()
            if not collision:
                break
            time += datetime.timedelta(minutes=1)

        return version

    @classmethod
    def copy(cls, version):
        return Version(dandiset=version.dandiset, metadata=version.metadata)

    def _populate_metadata(self):
        new: VersionMetadata
        new, created = VersionMetadata.objects.get_or_create(
            name=self.metadata.name,
            metadata={
                **self.metadata.metadata,
                'name': self.metadata.name,
                'identifier': f'DANDI:{self.dandiset.identifier}',
                'schema_version': settings.DANDI_SCHEMA_VERSION,
            },
        )

        if created:
            new.save()

        self.metadata = new

    def save(self, *args, **kwargs):
        self._populate_metadata()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f'{self.dandiset.identifier}/{self.version}'
