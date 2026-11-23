import pytest
from fastapi.testclient import TestClient
from html.parser import HTMLParser
from app.main import create_app
from app.core.config import Settings


class FrontendAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths=[]

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='script' and 'src' in attrs:
            self.paths.append(attrs['src'])
        if tag=='link' and attrs.get('rel')=='stylesheet':
            self.paths.append(attrs['href'])


def test_public_and_admin_entry_points(tmp_path):
    app=create_app(Settings(_env_file=None,database_url='sqlite:///'+str(tmp_path/'routes.db'),admin_token='test-only'))
    try:
        with TestClient(app) as client:
            for path in ('/','/admin','/admin/'):
                response=client.get(path)
                assert response.status_code==200
                assert 'Simulador de WhatsApp' not in response.text
                assets=FrontendAssets()
                assets.feed(response.text)
                assert assets.paths
                for asset in assets.paths:
                    assert asset.startswith('/')
                    assert client.get(asset).status_code==200
            assert client.get('/api/admin/requests').status_code==401
            assert client.get('/api/admin/requests',headers={'Authorization':'Bearer test-only'}).status_code==200
    finally:
        app.state.store.engine.dispose()

def test_vercel_rejects_sqlite(monkeypatch):
    monkeypatch.setenv('VERCEL','1')
    with pytest.raises(RuntimeError,match='PostgreSQL'):
        create_app(Settings(_env_file=None,allow_remote=True,admin_token='test-only',database_url='sqlite:///:memory:'))

def test_vercel_requires_admin_access(monkeypatch):
    monkeypatch.setenv('VERCEL','1')
    with pytest.raises(RuntimeError,match='ADMIN_TOKEN'):
        create_app(Settings(_env_file=None,allow_remote=False,admin_token='',database_url='postgresql://unused'))
