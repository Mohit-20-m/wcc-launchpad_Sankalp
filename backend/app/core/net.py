"""Client-address helpers. We never store a raw IP: only a salted hash,
enough to spot repeat abuse without keeping personal data."""

import hashlib

from fastapi import Request

from app.core.config import settings


def client_ip(request: Request) -> str:
    # X-Real-IP is set by nginx from the actual TCP peer ($remote_addr),
    # overriding anything the client sent -- unlike X-Forwarded-For, whose
    # first entries a client can forge. The backend is not exposed to the
    # host, so this header can only have come from nginx.
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "unknown"


def hash_ip(ip: str) -> str:
    return hashlib.sha256(f"{settings.jwt_secret}|ip|{ip}".encode()).hexdigest()[:32]


def request_ip_hash(request: Request) -> str:
    return hash_ip(client_ip(request))
