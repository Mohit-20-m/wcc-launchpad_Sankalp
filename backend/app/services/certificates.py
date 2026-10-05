"""Certificates: issue, sign, verify, render as PDF.

Each certificate has a public verification code and an HMAC over its
contents. Verification recomputes that HMAC, so a certificate whose name,
prize or rank was altered in the database no longer verifies.
"""
import hashlib
import hmac
import io
import secrets
from datetime import datetime, timezone

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

from app.core.config import settings

_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O/1/I


def new_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def normalize_code(code: str) -> str:
    raw = "".join(c for c in code.upper() if c.isalnum())
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}" if len(raw) == 12 else code.strip().upper()


def _stamp(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def signature_for(cert_id: str, event_id: str, user_id: str, name: str, kind: str, title: str, rank, issued_at: datetime, code: str) -> str:
    msg = "\x1f".join([cert_id, event_id, user_id, name, kind, title, "" if rank is None else str(rank), _stamp(issued_at), code])
    key = hashlib.sha256(("certificate:" + settings.jwt_secret).encode()).digest()
    return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()


def signature_ok(cert) -> bool:
    expected = signature_for(cert.id, cert.event_id, cert.user_id, cert.recipient_name, cert.kind, cert.title, cert.rank, cert.issued_at, cert.code)
    return hmac.compare_digest(expected, cert.signature)


KIND_HEADLINE = {"participation": "CERTIFICATE OF PARTICIPATION", "winner": "CERTIFICATE OF ACHIEVEMENT", "judge": "CERTIFICATE OF SERVICE"}


def render_pdf(cert, event_name: str, verify_url: str) -> bytes:
    ink, acid, cyan, cream = HexColor("#0d0d12"), HexColor("#d9ff3f"), HexColor("#36e2ff"), HexColor("#fff6df")
    buf = io.BytesIO()
    w, h = landscape(A4)
    c = canvas.Canvas(buf, pagesize=(w, h))
    c.setTitle(f"{KIND_HEADLINE.get(cert.kind, 'CERTIFICATE')}: {cert.recipient_name}")
    c.setFillColor(ink); c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setFillColor(acid); c.rect(28, 28, w - 56, h - 56, fill=1, stroke=0)          # offset-shadow look
    c.setFillColor(cream); c.rect(20, 36, w - 56, h - 56, fill=1, stroke=0)
    c.setStrokeColor(ink); c.setLineWidth(4); c.rect(20, 36, w - 56, h - 56, fill=0, stroke=1)
    c.setFillColor(ink); c.setFont("Helvetica-Bold", 13); c.drawString(50, h - 70, "WCC LAUNCHPAD")
    c.setFillColor(cyan); c.rect(50, h - 84, 60, 5, fill=1, stroke=0)
    c.setFillColor(ink); c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(w / 2 - 8, h - 140, KIND_HEADLINE.get(cert.kind, "CERTIFICATE"))
    c.setFont("Helvetica", 14); c.drawCentredString(w / 2 - 8, h - 185, "This certifies that")
    name = cert.recipient_name
    size = 44 if len(name) < 22 else 32 if len(name) < 34 else 24
    c.setFont("Helvetica-Bold", size); c.drawCentredString(w / 2 - 8, h - 245, name)
    c.setStrokeColor(ink); c.setLineWidth(2); c.line(w / 2 - 250, h - 258, w / 2 + 234, h - 258)
    c.setFont("Helvetica", 14)
    if cert.kind == "winner":
        line1 = f"won {cert.title}" + (f" (rank {cert.rank})" if cert.rank else "")
        line2 = f"at {event_name}" + (f" with \u201c{cert.project_title}\u201d" if cert.project_title else "")
    elif cert.kind == "judge":
        line1, line2 = "served as a judge", f"at {event_name}"
    else:
        line1 = f"took part in {event_name}"
        line2 = f"with \u201c{cert.project_title}\u201d" + (f" (team {cert.team_name})" if cert.team_name else "") if cert.project_title else ""
    c.drawCentredString(w / 2 - 8, h - 295, line1)
    if line2:
        c.drawCentredString(w / 2 - 8, h - 318, line2)
    c.setFont("Helvetica", 10)
    c.drawString(50, 72, f"Issued {cert.issued_at.strftime('%d %B %Y')}")
    c.drawString(50, 56, f"Verify: {verify_url}")
    c.setFont("Courier-Bold", 12); c.drawString(50, 92, f"CODE  {cert.code}")
    widget = qr.QrCodeWidget(verify_url)
    x0, y0, x1, y1 = widget.getBounds()
    drawing = Drawing(80, 80, transform=[80 / (x1 - x0), 0, 0, 80 / (y1 - y0), 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, c, w - 150, 52)
    c.showPage(); c.save()
    return buf.getvalue()
