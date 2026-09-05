# -*- encoding: utf-8 -*-
"""
castellan.core.remoting module

Functions for interacting with the Castellan credential management server.
"""
import asyncio
import base64
import json
import urllib.parse
from typing import TYPE_CHECKING, Dict, Any, Optional

from keri.core.scheming import Schemer
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
    return await _essr_health_roundtrip(essr)


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

