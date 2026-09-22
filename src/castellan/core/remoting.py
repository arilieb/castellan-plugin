# -*- encoding: utf-8 -*-
"""
Asynchronous utilities for interacting with the ESSR client and Castellan server.

This module provides functionality for performing health checks, fetching and
managing issued credentials, and interacting with the ESSR service. The methods in
this module primarily handle asynchronous tasks such as API requests and retries.

Logging is integrated to record errors and warnings during the processes.
"""
import asyncio
import base64
import json
import urllib.parse
from typing import TYPE_CHECKING, Dict, Any, Optional

from keri.core import parsing
from keri.core.scheming import Schemer
from keri.kering import Ilks
from locksmith.core.credentialing import outputCred

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
# ESSR Health
# ---------------------------------------------------------------------------

async def _essr_health_roundtrip(essr) -> Dict[str, Any]:
    """Perform a single GET /health roundtrip against the given ESSR client."""
    try:
        response = await essr.request(path="/health", method="GET")
        if response is not None and response.status_code == 200:
            data = response.json()
            data['success'] = True
            return data
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response is not None else 'No response'}"
            }
    except Exception as e:
        return {'success': False, 'error': f'ESSR request failed: {str(e)}'}


async def essr_health_check(app: "LocksmithApplication") -> Dict[str, Any]:
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}
    return await _essr_health_roundtrip(essr)  # type: ignore


async def essr_health_guard(essr, max_attempts: int = 5, retry_delay: float = 1.0) -> Dict[str, Any]:
    """
    Attempt an ESSR GET /health roundtrip against `essr`, retrying up to
    `max_attempts` times with `retry_delay` seconds between attempts.

    Returns as soon as a single roundtrip succeeds. If every attempt fails,
    returns the result of the last attempt (success=False).
    """
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    result: Dict[str, Any] = {'success': False, 'error': 'No response'}
    for attempt in range(1, max_attempts + 1):
        result = await _essr_health_roundtrip(essr)
        if result.get('success'):
            return result
        logger.warning(f"ESSR health check attempt {attempt}/{max_attempts} failed: {result.get('error')}")
        if attempt < max_attempts:
            await asyncio.sleep(retry_delay)

    return result

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
    dynamic_field_data: list | None = None,
) -> Dict[str, Any]:
    """
    Upload an issued credential to the Castellan server.

    Args:
        app: The Locksmith application instance
        credential_said: The SAID of the credential to upload
        schema: The credential schema
        issuer: The issuer AID
        recipient: The recipient AID
        dynamic_field_data: Optional metadata list (e.g., dynamic fields) to include with the credential

    Returns:
        Dict with 'success' boolean and optional 'error' or 'data' keys
    """
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
            'schema_said': schema.get("$id"),
            'schema_title': schema.get("title"),
        }

        # Add metadata if provided
        if dynamic_field_data:
            doc['dynamic_fields'] = dynamic_field_data

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


async def update_issued_credential_metadata(
    app: "LocksmithApplication",
    credential_said: str,
    dynamic_field_data: list | None = None,
) -> Dict[str, Any]:
    """
    Update the metadata (dynamic fields) of an issued credential on the Castellan server.

    Args:
        app: The Locksmith application instance
        credential_said: The SAID of the credential to update
        dynamic_field_data: Updated dynamic fields list

    Returns:
        Dict with 'success' boolean and optional 'error' or 'data' keys
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        body = {
            'dynamic_fields': dynamic_field_data or []
        }

        response = await essr.request(
            path=f"/issued-credentials/{urllib.parse.quote(credential_said, safe='')}",
            method="PATCH",
            json=body,
            timeout=30,
        )

        if response and response.status_code in (200, 204):
            return {'success': True, 'data': response.json() if response.content else {}}
        else:
            if response is not None:
                logger.error(f"Update failed with status {response.status_code}: {response.text}")
                try:
                    error_msg = response.json().get('description', f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
            else:
                error_msg = "No response"
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.error(f"Error updating issued credential metadata: {e}")
        return {'success': False, 'error': str(e)}


async def update_issued_credential_status(
    app: "LocksmithApplication",
    credential_said: str,
    status: str,
) -> Dict[str, Any]:
    """
    Push a local status change (e.g. a TEL revocation) to the Castellan server
    so its stored record matches local truth.

    Args:
        app: The Locksmith application instance
        credential_said: The SAID of the credential to update
        status: The new status value ("issued" or "revoked")

    Returns:
        Dict with 'success' boolean and optional 'error' or 'data' keys
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        body = {'status': status}

        response = await essr.request(
            path=f"/issued-credentials/{urllib.parse.quote(credential_said, safe='')}",
            method="PATCH",
            json=body,
            timeout=30,
        )

        if response and response.status_code in (200, 204):
            return {'success': True, 'data': response.json() if response.content else {}}
        else:
            if response is not None:
                logger.error(f"Status update failed with status {response.status_code}: {response.text}")
                try:
                    error_msg = response.json().get('description', f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
            else:
                error_msg = "No response"
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.error(f"Error updating issued credential status: {e}")
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


async def fetch_schema_fields(
    app: "LocksmithApplication",
    schema_said: str,
) -> Dict[str, Any]:
    """
    Fetch remembered fields for a schema from the Castellan server.

    Args:
        app: The Locksmith application instance
        schema_said: The SAID of the schema

    Returns:
        Dict with 'success' boolean and optional 'error' or 'fields' keys
        Example success response: {'success': True, 'fields': [{'label': 'Email', 'type': 'email'}, ...]}
        Example empty response: {'success': True, 'fields': []}
        Example error response: {'success': False, 'error': 'API error: 404'}
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        response = await essr.request(
            path=f"/schemas/{urllib.parse.quote(schema_said, safe='')}/fields",
            method="GET",
            timeout=30,
        )

        if response is not None and response.status_code == 200:
            data = response.json()
            # Backend should return: {'fields': [{'label': 'Email', 'type': 'email'}, ...]}
            return {
                'success': True,
                'fields': data.get('fields', [])
            }
        elif response is not None and response.status_code == 404:
            # No remembered fields for this schema - treat as success with empty list
            return {'success': True, 'fields': []}
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}"
            }
    except Exception as e:
        logger.error(f"Error fetching schema fields: {e}")
        return {'success': False, 'error': str(e)}


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
    dynamic_field_data: list | None = None,
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
            'schema_said': schema.get("$id"),
            'schema_title': schema.get("title"),
        }

        if dynamic_field_data:
            doc['dynamic_fields'] = dynamic_field_data

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


async def update_received_credential_metadata(
    app: "LocksmithApplication",
    credential_said: str,
    dynamic_field_data: list | None = None,
) -> Dict[str, Any]:
    """
    Update the metadata (dynamic fields) of a received credential on the Castellan server.

    Args:
        app: The Locksmith application instance
        credential_said: The SAID of the credential to update
        dynamic_field_data: Updated dynamic fields list

    Returns:
        Dict with 'success' boolean and optional 'error' or 'data' keys
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        body = {
            'dynamic_fields': dynamic_field_data or []
        }

        response = await essr.request(
            path=f"/received-credentials/{urllib.parse.quote(credential_said, safe='')}",
            method="PATCH",
            json=body,
            timeout=30,
        )

        if response and response.status_code in (200, 204):
            return {'success': True, 'data': response.json() if response.content else {}}
        else:
            if response is not None:
                logger.error(f"Update failed with status {response.status_code}: {response.text}")
                try:
                    error_msg = response.json().get('description', f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
            else:
                error_msg = "No response"
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.error(f"Error updating received credential metadata: {e}")
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------

async def fetch_identifier_keystate(
    app: "LocksmithApplication",
    identifier_prefix: str,
) -> Dict[str, Any]:
    """
    Fetch identifier key state from the Castellan server.

    Args:
        app: The Locksmith application instance
        identifier_prefix: The AID prefix of the identifier

    Returns:
        Dict with 'success' boolean and optional 'error' or 'data' keys
        data contains the key state information including 'sn' (sequence number)
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        response = await essr.request(
            path=f"/identifiers/{urllib.parse.quote(identifier_prefix, safe='')}",
            method="GET",
            timeout=30,
        )

        if response and response.status_code == 200:
            return {'success': True, 'data': response.json()}
        elif response.status_code == 404:
            return {'success': True, 'data': None}
        else:
            if response is not None:
                logger.error(f"Fetch identifier failed with status {response.status_code}: {response.text}")
                try:
                    error_msg = response.json().get('description', f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
            else:
                error_msg = "No response"
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.error(f"Error fetching identifier key state: {e}")
        return {'success': False, 'error': str(e)}


async def upload_identifier(
    app: "LocksmithApplication",
    aid: str,
    alias: str,
    kel_bytes: bytes,
    oobi: str = "",
) -> Dict[str, Any]:
    """
    Upload a peer-discovery identifier to castellan POST /identifiers.

    Sends a multipart/form-data request with:
      doc — JSON metadata {aid, alias, oobi}
      kel — raw CESR-encoded KEL bytes

    Returns dict with 'success' bool and, on success, the stored identifier doc.
    Returns 'conflict': True when castellan returns 409 (alias already taken).
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        files = {
            'doc': ('doc.json', json.dumps({"aid": aid, "alias": alias, "oobi": oobi}), 'application/json'),
            'kel': ('kel.cesr', kel_bytes, 'application/octet-stream'),
        }
        response = await essr.request(
            path="/identifiers",
            method="POST",
            files=files,
            timeout=30,
        )
        if response is not None and response.status_code in (200, 201):
            return {'success': True, 'data': response.json()}
        elif response is not None and response.status_code == 409:
            return {'success': False, 'conflict': True, 'error': 'Alias already uploaded to castellan'}
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}",
            }
    except Exception as e:
        logger.error(f"Error uploading identifier: {e}")
        return {'success': False, 'error': str(e)}


async def fetch_identifier_kel(app: "LocksmithApplication", aid: str) -> Dict[str, Any]:
    """
    GET /identifiers/{aid}/kel — fetch the CESR KEL stream for a peer identifier.

    Returns dict with 'success' bool and, on success, 'kel_bytes' (raw bytes).
    Returns empty kel_bytes if the identifier exists but KEL has not been captured yet.
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        response = await essr.request(
            path=f"/identifiers/{urllib.parse.quote(aid, safe='')}/kel",
            method="GET",
        )
        if response is not None and response.status_code == 200:
            data = response.json()
            kel_b64 = data.get("kel", "")
            kel_bytes = base64.b64decode(kel_b64) if kel_b64 else b""
            return {'success': True, 'kel_bytes': kel_bytes}
        elif response is not None and response.status_code == 404:
            return {'success': False, 'error': 'Identifier not found on castellan'}
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}",
            }
    except Exception as e:
        logger.error(f"Error fetching KEL for {aid}: {e}")
        return {'success': False, 'error': str(e)}


async def fetch_identifiers(
    app: "LocksmithApplication",
    page: int = 0,
    page_size: int = 10,
    filter_term: Optional[str] = None,
    order: Optional[list] = None,
    include_key_state: bool = False,
) -> Dict[str, Any]:
    """
    Fetch peer-discovery identifiers from the Castellan server (paginated).

    `include_key_state` asks the server to embed each row's remote key state
    in the response (so callers rendering a "Seq No" column don't need a
    separate fetch_identifier_keystate round-trip per row). Leave it False
    for large/unpaginated fetches (e.g. peer-discovery polling), since the
    server computes it per identifier and it isn't needed there.
    """
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
        if include_key_state:
            params.append("include_key_state=true")

        path = f"/identifiers?{'&'.join(params)}"
        response = await essr.request(path=path, method="GET")

        if response is not None and response.status_code == 200:
            data = response.json()
            data['success'] = True
            return data
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}",
            }
    except Exception as e:
        logger.error(f"Error fetching identifiers: {e}")
        return {'success': False, 'error': str(e)}


async def delete_identifier(app: "LocksmithApplication", aid: str) -> Dict[str, Any]:
    """Delete a peer-discovery identifier from the Castellan server."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        response = await essr.request(
            path=f"/identifiers/{urllib.parse.quote(aid, safe='')}",
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
        logger.error(f"Error deleting identifier: {e}")
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Intra-enterprise mailbox (multisig EXN relay)
# ---------------------------------------------------------------------------

async def post_message(
    app: "LocksmithApplication",
    recipient_aid: str,
    topic: str,
    raw: bytes,
    sender_aid: Optional[str] = None,
    multisig_alias: str = "",
) -> Dict[str, Any]:
    """
    POST a CESR-encoded message to castellan /messages.

    `sender_aid` is the castellan-uploaded identifier of the local participant.
    `recipient_aid` is the target group participant's castellan-uploaded AID.
    One call per recipient is required.

    Returns dict with 'success' bool and, on success, the stored Message doc.
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    if not sender_aid:
        return {'success': False, 'error': 'No sender AID provided for message post'}

    try:
        params = (
            f"recipient={urllib.parse.quote(recipient_aid, safe='')}"
            f"&sender={urllib.parse.quote(sender_aid, safe='')}"
            f"&topic={urllib.parse.quote(topic, safe='')}"
        )
        if multisig_alias:
            params += f"&multisig_alias={urllib.parse.quote(multisig_alias, safe='')}"
        response = await essr.request(
            path=f"/messages?{params}",
            method="POST",
            data=raw,
            headers={"Content-Type": "application/cesr"},
            timeout=30,
        )
        if response is not None and response.status_code in (200, 201):
            return {'success': True, 'data': response.json()}
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}",
            }
    except Exception as e:
        logger.error(f"Error posting message: {e}")
        return {'success': False, 'error': str(e)}


async def fetch_messages(
    app: "LocksmithApplication",
    aid: Optional[str] = None,
    topic: Optional[str] = None,
    unread_only: bool = True,
    page: int = 0,
    page_size: int = 50,
) -> Dict[str, Any]:
    """
    GET messages from castellan /messages for the given AID.

    `aid` must be the castellan-uploaded identifier prefix; it is passed as an
    explicit query param so castellan does not need to derive it from ESSR context.

    Returns dict with 'success' bool and, on success, 'messages' list.
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    if not aid:
        return {'success': False, 'error': 'No AID provided for message fetch'}

    try:
        params = [f"aid={urllib.parse.quote(aid, safe='')}", f"page={page}", f"page_size={page_size}"]
        if topic:
            params.append(f"topic={urllib.parse.quote(topic, safe='')}")
        if unread_only:
            params.append("unread=true")
        path = f"/messages?{'&'.join(params)}"
        response = await essr.request(path=path, method="GET")
        if response is not None and response.status_code == 200:
            data = response.json()
            data['success'] = True
            return data
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}",
            }
    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        return {'success': False, 'error': str(e)}


async def mark_message_read(
    app: "LocksmithApplication",
    message_id: str,
) -> Dict[str, Any]:
    """Mark a castellan mailbox message as read."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        response = await essr.request(
            path=f"/messages/{urllib.parse.quote(message_id, safe='')}",
            method="PUT",
            json={},
        )
        if response is not None and response.status_code == 200:
            return {'success': True}
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}",
            }
    except Exception as e:
        logger.error(f"Error marking message read: {e}")
        return {'success': False, 'error': str(e)}


async def upload_account_identifier(
        app: "LocksmithApplication",
        aid: str,
        alias: str
) -> Dict[str, Any]:
    """
    Upload an identifier to the healthKERI account.

    This uploads either a local identifier (from hby.habs) or a remote
    identifier (from org contacts) to the healthKERI account.

    Args:
        app: Application instance with vault and ESSR connection
        aid: AID of the identifier to upload
        alias: Display alias for the identifier

    Returns:
        Dict with 'success' and optional 'error' or 'data'
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        hby = app.vault.hby

        # Build the doc part
        doc = {
            'aid': aid,
            'alias': alias
        }

        # Generate OOBI if not provided and we have witness/controller endpoints
        # Get the KEL
        kel = bytearray()
        for msg in hby.db.clonePreIter(pre=aid):
            kel.extend(msg)

        if not kel:
            return {'success': False, 'error': f'No KEL data available for {aid}'}

        # Create multipart form data files
        files = {
            'kel': ('output.bin', bytes(kel), 'application/octet-stream'),
            'doc': ('data.json', json.dumps(doc), 'application/json')
        }

        # Make POST request to create identifier
        response = await essr.request(
            path="/identifiers",
            method="POST",
            files=files,
            timeout=60
        )

        if response and response.status_code in (200, 201):
            return {'success': True, 'data': response.json()}
        else:
            if response is not None:
                logger.error(f"Upload failed with status {response.status_code}: {response.text}")
                try:
                    error_data = response.json()
                    error_msg = error_data.get('description', f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
            else:
                logger.error("Upload failed: No response received")
                error_msg = "No response"

            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.error(f"Error uploading account identifier: {e}")
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
async def get_account(app: "LocksmithApplication", account_id: str) -> Dict[str, Any]:
    """ Load single account by account_id """
    try:
        essr = _get_essr(app)

        path = f"/accounts/{account_id}"
        response = await essr.request(path=path, method="GET")

        if response is not None and response.status_code == 200:
            data = response.json()
            return {"success": True, "account": data}
        else:
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}"
            }
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")
        return {'success': False, 'error': str(e)}


async def fetch_accounts(
    app: "LocksmithApplication",
    page: int = 0,
    page_size: int = 10,
    filter_term: Optional[str] = None,
    order: Optional[list] = None,
) -> Dict[str, Any]:
    """Fetch user accounts from the Castellan server (paginated)."""
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

        path = f"/accounts?{'&'.join(params)}"
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
        logger.error(f"Error fetching accounts: {e}")
        return {'success': False, 'error': str(e)}


async def create_account(
    app: "LocksmithApplication",
    name: str,
    email: str,
    identifier_aid: str,
    role: str,
    first_name: Optional[str] = "",
    last_name: Optional[str] = ""
) -> Dict[str, Any]:
    """Create a new user account on the Castellan server."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    if not app.vault or not app.vault.hby:
        return {'success': False, 'error': 'No local vault open'}

    try:
        hby = app.vault.hby

        # Build the data part
        data = {
            'username': name,
            "first_name": first_name,
            "last_name": last_name,
            'email': email,
            'aid': identifier_aid,
            'role': role.lower(),
        }

        # Get the KEL for the identifier
        kel = bytearray()
        for msg in hby.db.clonePreIter(pre=identifier_aid):
            kel.extend(msg)

        if not kel:
            return {'success': False, 'error': f'No KEL data available for {identifier_aid}'}

        # Create multipart form data files
        files = {
            'kel': ('output.bin', bytes(kel), 'application/octet-stream'),
            'data': ('data.json', json.dumps(data), 'application/json')
        }

        response = await essr.request(
            path="/accounts",
            method="POST",
            files=files,
            timeout=60,
        )

        if response is not None and response.status_code in (200, 201):
            result = response.json() if response.content else {}
            return {'success': True, 'data': result}
        else:
            if response is not None:
                logger.error(f"Create account failed with status {response.status_code}: {response.text}")
                try:
                    error_msg = response.json().get('description', f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
            else:
                error_msg = "No response"
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.error(f"Error creating account: {e}")
        return {'success': False, 'error': str(e)}

async def delete_account(
    app: "LocksmithApplication",
    account_id: str,
) -> Dict[str, Any]:
    """Delete a user account from the Castellan server."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        response = await essr.request(
            path=f"/accounts/{urllib.parse.quote(account_id, safe='')}",
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
        logger.error(f"Error deleting account: {e}")
        return {'success': False, 'error': str(e)}

async def update_account(
        app: "LocksmithApplication",
        account_id: str,
        username: Optional[str] = None,
        email: Optional[str] = None,
        role: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Update a user account on the Castellan server."""
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        # Build update body with only provided fields
        body = {}
        if username is not None:
            body['username'] = username
        if email is not None:
            body['email'] = email
        if role is not None:
            body['role'] = role.lower()
        if first_name is not None:
            body['first_name'] = first_name
        if last_name is not None:
            body['last_name'] = last_name

        if not body:
            return {'success': False, 'error': 'No fields to update'}

        response = await essr.request(
            path=f"/accounts/{urllib.parse.quote(account_id, safe='')}",
            method="POST",
            json=body,
            timeout=30,
        )

        if response is not None and response.status_code in (200, 204):
            data = response.json() if response.content else {}
            return {'success': True, 'data': data}
        else:
            if response is not None:
                logger.error(f"Update account failed with status {response.status_code}: {response.text}")
                try:
                    error_msg = response.json().get('description', f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
            else:
                error_msg = "No response"
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.error(f"Error updating account: {e}")
        return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Multisig Identifiers
# ---------------------------------------------------------------------------

async def create_multisig_identifier(
        app: "LocksmithApplication",
        kel: bytes,
        multisig_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Create a new multisig identifier on the Castellan server.

    Args:
        app: The Locksmith application instance
        aid: The account AID for the multisig identifier
        kel: The KEL file as bytes
        multisig_data: Dictionary containing multisig configuration including:
            - participants: List of account AIDs
            - thresholds: Threshold configuration per account
            - Any other multisig-specific fields

    Returns:
        Dict with 'success' boolean and optional 'error' or 'data' keys
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    files = {
        'kel': ('output.bin', bytes(kel), 'application/octet-stream'),
        'doc': ('data.json', json.dumps(multisig_data), 'application/json')
    }

    try:
        response = await essr.request(
            path="/multisig/identifiers",
            method="POST",
            files=files,
            timeout=60,
        )

        if response is not None and response.status_code in (200, 201):
            data = response.json() if response.content else {}
            data['success'] = True
            return data
        else:
            if response is not None:
                logger.error(f"Create multisig failed with status {response.status_code}: {response.text}")
                try:
                    error_msg = response.json().get('description', f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
            else:
                error_msg = "No response"
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.error(f"Error creating multisig identifier: {e}")
        return {'success': False, 'error': str(e)}


async def join_multisig_identifier(
        app: "LocksmithApplication",
        multisig_id: str,
        kel: bytes,
        multisig_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Join a multisig identifier on the Castellan server.

    Args:
        app: The Locksmith application instance
        multisig_id: The multisig identifier to join
        kel: The KEL file as bytes
        multisig_data: Dictionary containing my new member AID

    Returns:
        Dict with 'success' boolean and optional 'error' or 'data' keys
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    files = {
        'kel': ('output.bin', bytes(kel), 'application/octet-stream'),
        'doc': ('data.json', json.dumps(multisig_data), 'application/json')
    }

    try:
        response = await essr.request(
            path=f"/multisig/identifiers/{multisig_id}",
            method="PUT",
            files=files,
            timeout=60,
        )

        if response is not None and response.status_code in (200, 201):
            data = response.json() if response.content else {}
            data['success'] = True
            return data
        else:
            if response is not None:
                logger.error(f"Join multisig failed with status {response.status_code}: {response.text}")
                try:
                    error_msg = response.json().get('description', f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
            else:
                error_msg = "No response"
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.error(f"Error joining multisig identifier: {e}")
        return {'success': False, 'error': str(e)}


async def add_multisig_signature_identifier(
        app: "LocksmithApplication",
        multisig_id: str,
        icp: bytes,
        multisig_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Join a multisig identifier on the Castellan server.

    Args:
        app: The Locksmith application instance
        multisig_id: The multisig identifier to join
        icp: The KEL file as bytes
        multisig_data: Dictionary containing my new member AID

    Returns:
        Dict with 'success' boolean and optional 'error' or 'data' keys
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    files = {
        'icp': ('output.bin', bytes(icp), 'application/octet-stream'),
        'doc': ('data.json', json.dumps(multisig_data), 'application/json')
    }

    try:
        response = await essr.request(
            path=f"/multisig/identifiers/{multisig_id}/signatures",
            method="POST",
            files=files,
            timeout=60,
        )

        if response is not None and response.status_code in (200, 201):
            data = response.json() if response.content else {}
            data['success'] = True
            return data
        else:
            if response is not None:
                logger.error(f"Add multisig signature failed with status {response.status_code}: {response.text}")
                try:
                    error_msg = response.json().get('description', f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
            else:
                error_msg = "No response"
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.error(f"Error adding signature to multisig identifier: {e}")
        return {'success': False, 'error': str(e)}


async def create_multisig_registry(
    app: "LocksmithApplication",
    multisig_id: str,
    vcp_bytes: bytes,
    ixn_bytes: bytes,
    registry_name: str,
) -> Dict[str, Any]:
    """
    Create a credential registry for a multisig identifier.

    Args:
        app: The Locksmith application instance
        multisig_id: The multisig identifier AID (URL-encoded)
        vcp_bytes: The VCP (registry inception) event bytes
        ixn_bytes: The IXN (interaction) event bytes that anchor the VCP
        registry_name: User-friendly name for the registry

    Returns:
        Dict with 'success' boolean and optional 'error' or 'data' keys
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        # Build multipart form with VCP, IXN, and body
        files = {
            'vcp': ('vcp.cesr', vcp_bytes, 'application/octet-stream'),
            'ixn': ('ixn.cesr', ixn_bytes, 'application/octet-stream'),
            'body': ('body.json', json.dumps({'name': registry_name}), 'application/json'),
        }

        # URL-encode the multisig_id
        encoded_id = urllib.parse.quote(multisig_id, safe='')

        response = await essr.request(
            path=f"/multisig/identifiers/{encoded_id}/registries",
            method="POST",
            files=files,
            timeout=60,
        )

        if response is not None and response.status_code in (200, 201):
            return {'success': True, 'data': response.json() if response.content else {}}
        else:
            if response is not None:
                logger.error(f"Create registry failed with status {response.status_code}: {response.text}")
                try:
                    error_msg = response.json().get('description', f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
            else:
                error_msg = "No response"
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.exception(f"Error creating registry: {e}")
        return {'success': False, 'error': str(e)}

def get_multisig_state(app, identifier) -> str:
    """Determine multisig state: 'pending', 'ready', or 'active'."""
    aid = identifier.get('aid', '')
    current_event = identifier.get("current_event", None)
    key_state = identifier.get("key_state", None)
    rotation_request = identifier.get("rotation_request", None)
    vcp = identifier.get("vcp", None)
    my_member = get_my_member(app, identifier)

    if identifier.get('aid') is None:
        if all([member.get("member_aid", None) for member in identifier.get("members")]):
            return "inception_ready"
        if my_member.get("member_aid", None) is not None:
            return "inception_joined"
        else:
            return "inception"

    if rotation_request:
        return "rotation" if has_joined(app, identifier) else "rotation_joined"

    elif vcp:
        # Registry creation in progress - behaves like inception states
        return "registry_signed" if has_joined(app, identifier) else "registry_created"

    elif current_event:
        ilk = current_event.get('t')
        if ilk in (Ilks.icp, Ilks.dip):
            return "inception_signed" if has_joined(app, identifier) else "inception_created"
        elif ilk in (Ilks.rot, Ilks.drt):
            return "rotation_signed" if has_joined(app, identifier) else "rotation_created"
        else:
            return "interact_signed" if has_joined(app, identifier) else "interact"

    elif key_state:
        if aid in app.hby.kevers:
            kever = app.hby.kevers[aid]
            return "live_behind" if kever.sner.num < int(key_state.get('s', '0'), 16) else "live"
        else:
            return "live_behind"
    else:
        return "single"

def get_my_member(app, identifier) -> dict | None:
    """Find current user's member object in the multisig, if present."""
    my_account_aid = get_current_account_aid(app)
    if not my_account_aid:
        return None

    members = identifier.get('members', [])
    for member in members:
        if member.get('account_aid') == my_account_aid:
            return member

    return None

def get_current_account_aid(app) -> str:
    """Get the current user's Castellan account AID."""
    if not app or not app.vault:
        return ""

    account = app.vault.plugin_state.get("castellan", {}).get("account", {})
    return account.get("aid", "")

def is_member(app, identifier) -> bool:
    """Check if current user is a member of this multisig."""
    return get_my_member(app, identifier) is not None

def has_approved(app, identifier) -> bool:
    """Check if current user has joined the multisig."""
    my_member = get_my_member(app, identifier)
    return my_member is not None and my_member.get('member_aid') is not None

def has_joined(app, identifier) -> bool:
    """Check if current user has joined the multisig."""
    my_member = get_my_member(app, identifier)
    return has_approved(app, identifier) and my_member.get('public_key', None)

async def load_multisig_member_kels(app, identifier):
    """ Loop through all members of a multisig identifier and load the KELs of members who are not us."""

    for member in identifier.get("members", []):
        member_aid = member.get("member_aid")

        if not member_aid:
            raise ValueError("Member does not have a member_aid, multisig not ready to be completed")

        # Don't need to process our own KEL
        if member_aid in app.vault.hby.habs:
            continue

        result = await fetch_identifier_kel(app, member_aid)
        if not result.get("success"):
            raise ValueError(f"Error fetching KEL for {member_aid}: {result.get('error')}")

        ims = bytearray(result.get("kel_bytes"))
        parsing.Parser(kvy=app.vault.kvy, rvy=app.vault.hby.rvy, local=False).parse(ims)
        app.vault.kvy.processEscrows()

        if member_aid not in app.vault.kvy.kevers:
            raise ValueError(f"Member {member_aid} KEL would not parse.")

async def update_multisig_witnesses(
        app: "LocksmithApplication",
        multisig_id: str,
        adds: list[dict],
        witness_threshold: int,
        cuts: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """
    Update witnesses for a multisig identifier.

    Args:
        app: The Locksmith application instance
        multisig_id: The multisig identifier AID
        adds: List of witness dictionaries to add with keys: 'aid', 'alias', 'oobi'
        witness_threshold: The witness signing threshold
        cuts: Optional list of tuples (witness_aid, witness_alias, witness_oobi) to remove

    Returns:
        Dict with 'success' boolean and optional 'error' or 'data' keys
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    if cuts is None:
        cuts = []

    try:
        # Build request body
        body = {
            'adds': adds,
            'cuts': cuts,
            'witness_threshold': witness_threshold,
        }

        print(json.dumps(body, indent=2))

        # URL-encode the multisig_id
        encoded_id = urllib.parse.quote(multisig_id, safe='')

        response = await essr.request(
            path=f"/multisig/identifiers/{encoded_id}/witnesses",
            method="POST",
            json=body,
            timeout=60,
        )

        if response is not None and response.status_code in (200, 201):
            return {'success': True, 'data': response.json() if response.content else {}}
        else:
            if response is not None:
                logger.error(f"Update witnesses failed with status {response.status_code}: {response.text}")
                try:
                    error_msg = response.json().get('description', f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
            else:
                error_msg = "No response"
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.exception(f"Error updating witnesses: {e}")
        return {'success': False, 'error': str(e)}


async def complete_multisig_witnesses(
    app: "LocksmithApplication",
    multisig_id: str,
    rot: bytes,
    data: list[dict],
) -> Dict[str, Any]:
    """
    Complete witness rotation for a multisig identifier.

    Args:
        app: The Locksmith application instance
        multisig_id: The multisig identifier AID
        rot: The rotation event bytes
        data: Metadata dictionary to include with the rotation

    Returns:
        Dict with 'success' boolean and optional 'error' or 'data' keys
    """
    essr = _get_essr(app)
    if not essr:
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        # Build multipart form with rot and data
        files = {
            'rot': ('rot.cesr', rot, 'application/octet-stream'),
            'data': ('data.json', json.dumps({'witnesses': data}), 'application/json'),
        }

        # URL-encode the multisig_id
        encoded_id = urllib.parse.quote(multisig_id, safe='')

        response = await essr.request(
            path=f"/multisig/identifiers/{encoded_id}/witnesses",
            method="PUT",
            files=files,
            timeout=60,
        )

        if response is not None and response.status_code in (200, 201):
            return {'success': True, 'data': response.json() if response.content else {}}
        else:
            if response is not None:
                logger.error(f"Complete witnesses rotation failed with status {response.status_code}: {response.text}")
                try:
                    error_msg = response.json().get('description', f"Status {response.status_code}")
                except Exception:
                    error_msg = f"Status {response.status_code}"
            else:
                error_msg = "No response"
            return {'success': False, 'error': error_msg}

    except Exception as e:
        logger.exception(f"Error completing witnesses rotation: {e}")
        return {'success': False, 'error': str(e)}


async def rotate_multisig_identifier(app, ghab, isith, nsith, toad, cuts, adds, data=None):
    """ Perform a multisig key rotation

    Perform a key rotation on local member hab then use the Kevers of the other
    members to update and rotate the multisig identifier

    The calling function needs to update the smids and rmids of the ghab before calling this function

    """
    hby = app.hby
    member_hab = ghab.mhab

    member_hab.rotate(isith="1", nsith="1", ncount=1)

    verfers = []
    for smid in ghab.smids:
        verfers.append(hby.kevers[smid].verfers[0])

    ndigers = []
    for rmid in ghab.rmids:
        ndigers.append(hby.kevers[rmid].ndigers[0])

    rot = ghab.rotate(isith=isith, nsith=nsith, toad=toad, cuts=list(cuts), adds=list(adds),
                      data=data, verfers=verfers, digers=ndigers)

    print(rot)

    return rot

