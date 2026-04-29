#!/usr/bin/env python3
"""Send an OpsRisk Radar HTML report by email via the Resend API.

Usage:
    python scripts/send_report_email.py reports/daily/YYYY-MM-DD-email.html
    python scripts/send_report_email.py reports/weekly/YYYY-MM-DD.html

Required environment variables:
    RESEND_API_KEY     Resend.com API key (starts with ``re_``)
    REPORT_EMAIL_TO    Recipient email address
    REPORT_EMAIL_FROM  Sender email address
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_RESEND_URL = "https://api.resend.com/emails"


def _fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        _fail(
            "Missing report file path.\n"
            f"Usage: {sys.argv[0]} reports/daily/YYYY-MM-DD-email.html"
        )

    path = Path(sys.argv[1])

    if not path.exists():
        _fail(f"Report file not found: {path}")

    # Read required environment variables
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    to_addr = os.environ.get("REPORT_EMAIL_TO", "").strip()
    from_addr = os.environ.get("REPORT_EMAIL_FROM", "").strip()

    missing = []
    if not api_key:
        missing.append("RESEND_API_KEY")
    if not to_addr:
        missing.append("REPORT_EMAIL_TO")
    if not from_addr:
        missing.append("REPORT_EMAIL_FROM")

    if missing:
        _fail(
            "Missing required environment variable(s): "
            f"{', '.join(missing)}"
        )

    # Infer report type from file path
    path_str = str(path)
    if "weekly" in path_str:
        report_type = "Weekly Brief"
    else:
        report_type = "Daily Brief"

    # Extract date from filename (expects YYYY-MM-DD or YYYY-MM-DD-email)
    stem = path.stem
    date_part = stem[:10]  # first 10 chars: YYYY-MM-DD

    subject = f"OpsRisk Radar {report_type} - {date_part}"
    html_body = path.read_text(encoding="utf-8")

    payload = json.dumps(
        {
            "from": from_addr,
            "to": [to_addr],
            "subject": subject,
            "html": html_body,
        }
    ).encode()

    req = Request(
        _RESEND_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(req) as resp:
            result = json.loads(resp.read())
            email_id = result.get("id", "unknown")
            print(f"Email sent: id={email_id}")
    except HTTPError as exc:
        body = exc.read().decode(errors="replace")
        _fail(f"Resend API error {exc.code}: {body}")
    except URLError as exc:
        _fail(f"Network error: {exc.reason}")


if __name__ == "__main__":
    main()
