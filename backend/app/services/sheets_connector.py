"""
═══════════════════════════════════════════════════════════════
GOOGLE SHEETS CONNECTOR — Export Agent Output to Google Sheets
═══════════════════════════════════════════════════════════════
Uses gspread with OAuth2 user credentials (not service account)
to create spreadsheets owned by the user's personal Google account.

First-time setup: run `python -m app.services.sheets_connector` to
authenticate via browser and save refresh token.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import structlog

logger = structlog.get_logger()

# Lazy-loaded gspread client
_client = None

# Token file path (next to credentials JSON)
_TOKEN_FILE = None


def _get_token_path() -> str:
    global _TOKEN_FILE
    if _TOKEN_FILE:
        return _TOKEN_FILE
    from app.config import get_settings
    creds_path = get_settings().GOOGLE_SHEETS_CREDENTIALS_JSON
    _TOKEN_FILE = str(Path(creds_path).parent / "sheets-oauth-token.json")
    return _TOKEN_FILE


def get_gspread_client():
    """Return a cached gspread client using user OAuth2 credentials."""
    global _client
    if _client is not None:
        return _client

    from app.config import get_settings
    import gspread
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    token_path = _get_token_path()

    if not os.path.exists(token_path):
        raise RuntimeError(
            "OAuth token not found. Run this first:\n"
            "  cd backend && .venv/bin/python -m app.services.sheets_connector\n"
            "to authenticate via browser."
        )

    creds = Credentials.from_authorized_user_file(
        token_path,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file",
        ],
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Save refreshed token
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    _client = gspread.authorize(creds)
    return _client


def create_sheet_from_agent_output(
    session_id: str,
    step_number: int,
    step_type: str,
    output: str,
    sources: list[dict[str, str]],
    search_queries: list[str] | None = None,
) -> dict[str, str]:
    """
    Create a Google Sheet from agent execution output.
    Sheet is owned by the authenticated user's Google account.

    Returns: {"sheet_url": "...", "sheet_id": "..."}
    """
    from app.config import get_settings

    settings = get_settings()
    client = get_gspread_client()

    title = f"Ikshan Step {step_number} — {step_type.title()} ({datetime.now(timezone.utc).strftime('%b %d %H:%M')})"
    spreadsheet = client.create(title)

    # Move to target folder if configured
    folder_id = settings.GOOGLE_SHEETS_FOLDER_ID
    if folder_id:
        try:
            client.move_to_folder(spreadsheet, folder_id)
        except Exception as e:
            logger.warning("Could not move sheet to folder", error=str(e))

    # Make the sheet viewable by anyone with link
    spreadsheet.share("", perm_type="anyone", role="reader")

    # ── Sheet 1: Agent Output ─────────────────────────────────
    ws_output = spreadsheet.sheet1
    ws_output.update_title("Agent Output")

    output_rows = _markdown_to_sheet_sections(output)
    if output_rows:
        ws_output.update(f"A1:C{len(output_rows)}", output_rows)
    _format_section_headers(ws_output, output_rows)

    # ── Sheet 2: Sources ──────────────────────────────────────
    ws_sources = spreadsheet.add_worksheet(title="Sources", rows=max(len(sources) + 1, 2), cols=3)
    source_rows = [["Title", "URL", "Snippet"]]
    for s in sources:
        source_rows.append([
            s.get("title", ""),
            s.get("link", s.get("url", "")),
            s.get("snippet", ""),
        ])
    ws_sources.update(f"A1:C{len(source_rows)}", source_rows)
    ws_sources.format("A1:C1", {"textFormat": {"bold": True}})

    # ── Sheet 3: Metadata ─────────────────────────────────────
    meta_rows = [
        ["Field", "Value"],
        ["Session ID", session_id],
        ["Step Number", str(step_number)],
        ["Step Type", step_type],
        ["Timestamp (UTC)", datetime.now(timezone.utc).isoformat()],
        ["Search Queries", ", ".join(search_queries or [])],
    ]
    ws_meta = spreadsheet.add_worksheet(title="Metadata", rows=len(meta_rows), cols=2)
    ws_meta.update(f"A1:B{len(meta_rows)}", meta_rows)
    ws_meta.format("A1:B1", {"textFormat": {"bold": True}})

    sheet_url = spreadsheet.url
    sheet_id = spreadsheet.id

    logger.info(
        "Google Sheet created",
        sheet_url=sheet_url,
        step_number=step_number,
        step_type=step_type,
    )

    return {"sheet_url": sheet_url, "sheet_id": sheet_id}


# ── Helpers ────────────────────────────────────────────────────


def _markdown_table_to_rows(text: str) -> list[list[str]]:
    """Extract markdown tables from text into list-of-lists."""
    rows = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            continue
        if re.match(r"^\|[\s\-:|]+\|$", line):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if cells:
            rows.append(cells)
    return rows


def _markdown_to_sheet_sections(text: str) -> list[list[str]]:
    """
    Convert markdown agent output to sheet rows.

    Strategy:
    - Markdown tables → proper grid rows
    - H2/H3 headers → bold section label rows
    - Bullet points → individual rows
    - Plain text → single-cell rows
    """
    rows: list[list[str]] = []
    lines = text.strip().split("\n")
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        # Markdown table block
        if line.startswith("|"):
            table_text = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_text.append(lines[i])
                i += 1
            table_rows = _markdown_table_to_rows("\n".join(table_text))
            rows.extend(table_rows)
            rows.append([""])
            continue

        # Headers (## or ###)
        header_match = re.match(r"^#{2,4}\s+(.+)", line)
        if header_match:
            rows.append([""])
            rows.append([header_match.group(1).strip()])
            i += 1
            continue

        # Bullet points
        bullet_match = re.match(r"^[-*]\s+(.+)", line)
        if bullet_match:
            rows.append(["", bullet_match.group(1).strip()])
            i += 1
            continue

        # Numbered list
        num_match = re.match(r"^\d+\.\s+(.+)", line)
        if num_match:
            rows.append(["", num_match.group(1).strip()])
            i += 1
            continue

        # Bold key-value (e.g., **Key:** Value)
        kv_match = re.match(r"^\*\*(.+?)\*\*[:\s]+(.+)", line)
        if kv_match:
            rows.append([kv_match.group(1).strip(), kv_match.group(2).strip()])
            i += 1
            continue

        # Plain text
        rows.append([line])
        i += 1

    return rows


def _format_section_headers(worksheet, rows: list[list[str]]) -> None:
    """Bold rows that look like section headers."""
    try:
        for idx, row in enumerate(rows):
            if len(row) >= 1 and row[0] and (len(row) == 1 or all(c == "" for c in row[1:])):
                if row[0].strip():
                    cell = f"A{idx + 1}"
                    worksheet.format(cell, {"textFormat": {"bold": True, "fontSize": 11}})
    except Exception:
        pass


# ── One-time OAuth setup (run as script) ──────────────────────

def _setup_oauth():
    """Run once to authenticate via browser and save refresh token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    from app.config import get_settings
    settings = get_settings()
    creds_path = settings.GOOGLE_SHEETS_CREDENTIALS_JSON

    # We need an OAuth client ID, not service account.
    # Create OAuth Desktop credentials from the same project.
    oauth_client_path = str(Path(creds_path).parent / "sheets-oauth-client.json")

    if not os.path.exists(oauth_client_path):
        print("\n" + "=" * 60)
        print("SETUP: Google Sheets OAuth2 (one-time)")
        print("=" * 60)
        print(f"\n1. Go to Google Cloud Console → APIs & Credentials")
        print(f"   https://console.cloud.google.com/apis/credentials?project={json.load(open(creds_path))['project_id']}")
        print(f"\n2. Click '+ CREATE CREDENTIALS' → 'OAuth client ID'")
        print(f"   - Application type: 'Desktop app'")
        print(f"   - Name: 'Ikshan Sheets'")
        print(f"\n3. Download the JSON and save it as:")
        print(f"   {oauth_client_path}")
        print(f"\n4. Run this script again.")
        print("=" * 60)
        return

    flow = InstalledAppFlow.from_client_secrets_file(
        oauth_client_path,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file",
        ],
    )
    creds = flow.run_local_server(port=0)

    token_path = str(Path(creds_path).parent / "sheets-oauth-token.json")
    with open(token_path, "w") as f:
        f.write(creds.to_json())

    print(f"\nToken saved to {token_path}")
    print("Google Sheets export is now ready!")


if __name__ == "__main__":
    _setup_oauth()
