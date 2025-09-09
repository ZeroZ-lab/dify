from unittest.mock import MagicMock, patch

import pytest

from libs.smtp import SMTPClient


def _mail() -> dict:
    return {"to": "user@example.com", "subject": "Hi", "html": "<b>Hi</b>"}


@patch("libs.smtp.smtplib.SMTP")
def test_smtp_plain_success(mock_smtp_cls: MagicMock):
    mock_smtp = MagicMock()
    mock_smtp_cls.return_value = mock_smtp

    client = SMTPClient(server="smtp.example.com", port=25, username="", password="", _from="noreply@example.com")
    client.send(_mail())

    mock_smtp_cls.assert_called_once_with("smtp.example.com", 25, timeout=10)
    mock_smtp.sendmail.assert_called_once()
    mock_smtp.quit.assert_called_once()


@patch("libs.smtp.smtplib.SMTP")
def test_smtp_tls_opportunistic_success(mock_smtp_cls: MagicMock):
    mock_smtp = MagicMock()
    mock_smtp_cls.return_value = mock_smtp

    client = SMTPClient(
        server="smtp.example.com",
        port=587,
        username="user",
        password="pass",
        _from="noreply@example.com",
        use_tls=True,
        opportunistic_tls=True,
    )
    client.send(_mail())

    mock_smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=10)
    assert mock_smtp.ehlo.call_count == 2
    mock_smtp.starttls.assert_called_once()
    mock_smtp.login.assert_called_once_with("user", "pass")
    mock_smtp.sendmail.assert_called_once()
    mock_smtp.quit.assert_called_once()


@patch("libs.smtp.smtplib.SMTP")
def test_smtp_send_raises_exception_propagates(mock_smtp_cls: MagicMock):
    import smtplib

    mock_smtp = MagicMock()
    mock_smtp.sendmail.side_effect = smtplib.SMTPException("fail")
    mock_smtp_cls.return_value = mock_smtp

    client = SMTPClient(server="smtp.example.com", port=25, username="", password="", _from="noreply@example.com")
    with pytest.raises(smtplib.SMTPException):
        client.send(_mail())
    mock_smtp.quit.assert_called_once()

