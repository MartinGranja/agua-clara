import pytest
from app.main import create_app
from app.core.config import Settings

def test_vercel_rejects_sqlite(monkeypatch):
    monkeypatch.setenv('VERCEL','1')
    with pytest.raises(RuntimeError,match='PostgreSQL'):
        create_app(Settings(_env_file=None,allow_remote=True,admin_token='test-only',database_url='sqlite:///:memory:'))

def test_vercel_requires_admin_access(monkeypatch):
    monkeypatch.setenv('VERCEL','1')
    with pytest.raises(RuntimeError,match='ADMIN_TOKEN'):
        create_app(Settings(_env_file=None,allow_remote=False,admin_token='',database_url='postgresql://unused'))
