"""Test package for unittest discovery."""

# Install before any unit, integration, or snapshot test imports a provider.
# Individual intentional live-call tests must opt out with ``@allow_network``.
from tests.unit.network_guard import install

install()
