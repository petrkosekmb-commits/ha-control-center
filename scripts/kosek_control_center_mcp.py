#!/usr/bin/env python3
"""Dependency-free local MCP server for HA Control Center."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import socket
import ssl
import struct
import subprocess
import sys
import time
from contextlib import contextmanager
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = "2025-03-26"
VERSION = "0.3.0"
PENDING: dict[str, dict[str, Any]] = {}
MODULE_KEYWORDS = {
    "fve": ["fve", "solar", "pv", "photovolta", "inverter", "sunways", "solarmax", "battery", "bater"],
    "tesla": ["tesla", "model_", "charging", "charger", "vehicle"],
    "traccar": ["traccar", "device_tracker", "tracker", "gps"],
}


def load_config() -> dict[str, Any]:
    raw = os.environ.pop("KCC_CONFIG_JSON", "")
    if not raw:
        return {"instances": []}
    data = json.loads(raw)
    if not data.get("instances"):
        raise RuntimeError("V nastavení není žádná Home Assistant instance.")
    return data


CONFIG = load_config()
CONFIG_PATH = Path(os.environ.get("KCC_CONFIG_PATH") or (Path(os.environ["APPDATA"]) / "KosekControlCenter" / "config.json"))
CONFIG_STAMP: tuple[int, int] | None = None


def refresh_config() -> None:
    """Reload DPAPI credentials when the local settings change, without restarting MCP."""
    global CONFIG, CONFIG_STAMP
    try:
        stat = CONFIG_PATH.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        if stamp == CONFIG_STAMP:
            return
        helper = Path(__file__).with_name("read-runtime-config.ps1")
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        # A parent PowerShell 7 runtime can pass incompatible module paths to 5.1.
        child_env = {key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"}
        result = subprocess.run(
            [str(powershell), "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(helper), "-ConfigPath", str(CONFIG_PATH)],
            capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW, env=child_env,
        )
        if result.returncode:
            raise ValueError("credential loader failed")
        updated = json.loads(result.stdout.decode("utf-8-sig"))
        if not updated.get("instances") or any(not x.get("token") for x in updated["instances"]):
            raise ValueError("missing credentials")
        after = CONFIG_PATH.stat()
        if (after.st_mtime_ns, after.st_size) != stamp:
            raise ValueError("settings changed during reload")
    except Exception:
        # Never expose helper stderr, settings contents, or a token in an MCP error.
        raise RuntimeError("Nelze nacist lokalni nastaveni konektoru. Overte soubor config.json a spusteni pod stejnym uzivatelem Windows, ktery token ulozil.") from None
    CONFIG = updated
    CONFIG_STAMP = stamp


def instance_for(args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("instance", "")).strip()
    instances = CONFIG["instances"]
    if not name and len(instances) == 1:
        return instances[0]
    for item in instances:
        if str(item.get("name", "")).casefold() == name.casefold():
            return item
    choices = ", ".join(str(x.get("name")) for x in instances)
    raise ValueError(f"Neznámá nebo neurčená instance. Dostupné: {choices}")


def ssl_context(item: dict[str, Any]) -> ssl.SSLContext:
    if item.get("verifySsl", True):
        return ssl.create_default_context()
    return ssl._create_unverified_context()


def tailscale_cli(*args: str) -> Any:
    executable = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Tailscale' / 'tailscale.exe'
    try:
        result = subprocess.run([str(executable), *args], capture_output=True, timeout=25,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise ValueError('command failed')
        return json.loads(result.stdout) if '--json' in args else None
    except Exception:
        raise RuntimeError('Tailscale nelze ovladat. Overte instalaci, opravneni a mistni prihlaseni. Zadny HA zapis nebyl zahajen.') from None


def endpoint_reachable(item: dict[str, Any]) -> bool:
    url = urllib.parse.urlparse(item['baseUrl'])
    try:
        with socket.create_connection((url.hostname, url.port or (443 if url.scheme == 'https' else 80)), timeout=3):
            return True
    except OSError:
        return False


@contextmanager
def network_lock():
    # One lock across MCP processes and the scheduled health check, held through HA I/O.
    import msvcrt
    path = CONFIG_PATH.with_name('tailscale-operation.lock')
    with path.open('a+b') as lock:
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b'0'); lock.flush()
        deadline = time.monotonic() + 45
        while True:
            try:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Jina operace HA Control Center pouziva sit. Zkuste pozdeji.') from None
                time.sleep(0.1)
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def ensure_network(item: dict[str, Any]) -> dict[str, Any]:
    route = item.get('tailscale') or {}
    if not route.get('enabled'):
        return {'action': 'not_configured'}
    if endpoint_reachable(item):
        return {'action': 'kept_current_connection'}
    profile_id = route.get('profileId')
    account = route.get('account')
    profiles = tailscale_cli('switch', '--list', '--json')
    matches = [p for p in profiles if p.get('id') == profile_id and p.get('account') == account]
    if len(matches) != 1:
        raise RuntimeError('Prirazeny profil Tailscale chybi nebo ma jiny ucet. Prihlaste spravny ucet mistne; profil se nehada.')
    previous = next((p['id'] for p in profiles if p.get('selected')), None)
    changed = previous != profile_id
    if changed and previous is None:
        raise RuntimeError('Nelze urcit aktivni profil Tailscale; automaticke prepnuti zastaveno.')
    try:
        if changed:
            tailscale_cli('switch', profile_id)
        state = tailscale_cli('status', '--json')
        if state.get('BackendState') == 'Stopped':
            tailscale_cli('up', '--timeout=15s')
            state = tailscale_cli('status', '--json')
        if state.get('BackendState') != 'Running':
            raise RuntimeError('Tailscale vyzaduje mistni prihlaseni nebo schvaleni zarizeni.')
        selected = [p for p in tailscale_cli('switch', '--list', '--json') if p.get('selected')]
        if len(selected) != 1 or selected[0].get('id') != profile_id or selected[0].get('account') != account:
            raise RuntimeError('Aktivni profil Tailscale neodpovida prirazeni domu.')
        for attempt in range(5):
            if endpoint_reachable(item):
                return {'action': 'switched_profile' if changed else 'reconnected', 'profile_id': profile_id}
            if attempt < 4:
                time.sleep(1)
        raise RuntimeError('Cilovy Home Assistant neni dostupny ani ve spravnem profilu Tailscale.')
    except Exception as exc:
        if changed:
            try:
                tailscale_cli('switch', previous)
            except Exception:
                raise RuntimeError('Pripojeni selhalo a puvodni profil Tailscale se nepodarilo obnovit. Overte Tailscale mistne.') from None
        raise exc


def execute_tool(name: str, args: dict[str, Any]) -> Any:
    if name == 'list_instances':
        return TOOLS[name][2](args)
    target_args = args
    if name in ('confirm_service_call', 'confirm_dashboard_save'):
        pending = PENDING.get(str(args.get('confirmation_code', '')))
        if not pending:
            return TOOLS[name][2](args)
        target_args = {'instance': pending['instance']}
    item = instance_for(target_args)
    if not (item.get('tailscale') or {}).get('enabled'):
        return TOOLS[name][2](args)
    with network_lock():
        network = ensure_network(item)
        value = TOOLS[name][2](args)
        if isinstance(value, dict):
            value['network'] = network
        return value


class ConnectionProblem(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def token_metadata(token: str, now: float | None = None) -> dict[str, Any]:
    """Read only expiry claims, never treat unverified JWT claims as authorization."""
    try:
        part = token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
        exp = claims['exp']
        if isinstance(exp, bool) or not isinstance(exp, (int, float)):
            raise ValueError('invalid expiry')
        expiry = datetime.fromtimestamp(exp, timezone.utc)
        remaining = exp - (datetime.now(timezone.utc).timestamp() if now is None else now)
        return {'expires_utc': expiry.isoformat(), 'days_remaining': int(remaining // 86400),
                'warning_days': 0 if remaining <= 0 else 30 if remaining <= 30 * 86400 else 90 if remaining <= 90 * 86400 else None,
                'expiry_state': 'expired' if remaining <= 0 else 'expiring_soon' if remaining <= 90 * 86400 else 'valid_by_date',
                'claims_verified': False}
    except (ValueError, TypeError, KeyError, IndexError, OverflowError, OSError):
        return {'expiry_state': 'unknown', 'claims_verified': False}


def rejected_token(item: dict[str, Any]) -> ConnectionProblem:
    state = token_metadata(str(item.get('token', '')))['expiry_state']
    detail = ('Token je podle sveho data po platnosti.' if state == 'expired' else
              'Datum platnosti tokenu dosud neuplynulo; mohl byt zrusen nebo patrit jine instanci.' if state in ('valid_by_date', 'expiring_soon') else
              'Datum platnosti tokenu nelze urcit.')
    return ConnectionProblem('auth_rejected', f"Home Assistant odmitl token (401). {detail} Overte ucet a instanci; pro bezpecnou vymenu pouzijte scripts/update-token.ps1. Hodnotu tokenu neposilejte do chatu.")


def connection_health(args: dict[str, Any]) -> dict[str, Any]:
    item = instance_for(args)
    result = {'instance': item['name'], 'checked_utc': datetime.now(timezone.utc).isoformat(),
              'token': token_metadata(str(item.get('token', '')))}
    try:
        reply = api_request(item, '/api/')
        if not isinstance(reply, dict) or reply.get('message') != 'API running.':
            raise ConnectionProblem('unexpected_response', 'Adresa nevraci ocekavane Home Assistant API.')
        result.update(status='ok', message='Pripojeni overeno.')
        if result['token']['expiry_state'] == 'expiring_soon':
            result.update(status='warning', message='Token vyprsi do 90 dni; pripravte jeho vymenu.')
        if result['token']['expiry_state'] == 'expired':
            result.update(status='warning', message='API token prijalo, ale mistni cas a datum tokenu si odporuji. Overte hodiny.')
    except ConnectionProblem as exc:
        result.update(status=exc.code, message=str(exc))
    return result


def api_request(item: dict[str, Any], path: str, method: str = "GET", payload: Any = None) -> Any:
    url = str(item["baseUrl"]).rstrip("/") + path
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {item['token']}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30, context=ssl_context(item)) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise rejected_token(item) from None
        raise ConnectionProblem('permission_denied' if exc.code == 403 else 'http_error', f'Home Assistant HTTP {exc.code}.') from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, 'reason', exc)
        if isinstance(reason, ssl.SSLCertVerificationError):
            raise ConnectionProblem('tls_error', 'Nelze overit certifikat Home Assistantu. Overte certifikat a systemovy cas; nevypinejte overovani TLS.') from None
        raise ConnectionProblem('unreachable', 'Home Assistant neni dostupny. Overte adresu, sit nebo VPN. Tato chyba sama o sobe neznamena neplatny token.') from None
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    if "json" in content_type or text[:1] in "[{":
        return json.loads(text)
    return text


class SimpleWebSocket:
    def __init__(self, item: dict[str, Any]):
        parsed = urllib.parse.urlparse(str(item["baseUrl"]))
        secure = parsed.scheme == "https"
        host = parsed.hostname or ""
        port = parsed.port or (443 if secure else 80)
        path = parsed.path.rstrip("/") + "/api/websocket"
        raw_sock = socket.create_connection((host, port), timeout=30)
        self.sock = ssl_context(item).wrap_socket(raw_sock, server_hostname=host) if secure else raw_sock
        self.sock.settimeout(30)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        host_header = host if port in (80, 443) else f"{host}:{port}"
        request = (
            f"GET {path} HTTP/1.1\r\nHost: {host_header}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                self.sock.close()
                raise RuntimeError('WebSocket spojeni skoncilo pred dokoncenim handshake.')
            response += chunk
            if len(response) > 65536:
                self.sock.close()
                raise RuntimeError("Neplatná WebSocket odpověď.")
        header, self.buffer = response.split(b"\r\n\r\n", 1)
        expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode('ascii')).digest())
        fields = dict(line.split(b':', 1) for line in header.split(b'\r\n')[1:] if b':' in line)
        accept = next((v.strip() for k, v in fields.items() if k.lower() == b'sec-websocket-accept'), None)
        if b" 101 " not in header.split(b"\r\n", 1)[0] or accept != expected:
            self.sock.close()
            raise RuntimeError('Server neprovedl platny WebSocket handshake.')

    def _exact(self, size: int) -> bytes:
        data, self.buffer = self.buffer[:size], self.buffer[size:]
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise RuntimeError("WebSocket spojení bylo ukončeno.")
            data += chunk
        return data

    def send(self, value: Any, opcode: int = 1) -> None:
        payload = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode("utf-8")
        mask = os.urandom(4)
        length = len(payload)
        head = bytes([0x80 | opcode])
        if length < 126:
            head += bytes([0x80 | length])
        elif length < 65536:
            head += bytes([0x80 | 126]) + struct.pack("!H", length)
        else:
            head += bytes([0x80 | 127]) + struct.pack("!Q", length)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(head + mask + masked)

    def receive(self) -> dict[str, Any]:
        while True:
            first, second = self._exact(2)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._exact(8))[0]
            mask = self._exact(4) if second & 0x80 else b""
            payload = self._exact(length)
            if mask:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 8:
                raise RuntimeError("Home Assistant ukončil WebSocket spojení.")
            if opcode == 9:
                self.send(payload, opcode=10)
                continue
            if opcode == 1:
                return json.loads(payload.decode("utf-8"))

    def close(self) -> None:
        try:
            self.send(b"", opcode=8)
        except Exception:
            pass
        self.sock.close()


def websocket_command(item: dict[str, Any], command: dict[str, Any]) -> Any:
    ws = SimpleWebSocket(item)
    try:
        hello = ws.receive()
        if hello.get("type") != "auth_required":
            raise RuntimeError(f"Neočekávaná autentizační odpověď: {hello}")
        ws.send({"type": "auth", "access_token": item["token"]})
        auth = ws.receive()
        if auth.get("type") != "auth_ok":
            raise rejected_token(item)
        command = dict(command)
        command["id"] = 1
        ws.send(command)
        while True:
            result = ws.receive()
            if result.get("id") == 1:
                if not result.get("success"):
                    raise RuntimeError(f"Home Assistant WebSocket chyba: {result.get('error')}")
                return result.get("result")
    finally:
        ws.close()


def compact_state(state: dict[str, Any]) -> dict[str, Any]:
    attrs = state.get("attributes") or {}
    keep = {key: attrs[key] for key in ("friendly_name", "unit_of_measurement", "device_class", "icon") if key in attrs}
    return {"entity_id": state.get("entity_id"), "state": state.get("state"), "attributes": keep,
            "last_changed": state.get("last_changed"), "last_updated": state.get("last_updated")}


def list_instances(_: dict[str, Any]) -> Any:
    return [{"name": x.get("name"), "base_url": x.get("baseUrl"), "verify_ssl": x.get("verifySsl", True)} for x in CONFIG["instances"]]


def ha_status(args: dict[str, Any]) -> Any:
    item = instance_for(args)
    root = api_request(item, "/api/")
    config = api_request(item, "/api/config")
    states = api_request(item, "/api/states")
    unavailable = [compact_state(x) for x in states if x.get("state") in ("unavailable", "unknown")]
    return {"instance": item["name"], "api": root, "version": config.get("version"),
            "location_name": config.get("location_name"), "time_zone": config.get("time_zone"),
            "entity_count": len(states), "unavailable_count": len(unavailable), "unavailable_sample": unavailable[:50]}


def search_entities(args: dict[str, Any]) -> Any:
    item = instance_for(args)
    query = str(args.get("query", "")).casefold().strip()
    domain = str(args.get("domain", "")).casefold().strip()
    wanted_state = str(args.get("state", "")).casefold().strip()
    limit = max(1, min(int(args.get("limit", 50)), 200))
    result = []
    for state in api_request(item, "/api/states"):
        entity_id = str(state.get("entity_id", ""))
        friendly = str((state.get("attributes") or {}).get("friendly_name", ""))
        haystack = f"{entity_id} {friendly}".casefold()
        if query and query not in haystack:
            continue
        if domain and not entity_id.casefold().startswith(domain + "."):
            continue
        if wanted_state and str(state.get("state", "")).casefold() != wanted_state:
            continue
        result.append(compact_state(state))
        if len(result) >= limit:
            break
    return {"instance": item["name"], "matches": result, "returned": len(result), "limit": limit}


def get_state(args: dict[str, Any]) -> Any:
    item = instance_for(args)
    entity_id = urllib.parse.quote(str(args["entity_id"]), safe="._-")
    return api_request(item, f"/api/states/{entity_id}")


def module_summary(args: dict[str, Any]) -> Any:
    item = instance_for(args)
    module = str(args.get("module", "")).casefold()
    if module not in MODULE_KEYWORDS:
        raise ValueError("Modul musí být fve, tesla nebo traccar.")
    matches = []
    for state in api_request(item, "/api/states"):
        friendly = str((state.get("attributes") or {}).get("friendly_name", ""))
        haystack = f"{state.get('entity_id', '')} {friendly}".casefold()
        if any(word in haystack for word in MODULE_KEYWORDS[module]):
            matches.append(compact_state(state))
    problems = [x for x in matches if x.get("state") in ("unavailable", "unknown", "none", "")]
    return {"instance": item["name"], "module": module, "matched_count": len(matches),
            "problem_count": len(problems), "problems": problems[:100], "entities": matches[:200]}


def get_error_log(args: dict[str, Any]) -> Any:
    item = instance_for(args)
    text = str(api_request(item, "/api/error_log"))
    max_chars = max(1000, min(int(args.get("max_chars", 30000)), 100000))
    return {"instance": item["name"], "truncated": len(text) > max_chars, "log": text[-max_chars:]}


def get_history(args: dict[str, Any]) -> Any:
    item = instance_for(args)
    entity_id = str(args["entity_id"])
    hours = max(1, min(int(args.get("hours", 24)), 168))
    start = datetime.now(timezone.utc).timestamp() - hours * 3600
    iso = datetime.fromtimestamp(start, timezone.utc).isoformat()
    query = urllib.parse.urlencode({"filter_entity_id": entity_id, "minimal_response": "", "no_attributes": ""})
    return api_request(item, f"/api/history/period/{urllib.parse.quote(iso, safe=':+-')}?{query}")


def list_dashboards(args: dict[str, Any]) -> Any:
    item = instance_for(args)
    return {"instance": item["name"], "dashboards": websocket_command(item, {"type": "lovelace/dashboards/list"})}


def dashboard_config(item: dict[str, Any], url_path: str) -> Any:
    command: dict[str, Any] = {"type": "lovelace/config"}
    if url_path:
        command["url_path"] = url_path
    return websocket_command(item, command)


def get_dashboard(args: dict[str, Any]) -> Any:
    item = instance_for(args)
    url_path = str(args.get("url_path", "")).strip()
    config = dashboard_config(item, url_path)
    return {"instance": item["name"], "url_path": url_path, "sha256": json_sha(config), "config": config}


def json_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-") or "default"


def local_backup(item: dict[str, Any], url_path: str, config: Any) -> Path:
    root = Path(CONFIG.get("localBackupRoot") or (Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "KosekControlCenter" / "backups"))
    folder = root / safe_name(str(item["name"])) / "lovelace"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = folder / f"{safe_name(url_path or 'default')}-before-{stamp}.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def prepare_dashboard_save(args: dict[str, Any]) -> Any:
    item = instance_for(args)
    url_path = str(args.get("url_path", "")).strip()
    proposed = args["config"]
    current = dashboard_config(item, url_path)
    current_sha = json_sha(current)
    expected = str(args.get("expected_current_sha256", "")).strip()
    if expected and expected != current_sha:
        raise RuntimeError("Živý dashboard se od načtení změnil. Načtěte jej znovu a připravte nový návrh.")
    backup = local_backup(item, url_path, current)
    code = secrets.token_urlsafe(8)
    PENDING[code] = {"kind": "dashboard", "instance": item["name"], "url_path": url_path,
                     "config": proposed, "current_sha": current_sha, "backup": str(backup)}
    return {"status": "prepared_not_saved", "confirmation_code": code, "instance": item["name"],
            "url_path": url_path, "current_sha256": current_sha, "proposed_sha256": json_sha(proposed),
            "local_backup": str(backup),
            "instruction": "Návrh je připraven a zálohován. Pokud změnu pokrývá konkrétní pokyn uživatele, pokračujte confirm_dashboard_save bez dalšího potvrzování."}


def confirm_dashboard_save(args: dict[str, Any]) -> Any:
    code = str(args.get("confirmation_code", ""))
    pending = PENDING.pop(code, None)
    if not pending or pending.get("kind") != "dashboard":
        raise ValueError("Neznámý nebo expirovaný potvrzovací kód.")
    item = instance_for({"instance": pending["instance"]})
    current = dashboard_config(item, pending["url_path"])
    if json_sha(current) != pending["current_sha"]:
        raise RuntimeError("Živý dashboard se po přípravě změnil. Uložení bylo zastaveno.")
    command = {"type": "lovelace/config/save", "config": pending["config"]}
    if pending["url_path"]:
        command["url_path"] = pending["url_path"]
    websocket_command(item, command)
    verified = dashboard_config(item, pending["url_path"])
    expected = json_sha(pending["config"])
    actual = json_sha(verified)
    return {"status": "saved_and_verified" if expected == actual else "saved_but_verification_mismatch",
            "instance": item["name"], "url_path": pending["url_path"], "expected_sha256": expected,
            "actual_sha256": actual, "local_backup": pending["backup"]}


def prepare_service_call(args: dict[str, Any]) -> Any:
    item = instance_for(args)
    preview = {"instance": item["name"], "domain": str(args["domain"]), "service": str(args["service"]),
               "service_data": args.get("service_data") or {}}
    code = secrets.token_urlsafe(8)
    PENDING[code] = {"kind": "service", **preview}
    return {"status": "prepared_not_called", "confirmation_code": code, "preview": preview,
            "instruction": "Volání je připraveno. Pokud službu a její rozsah pokrývá konkrétní pokyn uživatele, pokračujte confirm_service_call bez dalšího potvrzování."}


def confirm_service_call(args: dict[str, Any]) -> Any:
    code = str(args.get("confirmation_code", ""))
    pending = PENDING.pop(code, None)
    if not pending or pending.get("kind") != "service":
        raise ValueError("Neznámý nebo expirovaný potvrzovací kód.")
    item = instance_for({"instance": pending["instance"]})
    domain = urllib.parse.quote(pending["domain"], safe="_-")
    service = urllib.parse.quote(pending["service"], safe="_-")
    result = api_request(item, f"/api/services/{domain}/{service}", "POST", pending["service_data"])
    return {"status": "called", "instance": item["name"], "domain": pending["domain"],
            "service": pending["service"], "result": result}


def save_dashboard(args: dict[str, Any]) -> Any:
    """Apply a requested change with backup, conflict detection and read-back."""
    if not str(args.get("expected_current_sha256", "")).strip():
        raise ValueError("Předejte expected_current_sha256 z posledního načtení dashboardu.")
    prepared = prepare_dashboard_save(args)
    return confirm_dashboard_save({"confirmation_code": prepared["confirmation_code"]})


def call_service(args: dict[str, Any]) -> Any:
    """Execute a service already covered by the user's concrete request."""
    prepared = prepare_service_call(args)
    return confirm_service_call({"confirmation_code": prepared["confirmation_code"]})


SENSITIVE_KEY = re.compile(r"token|password|secret|api[_-]?key|authorization|credential", re.I)
SENSITIVE_VALUE = re.compile(r"(?i)([?&](?:token|api[_-]?key|auth|access_token)=)[^&\s]+|Bearer\s+[A-Za-z0-9._~+/=-]+")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "[REDACTED]" if SENSITIVE_KEY.search(str(key)) else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return SENSITIVE_VALUE.sub(lambda match: match.group(1) + "[REDACTED]" if match.lastindex else "[REDACTED]", value)
    return value


def export_dashboard_sanitized(args: dict[str, Any]) -> Any:
    item = instance_for(args)
    url_path = str(args.get("url_path", "")).strip()
    config = redact(dashboard_config(item, url_path))
    root = Path(CONFIG.get("localExportRoot") or (Path.home() / "Documents" / "Codex" / "Home Assistant"))
    folder = root / "01-dashboards" / safe_name(str(item["name"])) / "exports"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = folder / f"{safe_name(url_path or 'default')}-{stamp}-sanitized.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "exported_sanitized", "instance": item["name"], "url_path": url_path,
            "path": str(path), "sha256": json_sha(config)}


INSTANCE = {"type": "string", "description": "Název instance; lze vynechat, pokud je nastavena právě jedna."}
TOOLS: dict[str, tuple[str, dict[str, Any], Any]] = {
    "connection_health": ("Overit pripojeni a datum platnosti tokenu bez vypsani prihlasovacich udaju.", {"type": "object", "properties": {"instance": INSTANCE}}, connection_health),
    "list_instances": ("Vypsat bezpečné názvy nastavených instancí bez tokenů.", {"type": "object", "properties": {}}, list_instances),
    "status": ("Souhrn připojení, verze a nedostupných entit. Pouze čtení.", {"type": "object", "properties": {"instance": INSTANCE}}, ha_status),
    "search_entities": ("Hledat živé entity podle názvu, domény nebo stavu.", {"type": "object", "properties": {"instance": INSTANCE, "query": {"type": "string"}, "domain": {"type": "string"}, "state": {"type": "string"}, "limit": {"type": "integer", "default": 50, "maximum": 200}}}, search_entities),
    "get_state": ("Načíst úplný živý stav jedné entity.", {"type": "object", "required": ["entity_id"], "properties": {"instance": INSTANCE, "entity_id": {"type": "string"}}}, get_state),
    "module_summary": ("Shrnout entity oblasti FVE, Tesla nebo Traccar.", {"type": "object", "required": ["module"], "properties": {"instance": INSTANCE, "module": {"type": "string", "enum": ["fve", "tesla", "traccar"]}}}, module_summary),
    "get_error_log": ("Načíst konec živého Home Assistant error logu.", {"type": "object", "properties": {"instance": INSTANCE, "max_chars": {"type": "integer", "default": 30000, "maximum": 100000}}}, get_error_log),
    "get_history": ("Načíst historii jedné entity za 1 až 168 hodin.", {"type": "object", "required": ["entity_id"], "properties": {"instance": INSTANCE, "entity_id": {"type": "string"}, "hours": {"type": "integer", "default": 24, "maximum": 168}}}, get_history),
    "list_dashboards": ("Vypsat živé Lovelace dashboardy přes WebSocket.", {"type": "object", "properties": {"instance": INSTANCE}}, list_dashboards),
    "get_dashboard": ("Načíst živou konfiguraci Lovelace dashboardu a její SHA-256.", {"type": "object", "properties": {"instance": INSTANCE, "url_path": {"type": "string"}}}, get_dashboard),
    "prepare_dashboard_save": ("Připravit změnu dashboardu, ověřit živý otisk a vytvořit lokální zálohu. Nic neukládá.", {"type": "object", "required": ["config"], "properties": {"instance": INSTANCE, "url_path": {"type": "string"}, "config": {"type": "object"}, "expected_current_sha256": {"type": "string"}}}, prepare_dashboard_save),
    "confirm_dashboard_save": ("Uložit připravený dashboard v rozsahu pokynu uživatele bez dalšího potvrzování; ověřit živý otisk a výsledek.", {"type": "object", "required": ["confirmation_code"], "properties": {"confirmation_code": {"type": "string"}}}, confirm_dashboard_save),
    "prepare_service_call": ("Připravit přesný náhled volání Home Assistant služby. Nic nevolá.", {"type": "object", "required": ["domain", "service"], "properties": {"instance": INSTANCE, "domain": {"type": "string"}, "service": {"type": "string"}, "service_data": {"type": "object"}}}, prepare_service_call),
    "confirm_service_call": ("Provést připravené volání služby v rozsahu pokynu uživatele bez dalšího potvrzování.", {"type": "object", "required": ["confirmation_code"], "properties": {"confirmation_code": {"type": "string"}}}, confirm_service_call),
    "save_dashboard": ("Uložit dashboard podle konkrétního pokynu uživatele bez dalšího potvrzování. Automaticky zálohuje, kontroluje souběžné změny a ověří uložený obsah.", {"type": "object", "required": ["config", "expected_current_sha256"], "properties": {"instance": INSTANCE, "url_path": {"type": "string"}, "config": {"type": "object"}, "expected_current_sha256": {"type": "string", "minLength": 1}}}, save_dashboard),
    "call_service": ("Provést Home Assistant službu podle konkrétního pokynu uživatele bez dalšího potvrzování. Po volání ověřte stav dotčených entit.", {"type": "object", "required": ["domain", "service"], "properties": {"instance": INSTANCE, "domain": {"type": "string"}, "service": {"type": "string"}, "service_data": {"type": "object"}}}, call_service),
    "export_dashboard_sanitized": ("Na výslovnou žádost uložit očištěný dashboard lokálně bez zjevných tokenů a hesel.", {"type": "object", "properties": {"instance": INSTANCE, "url_path": {"type": "string"}}}, export_dashboard_sanitized),
}


def response(request_id: Any, result: Any = None, error: Any = None) -> dict[str, Any]:
    payload = {"jsonrpc": "2.0", "id": request_id}
    payload["error" if error is not None else "result"] = error if error is not None else result
    return payload


def handle(request: dict[str, Any]) -> dict[str, Any] | None:
    request_id = request.get("id")
    method = request.get("method")
    if method == "initialize":
        return response(request_id, {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "kosek-control-center", "version": VERSION}})
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return response(request_id, {})
    if method == "tools/list":
        return response(request_id, {"tools": [{"name": name, "description": item[0], "inputSchema": item[1]} for name, item in TOOLS.items()]})
    if method == "tools/call":
        params = request.get("params", {})
        name = params.get("name")
        if name not in TOOLS:
            return response(request_id, error={"code": -32601, "message": f"Neznámý nástroj: {name}"})
        try:
            refresh_config()
            value = execute_tool(name, params.get("arguments", {}))
            return response(request_id, {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}], "isError": False})
        except Exception as exc:
            return response(request_id, {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}], "isError": True})
    if request_id is not None:
        return response(request_id, error={"code": -32601, "message": f"Metoda neexistuje: {method}"})
    return None


def main() -> None:
    if '--health-check' in sys.argv:
        try:
            refresh_config()
            # Background monitoring must never switch the user's network profile.
            with network_lock():
                checks = [connection_health({'instance': item['name']}) for item in CONFIG['instances']]
            print(json.dumps({'checks': checks}, ensure_ascii=False))
            sys.exit(0 if all(x['status'] == 'ok' for x in checks) else 1)
        except Exception:
            print(json.dumps({'checks': [], 'status': 'config_error', 'message': 'Nelze nacist nastaveni nebo dokoncit kontrolu.'}))
            sys.exit(2)
    for line in sys.stdin.buffer:
        try:
            request = json.loads(line.decode("utf-8-sig"))
            result = handle(request)
            if result is not None:
                sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            sys.stderr.write(f"HA Control Center MCP chyba: {exc}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    main()
