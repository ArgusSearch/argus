"""Create the Argus Pages project and manage only its two authorized DNS names."""

import json
import os
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ACCOUNT = "c452dd4753dd99c4d03eec47380d0470"
ZONE = "caniberk.dev"
PROJECT = "argus-eye"
WEB = f"argus.{ZONE}"
API = f"argus-api.{ZONE}"
PROJECTS = f"/accounts/{ACCOUNT}/pages/projects"


class CloudflareError(Exception):
    def __init__(self, status, path, errors):
        self.status = status
        super().__init__(f"Cloudflare HTTP {status} for {path}: {errors}")


def credential():
    if token := os.environ.get("CLOUDFLARE_API_TOKEN"):
        return token
    result = subprocess.run(["wrangler", "auth", "token", "--json"], capture_output=True, check=False)
    if result.returncode:
        raise SystemExit("Wrangler credentials unavailable. Run wrangler whoami or supply a scoped API token.")
    return json.loads(result.stdout)["token"]


def request(token, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(
        "https://api.cloudflare.com/client/v4" + path,
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=30) as response:
            status, body = response.status, json.load(response)
    except HTTPError as error:
        status, body = error.code, json.load(error)
    if not body.get("success"):
        raise CloudflareError(status, path, body.get("errors"))
    return body["result"]


def project(token):
    try:
        info = request(token, f"{PROJECTS}/{PROJECT}")
    except CloudflareError as error:
        if error.status != 404:
            raise
        info = request(token, PROJECTS, {"name": PROJECT, "production_branch": "main"})
    if info["production_branch"] != "main" or info.get("source"):
        raise SystemExit(f"Refusing to deploy to {PROJECT}: expected a Direct Upload project with branch main.")
    return info["subdomain"]


def dns_path(token):
    zones = request(token, f"/zones?name={ZONE}")
    if len(zones) != 1 or zones[0]["account"]["id"] != ACCOUNT:
        raise SystemExit(f"Cannot identify the expected Cloudflare zone for {ZONE}.")
    return f"/zones/{zones[0]['id']}/dns_records"


def dns_records(token, path, name):
    records = request(token, f"{path}?{urlencode({'name.exact': name, 'per_page': 100})}")
    if any(item["name"].lower() != name for item in records):
        raise SystemExit(f"Cloudflare returned DNS records outside {name}.")
    return records


def verify_dns(token, path, name, target):
    matches = dns_records(token, path, name)
    records = ", ".join(f"{item['type']} {item['content']}" for item in matches)
    print(f"{name}: {records or '(no records)'}")
    if matches and (
        len(matches) != 1
        or not target
        or matches[0]["type"] != "CNAME"
        or matches[0]["content"].rstrip(".") != target
        or not matches[0]["proxied"]
    ):
        raise SystemExit(f"Existing DNS at {name} needs review. No record was replaced.")
    return bool(matches)


def main():
    command, *args = sys.argv[1:]
    if command == "web-domain" and args != ["--go"]:
        raise SystemExit("Use web-domain --go to attach the Pages domain.")
    token = credential()
    if command == "project":
        print(project(token))
        return
    if command not in {"preflight", "web-domain"}:
        raise SystemExit("Expected project, preflight or web-domain.")
    path = dns_path(token)
    subdomain = request(token, f"{PROJECTS}/{PROJECT}")["subdomain"]
    has_web = verify_dns(token, path, WEB, subdomain)
    if command == "preflight":
        target = f"{args[0]}.cfargotunnel.com" if args else None
        has_api = verify_dns(token, path, API, target)
        print("API_CNAME_PRESENT" if has_api else "API_CNAME_MISSING")
        return
    # The standalone web attachment can run before the tunnel exists. This read
    # keeps the preflight visibility requirement without altering the API record.
    dns_records(token, path, API)
    domains = f"{PROJECTS}/{PROJECT}/domains"
    if not any(domain["name"] == WEB for domain in request(token, domains)):
        request(token, domains, {"name": WEB})
        has_web = verify_dns(token, path, WEB, subdomain)
    if not has_web:
        request(token, path, {"type": "CNAME", "name": WEB, "content": subdomain, "proxied": True, "ttl": 1})


if __name__ == "__main__":
    try:
        main()
    except CloudflareError as error:
        raise SystemExit(str(error)) from None
