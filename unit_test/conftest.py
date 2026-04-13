import os
import sys
import django
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "memoria.settings.dev")
django.setup()


@pytest.fixture(scope="session")
def data(django_db_blocker):
    from unit_test.mock_data import cleanup_all_test_data, create_all_test_data
    with django_db_blocker.unblock():
        cleanup_all_test_data()
        return create_all_test_data()
