"""Tests for the downloader plugin (S13b): fetch a URL to a file on disk.

Hermetic — no network. The FetchClient uses a canned URL→response map.
"""

from __future__ import annotations

import pytest

from atlas.exceptions import PluginError
from atlas.net import FetchClient
from atlas.plugins.downloader_plugin import DownloaderPlugin


class _FakeResp:
    def __init__(self, content, status=200, url=None, content_type="application/pdf"):
        self.content = content
        self.headers = {"content-type": content_type}
        self.status_code = status
        self.url = url
        self.encoding = "utf-8"


def _downloader(resp_map, download_dir):
    def http_get(url, headers):
        return resp_map[url]

    client = FetchClient(
        http_get=http_get,
        respect_robots=False,
        per_domain_delay=0.0,
        cache_ttl=0.0,
        sleep=lambda _s: None,
    )
    return DownloaderPlugin(client, download_dir)


def test_download_writes_file_and_returns_metadata(tmp_path):
    url = "https://example.com/docs/report.pdf"
    dl = _downloader({url: _FakeResp(b"PDFDATA", url=url)}, tmp_path)
    result = dl.download(url)
    assert result["bytes"] == 7
    assert result["outcome"] == "ok"
    written = tmp_path / "report.pdf"
    assert written.read_bytes() == b"PDFDATA"
    assert result["path"] == str(written)


def test_download_uses_explicit_filename_sanitised(tmp_path):
    url = "https://example.com/x"
    dl = _downloader({url: _FakeResp(b"data", url=url)}, tmp_path)
    result = dl.download(url, filename="../weird name!.txt")
    written = tmp_path / "weird_name_.txt"
    assert written.exists()
    assert result["path"] == str(written)


def test_download_derives_name_when_url_has_no_basename(tmp_path):
    url = "https://example.com/"
    dl = _downloader({url: _FakeResp(b"data", url=url)}, tmp_path)
    result = dl.download(url)
    assert result["bytes"] == 4
    assert (tmp_path / "example.com.download").exists()


def test_download_rejects_non_http(tmp_path):
    dl = _downloader({}, tmp_path)
    with pytest.raises(PluginError):
        dl.download("ftp://example.com/file")


def test_download_blocked_raises(tmp_path):
    url = "https://example.com/secret.pdf"
    dl = _downloader({url: _FakeResp(b"", status=403, url=url)}, tmp_path)
    with pytest.raises(PluginError) as exc:
        dl.download(url)
    assert "blocked" in str(exc.value)


def test_download_health_ok(tmp_path):
    dl = _downloader({}, tmp_path)
    assert dl.health_check().healthy is True
