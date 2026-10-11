"""Ръбът на production: nginx и доверието на uvicorn в заглавките от него.

Одит от 11.10.2026 (сесията по сайта, потвърден на живо същия ден):

1. API-то отговаряше по чист HTTP на голия IP и на ВСЯКО име:
   `curl -H 'Host: evil.example' http://169.58.72.254/api/v1/health` → 200.
   Правилото на Ив: никой порт навън без DNS+TLS.
2. uvicorn вярваше на `X-Forwarded-For` от всеки (`--forwarded-allow-ips "*"`),
   а nginx ДОБАВЯШЕ реалния адрес към подадения от клиента. С `*` uvicorn взима
   НАЙ-ЛЕВИЯ елемент — тоест този, който клиентът е написал. Адресът в одитния
   дневник на входа (`request.client.host`) се задаваше от нападателя.
3. `nginx:1.27-alpine` (1.27.5) — стар клон, а версията излизаше в `Server`.
4. Блокът на app.heppsu.com: мъртъв `ssl_stapling` и подразбиращите се шифри
   (CBC с HMAC-SHA1, ARIA, CAMELLIA).

Три нива проверка:
- структурата на файловете (върви навсякъде, бързо);
- истинският `ProxyHeadersMiddleware` на uvicorn с точно стойността от compose;
- истинският nginx в Docker, със СЪЩИЯ образ, който compose пуска в production:
  `nginx -t` и заявки отвън (върви в CI; локално без Docker се пропуска шумно).
"""

from __future__ import annotations

import http.client
import os
import re
import shutil
import socket
import ssl
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
INFRA = ROOT / "infra"
COMPOSE = INFRA / "docker-compose.yml"
AIFOS_CONF = INFRA / "nginx" / "conf.d" / "aifos.conf"
TLS_CONF = INFRA / "nginx" / "sites-available" / "heppsu-tls.conf"
HTTP_CONF = INFRA / "nginx" / "sites-available" / "heppsu-http.conf"
DEPLOY_SH = INFRA / "deploy.sh"

# Mozilla Server Side TLS 6.0, „intermediate“, OpenSSL имена
# (https://ssl-config.mozilla.org/guidelines/latest.json). Без DHE: 6.0 ги махна,
# а и nginx без `ssl_dhparam` не ги ползва.
MOZILLA_INTERMEDIATE = [
    "ECDHE-ECDSA-AES128-GCM-SHA256",
    "ECDHE-RSA-AES128-GCM-SHA256",
    "ECDHE-ECDSA-AES256-GCM-SHA384",
    "ECDHE-RSA-AES256-GCM-SHA384",
    "ECDHE-ECDSA-CHACHA20-POLY1305",
    "ECDHE-RSA-CHACHA20-POLY1305",
]


# ── Малък парсер на nginx конфигурация ──────────────────────────────────────
#
# Достатъчен за тези файлове: директиви, блокове, кавички, коментари. Не е
# пълен nginx парсер; истинската проверка е `nginx -t` по-долу.


def _tokens(text: str):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == "#":
            while i < n and text[i] != "\n":
                i += 1
        elif c in "{};":
            yield c
            i += 1
        elif c in "\"'":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            yield text[i + 1 : j]
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in "{};":
                j += 1
            yield text[i:j]
            i = j


def parse_nginx(text: str) -> list:
    """Връща списък от (име, аргументи, деца); децата са None за проста директива."""
    stack: list[list] = [[]]
    current: list[str] = []
    for tok in _tokens(text):
        if tok == ";":
            stack[-1].append((current[0], current[1:], None))
            current = []
        elif tok == "{":
            node = (current[0], current[1:], [])
            stack[-1].append(node)
            stack.append(node[2])
            current = []
        elif tok == "}":
            stack.pop()
        else:
            current.append(tok)
    assert len(stack) == 1 and not current, "незатворен блок"
    return stack[0]


def directives(block, name):
    return [args for n, args, children in block if n == name and children is None]


def servers(tree):
    return [children for n, _, children in tree if n == "server"]


def walk(tree):
    for n, args, children in tree:
        yield n, args, children
        if children:
            yield from walk(children)


def listens(server):
    return [" ".join(a) for a in directives(server, "listen")]


def is_default(server, port: str) -> bool:
    return any(
        (lst.split()[0] in (port, f"[::]:{port}")) and "default_server" in lst.split()
        for lst in listens(server)
    )


@pytest.fixture(scope="module")
def tls_tree():
    return parse_nginx(TLS_CONF.read_text())


@pytest.fixture(scope="module")
def aifos_tree():
    return parse_nginx(AIFOS_CONF.read_text())


# ── 1. Голият IP и непознатите имена не стигат до приложението ──────────────


def test_na_production_podrazbirashtiyat_server_na_80_ne_proksira(tls_tree):
    """Заявка по IP или с чуждо име на 80 се затваря (444), без отговор."""
    default80 = [s for s in servers(tls_tree) if is_default(s, "80")]
    assert default80, "heppsu-tls.conf трябва да държи default_server на 80"
    for s in default80:
        assert {"80 default_server", "[::]:80 default_server"} <= set(listens(s))
        assert directives(s, "return") == [["444"]]
        assert not any(n == "proxy_pass" for n, _, _ in walk(s))


def test_na_production_podrazbirashtiyat_server_na_443_otkazva_rukostiskaneto(tls_tree):
    """Без SNI или с чуждо SNI TLS не стига до сертификата, нито до приложението."""
    default443 = [s for s in servers(tls_tree) if is_default(s, "443")]
    assert default443, "heppsu-tls.conf трябва да държи default_server на 443"
    for s in default443:
        assert directives(s, "ssl_reject_handshake") == [["on"]]
        assert not any(n == "proxy_pass" for n, _, _ in walk(s))


def test_obshtiyat_aifos_conf_ne_zavzema_default_server(aifos_tree):
    """aifos.conf е общ за prod, preprod и demo.

    Ако той обяви `default_server`, а файлът на production — също, nginx не
    тръгва („a duplicate default server“). Затова общият блок остава без флага:
    на preprod и demo е единственият сървър и пак хваща заявките по IP, а на
    production изричният `default_server` в nginx-extra го изпреварва.
    """
    for s in servers(aifos_tree):
        for lst in listens(s):
            assert "default_server" not in lst.split(), lst


def test_bootstrap_failat_po_http_sashto_ne_proksira_po_ip():
    """Стъпка 1 (преди сертификат) също не бива да отваря API-то по IP."""
    default80 = [s for s in servers(parse_nginx(HTTP_CONF.read_text())) if is_default(s, "80")]
    assert default80 and all(directives(s, "return") == [["444"]] for s in default80)


def test_proverkata_na_lets_encrypt_ostava_na_80(tls_tree):
    """Подновяването е webroot по http-01 (renewal/heppsu.com.conf на Phobos)."""
    named80 = [
        s for s in servers(tls_tree)
        if not is_default(s, "80") and any(lst.split()[0] in ("80", "[::]:80") for lst in listens(s))
    ]
    assert named80
    for s in named80:
        names = set(directives(s, "server_name")[0])
        assert {"heppsu.com", "www.heppsu.com", "app.heppsu.com"} <= names
        acme = [c for n, a, c in s if n == "location" and a == ["/.well-known/acme-challenge/"]]
        assert acme and directives(acme[0], "root") == [["/var/www/certbot"]]


# ── 2. Адресът на клиента не се задава от клиента ───────────────────────────


def test_nginx_prezapisva_x_forwarded_for_vmesto_da_dobavya():
    for path in (AIFOS_CONF, TLS_CONF, HTTP_CONF):
        tree = parse_nginx(path.read_text())
        seen = 0
        for n, args, children in walk(tree):
            if n == "proxy_set_header" and children is None and args[0].lower() == "x-forwarded-for":
                assert args[1] == "$remote_addr", f"{path.name}: {args}"
                seen += 1
            assert "$proxy_add_x_forwarded_for" not in args, path.name
        if any(n == "proxy_pass" for n, _, _ in walk(tree)):
            assert seen, f"{path.name} проксира, без да задава X-Forwarded-For"


def _forwarded_allow_ips() -> str:
    text = COMPOSE.read_text()
    m = re.search(r'"--forwarded-allow-ips",\s*"([^"]*)"', text)
    assert m, "uvicorn трябва да се пуска с --forwarded-allow-ips"
    return m.group(1)


def _client_seen_by_app(peer: str, xff: str | None) -> str:
    """Пуска истинския ProxyHeadersMiddleware на uvicorn със стойността от compose."""
    import asyncio

    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    seen = {}

    async def app(scope, receive, send):
        seen["client"] = scope["client"][0]

    headers = [(b"host", b"app.heppsu.com")]
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    scope = {"type": "http", "client": (peer, 51000), "headers": headers, "scheme": "http"}
    middleware = ProxyHeadersMiddleware(app, trusted_hosts=_forwarded_allow_ips())
    asyncio.run(middleware(scope, None, None))
    return seen["client"]


def test_uvicorn_ne_vyarva_na_vsekigo():
    assert _forwarded_allow_ips().strip() != "*"


def test_podpraven_x_forwarded_for_ne_stava_adres_na_klienta():
    """Старото nginx поведение: „<написано от клиента>, <реалният адрес>“.

    Дори да остане такъв ред някъде, приложението трябва да види реалния адрес
    (добавения от nginx), не подправения. Мрежата на prod е 172.20.0.0/16,
    nginx е 172.20.0.3 (docker network inspect aifos-prod_backend, 11.10.2026).
    """
    assert _client_seen_by_app("172.20.0.3", "6.6.6.6, 203.0.113.7") == "203.0.113.7"
    assert _client_seen_by_app("172.20.0.3", "203.0.113.7") == "203.0.113.7"


def test_x_forwarded_for_ot_nedoveren_izprashtach_se_prenebregva():
    """Само nginx (вътрешната мрежа на compose) може да казва кой е клиентът."""
    assert _client_seen_by_app("203.0.113.9", "6.6.6.6") == "203.0.113.9"


# ── 3. Образът и версията ───────────────────────────────────────────────────


def nginx_image() -> str:
    m = re.search(r"^  nginx:\n(?:    .*\n)*?    image:\s*(\S+)", COMPOSE.read_text(), re.M)
    assert m, "не намирам образа на nginx в compose"
    return m.group(1)


def test_obrazat_na_nginx_e_zakovan_na_poddurzhan_klon():
    image = nginx_image()
    m = re.fullmatch(r"nginx:(\d+)\.(\d+)\.(\d+)-alpine", image)
    assert m, f"образът трябва да е заковано издание x.y.z-alpine, не {image}"
    assert tuple(map(int, m.groups()[:2])) >= (1, 30), "1.27 е изоставен клон"


def test_versiyata_na_nginx_ne_izliza_navan(aifos_tree):
    """Общо за всички среди, на ниво http — важи и за страниците за грешка."""
    assert directives(aifos_tree, "server_tokens") == [["off"]]


# ── 4. TLS на app.heppsu.com ────────────────────────────────────────────────


def test_tls_po_mozilla_intermediate_za_vsichki_hostove(tls_tree):
    assert directives(tls_tree, "ssl_protocols") == [["TLSv1.2", "TLSv1.3"]]
    assert [a[0].split(":") for a in directives(tls_tree, "ssl_ciphers")] == [MOZILLA_INTERMEDIATE]
    for s in servers(tls_tree):
        # Никой server блок не връща подразбиращите се шифри или стари протоколи.
        assert not directives(s, "ssl_ciphers"), listens(s)
        assert not directives(s, "ssl_protocols"), listens(s)


def test_nyama_mrtav_ssl_stapling(tls_tree):
    """Let's Encrypt спря OCSP; nginx предупреждаваше при всяко зареждане."""
    assert not [a for n, a, _ in walk(tls_tree) if n.startswith("ssl_stapling")]


# ── deploy.sh: проверката на здравето вече не минава през голия IP ──────────


SSH_LOG_STUB = """#!/bin/sh
printf '%s\\n' "$*" >> "$SSH_LOG"
cat >/dev/null 2>&1 || true
exit 0
"""
CURL_STUB = """#!/usr/bin/env python3
import sys
adres = next((a for a in sys.argv[1:] if a.startswith("http")), "")
if adres.endswith("/openapi.json"):
    print('{"paths":{"/api/v1/support/report":{}}}')
print("ok")
"""


def _git(*args, cwd, env):
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True,
                          text=True, check=True).stdout.strip()


def _run_deploy_to_the_end(tmp_path, env_name):
    """Пуска deploy.sh до края с подставени ssh/scp/curl и връща командите към сървъра."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(origin)], check=True)
    work = tmp_path / "work"
    (work / "infra" / "ci").mkdir(parents=True)
    (work / "apps").mkdir()
    (work / "apps" / "README").write_text("x")
    (work / "infra" / "deploy.sh").write_text(DEPLOY_SH.read_text())
    (work / "infra" / "dod.yml").write_text((INFRA / "dod.yml").read_text())
    (work / "infra" / "ci" / "check_migrations.py").write_text("raise SystemExit(0)\n")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    _git("init", "--quiet", "-b", "main", str(work), cwd=tmp_path, env=env)
    _git("add", "-A", cwd=work, env=env)
    _git("commit", "--quiet", "-m", "издание", cwd=work, env=env)
    _git("remote", "add", "origin", str(origin), cwd=work, env=env)
    _git("push", "--quiet", "origin", "main", cwd=work, env=env)
    sha = _git("rev-parse", "--short", "HEAD", cwd=work, env=env)
    for etiket in ("tested", "security", "legal"):
        _git("tag", f"{etiket}/{sha}", sha, cwd=work, env=env)
        _git("push", "--quiet", "origin", f"{etiket}/{sha}", cwd=work, env=env)

    binn = tmp_path / "bin"
    binn.mkdir()
    for name, body in (("ssh", SSH_LOG_STUB), ("scp", SSH_LOG_STUB), ("curl", CURL_STUB)):
        (binn / name).write_text(body)
        (binn / name).chmod(0o755)
    log = tmp_path / "ssh.log"
    env.update(PATH=f"{binn}:{env['PATH']}", AIFOS_HOST="test-host", SSH_LOG=str(log))
    args = ["bash", "infra/deploy.sh", env_name, "main"] + ([sha] if env_name == "prod" else [])
    result = subprocess.run(args, cwd=work, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return [line for line in log.read_text().splitlines() if "/api/v1/health" in line]


def test_deploy_na_production_proverya_zdraveto_prez_imeto_i_tls(tmp_path):
    """След поправката голият IP на 80 връща 444 — старата проверка
    `curl http://127.0.0.1:80/api/v1/health` би обявила всеки деплой за провален
    и би върнала предишната версия. Проверката минава през истинското име и TLS,
    както клиентите, но към 127.0.0.1, за да не зависи от DNS."""
    health = _run_deploy_to_the_end(tmp_path, "prod")
    assert health, "deploy.sh не провери здравето"
    for line in health:
        assert "--resolve app.heppsu.com:443:127.0.0.1" in line, line
        assert "https://app.heppsu.com/api/v1/health" in line, line
        assert "http://127.0.0.1" not in line, line


def test_deploy_na_preprod_proverya_zdraveto_kakto_dosega(tmp_path):
    """Preprod няма име и сертификат — там проверката остава по IP и порт 8080."""
    health = _run_deploy_to_the_end(tmp_path, "preprod")
    assert health and all("http://127.0.0.1:8080/api/v1/health" in line for line in health)


# ── Истинският nginx в Docker, със същия образ ──────────────────────────────


def _docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


if not _docker_ok():
    if os.environ.get("CI"):
        # В CI Docker има; ако го няма, това е повреда, не причина да се пропусне.
        raise RuntimeError("CI без Docker — проверката на nginx не може да се пусне")
    docker_only = pytest.mark.skip(reason="няма Docker локално; върви в CI (api.yml)")
else:
    def docker_only(test):
        return test

UPSTREAM_CONF = """
server {
    listen 8000;
    location / {
        default_type text/plain;
        return 200 "xff=$http_x_forwarded_for|real=$http_x_real_ip|proto=$http_x_forwarded_proto|host=$host\\n";
    }
}
"""


def _docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


def _port(container, inner):
    out = _docker("port", container, f"{inner}/tcp").stdout.splitlines()[0]
    return int(out.rsplit(":", 1)[1])


def _wait_for(port):
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return
        except OSError:
            time.sleep(0.5)
    raise AssertionError(f"nginx не слуша на {port}")


def _start_edge(tmp, net, name, extra_files):
    conf_d = tmp / name / "conf.d"
    extra = tmp / name / "extra"
    conf_d.mkdir(parents=True)
    extra.mkdir()
    shutil.copy(AIFOS_CONF, conf_d / "aifos.conf")
    for src, dst in extra_files:
        shutil.copy(src, extra / dst)
    _docker(
        "run", "-d", "--name", name, "--network", net,
        "-p", "127.0.0.1::80", "-p", "127.0.0.1::443",
        "-v", f"{conf_d}:/etc/nginx/conf.d:ro",
        "-v", f"{extra}:/etc/nginx/extra:ro",
        "-v", f"{tmp / 'website'}:/var/www/heppsu:ro",
        "-v", f"{tmp / 'certbot'}:/var/www/certbot:ro",
        "-v", f"{tmp / 'letsencrypt'}:/etc/letsencrypt:ro",
        nginx_image(),
    )
    p80, p443 = _port(name, 80), _port(name, 443)
    _wait_for(p80)
    return p80, p443


@pytest.fixture(scope="module")
def edge(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("edge")
    tag = uuid.uuid4().hex[:8]
    net, upstream = f"aifos-edge-{tag}", f"aifos-edge-api-{tag}"
    prod, preprod = f"aifos-edge-prod-{tag}", f"aifos-edge-preprod-{tag}"

    live = tmp / "letsencrypt" / "live" / "heppsu.com"
    live.mkdir(parents=True)
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
         "-subj", "/CN=heppsu.com",
         "-addext", "subjectAltName=DNS:heppsu.com,DNS:www.heppsu.com,DNS:app.heppsu.com",
         "-keyout", str(live / "privkey.pem"), "-out", str(live / "fullchain.pem")],
        check=True, capture_output=True,
    )
    (live / "privkey.pem").chmod(0o644)
    (tmp / "website").mkdir()
    (tmp / "website" / "index.html").write_text("<!doctype html><title>heppsu</title>")
    acme = tmp / "certbot" / ".well-known" / "acme-challenge"
    acme.mkdir(parents=True)
    (acme / "proba-token").write_text("proba-token.otpechatak")
    (tmp / "upstream").mkdir()
    (tmp / "upstream" / "default.conf").write_text(UPSTREAM_CONF)

    _docker("network", "create", net)
    try:
        _docker("run", "-d", "--name", upstream, "--network", net, "--network-alias", "api",
                "-v", f"{tmp / 'upstream'}:/etc/nginx/conf.d:ro", nginx_image())
        prod_ports = _start_edge(tmp, net, prod, [(TLS_CONF, "heppsu.conf")])
        preprod_ports = _start_edge(tmp, net, preprod, [])
        yield {"prod": prod, "preprod": preprod, "prod_ports": prod_ports,
               "preprod_ports": preprod_ports}
    finally:
        for c in (prod, preprod, upstream):
            logs = _docker("logs", c, check=False)
            print(f"── {c}\n{logs.stdout}{logs.stderr}")
            _docker("rm", "-f", c, check=False)
        _docker("network", "rm", net, check=False)


def _http(port, host, path="/api/v1/health", headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("GET", path, headers={"Host": host, **(headers or {})})
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read().decode()
    finally:
        conn.close()


def _tls_context(ciphers=None, tls12_only=False):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    if tls12_only:
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    if ciphers:
        ctx.set_ciphers(ciphers)
    return ctx


def _https(port, sni, path="/api/v1/health", headers=None, ctx=None):
    host = sni or "127.0.0.1"
    extra = "".join(f"{k}: {v}\r\n" for k, v in (headers or {}).items())
    request = f"GET {path} HTTP/1.1\r\nHost: {host}\r\n{extra}Connection: close\r\n\r\n"
    with (
        socket.create_connection(("127.0.0.1", port), timeout=10) as raw,
        (ctx or _tls_context()).wrap_socket(raw, server_hostname=sni) as tls,
    ):
        tls.sendall(request.encode())
        data = b""
        while chunk := tls.recv(65536):
            data += chunk
    head, _, body = data.decode().partition("\r\n\r\n")
    return int(head.split()[1]), head, body


@docker_only
def test_nginx_t_minava_sas_sashtiya_obraz_i_bez_preduprezhdeniya(edge):
    for c in (edge["prod"], edge["preprod"]):
        r = _docker("exec", c, "nginx", "-t", check=False)
        assert r.returncode == 0, r.stderr
        assert "[warn]" not in r.stderr, r.stderr
        assert "[emerg]" not in r.stderr, r.stderr


@docker_only
@pytest.mark.parametrize("host", ["169.58.72.254", "evil.example"])
def test_goliyat_ip_i_chuzhdo_ime_po_http_ne_poluchavat_nishto(edge, host):
    with pytest.raises((http.client.RemoteDisconnected, ConnectionResetError)):
        _http(edge["prod_ports"][0], host)


@docker_only
@pytest.mark.parametrize("sni", [None, "evil.example", "169.58.72.254"])
def test_tls_bez_sni_ili_s_chuzhdo_ime_se_otkazva(edge, sni):
    with pytest.raises((ssl.SSLError, ConnectionResetError)):
        _https(edge["prod_ports"][1], sni)


@docker_only
def test_imenata_po_http_otivat_na_https(edge):
    status, headers, _ = _http(edge["prod_ports"][0], "app.heppsu.com")
    assert status == 301
    assert headers["Location"] == "https://app.heppsu.com/api/v1/health"
    assert headers["Server"] == "nginx"


@docker_only
def test_lets_encrypt_minava_po_http(edge):
    status, _, body = _http(edge["prod_ports"][0], "app.heppsu.com",
                            "/.well-known/acme-challenge/proba-token")
    assert (status, body) == (200, "proba-token.otpechatak")


@docker_only
def test_prilozhenieto_po_https_vizhda_istinskiya_adres(edge):
    status, head, body = _https(edge["prod_ports"][1], "app.heppsu.com",
                                headers={"X-Forwarded-For": "6.6.6.6",
                                         "X-Real-IP": "6.6.6.6"})
    assert status == 200, head
    fields = dict(part.split("=", 1) for part in body.strip().split("|"))
    assert "6.6.6.6" not in body, body
    assert fields["xff"] == fields["real"] and fields["xff"], body
    assert fields["proto"] == "https"
    assert "\r\nServer: nginx\r\n" in head + "\r\n", head


@docker_only
def test_tls_1_2_otkazva_cbc_sha1_i_priema_gcm(edge):
    port = edge["prod_ports"][1]
    with pytest.raises(ssl.SSLError):
        _https(port, "app.heppsu.com",
               ctx=_tls_context("ECDHE-RSA-AES128-SHA:@SECLEVEL=0", tls12_only=True))
    status, _, _ = _https(port, "app.heppsu.com",
                          ctx=_tls_context("ECDHE-RSA-AES128-GCM-SHA256", tls12_only=True))
    assert status == 200


@docker_only
def test_preprod_i_demo_bez_ime_prodalzhavat_po_ip(edge):
    """aifos.conf е общ; на Deimos nginx-extra е празна и средите вървят по IP:порт.

    Затварянето им иска име и сертификат (demo.heppsu.com и т.н.) — отделна
    задача. Тази промяна не бива да ги свали: деплоят на preprod и етикетът
    tested/<sha> зависят от тях.
    """
    status, headers, body = _http(edge["preprod_ports"][0], "169.58.90.87",
                                  headers={"X-Forwarded-For": "6.6.6.6"})
    assert status == 200, body
    assert "6.6.6.6" not in body
    assert headers["Server"] == "nginx"
