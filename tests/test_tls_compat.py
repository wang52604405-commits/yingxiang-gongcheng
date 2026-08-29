# -*- coding: utf-8 -*-
"""桌面端 HTTPS 信任链兼容回归测试。"""

from __future__ import annotations

import ssl
import unittest
import urllib.request
from unittest.mock import MagicMock, patch

import cloud_client
import tls_compat


class TrustedTlsTests(unittest.TestCase):
    def test_fallback_context_never_disables_certificate_validation(self):
        with patch.object(tls_compat, "_truststore", None), patch.object(
            tls_compat, "_certifi", None
        ):
            context = tls_compat.trusted_ssl_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_secure_opener_installs_explicit_trusted_https_handler(self):
        context = ssl.create_default_context()
        with patch.object(
            tls_compat, "trusted_ssl_context", return_value=context
        ) as trusted_context:
            opener = tls_compat.build_secure_opener()
        trusted_context.assert_called_once_with()
        self.assertTrue(
            any(isinstance(handler, urllib.request.HTTPSHandler) for handler in opener.handlers)
        )

    def test_cloud_requests_keep_no_redirect_rule_with_trusted_transport(self):
        opener = MagicMock()
        request = object()
        with patch.object(
            cloud_client.tls_compat, "build_secure_opener", return_value=opener
        ) as secure_opener:
            cloud_client._open_no_redirect(request, timeout=9)
        handler = secure_opener.call_args.args[0]
        self.assertIsInstance(handler, cloud_client._NoCredentialRedirect)
        opener.open.assert_called_once_with(request, timeout=9)


if __name__ == "__main__":
    unittest.main()
