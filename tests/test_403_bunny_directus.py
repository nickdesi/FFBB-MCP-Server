"""Parade 403 BunnyCDN vs Directus — handle_api_error.

Couvre la distinction introduite dans services/common.py :
- HTTPStatusError 403 JSON (Directus) -> guidance saison archivée + ffbb_saisons()
- HTTPStatusError 403 HTML (BunnyCDN) -> guidance User-Agent / ffbb-data-client
- Erreurs SDK duck-typées (status_code + message tagué BunnyCDN/Directus)
  car le SDK lève FFBBHTTPError, pas HTTPStatusError.
"""

from httpx import HTTPStatusError, Request, Response

from ffbb_mcp.services.common import handle_api_error


def _http_error(status: int, content_type: str, body: bytes) -> HTTPStatusError:
    req = Request("GET", "https://api.ffbb.app/items/ffbbserver_competitions/1")
    resp = Response(
        status, request=req, headers={"content-type": content_type}, content=body
    )
    return HTTPStatusError(f"HTTP {status}", request=req, response=resp)


class _SdkError(Exception):
    """Duck-type minimal de FFBBHTTPError (évite l'import dur du SDK)."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def test_403_directus_json_guides_to_saisons():
    exc = _http_error(
        403,
        "application/json",
        b'{"errors":[{"message":"You don\'t have permission."}]}',
    )
    err = handle_api_error(exc)
    msg = err.error.message
    assert "Directus" in msg
    assert "ffbb_saisons()" in msg
    assert "saison archivée" in msg


def test_403_bunnycdn_html_guides_to_user_agent():
    exc = _http_error(
        403,
        "text/html",
        b"<html><body>Request blocked by BunnyCDN-FR1</body></html>",
    )
    err = handle_api_error(exc)
    msg = err.error.message
    assert "BunnyCDN" in msg
    assert "ffbb-data-client" in msg


def test_403_sdk_directus_message():
    exc = _SdkError("FFBB access denied by Directus (HTTP 403).", 403)
    err = handle_api_error(exc)
    msg = err.error.message
    assert "Directus" in msg
    assert "ffbb_saisons()" in msg


def test_403_sdk_bunnycdn_message():
    exc = _SdkError("FFBB access blocked by CDN (403 BunnyCDN).", 403)
    err = handle_api_error(exc)
    msg = err.error.message
    assert "BunnyCDN" in msg
    assert "ffbb-data-client" in msg


def test_404_sdk_maps_to_introuvable():
    exc = _SdkError("FFBB service returned HTTP 404", 404)
    err = handle_api_error(exc)
    assert "introuvable (404)" in err.error.message
