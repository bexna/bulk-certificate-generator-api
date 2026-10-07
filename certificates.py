"""Single-template PDF certificate renderer."""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas


def render_certificate(recipient_name: str, course_name: str, issued_by: str) -> bytes:
    """Render one certificate and return its PDF bytes."""
    buffer = BytesIO()
    page_width, page_height = landscape(letter)
    pdf = canvas.Canvas(buffer, pagesize=(page_width, page_height))
    pdf.setTitle(f"Certificate - {recipient_name}")

    # A restrained, printable single-template design.
    pdf.setFillColor(colors.HexColor("#142D4E"))
    pdf.rect(0, page_height - 28, page_width, 28, fill=1, stroke=0)
    pdf.setStrokeColor(colors.HexColor("#D2A84A"))
    pdf.setLineWidth(3)
    pdf.rect(30, 30, page_width - 60, page_height - 88, fill=0, stroke=1)

    pdf.setFillColor(colors.HexColor("#142D4E"))
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawCentredString(page_width / 2, page_height - 105, "CERTIFICATE OF COMPLETION")
    pdf.setFillColor(colors.HexColor("#536579"))
    pdf.setFont("Helvetica", 13)
    pdf.drawCentredString(page_width / 2, page_height - 155, "This certificate is proudly presented to")
    pdf.setFillColor(colors.HexColor("#142D4E"))
    pdf.setFont("Helvetica-Bold", 30)
    pdf.drawCentredString(page_width / 2, page_height - 210, recipient_name)
    pdf.setStrokeColor(colors.HexColor("#D2A84A"))
    pdf.setLineWidth(1)
    pdf.line(page_width * 0.2, page_height - 225, page_width * 0.8, page_height - 225)
    pdf.setFillColor(colors.HexColor("#536579"))
    pdf.setFont("Helvetica", 13)
    pdf.drawCentredString(page_width / 2, page_height - 265, "for successfully completing")
    pdf.setFillColor(colors.HexColor("#142D4E"))
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawCentredString(page_width / 2, page_height - 300, course_name)
    pdf.setFillColor(colors.HexColor("#536579"))
    pdf.setFont("Helvetica", 11)
    pdf.drawCentredString(page_width / 2, 75, f"Issued by {issued_by}")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
