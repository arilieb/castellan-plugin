# -*- encoding: utf-8 -*-
"""
castellan.core.remoting module

Functions for interacting with the Castellan credential management server.
"""
import json
import urllib.parse
from typing import TYPE_CHECKING, Dict, Any, Optional

from keri.core.scheming import Schemer
from locksmith.core.credentialing import outputCred, escape_keys

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication

from keri import help

logger = help.ogler.getLogger(__name__)


def _get_essr(app: "LocksmithApplication"):
    """Get the ESSR client from plugin state."""
    if not app.vault:
        return None
    return app.vault.plugin_state.get("castellan", {}).get("essr")


# ---------------------------------------------------------------------------
# Issued credentials
# ---------------------------------------------------------------------------

async def fetch_issued_credentials(
    app: "LocksmithApplication",
    page: int = 0,
    page_size: int = 10,
    filter_term: Optional[str] = None,
    order: Optional[list] = None,
) -> Dict[str, Any]:
    """Fetch issued credentials from the Castellan server (paginated)."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        params = [f"page={page}", f"page_size={page_size}"]
        if filter_term:
            params.append(f"filter={urllib.parse.quote(filter_term)}")
        if order:
            for o in order:
                params.append(f"order={urllib.parse.quote(o)}")

        path = f"/issued-credentials?{'&'.join(params)}"
        response = await essr.request(path=path, method="GET")

        print(response.status_code)
        print(response.text)
        if response is not None and response.status_code == 200:
            data = response.json()
            data['success'] = True
            return data
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}"
            }
    except Exception as e:
        logger.error(f"Error fetching issued credentials: {e}")
        return {'success': False, 'error': str(e)}


async def fetch_all_castellan_issued_saids(app: "LocksmithApplication") -> set:
    """Fetch all issued credential SAIDs currently stored on the Castellan server."""
    essr = _get_essr(app)
    if not essr:
        return set()

    try:
        response = await essr.request(path="/issued-credentials?page_size=10000", method="GET")
        if response is not None and response.status_code == 200:
            data = response.json()
            return {cred['said'] for cred in data.get('credentials', [])}
        return set()
    except Exception as e:
        logger.error(f"Error fetching castellan issued SAIDs: {e}")
        return set()


async def upload_issued_credential(
    app: "LocksmithApplication",
    credential_said: str,
    schema: dict,
    issuer: str,
    recipient: str,
) -> Dict[str, Any]:
    """Upload an issued credential to the Castellan server."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    if not app.vault or not app.vault.hby:
        return {'success': False, 'error': 'No local vault open'}

    try:
        hby = app.vault.hby
        rgy = app.vault.rgy

        doc = {
            'said': credential_said,
            'issuer': issuer,
            'recipient': recipient,
            'schema': escape_keys(schema),
        }

        acdc = outputCred(hby, rgy, credential_said)
        if not acdc:
            return {'success': False, 'error': f'No ACDC data for {credential_said}'}

        files = {
            'acdc': ('output.bin', bytes(acdc), 'application/octet-stream'),
            'doc': ('data.json', json.dumps(doc), 'application/json'),
        }

        response = await essr.request(
            path="/issued-credentials",
            method="POST",
            files=files,
            timeout=60,
        )

        if response and response.status_code in (200, 201):
            return {'success': True, 'data': response.json()}
        else:
            if response is not None:
                logger.error(f"Upload failed with status {response.status_code}: {response.text}")
                try:
                    error_msg = response.json().get('description', f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
            else:
                error_msg = "No response"
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.error(f"Error uploading issued credential: {e}")
        return {'success': False, 'error': str(e)}


async def delete_issued_credential(
    app: "LocksmithApplication",
    said: str,
) -> Dict[str, Any]:
    """Delete an issued credential from the Castellan server."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        response = await essr.request(
            path=f"/issued-credentials/{urllib.parse.quote(said, safe='')}",
            method="DELETE",
        )

        if response is not None and response.status_code == 204:
            return {'success': True}
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}"
            }
    except Exception as e:
        logger.error(f"Error deleting issued credential: {e}")
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

async def fetch_schemas(
    app: "LocksmithApplication",
    page: int = 0,
    page_size: int = 10,
    filter_term: Optional[str] = None,
    order: Optional[list] = None,
) -> Dict[str, Any]:
    """Fetch schemas from the Castellan server (paginated)."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        params = [f"page={page}", f"page_size={page_size}"]
        if filter_term:
            params.append(f"filter={urllib.parse.quote(filter_term)}")
        if order:
            for o in order:
                params.append(f"order={urllib.parse.quote(o)}")

        path = f"/schemas?{'&'.join(params)}"
        response = await essr.request(path=path, method="GET")

        if response is not None and response.status_code == 200:
            data = response.json()
            data['success'] = True
            return data
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}"
            }
    except Exception as e:
        logger.error(f"Error fetching schemas: {e}")
        return {'success': False, 'error': str(e)}


async def fetch_all_castellan_schema_saids(app: "LocksmithApplication") -> set:
    """Fetch all schema SAIDs currently stored on the Castellan server."""
    essr = _get_essr(app)
    if not essr:
        return set()

    try:
        response = await essr.request(path="/schemas?page_size=10000", method="GET")
        if response is not None and response.status_code == 200:
            data = response.json()
            return {schema['said'] for schema in data.get('schemas', [])}
        return set()
    except Exception as e:
        logger.error(f"Error fetching castellan schema SAIDs: {e}")
        return set()


async def upload_schema(
    app: "LocksmithApplication",
    schema_said: str,
    sad: dict,
) -> Dict[str, Any]:
    """Upload a schema to the Castellan server."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    if not app.vault or not app.vault.rgy:
        return {'success': False, 'error': 'No local vault open'}

    try:
        # Retrieve schema bytes from registry
        schemer = Schemer(sed=sad)
        schema_bytes = schemer.raw
        if not schema_bytes:
            return {'success': False, 'error': f'No schema data for {schema_said}'}

        files = {
            'schema': ('schema.json', bytes(schema_bytes), 'application/json')
        }

        response = await essr.request(
            path="/schemas",
            method="POST",
            files=files,
            timeout=60,
        )

        if response and response.status_code in (200, 201):
            return {'success': True, 'data': response.json()}
        else:
            if response is not None:
                logger.error(f"Upload failed with status {response.status_code}: {response.text}")
                try:
                    error_msg = response.json().get('description', f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
            else:
                error_msg = "No response"
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.error(f"Error uploading schema: {e}")
        return {'success': False, 'error': str(e)}


async def delete_schema(
    app: "LocksmithApplication",
    said: str,
) -> Dict[str, Any]:
    """Delete a schema from the Castellan server."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        response = await essr.request(
            path=f"/schemas/{urllib.parse.quote(said, safe='')}",
            method="DELETE",
        )

        if response is not None and response.status_code == 204:
            return {'success': True}
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}"
            }
    except Exception as e:
        logger.error(f"Error deleting schema: {e}")
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Received credentials
# ---------------------------------------------------------------------------

async def fetch_received_credentials(
    app: "LocksmithApplication",
    page: int = 0,
    page_size: int = 10,
    filter_term: Optional[str] = None,
    order: Optional[list] = None,
) -> Dict[str, Any]:
    """Fetch received credentials from the Castellan server (paginated)."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        params = [f"page={page}", f"page_size={page_size}"]
        if filter_term:
            params.append(f"filter={urllib.parse.quote(filter_term)}")
        if order:
            for o in order:
                params.append(f"order={urllib.parse.quote(o)}")

        path = f"/received-credentials?{'&'.join(params)}"
        response = await essr.request(path=path, method="GET")

        if response is not None and response.status_code == 200:
            data = response.json()
            data['success'] = True
            return data
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}"
            }
    except Exception as e:
        logger.error(f"Error fetching received credentials: {e}")
        return {'success': False, 'error': str(e)}


async def fetch_all_castellan_received_saids(app: "LocksmithApplication") -> set:
    """Fetch all received credential SAIDs currently stored on the Castellan server."""
    essr = _get_essr(app)
    if not essr:
        return set()

    try:
        response = await essr.request(path="/received-credentials?page_size=10000", method="GET")
        if response is not None and response.status_code == 200:
            data = response.json()
            return {cred['said'] for cred in data.get('credentials', [])}
        return set()
    except Exception as e:
        logger.error(f"Error fetching castellan received SAIDs: {e}")
        return set()


async def upload_received_credential(
    app: "LocksmithApplication",
    credential_said: str,
    schema: dict,
    issuer: str,
    holder: str,
) -> Dict[str, Any]:
    """Upload a received credential to the Castellan server."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    if not app.vault or not app.vault.hby:
        return {'success': False, 'error': 'No local vault open'}

    try:
        hby = app.vault.hby
        rgy = app.vault.rgy

        doc = {
            'said': credential_said,
            'issuer': issuer,
            'holder': holder,
            'schema': escape_keys(schema),
        }

        acdc = outputCred(hby, rgy, credential_said)
        if not acdc:
            return {'success': False, 'error': f'No ACDC data for {credential_said}'}

        files = {
            'acdc': ('output.bin', bytes(acdc), 'application/octet-stream'),
            'doc': ('data.json', json.dumps(doc), 'application/json'),
        }

        response = await essr.request(
            path="/received-credentials",
            method="POST",
            files=files,
            timeout=60,
        )

        if response and response.status_code in (200, 201):
            return {'success': True, 'data': response.json()}
        else:
            if response is not None:
                logger.error(f"Upload failed with status {response.status_code}: {response.text}")
                try:
                    error_msg = response.json().get('description', f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
            else:
                error_msg = "No response"
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.error(f"Error uploading received credential: {e}")
        return {'success': False, 'error': str(e)}


async def delete_received_credential(
    app: "LocksmithApplication",
    said: str,
) -> Dict[str, Any]:
    """Delete a received credential from the Castellan server."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        response = await essr.request(
            path=f"/received-credentials/{urllib.parse.quote(said, safe='')}",
            method="DELETE",
        )

        if response is not None and response.status_code == 204:
            return {'success': True}
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}"
            }
    except Exception as e:
        logger.error(f"Error deleting received credential: {e}")
        return {'success': False, 'error': str(e)}
