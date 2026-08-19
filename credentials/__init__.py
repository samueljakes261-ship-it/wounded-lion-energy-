"""
Credential management layer for external scraping/API services
(currently ZenRows).

Responsibilities live in dedicated modules:

- crypto.py    -- Fernet encryption of secrets at rest, keyed by
                  MASTER_CREDENTIAL_KEY (never stored on disk).
- models.py    -- StoredCredential (encrypted, persisted) and
                  CredentialRuntimeState (non-secret health metadata).
- store.py     -- CredentialStore: loads/saves credentials.json and
                  the companion runtime-state file.
- failures.py  -- FailureType classification.
- manager.py   -- CredentialManager: selection, cooldown, disable,
                  failover.
- health.py    -- request-free health checks.
- zenrows_provider.py -- shared connect-with-failover() used by the
                  existing ZenRowsSession classes.
- cli.py       -- `python -m credentials.cli ...` management commands.

NEVER log or raise an exception containing a plaintext secret,
decrypted API key, or MASTER_CREDENTIAL_KEY. Only credential_id values
and failure classifications are safe to log.
"""
from dotenv import load_dotenv

# Loaded once here so that every module in this package (and every
# caller that merely imports something from `credentials`) can rely on
# .env already being read, regardless of import order.
load_dotenv()
