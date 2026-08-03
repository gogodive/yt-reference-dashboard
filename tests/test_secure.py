import base64
import json

import pytest

from src import secure

PW = "테스트암호1234"


def test_encrypt_decrypt_roundtrip():
    data = "한글과 English 섞인 내용 🔥".encode("utf-8")
    assert secure.decrypt(secure.encrypt(data, PW), PW) == data


def test_wrong_password_fails():
    payload = secure.encrypt(b"secret", PW)
    with pytest.raises(Exception):
        secure.decrypt(payload, "틀린암호")


def test_payload_layout_matches_browser_expectations():
    """브라우저 JS가 salt=raw[0:16], nonce=raw[16:28], ct=raw[28:] 로 자른다."""
    raw = base64.b64decode(secure.encrypt(b"x", PW))
    assert secure.SALT_BYTES == 16
    assert secure.NONCE_BYTES == 12
    assert len(raw) > 28
    # 같은 평문·같은 암호라도 salt/nonce 가 매번 달라야 한다
    other = base64.b64decode(secure.encrypt(b"x", PW))
    assert raw[:28] != other[:28]


def test_gate_html_does_not_leak_plaintext():
    """이게 이 모듈의 핵심 보안 속성이다."""
    inner = "<h1>모니터링 채널: 워터양, 물찬건어물</h1><td>조회수 46,800</td>"
    html = secure.build_gate_html(inner, PW, "테스트 대시보드")

    assert "워터양" not in html
    assert "물찬건어물" not in html
    assert "46,800" not in html
    assert "모니터링 채널" not in html
    assert PW not in html          # 암호 자체도 들어가면 안 된다


def test_gate_html_is_decryptable_with_the_password():
    inner = "<h1>대시보드 본문</h1>"
    html = secure.build_gate_html(inner, PW, "테스트")

    start = html.index('const PAYLOAD = "') + len('const PAYLOAD = "')
    payload = html[start:html.index('"', start)]
    assert secure.decrypt(payload, PW).decode("utf-8") == inner


def test_gate_html_uses_same_parameters_as_browser():
    html = secure.build_gate_html("<p>x</p>", PW, "테스트")
    assert f"const ITER = {secure.ITERATIONS};" in html
    assert "PBKDF2" in html and "SHA-256" in html and "AES-GCM" in html
    assert "raw.slice(0, 16)" in html
    assert "raw.slice(16, 28)" in html
    assert "raw.slice(28)" in html
    assert "<title>테스트</title>" in html


def test_state_roundtrip(tmp_path):
    (tmp_path / "wateryang.json").write_text(
        json.dumps({"handle": "wateryang", "videos": [{"video_id": "a"}]}), encoding="utf-8")
    (tmp_path / "_index.json").write_text(json.dumps({"p1": "wateryang"}), encoding="utf-8")

    secure.save_state(tmp_path, PW)
    enc = tmp_path / secure.STATE_FILE
    assert enc.exists()
    assert "wateryang" not in enc.read_text(encoding="utf-8")   # 채널명이 새어나오면 안 된다

    for p in tmp_path.glob("*.json"):
        p.unlink()
    assert secure.load_state(tmp_path, PW) == 2
    assert json.loads((tmp_path / "wateryang.json").read_text(encoding="utf-8"))["handle"] == "wateryang"
    assert json.loads((tmp_path / "_index.json").read_text(encoding="utf-8")) == {"p1": "wateryang"}


def test_load_state_without_file_is_a_noop(tmp_path):
    assert secure.load_state(tmp_path, PW) == 0


def test_require_password(monkeypatch):
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    with pytest.raises(secure.MissingPassword):
        secure.require_password()
    monkeypatch.setenv("DASHBOARD_PASSWORD", "abc")
    assert secure.require_password() == "abc"
