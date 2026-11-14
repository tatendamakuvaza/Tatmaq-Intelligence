"""Storage backends and AI provider clients, exercised against local files and scripted HTTP.

The Supabase and AI-provider tests check that requests are formed as those services
document them. They do not replace a check against the live service.
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

from app.llm import AnthropicClient, LLMError, LLMTemporaryError, OpenAICompatibleClient, parse_json_object
from app.security.signing import InvalidLink, sign, unsign
from app.storage import LocalStorage, ObjectExists, ObjectNotFound, StorageError, SupabaseStorage


def test_local_storage_rejects_unsafe_keys_and_never_overwrites_by_default(tmp_path):
    storage = LocalStorage(tmp_path / "store", "secret")
    source = tmp_path / "file.bin"
    source.write_bytes(b"one")
    for key in ("../outside.txt", "/etc/passwd", "org/../../x", "org//x", "org/x y", "", "org/\x00"):
        with pytest.raises(StorageError):
            storage.path(key)
    storage.put_file("org/a/file.bin", source, content_type="x")
    with pytest.raises(ObjectExists):
        storage.put_file("org/a/file.bin", source, content_type="x")
    source.write_bytes(b"two")
    storage.put_file("org/a/file.bin", source, content_type="x", overwrite=True)  # derived files may be replaced
    assert storage.size("org/a/file.bin") == 3 and storage.exists("org/a/file.bin")
    with pytest.raises(ObjectNotFound):
        storage.size("org/a/missing.bin")
    upload = storage.create_upload_target("org/a/new.csv", content_type="text/csv", max_bytes=10, ttl_seconds=60)
    assert upload.method == "PUT" and upload.url.startswith("/v1/uploads/")


def test_signed_links_expire_and_are_bound_to_one_purpose():
    link = sign({"k": "org/a/x.pdf"}, purpose="download", secret="s3cret", ttl_seconds=60)
    assert unsign(link, purpose="download", secret="s3cret")["k"] == "org/a/x.pdf"
    for bad, kwargs in [(link, {"purpose": "upload", "secret": "s3cret"}), (link, {"purpose": "download", "secret": "other"}),
                        (link[:-2] + "xx", {"purpose": "download", "secret": "s3cret"}), ("garbage", {"purpose": "download", "secret": "s3cret"})]:  # fmt: skip
        with pytest.raises(InvalidLink):
            unsign(bad, **kwargs)
    expired = sign({"k": "x"}, purpose="download", secret="s3cret", ttl_seconds=-1)
    with pytest.raises(InvalidLink, match="expired"):
        unsign(expired, purpose="download", secret="s3cret")
    time.sleep(0)


def test_supabase_storage_forms_requests_as_documented(tmp_path):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if request.method == "POST" and "/object/upload/sign/" in path:
            return httpx.Response(200, json={"url": "/object/upload/sign/private/org/a/original.csv?token=tok123"})
        if request.method == "POST" and "/object/sign/" in path:
            return httpx.Response(200, json={"signedURL": "/object/sign/private/org/a/report.pdf?token=dl456"})
        if request.method == "HEAD":
            return httpx.Response(200 if path.endswith("original.csv") else 400)
        if request.method == "GET" and "/object/info/" in path:
            return httpx.Response(200, json={"size": 2048})
        if request.method == "GET":
            return httpx.Response(200, content=b"col\n1\n")
        if request.method == "POST":
            return (
                httpx.Response(409, json={"error": "Duplicate", "message": "The resource already exists"})
                if path.endswith("exists.parquet")
                else httpx.Response(200, json={"Key": "ok"})
            )
        return httpx.Response(500, text="boom")

    storage = SupabaseStorage(url="https://abc.supabase.co/", secret_key="sb_secret_x", bucket="private",
                              client=httpx.Client(transport=httpx.MockTransport(handler)))  # fmt: skip
    target = storage.create_upload_target("org/a/original.csv", content_type="text/csv", max_bytes=10, ttl_seconds=60)
    assert target.method == "PUT" and target.headers == {"Content-Type": "text/csv"}
    assert target.url == "https://abc.supabase.co/storage/v1/object/upload/sign/private/org/a/original.csv?token=tok123"
    assert "x-upsert" not in seen[-1].headers  # never upsert: an original cannot be replaced through an upload link
    assert seen[-1].headers["apikey"] == "sb_secret_x" and seen[-1].headers["authorization"] == "Bearer sb_secret_x"

    link = storage.create_download_url(
        "org/a/report.pdf", filename="Q3 report.pdf", content_type="application/pdf", ttl_seconds=300
    )
    assert (
        link
        == "https://abc.supabase.co/storage/v1/object/sign/private/org/a/report.pdf?token=dl456&download=Q3%20report.pdf"
    )
    assert json.loads(seen[-1].content) == {"expiresIn": 300}

    assert storage.exists("org/a/original.csv") and not storage.exists("org/a/missing.csv")
    assert storage.size("org/a/original.csv") == 2048
    destination = tmp_path / "download.csv"
    storage.download_to("org/a/original.csv", destination)
    assert destination.read_bytes() == b"col\n1\n"

    storage.put_file("org/a/raw.parquet", destination, content_type="application/x", overwrite=True)
    assert (
        seen[-1].headers["x-upsert"] == "true" and seen[-1].url.path == "/storage/v1/object/private/org/a/raw.parquet"
    )
    with pytest.raises(ObjectExists):
        storage.put_file("org/a/exists.parquet", destination, content_type="application/x")
    with pytest.raises(StorageError):
        storage.exists("../escape")


def scripted(handler):
    return httpx.MockTransport(handler)


def test_openai_compatible_client_request_and_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200, json={"model": "served-model", "usage": {"prompt_tokens": 31, "completion_tokens": 9},
                                         "choices": [{"message": {"content": '```json\n{"operations": []}\n```'}}]})  # fmt: skip

    client = OpenAICompatibleClient(
        api_key="k-123", model="any-model", base_url="https://llm.example.com/v1/", transport=scripted(handler)
    )
    response = asyncio.run(client.complete_json(system="be brief", user="plan this"))
    body = json.loads(seen["request"].content)
    assert seen["request"].url == "https://llm.example.com/v1/chat/completions"
    assert seen["request"].headers["authorization"] == "Bearer k-123"
    assert body == {"model": "any-model", "response_format": {"type": "json_object"},
                    "messages": [{"role": "system", "content": "be brief"}, {"role": "user", "content": "plan this"}]}  # fmt: skip
    assert (response.data, response.model, response.tokens_input, response.tokens_output) == (
        {"operations": []},
        "served-model",
        31,
        9,
    )


def test_anthropic_client_request_and_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200, json={"model": "m", "usage": {"input_tokens": 12, "output_tokens": 4},
                                         "content": [{"type": "text", "text": '{"ok": true}'}]})  # fmt: skip

    client = AnthropicClient(api_key="k-456", model="some-model", transport=scripted(handler))
    response = asyncio.run(client.complete_json(system="rules", user="question", max_output_tokens=500))
    body = json.loads(seen["request"].content)
    assert seen["request"].url == "https://api.anthropic.com/v1/messages"
    assert (
        seen["request"].headers["x-api-key"] == "k-456" and seen["request"].headers["anthropic-version"] == "2023-06-01"
    )
    assert body["max_tokens"] == 500 and body["messages"] == [{"role": "user", "content": "question"}]
    assert body["system"].startswith("rules") and response.data == {"ok": True} and response.tokens_input == 12


@pytest.mark.parametrize(
    ("status", "error"), [(429, LLMTemporaryError), (503, LLMTemporaryError), (401, LLMError), (400, LLMError)]
)
def test_provider_errors_are_classified(status, error):
    client = OpenAICompatibleClient(
        api_key="k", model="m", transport=scripted(lambda request: httpx.Response(status, text="nope"))
    )
    with pytest.raises(error):
        asyncio.run(client.complete_json(system="s", user="u"))

    def unreachable(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(LLMTemporaryError):
        asyncio.run(
            OpenAICompatibleClient(api_key="k", model="m", transport=scripted(unreachable)).complete_json(
                system="s", user="u"
            )
        )


def test_model_replies_are_parsed_strictly_as_json_objects():
    assert parse_json_object('{"a": 1}') == {"a": 1}
    assert parse_json_object('Here you go:\n```json\n{"a": {"b": [1, 2]}}\n```') == {"a": {"b": [1, 2]}}
    for reply in ("", "I cannot help with that.", "[1, 2, 3]", '{"a": '):
        with pytest.raises(LLMError):
            parse_json_object(reply)
