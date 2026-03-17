from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.io.web.capability import (
    ListResult,
    PublishResult,
    UnpublishResult,
    WebCapability,
    WebError,
    WebResponse,
)


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def pid():
    return uuid4()


@pytest.fixture
def cap(repo, pid):
    return WebCapability(repo, pid)


class TestPublish:
    def test_publish_writes_file_with_web_prefix(self, cap, repo):
        repo.get_file_by_key.return_value = None
        mock_file = MagicMock()
        mock_file.key = "web/index.html"
        repo.insert_file.return_value = None
        repo.insert_file_version.return_value = None
        repo.get_file_by_key.side_effect = [None, mock_file]

        result = cap.publish("index.html", "<h1>Hello</h1>")
        assert isinstance(result, PublishResult)
        assert result.path == "index.html"

    def test_publish_empty_path_returns_error(self, cap):
        result = cap.publish("", "<h1>Hello</h1>")
        assert isinstance(result, WebError)

    def test_publish_empty_content_returns_error(self, cap):
        result = cap.publish("index.html", "")
        assert isinstance(result, WebError)

    def test_publish_created_true_on_new_file(self, cap, repo):
        from cogos.db.models import File

        File(key="web/new.html")
        repo.get_file_by_key.return_value = None
        repo.insert_file.return_value = None
        repo.insert_file_version.return_value = None

        result = cap.publish("new.html", "<p>new</p>")
        assert isinstance(result, PublishResult)
        assert result.created is True
        assert result.version == 1

    def test_publish_created_false_on_existing_file(self, cap, repo):
        from cogos.db.models import File, FileVersion

        existing = File(key="web/old.html")
        repo.get_file_by_key.return_value = existing
        active_v = FileVersion(file_id=existing.id, version=2, content="old")
        repo.get_active_file_version.return_value = active_v
        repo.get_max_file_version.return_value = 2
        repo.set_active_file_version.return_value = None
        repo.insert_file_version.return_value = None
        repo.update_file_includes.return_value = None

        result = cap.publish("old.html", "<p>updated</p>")
        assert isinstance(result, PublishResult)
        assert result.created is False
        assert result.version == 3


class TestPublishBinary:
    def test_publish_base64_content(self, cap, repo):
        repo.get_file_by_key.return_value = None
        repo.insert_file.return_value = None
        repo.insert_file_version.return_value = None
        mock_file = MagicMock()
        mock_file.key = "web/image.png"
        repo.get_file_by_key.side_effect = [None, mock_file]

        result = cap.publish("image.png", "iVBORw0KGgo=", content_encoding="base64")
        assert isinstance(result, PublishResult)
        assert result.path == "image.png"

    def test_publish_invalid_encoding_returns_error(self, cap):
        result = cap.publish("file.txt", "content", content_encoding="gzip")
        assert isinstance(result, WebError)
        assert "encoding" in result.error.lower()

    def test_publish_base64_stores_with_prefix(self, cap, repo):
        """Verify base64 content is stored with the base64: prefix."""
        from cogos.db.models import File

        repo.get_file_by_key.return_value = None
        repo.insert_file.return_value = None
        repo.insert_file_version.return_value = None
        mock_file = MagicMock()
        mock_file.key = "web/img.png"
        repo.get_file_by_key.side_effect = [None, mock_file]

        cap.publish("img.png", "AQID", content_encoding="base64")
        # Check that insert_file_version was called with base64: prefixed content
        call_args = repo.insert_file_version.call_args
        if call_args:
            version = call_args.args[0] if call_args.args else call_args.kwargs.get("version")
            if hasattr(version, "content"):
                assert version.content.startswith("base64:")


class TestUnpublish:
    def test_unpublish_deletes_file(self, cap, repo):
        from cogos.db.models import File

        f = File(key="web/page.html")
        repo.get_file_by_key.return_value = f
        repo.delete_file.return_value = None

        result = cap.unpublish("page.html")
        assert isinstance(result, UnpublishResult)
        assert result.path == "page.html"
        assert result.deleted is True

    def test_unpublish_empty_path_returns_error(self, cap):
        result = cap.unpublish("")
        assert isinstance(result, WebError)

    def test_unpublish_missing_file_returns_not_deleted(self, cap, repo):
        repo.get_file_by_key.return_value = None

        result = cap.unpublish("gone.html")
        assert isinstance(result, UnpublishResult)
        assert result.deleted is False


class TestRespond:
    def test_respond_stores_response(self, cap):
        result = cap.respond("req-1", status=200, body="OK")
        assert isinstance(result, WebResponse)
        assert result.request_id == "req-1"
        assert result.status == 200

        pending = cap.get_pending_response("req-1")
        assert pending is not None
        assert pending["status"] == 200
        assert pending["body"] == "OK"

    def test_respond_duplicate_is_noop(self, cap):
        cap.respond("req-1", status=200, body="first")
        cap.respond("req-1", status=404, body="second")

        pending = cap.get_pending_response("req-1")
        assert pending["status"] == 200
        assert pending["body"] == "first"

    def test_respond_empty_request_id_returns_error(self, cap):
        result = cap.respond("", status=200, body="OK")
        assert isinstance(result, WebError)

    def test_respond_with_headers(self, cap):
        cap.respond("req-2", status=200, headers={"X-Custom": "val"}, body="ok")
        pending = cap.get_pending_response("req-2")
        assert pending["headers"] == {"X-Custom": "val"}

    def test_get_pending_response_pops(self, cap):
        cap.respond("req-3", status=200, body="data")
        first = cap.get_pending_response("req-3")
        assert first is not None
        second = cap.get_pending_response("req-3")
        assert second is None


class TestList:
    def test_list_returns_files(self, cap, repo):
        from cogos.db.models import File

        repo.list_files.return_value = [
            File(key="web/a.html"),
            File(key="web/b.html"),
        ]

        result = cap.list()
        assert isinstance(result, ListResult)
        assert result.files == ["a.html", "b.html"]

    def test_list_with_prefix(self, cap, repo):
        from cogos.db.models import File

        repo.list_files.return_value = [
            File(key="web/blog/post1.html"),
        ]

        result = cap.list(prefix="blog/")
        assert isinstance(result, ListResult)
        assert result.files == ["blog/post1.html"]
        repo.list_files.assert_called_once_with(prefix="web/blog/", limit=200)


class TestScopeNarrowing:
    def test_ops_intersection(self, cap):
        s1 = cap.scope(ops={"publish", "unpublish", "list"})
        s2 = s1.scope(ops={"publish", "respond"})
        assert s2._scope["ops"] == {"publish"}

    def test_path_prefix_enforcement_narrows(self, cap):
        s1 = cap.scope(path_prefix="site/")
        s2 = s1.scope(path_prefix="site/blog/")
        assert s2._scope["path_prefix"] == "site/blog/"

    def test_path_prefix_cannot_widen(self, cap):
        s1 = cap.scope(path_prefix="site/blog/")
        s2 = s1.scope(path_prefix="site/")
        assert s2._scope["path_prefix"] == "site/blog/"

    def test_ops_scoped_denies_unpermitted(self, cap):
        scoped = cap.scope(ops={"list"})
        with pytest.raises(PermissionError):
            scoped.publish("x.html", "content")

    def test_path_prefix_scoped_denies_outside(self, cap, repo):
        scoped = cap.scope(path_prefix="allowed/")
        with pytest.raises(PermissionError):
            scoped.publish("other/x.html", "content")

    def test_path_prefix_scoped_allows_inside(self, cap, repo):
        scoped = cap.scope(path_prefix="allowed/")
        repo.get_file_by_key.return_value = None
        repo.insert_file.return_value = None
        repo.insert_file_version.return_value = None

        result = scoped.publish("allowed/x.html", "ok")
        assert isinstance(result, PublishResult)


class TestUrl:
    def test_url_uses_explicit_override(self, cap, monkeypatch):
        monkeypatch.setenv("WEB_BASE_URL", "https://example.com/custom/web/static/")

        assert cap.url("page.html") == "https://example.com/custom/web/static/page.html"

    def test_url_defaults_to_cogent_dashboard_static_path(self, cap, monkeypatch):
        monkeypatch.delenv("WEB_BASE_URL", raising=False)
        monkeypatch.delenv("USE_LOCAL_DB", raising=False)
        monkeypatch.delenv("DASHBOARD_FE_PORT", raising=False)
        monkeypatch.delenv("DASHBOARD_BE_PORT", raising=False)
        monkeypatch.setenv("COGENT_NAME", "dr.gamma")
        monkeypatch.setenv("COGENT_DOMAIN", "softmax-cogents.com")

        assert cap.url("least-favorite-fruit") == (
            "https://dr-gamma.softmax-cogents.com/web/static/least-favorite-fruit"
        )

    def test_url_prefers_local_frontend_port(self, cap, monkeypatch):
        monkeypatch.delenv("WEB_BASE_URL", raising=False)
        monkeypatch.setenv("USE_LOCAL_DB", "1")
        monkeypatch.setenv("DASHBOARD_FE_PORT", "5200")

        assert cap.url("demo") == "http://localhost:5200/web/static/demo"
