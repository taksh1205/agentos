"""Bounded file validation. Treat all extracted content as untrusted evidence."""

import asyncio
import sys
from io import BytesIO

from pypdf import PdfReader


def extract(filename: str, data: bytes) -> str:
    if len(data) > 5_000_000:
        raise ValueError("5 MB upload limit")
    if filename.lower().endswith(".pdf"):
        if not data.startswith(b"%PDF-"):
            raise ValueError("Invalid PDF signature")
        try:
            reader = PdfReader(BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise ValueError("Encrypted PDFs are unsupported")
            if len(reader.pages) > 100:
                raise ValueError("100-page limit")
            chunks = []
            total = 0
            for page in reader.pages:
                value = page.extract_text() or ""
                total += len(value)
                if total > 500000:
                    raise ValueError("Extracted text limit")
                chunks.append(value)
            content = "\n\n".join(chunks)
        except Exception as exc:
            raise ValueError("PDF extraction failed or exceeded limits") from exc
    elif filename.lower().endswith((".txt", ".md", ".csv")):
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Text must be UTF-8") from exc
    else:
        raise ValueError("Supported formats: PDF, TXT, MD, CSV")
    if not content.strip():
        raise ValueError("Document has no extractable text; OCR is not configured")
    if len(content) > 500000:
        raise ValueError("Extracted text limit")
    return content


async def extract_upload(filename: str, data: bytes) -> str:
    if not filename.lower().endswith(".pdf"):
        return extract(filename, data)
    if not data.startswith(b"%PDF-"):
        raise ValueError("Invalid PDF signature")
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "agentos.ingestion",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env={},
    )
    try:
        output, _ = await asyncio.wait_for(proc.communicate(data), 15)
        if proc.returncode:
            raise ValueError("PDF extraction failed or exceeded limits")
        return output.decode("utf-8")
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


if __name__ == "__main__":
    if sys.platform.startswith("linux"):
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
        resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
    sys.stdout.buffer.write(extract("upload.pdf", sys.stdin.buffer.read(5_000_001)).encode())
