import hashlib

from django.core.files.base import ContentFile
from django.core.files.storage import Storage
import pytest

from dandiapi.api import tasks
from dandiapi.api.models import AssetBlob, Validation

from .fuzzy import TIMESTAMP_RE


@pytest.mark.django_db
def test_validate(api_client, user):
    api_client.force_authenticate(user=user)

    object_key = 'test.txt'
    contents = b'test content'

    h = hashlib.sha256()
    h.update(contents)
    sha256 = h.hexdigest()

    Validation.blob.field.storage.save(object_key, ContentFile(contents))

    assert (
        api_client.post(
            '/api/uploads/validate/',
            {
                'object_key': object_key,
                'sha256': sha256,
            },
            format='json',
        ).status_code
        == 204
    )

    validation = Validation.objects.get(sha256=sha256)
    assert validation.blob.name == object_key
    assert validation.state == Validation.State.IN_PROGRESS

    # TODO how to test that the celery job kicked off?


@pytest.mark.django_db
@pytest.mark.parametrize('state', [Validation.State.SUCCEEDED, Validation.State.FAILED])
@pytest.mark.parametrize(
    'contents', [b'Very little content!', b'X' * 1024, b'X' * 1024 * 16], ids=['20B', '1KB', '16KB']
)
def test_validate_no_object_key(api_client, user, asset_blob_factory, state, contents):
    api_client.force_authenticate(user=user)

    object_key = 'test.txt'

    h = hashlib.sha256()
    h.update(contents)
    sha256 = h.hexdigest()

    Validation.blob.field.storage.save(object_key, ContentFile(contents))

    # Save an existing Validation that will be updated
    Validation(blob=object_key, sha256=sha256, state=state).save()

    # Save an existing AssetBlob with the same checksum
    asset_blob = asset_blob_factory(sha256=sha256)
    asset_blob.save()

    assert (
        api_client.post(
            '/api/uploads/validate/',
            {
                'sha256': sha256,
            },
            format='json',
        ).status_code
        == 204
    )

    validation = Validation.objects.get(sha256=sha256)
    assert validation.blob.name == asset_blob.blob.name
    assert validation.state == Validation.State.IN_PROGRESS


@pytest.mark.django_db
def test_validate_no_object_key_wrong_sha256(api_client, user):
    api_client.force_authenticate(user=user)

    resp = api_client.post(
        '/api/uploads/validate/',
        {
            'sha256': 'f' * 64,
        },
        format='json',
    )
    assert resp.status_code == 400
    assert resp.data == ['A validation for an object with that checksum does not exist.']


@pytest.mark.django_db
def test_validate_in_progress_validation(api_client, user):
    api_client.force_authenticate(user=user)

    object_key = 'test.txt'
    contents = b'test content'

    h = hashlib.sha256()
    h.update(contents)
    sha256 = h.hexdigest()

    Validation.blob.field.storage.save(object_key, ContentFile(contents))

    # Save an existing Validation that will be updated
    Validation(blob=object_key, sha256=sha256, state=Validation.State.IN_PROGRESS).save()

    resp = api_client.post(
        '/api/uploads/validate/',
        {
            'object_key': object_key,
            'sha256': sha256,
        },
        format='json',
    )
    assert resp.status_code == 200
    assert resp.data == 'Validation already in progress.'


@pytest.mark.django_db
def test_validate_object_does_not_exist(api_client, user):
    api_client.force_authenticate(user=user)

    object_key = 'does-not-exist.txt'
    contents = b'test content'

    h = hashlib.sha256()
    h.update(contents)
    sha256 = h.hexdigest()

    resp = api_client.post(
        '/api/uploads/validate/',
        {
            'object_key': object_key,
            'sha256': sha256,
        },
        format='json',
    )
    assert resp.status_code == 400
    assert resp.data == ['Object does not exist.']


@pytest.mark.django_db
@pytest.mark.parametrize(
    'state', [Validation.State.IN_PROGRESS, Validation.State.SUCCEEDED, Validation.State.FAILED]
)
def test_get_validation(api_client, user, state):
    api_client.force_authenticate(user=user)

    object_key = 'does-not-exist.txt'
    contents = b'test content'
    error = 'Serious errors encountered'

    h = hashlib.sha256()
    h.update(contents)
    sha256 = h.hexdigest()

    # Save an existing Validation that will be updated
    Validation(blob=object_key, sha256=sha256, state=state, error=error).save()

    assert (
        api_client.get(
            f'/api/uploads/validations/{sha256}/',
            {
                'object_key': object_key,
                'sha256': sha256,
            },
            format='json',
        ).data
        == {
            'state': str(state),
            'sha256': sha256,
            'created': TIMESTAMP_RE,
            'modified': TIMESTAMP_RE,
        }
        if state != Validation.State.FAILED
        else {
            'state': str(state),
            'sha256': sha256,
            'error': error,
            'created': TIMESTAMP_RE,
            'modified': TIMESTAMP_RE,
        }
    )


@pytest.mark.django_db
def test_validation_task(storage: Storage):
    # Pretend like Validation was defined with the given storage
    Validation.blob.field.storage = storage

    object_key = 'test.txt'
    contents = b'test content'

    h = hashlib.sha256()
    h.update(contents)
    sha256 = h.hexdigest()

    # Save the file in the backing storage
    storage.save(object_key, ContentFile(contents))

    validation = Validation(blob=object_key, state=Validation.State.IN_PROGRESS, sha256=sha256)
    validation.save()

    tasks.validate(validation.id)

    validation.refresh_from_db()

    assert validation.state == Validation.State.SUCCEEDED
    assert validation.error is None

    # Successful validations also write an AssetBlob
    asset_blob = AssetBlob.objects.get(sha256=sha256)
    assert asset_blob.blob.name == f'blobs/{sha256[0:3]}/{sha256[3:6]}/{sha256[6:]}'
    assert storage.exists(asset_blob.blob.name)

    # After copying the object, the original uploaded blob should be removed.
    assert not storage.exists(validation.blob.name)


@pytest.mark.django_db
def test_validation_task_incorrect_checksum():
    object_key = 'test.txt'
    contents = b'test content'

    h = hashlib.sha256()
    h.update(contents)
    correct_sha256 = h.hexdigest()
    # This will make the checksum incorrect
    h.update(b'bad data')
    sha256 = h.hexdigest()

    Validation.blob.field.storage.save(object_key, ContentFile(contents))

    validation = Validation(blob=object_key, state=Validation.State.IN_PROGRESS, sha256=sha256)
    validation.save()

    tasks.validate(validation.id)

    validation.refresh_from_db()

    assert validation.state == Validation.State.FAILED
    assert (
        validation.error
        == f'Given checksum {sha256} did not match calculated checksum {correct_sha256}.'
    )
