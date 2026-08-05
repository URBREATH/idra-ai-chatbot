import os
import jwt
import logging
from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

KEYCLOAK_PUBLIC_KEY = os.getenv("KEYCLOAK_PUBLIC_KEY", None)
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "master")


def extract_user_id_from_keycloak_token(authorization: str | None = Header(default=None)) -> str:
    """
    Extract 'sub' claim (user ID) from Keycloak JWT token.
    
    Keycloak tokens include:
    - 'sub': Unique user identifier
    - 'preferred_username': Username
    - 'email': User email
    
    If KEYCLOAK_PUBLIC_KEY is not set, token is parsed WITHOUT verification
    (use only in development; production MUST verify).
    
    Args:
        authorization: Authorization header (Bearer token)
    
    Returns:
        User ID (sub claim from Keycloak)
    
    Raises:
        HTTPException 401/403 for missing/invalid tokens
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    token = authorization.removeprefix("Bearer ").strip()
    
    try:
        # If public key is provided, verify the signature (recommended for production)
        if KEYCLOAK_PUBLIC_KEY:
            payload = jwt.decode(
                token,
                KEYCLOAK_PUBLIC_KEY,
                algorithms=["RS256"],
            )
        else:
            # Development mode: decode without verification
            logger.warning("Decoding Keycloak token without verification (dev mode)")
            payload = jwt.decode(token, options={"verify_signature": False}, algorithms=["RS256"])
        
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=403, detail="Token missing 'sub' claim")
        
        return user_id
    
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.error(f"Invalid token: {e}")
        raise HTTPException(status_code=403, detail="Invalid token")


def require_admin_authorization(authorization: str | None = Header(default=None)) -> str:
    """Validate admin token (simple Bearer token, not JWT)."""
    expected_token = os.getenv("ADMIN_TOKEN")
    if not expected_token:
        raise HTTPException(status_code=401, detail="Admin token not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    if token != expected_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")
    return token
