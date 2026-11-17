"""Local offline QR code generator with graceful fallback."""
from __future__ import annotations

import base64
import io


def generate_qr_base64(data: str, size: int = 300) -> str:
    """Generate a clean PNG QR code as a data URI."""
    try:
        import qrcode

        box_size = max(4, size // 30)
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=box_size,
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode()
        return f"data:image/png;base64,{img_base64}"
    except ImportError:
        # Minimal SVG placeholder when qrcode package is absent in dev environments
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">'
            '<rect width="120" height="120" fill="#ffffff"/>'
            '<rect x="10" y="10" width="32" height="32" fill="none" stroke="#111" stroke-width="6"/>'
            '<rect x="20" y="20" width="12" height="12" fill="#111"/>'
            '<rect x="78" y="10" width="32" height="32" fill="none" stroke="#111" stroke-width="6"/>'
            '<rect x="88" y="20" width="12" height="12" fill="#111"/>'
            '<rect x="10" y="78" width="32" height="32" fill="none" stroke="#111" stroke-width="6"/>'
            '<rect x="20" y="88" width="12" height="12" fill="#111"/>'
            '<rect x="52" y="52" width="16" height="16" fill="#0b8f7e"/>'
            "</svg>"
        )
        b64 = base64.b64encode(svg.encode()).decode()
        return f"data:image/svg+xml;base64,{b64}"
