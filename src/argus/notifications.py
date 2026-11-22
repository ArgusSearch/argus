"""Operator-owned notification delivery and HTTPS connection checks."""

from __future__ import annotations

import http.client
import ipaddress
import json
import logging
import os
import smtplib
import socket
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.message import EmailMessage
from urllib.parse import urlsplit

from argus.contracts.findings import Incident
from argus.settings import Settings, SettingsStore

log = logging.getLogger(__name__)


class DeliveryError(Exception):
    """A sanitized delivery failure safe to display to the operator."""


def check_url(url: str) -> None:
    try:
        endpoint = urlsplit(url)
        if (
            len(url) > 2048
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url)
            or endpoint.scheme != "https"
            or not endpoint.hostname
            or endpoint.port not in (None, 443)
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.fragment
        ):
            raise ValueError
    except ValueError:
        raise DeliveryError("Enter a public HTTPS URL without embedded credentials.") from None


class _PublicHTTPS(http.client.HTTPSConnection):
    def connect(self) -> None:
        # Connect to the vetted address directly. TLS still validates the original hostname.
        records = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        if not records or any(
            not ipaddress.ip_address(record[4][0]).is_global or ipaddress.ip_address(record[4][0]).is_multicast
            for record in records
        ):
            raise DeliveryError("The endpoint must resolve to a public address.")
        family, kind, proto, _, address = records[0]
        with socket.socket(family, kind, proto) as peer:
            peer.settimeout(self.timeout)
            peer.connect(address)
            self.sock = ssl.create_default_context().wrap_socket(peer, server_hostname=self.host)


def send_https(url: str, message: dict[str, object] | None = None) -> None:
    check_url(url)
    endpoint = urlsplit(url)
    assert endpoint.hostname is not None
    target = endpoint.path or "/"
    if endpoint.query:
        target += "?" + endpoint.query
    client = _PublicHTTPS(endpoint.hostname, timeout=5)
    try:
        body = json.dumps(message) if message is not None else None
        method = "POST" if body is not None else "GET"
        client.request(method, target, body=body, headers={"Content-Type": "application/json"} if body else {})
        response = client.getresponse()
        if not 200 <= response.status < 300:
            raise DeliveryError(f"The endpoint responded with HTTP {response.status}.")
    except (OSError, ValueError, http.client.HTTPException):
        raise DeliveryError("The endpoint could not be reached over HTTPS.") from None
    finally:
        client.close()


def send_email(recipient: str, subject: str, body: str) -> None:
    host, sender = os.environ.get("ARGUS_SMTP_HOST"), os.environ.get("ARGUS_SMTP_FROM")
    if not host or not sender:
        raise DeliveryError("Set ARGUS_SMTP_HOST and ARGUS_SMTP_FROM on the API server to send email.")
    message = EmailMessage()
    try:
        message["From"], message["To"], message["Subject"] = sender, recipient, subject
        message.set_content(body)
        with smtplib.SMTP_SSL(
            host, int(os.environ.get("ARGUS_SMTP_PORT", "465")), timeout=5, context=ssl.create_default_context()
        ) as smtp:
            if user := os.environ.get("ARGUS_SMTP_USER"):
                smtp.login(user, os.environ.get("ARGUS_SMTP_PASSWORD", ""))
            smtp.send_message(message)
    except (ValueError, OSError, smtplib.SMTPException):
        raise DeliveryError("The mail server could not deliver the message.") from None


class IncidentNotices:
    """Buffer quiet incidents and send each notice once through the configured channels."""

    def __init__(self, settings: SettingsStore) -> None:
        self.settings = settings
        self.pending: dict[str, Incident] = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="argus-notices")
        self.capacity = threading.BoundedSemaphore(32)

    def add(self, incident: Incident, now: datetime) -> None:
        settings = self.settings.read()
        if not any(
            (settings.channels.email, settings.channels.slack, settings.channels.pagerduty, settings.channels.webhook)
        ):
            return
        self.pending[incident.id] = incident.model_copy(deep=True)
        if len(self.pending) > 200:
            del self.pending[next(iter(self.pending))]
        self.flush(now)

    def flush(self, now: datetime) -> None:
        settings = self.settings.read()
        for key, incident in list(self.pending.items()):
            impact = incident.findings.impact
            cost = impact.gmv_eur_per_hour.value if impact is not None else 0
            if settings.quiet_hours.holds(now, cost):
                continue
            if not self.capacity.acquire(blocking=False):
                break
            del self.pending[key]
            self.executor.submit(self._deliver, incident, settings)

    def _deliver(self, incident: Incident, settings: Settings) -> None:
        channels, config = settings.channels, settings.notifications
        heading = f"Argus {incident.id}: {incident.title}"
        try:
            if channels.email and config.email:
                try:
                    send_email(config.email, heading, f"{heading}\nVerdict: {incident.verdict.value}")
                except DeliveryError as exc:
                    log.warning("Argus email delivery failed: %s", exc)
            for key in ("slack", "pagerduty", "webhook"):
                endpoint = getattr(config, f"{key}_url")
                if not getattr(channels, key) or endpoint is None:
                    continue
                try:
                    send_https(endpoint.get_secret_value(), {"text": heading, "incident_id": incident.id})
                except DeliveryError as exc:
                    log.warning("Argus %s delivery failed: %s", key, exc)
        finally:
            self.capacity.release()

    def close(self) -> None:
        self.executor.shutdown(cancel_futures=True)
