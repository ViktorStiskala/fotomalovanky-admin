"""Generic download service with proxy support."""

import hashlib
import ssl
from typing import Literal
from urllib.parse import urlparse

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import ProxyConfig
from app.services.download.config import (
    ACCEPT_LANGUAGES,
    BASE_HEADERS,
    RETRYABLE_STATUS_CODES,
    USER_AGENTS,
    RetryConfig,
)

logger = structlog.get_logger(__name__)


class DownloadService:
    """Service for downloading files with optional proxy fallback.

    Usage:
        async with DownloadService() as service:
            data = await service.download(url)

    Or manually:
        service = DownloadService()
        try:
            data = await service.download(url)
        finally:
            await service.close()
    """

    def __init__(
        self,
        timeout: float = 30.0,
        retries: int | RetryConfig | Literal[False] | None = None,
    ) -> None:
        """Initialize download service.

        Args:
            timeout: Default timeout for direct downloads
            retries: Retry configuration
                - None: Use defaults (3 attempts, 1-10s exponential backoff)
                - False: Disable retries entirely
                - int: Number of attempts with default backoff
                - RetryConfig: Full customization
        """
        from app.config import settings

        self.proxies = settings.proxies
        self.default_timeout = timeout
        self._retry_config = self._parse_retry_config(retries)

        # Shared client for direct downloads (reused across requests)
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
        )

    def _parse_retry_config(
        self,
        retries: int | RetryConfig | Literal[False] | None,
    ) -> RetryConfig | None:
        """Parse retry configuration into RetryConfig or None (disabled)."""
        if retries is None:
            return RetryConfig()  # defaults
        if retries is False:
            return None  # disabled
        if isinstance(retries, int):
            return RetryConfig(max_attempts=retries)
        return retries  # RetryConfig instance

    def _get_retrying(self) -> AsyncRetrying:
        """Get configured AsyncRetrying instance."""
        if self._retry_config is None:
            raise RuntimeError("Retries are disabled")
        return AsyncRetrying(
            retry=retry_if_exception_type(httpx.RequestError),
            stop=stop_after_attempt(self._retry_config.max_attempts),
            wait=wait_exponential(
                multiplier=self._retry_config.multiplier,
                min=self._retry_config.min_wait,
                max=self._retry_config.max_wait,
            ),
            reraise=True,
        )

    async def close(self) -> None:
        """Close the HTTP client. Call when done with the service."""
        await self._client.aclose()

    async def __aenter__(self) -> "DownloadService":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    def _select_for_host(self, hostname: str, options: tuple[str, ...], seed: int = 0) -> str:
        """Deterministically select an option based on hostname.

        Args:
            hostname: Hostname to hash
            options: Tuple of options to select from
            seed: Different seed values produce different selections for same hostname
        """
        hash_input = f"{hostname}:{seed}".encode()
        hash_bytes = hashlib.md5(hash_input, usedforsecurity=False).digest()
        index = int.from_bytes(hash_bytes[:4], "big") % len(options)
        return options[index]

    def _build_headers(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Build request headers.

        Args:
            url: URL to extract hostname for deterministic header selection
            headers: Complete headers to use (replaces defaults entirely)
            extra_headers: Additional headers to merge with defaults

        Note: headers and extra_headers are mutually exclusive.
        """
        if headers is not None:
            return headers

        hostname = urlparse(url).hostname or "unknown"
        result = {
            **BASE_HEADERS,
            "User-Agent": self._select_for_host(hostname, USER_AGENTS, seed=0),
            "Accept-Language": self._select_for_host(hostname, ACCEPT_LANGUAGES, seed=1),
        }
        if extra_headers:
            result.update(extra_headers)
        return result

    def _get_ssl_context(self, proxy: ProxyConfig) -> ssl.SSLContext | bool:
        """Get SSL context for proxy with certificate verification.

        For MITM proxies (like BrightData), we use VERIFY_ALLOW_PROXY_CERTS flag
        which relaxes OpenSSL 3.5+ strict validation of proxy-generated certificates
        (specifically the missing Authority Key Identifier extension).

        If certificate_path is set, creates an SSL context with:
        - The proxy's CA certificate loaded
        - VERIFY_ALLOW_PROXY_CERTS flag for proxy certificate compatibility
        - Full certificate verification and hostname checking

        Otherwise, returns True to use default system verification.
        """
        if proxy.certificate_path:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.load_verify_locations(proxy.certificate_path)
            ctx.verify_mode = ssl.CERT_REQUIRED
            ctx.check_hostname = True
            ctx.verify_flags = ssl.VERIFY_ALLOW_PROXY_CERTS
            return ctx
        return True

    async def _download_direct(
        self,
        url: str,
        request_headers: dict[str, str],
    ) -> bytes:
        """Direct download using shared client (with configurable retries)."""

        async def fetch() -> bytes:
            response = await self._client.get(url, headers=request_headers)
            response.raise_for_status()
            return response.content

        if self._retry_config is None:
            return await fetch()

        async for attempt in self._get_retrying():
            with attempt:
                return await fetch()

        raise RuntimeError("Unreachable")

    async def _download_proxy(
        self,
        url: str,
        request_headers: dict[str, str],
        proxy: ProxyConfig,
        timeout: float,
    ) -> bytes:
        """Download via proxy (creates new client per request, with configurable retries)."""

        async def fetch() -> bytes:
            async with httpx.AsyncClient(
                proxy=proxy.url,
                verify=self._get_ssl_context(proxy),
                timeout=timeout,
                follow_redirects=True,
            ) as client:
                response = await client.get(url, headers=request_headers)
                response.raise_for_status()
                logger.info("Downloaded via proxy", url=url, host=proxy.host, size=len(response.content))
                return response.content

        if self._retry_config is None:
            return await fetch()

        async for attempt in self._get_retrying():
            with attempt:
                return await fetch()

        raise RuntimeError("Unreachable")

    async def download(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
        proxy: bool = False,
        proxy_fallback: bool = False,
        timeout: float = 30.0,
        proxy_timeout: float = 60.0,
    ) -> bytes:
        """Download file from URL.

        Args:
            url: URL to download from
            headers: Complete headers (replaces all defaults, mutually exclusive with extra_headers)
            extra_headers: Additional headers to merge with defaults (mutually exclusive with headers)
            proxy: Use first available proxy directly (mutually exclusive with proxy_fallback)
            proxy_fallback: Try direct first, fall back to proxies on failure (mutually exclusive with proxy)
            timeout: Timeout for direct downloads (default: 30.0)
            proxy_timeout: Timeout when using proxy (default: 60.0)

        Raises:
            ValueError: If both headers and extra_headers are provided
            ValueError: If both proxy and proxy_fallback are True
        """
        if headers is not None and extra_headers is not None:
            raise ValueError("Cannot specify both 'headers' and 'extra_headers'")
        if proxy and proxy_fallback:
            raise ValueError("Cannot specify both 'proxy' and 'proxy_fallback'")

        request_headers = self._build_headers(url, headers, extra_headers)

        # Direct proxy mode - use first available proxy
        if proxy:
            if not self.proxies:
                raise ValueError("No proxies configured")
            return await self._download_proxy(url, request_headers, self.proxies[0], proxy_timeout)

        # Proxy fallback mode - try direct, then proxies
        if proxy_fallback:
            try:
                return await self._download_direct(url, request_headers)
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in RETRYABLE_STATUS_CODES:
                    raise  # Not a bot-protection error, don't try proxies
                logger.warning(
                    "Direct download blocked, trying proxies",
                    url=url,
                    status=e.response.status_code,
                )
                last_error: Exception = e
            except httpx.RequestError as e:
                # Network errors after tenacity retries exhausted - try proxies
                logger.warning("Direct download failed with network error", url=url, error=str(e))
                last_error = e

            # Try each proxy in order
            for i, proxy_config in enumerate(self.proxies):
                try:
                    logger.info("Trying proxy", proxy_index=i, host=proxy_config.host)
                    return await self._download_proxy(url, request_headers, proxy_config, proxy_timeout)
                except Exception as e:
                    last_error = e
                    logger.warning(
                        "Proxy download failed",
                        proxy_index=i,
                        host=proxy_config.host,
                        error=str(e),
                    )

            # All attempts failed
            raise last_error

        # Default: direct download only (uses shared client)
        return await self._download_direct(url, request_headers)
