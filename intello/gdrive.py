"""Google Drive integration — supports both public and private (OAuth) files."""
import io
import os
import json
from typing import Optional

import httpx

# OAuth credentials (set via env or /opt/intello/gdrive_credentials.json)
CREDENTIALS_PATH = os.environ.get("GDRIVE_CREDENTIALS", "/data/gdrive_credentials.json")
TOKEN_PATH = os.environ.get("GDRIVE_TOKEN", "/data/gdrive_token.json")
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def _extract_file_id(url: str) -> Optional[str]:
    """Extract Google Drive file ID from various URL formats."""
    if "/d/" in url:
        return url.split("/d/")[1].split("/")[0].split("?")[0]
    if "id=" in url:
        return url.split("id=")[1].split("&")[0]
    return None


async def fetch_public(url: str) -> str:
    """Fetch a public Google Drive file via direct download."""
    file_id = _extract_file_id(url)
    if not file_id:
        return f"[Could not parse file ID from: {url}]"
    direct = f"https://drive.google.com/uc?export=download&id={file_id}"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        r = await c.get(direct)
        if r.status_code == 200:
            return r.text[:50_000]
        return f"[Failed to fetch: HTTP {r.status_code}]"


def _get_drive_service(token_data: Optional[dict] = None):
    """Build an authenticated Google Drive API service."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if token_data:
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)
    elif os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH) as f:
            creds = Credentials.from_authorized_user_info(json.load(f), SCOPES)
    else:
        return None

    # Refresh if expired
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def get_oauth_url(redirect_uri: str) -> Optional[str]:
    """Generate the Google OAuth consent URL. Returns None if no credentials configured."""
    if not os.path.exists(CREDENTIALS_PATH):
        return None
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(CREDENTIALS_PATH, scopes=SCOPES, redirect_uri=redirect_uri)
    url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    return url


def exchange_code(code: str, redirect_uri: str) -> dict:
    """Exchange OAuth authorization code for tokens. Returns token data."""
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(CREDENTIALS_PATH, scopes=SCOPES, redirect_uri=redirect_uri)
    flow.fetch_token(code=code)
    creds = flow.credentials
    token_data = json.loads(creds.to_json())
    with open(TOKEN_PATH, "w") as f:
        json.dump(token_data, f)
    return token_data


def fetch_private(url: str, token_data: Optional[dict] = None) -> str:
    """Fetch a private Google Drive file using OAuth credentials."""
    file_id = _extract_file_id(url)
    if not file_id:
        return f"[Could not parse file ID from: {url}]"

    service = _get_drive_service(token_data)
    if not service:
        return "[Google Drive OAuth not configured. Connect via the 🔗 button.]"

    try:
        from googleapiclient.http import MediaIoBaseDownload
        # Get file metadata
        meta = service.files().get(fileId=file_id, fields="name,mimeType,size").execute()
        mime = meta.get("mimeType", "")
        name = meta.get("name", "unknown")

        # For Google Docs/Sheets/Slides, export as plain text
        export_mimes = {
            "application/vnd.google-apps.document": "text/plain",
            "application/vnd.google-apps.spreadsheet": "text/csv",
            "application/vnd.google-apps.presentation": "text/plain",
        }
        if mime in export_mimes:
            content = service.files().export(fileId=file_id, mimeType=export_mimes[mime]).execute()
            text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
        else:
            buf = io.BytesIO()
            request = service.files().get_media(fileId=file_id)
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            text = buf.getvalue().decode("utf-8", errors="replace")

        return f"[File: {name}]\n{text[:50_000]}"
    except Exception as e:
        return f"[Google Drive error: {e}]"


def is_authenticated() -> bool:
    """Check if we have a valid stored token."""
    if not os.path.exists(TOKEN_PATH):
        return False
    try:
        _get_drive_service()
        return True
    except Exception:
        return False


# --- Folder browsing & batch operations ---

def list_folder(folder_id: str = "root", query: str = "") -> list[dict]:
    """List files in a Google Drive folder."""
    service = _get_drive_service()
    if not service:
        return []

    q = f"'{folder_id}' in parents and trashed = false"
    if query:
        q += f" and name contains '{query}'"

    results = []
    page_token = None
    while True:
        resp = service.files().list(
            q=q, fields="nextPageToken, files(id, name, mimeType, size, modifiedTime)",
            pageSize=100, pageToken=page_token,
            orderBy="folder,name"
        ).execute()

        for f in resp.get("files", []):
            results.append({
                "id": f["id"],
                "name": f["name"],
                "mime_type": f["mimeType"],
                "is_folder": f["mimeType"] == "application/vnd.google-apps.folder",
                "size": int(f.get("size", 0)),
                "modified": f.get("modifiedTime", ""),
            })

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return results


def batch_fetch(file_ids: list[str]) -> list[dict]:
    """Fetch content of multiple files. Returns [{id, name, content, error}]."""
    service = _get_drive_service()
    if not service:
        return [{"id": fid, "error": "Not authenticated"} for fid in file_ids]

    results = []
    for fid in file_ids:
        try:
            meta = service.files().get(fileId=fid, fields="name,mimeType").execute()
            name = meta.get("name", fid)
            mime = meta.get("mimeType", "")

            export_mimes = {
                "application/vnd.google-apps.document": "text/plain",
                "application/vnd.google-apps.spreadsheet": "text/csv",
                "application/vnd.google-apps.presentation": "text/plain",
            }

            if mime in export_mimes:
                content = service.files().export(fileId=fid, mimeType=export_mimes[mime]).execute()
                text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
            else:
                from googleapiclient.http import MediaIoBaseDownload
                buf = io.BytesIO()
                request = service.files().get_media(fileId=fid)
                downloader = MediaIoBaseDownload(buf, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                text = buf.getvalue().decode("utf-8", errors="replace")

            results.append({"id": fid, "name": name, "content": text[:100_000]})
        except Exception as e:
            results.append({"id": fid, "name": fid, "error": str(e)})

    return results
