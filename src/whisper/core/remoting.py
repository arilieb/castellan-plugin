# -*- encoding: utf-8 -*-
"""
whisper.core.remoting module

Functions and services for interacting with the healthKERI API.
These were extracted from locksmith.core.remoting as part of plugin architecture refactoring.
"""
import json

import urllib.parse

from typing import TYPE_CHECKING, Dict, Any, Optional

from locksmith.core.credentialing import outputCred, escape_keys

if TYPE_CHECKING:
    from locksmith.core.apping import LocksmithApplication

from keri import help

logger = help.ogler.getLogger(__name__)


async def fetch_published_credentials(
    app: "LocksmithApplication",
    page: int = 0,
    page_size: int = 10,
    filter_term: Optional[str] = None,
    order: Optional[list] = None
) -> Dict[str, Any]:
    """
    Fetch published credentials from the healthKERI API.

    Args:
        app: Application instance with vault and ESSR connection
        page: Page number (0-indexed)
        page_size: Number of items per page
        filter_term: Optional filter/search term
        order: Optional list of sort orders (e.g., ['+alias', '-aid'])

    Returns:
        API response with 'identifiers', 'count', 'page', 'num_pages'
    """
    if not app.vault or not app.vault.plugin_state.get("healthkeri", {}).get("essr"):
        return {'success': False, 'error': 'No ESSR connection'}

    try:
        # Build query parameters
        params = [f"published=true", f"page={page}", f"page_size={page_size}"]

        if filter_term:
            params.append(f"filter={urllib.parse.quote(filter_term)}")

        if order:
            for o in order:
                params.append(f"order={urllib.parse.quote(o)}")

        path = f"/credentials?{'&'.join(params)}"

        # Make async request - APIClient.request is the async method
        response = await app.vault.plugin_state.get("healthkeri", {}).get("essr").request(path=path, method="GET")

        if response is not None and response.status_code == 200:
            data = response.json()
            data['success'] = True
            return data
        else:
            print(response.json())
            return {
                'success': False,
                'error': f"API error: {response.status_code if response else 'No response'}"
            }

    except Exception as e:
        logger.error(f"Error fetching account identifiers: {e}")
        return {'success': False, 'error': str(e)}


async def publish_credential(
    app: "LocksmithApplication",
    credential_said: str, schema: dict, issuer: str, recipient: str
) -> Dict[str, Any]:
    """
    Publishes a digital credential using the specified schema, issuer, and recipient details. This
    method verifies the necessary vault components, constructs the required document and credential
    data, and attempts a POST request to publish the credential.

    If all operations succeed, the method returns the server response. Otherwise, it provides
    appropriate error details.

    Parameters:
        app (LocksmithApplication): The Locksmith application instance, which includes the vault
            and ESSR connection for credential handling.
        credential_said (str): The SAID (Self-Addressing Identifier) of the credential being
            published.
        schema (dict): The schema data dict identifying the credential's structure and constraints.
        issuer (str): The identifier of the entity issuing the credential.
        recipient (str): The identifier of the entity receiving the credential.

    Returns:
        Dict[str, Any]: A dictionary containing the success status and either the server response
            data for a successful operation or an error message in case of a failure.
    """

    if not app.vault or not app.vault.plugin_state.get("healthkeri", {}).get("essr"):
        return {'success': False, 'error': 'No ESSR connection'}

    if not app.vault.hby:
        return {'success': False, 'error': 'No local vault open'}

    try:
        hby = app.vault.hby
        rgy = app.vault.rgy

        # Build the doc part
        doc = {
            'said': credential_said,
            'issuer': issuer,
            'recipient': recipient,
            'schema': escape_keys(schema),
            'publish': True,
        }

        # Get the ACDC
        acdc = outputCred(hby, rgy, credential_said)

        if not acdc:
            return {'success': False, 'error': f'No ACDC data available for {credential_said}'}

        # Create multipart form data files
        files = {
            'acdc': ('output.bin', bytes(acdc), 'application/octet-stream'),
            'doc': ('data.json', json.dumps(doc), 'application/json')
        }

        # Make POST request to create identifier
        response = await app.vault.plugin_state.get("healthkeri", {}).get("essr").request(
            path="/credentials",
            method="POST",
            files=files,
            timeout=60
        )

        if response and response.status_code in (200, 201):
            return {'success': True, 'data': response.json()}
        else:
            if response is not None:
                logger.error(f"Publish failed with status {response.status_code}: {response.text}")
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
        logger.error(f"Error publishing credential: {e}")
        return {'success': False, 'error': str(e)}
