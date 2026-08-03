"""접속 암호로 잠그는 정적 대시보드 + 수집 데이터 암호화 저장.

기존 `gogodive/sales-dashboard` 와 동일한 방식을 쓴다.

    payload = base64( salt[16] || nonce[12] || AES-GCM(암호문) )
    key     = PBKDF2-HMAC-SHA256(password, salt, 600_000회, 32바이트)

브라우저는 WebCrypto 로 같은 파라미터를 써서 복호화한다. 데이터 자체가
암호화돼 있으므로 저장소가 public 이어도 암호를 모르면 아무것도 읽을 수 없다.

수집 원본(data/*.json)도 같은 방식으로 묶어 `data/state.enc` 하나로 커밋한다.
그래야 모니터링 채널 목록이 public 저장소에 노출되지 않는다.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERATIONS = 600_000
SALT_BYTES = 16
NONCE_BYTES = 12
STATE_FILE = "state.enc"


class MissingPassword(RuntimeError):
    pass


def require_password() -> str:
    pw = os.environ.get("DASHBOARD_PASSWORD")
    if not pw:
        raise MissingPassword(
            "DASHBOARD_PASSWORD 환경변수가 없습니다.\n"
            "  · 대시보드 접속 암호이자 수집 데이터 암호화 키입니다.\n"
            "  · GitHub → Settings → Secrets → DASHBOARD_PASSWORD 로 등록하세요.")
    return pw


def _derive(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=ITERATIONS)
    return kdf.derive(password.encode("utf-8"))


def encrypt(plaintext: bytes, password: str) -> str:
    """salt || nonce || 암호문 을 base64 문자열로."""
    salt = os.urandom(SALT_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(_derive(password, salt)).encrypt(nonce, plaintext, None)
    return base64.b64encode(salt + nonce + ciphertext).decode("ascii")


def decrypt(payload: str, password: str) -> bytes:
    raw = base64.b64decode(payload)
    salt, nonce, ciphertext = (raw[:SALT_BYTES],
                               raw[SALT_BYTES:SALT_BYTES + NONCE_BYTES],
                               raw[SALT_BYTES + NONCE_BYTES:])
    return AESGCM(_derive(password, salt)).decrypt(nonce, ciphertext, None)


# ---------- 수집 데이터 암호화 저장 ----------

def _state_files(data_dir: Path) -> list[Path]:
    return sorted(p for p in data_dir.glob("*.json"))


def save_state(data_dir: str | Path, password: str) -> Path:
    """data/*.json 을 한 덩어리로 묶어 암호화해 data/state.enc 로 저장한다."""
    data_dir = Path(data_dir)
    bundle = {p.name: json.loads(p.read_text(encoding="utf-8"))
              for p in _state_files(data_dir)}
    payload = encrypt(json.dumps(bundle, ensure_ascii=False).encode("utf-8"), password)
    path = data_dir / STATE_FILE
    path.write_text(payload, encoding="utf-8")
    return path


def load_state(data_dir: str | Path, password: str) -> int:
    """data/state.enc 를 풀어 개별 json 파일로 되돌린다. 없으면 0을 반환."""
    data_dir = Path(data_dir)
    path = data_dir / STATE_FILE
    if not path.exists():
        return 0
    bundle = json.loads(decrypt(path.read_text(encoding="utf-8"), password))
    data_dir.mkdir(parents=True, exist_ok=True)
    for name, content in bundle.items():
        (data_dir / name).write_text(
            json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(bundle)


# ---------- 암호 입력 화면 ----------

GATE_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>__TITLE__</title>
<style>
  * {{ box-sizing: border-box; margin: 0; }}
  body {{ background: #f9f9f7; color: #0b0b0b; min-height: 100vh;
         display: flex; align-items: center; justify-content: center;
         font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
  .box {{ background: #fcfcfb; border: 1px solid rgba(11,11,11,0.10); border-radius: 12px;
         padding: 32px; width: 340px; }}
  h1 {{ font-size: 17px; font-weight: 650; }}
  p {{ font-size: 13px; color: #52514e; margin-top: 6px; }}
  input {{ width: 100%; margin-top: 16px; padding: 10px 12px; font: inherit;
          border: 1px solid #c3c2b7; border-radius: 8px; }}
  button {{ width: 100%; margin-top: 10px; padding: 10px; font: inherit; font-weight: 600;
           color: #fff; background: #2a78d6; border: 0; border-radius: 8px; cursor: pointer; }}
  button:disabled {{ opacity: .6; cursor: default; }}
  .err {{ color: #d03b3b; font-size: 13px; margin-top: 10px; display: none; }}
</style>
</head>
<body>
<div class="box">
  <h1>🔒 __TITLE__</h1>
  <p>내부 자료입니다. 노션에 안내된 접속 암호를 입력하세요.</p>
  <form id="f">
    <input type="password" id="pw" placeholder="접속 암호" autocomplete="current-password" autofocus>
    <button id="btn" type="submit">열기</button>
    <div class="err" id="err">암호가 올바르지 않습니다.</div>
  </form>
</div>
<script>
const PAYLOAD = "__PAYLOAD__";
const ITER = {iterations};

async function decrypt(password) {{
  const raw = Uint8Array.from(atob(PAYLOAD), c => c.charCodeAt(0));
  const salt = raw.slice(0, 16), nonce = raw.slice(16, 28), ct = raw.slice(28);
  const keyMaterial = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
  const key = await crypto.subtle.deriveKey(
    {{ name: "PBKDF2", salt, iterations: ITER, hash: "SHA-256" }},
    keyMaterial, {{ name: "AES-GCM", length: 256 }}, false, ["decrypt"]);
  const plain = await crypto.subtle.decrypt({{ name: "AES-GCM", iv: nonce }}, key, ct);
  return new TextDecoder().decode(plain);
}}

async function tryOpen(password, silent) {{
  const btn = document.getElementById("btn");
  btn.disabled = true; btn.textContent = "확인 중…";
  try {{
    const html = await decrypt(password);
    sessionStorage.setItem("{storage_key}", password);
    document.open(); document.write(html); document.close();
  }} catch (e) {{
    btn.disabled = false; btn.textContent = "열기";
    if (!silent) document.getElementById("err").style.display = "block";
  }}
}}

document.getElementById("f").addEventListener("submit", ev => {{
  ev.preventDefault();
  tryOpen(document.getElementById("pw").value, false);
}});
const saved = sessionStorage.getItem("{storage_key}");
if (saved) tryOpen(saved, true);
</script>
</body>
</html>
"""


def build_gate_html(inner_html: str, password: str, title: str,
                    storage_key: str = "ytref_pw") -> str:
    """대시보드 HTML을 암호화해 암호 입력 화면으로 감싼다."""
    payload = encrypt(inner_html.encode("utf-8"), password)
    return (GATE_TEMPLATE
            .format(iterations=ITERATIONS, storage_key=storage_key)
            .replace("__TITLE__", title)
            .replace("__PAYLOAD__", payload))
