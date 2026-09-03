import socket
import unittest
from ftplib import error_perm, error_temp
from unittest.mock import MagicMock, patch

from app.models.catalog import XmlServerSetting
from app.services.xml_auto_import import _download_xml_file, _pending_xml_files, connect


def setting(attempts=5, delay=3):
    return XmlServerSetting(
        protocol="FTP", host="ftp.test", port=21, username="user", password="secret",
        xml_dir="/xml", connection_attempts=attempts, retry_delay_seconds=delay,
    )


def client(connect_error=None, login_error=None):
    value = MagicMock()
    if connect_error:
        value.connect.side_effect = connect_error
    if login_error:
        value.login.side_effect = login_error
    return value


class FtpRetryTests(unittest.TestCase):
    def run_connect(self, clients, config=None):
        with patch("app.services.xml_auto_import.FTP", side_effect=clients) as factory, patch("app.services.xml_auto_import.time.sleep") as sleep:
            result = connect(config or setting())
        return result, factory, sleep

    def test_connects_on_first_attempt_without_sleep(self):
        expected = client()
        result, factory, sleep = self.run_connect([expected])
        self.assertIs(result, expected)
        self.assertEqual(factory.call_count, 1)
        sleep.assert_not_called()

    def test_connects_on_second_attempt(self):
        result, factory, sleep = self.run_connect([client(ConnectionRefusedError()), client()])
        self.assertEqual(result._vrcatalog_attempt, 2)
        self.assertEqual(factory.call_count, 2)
        sleep.assert_called_once_with(3)

    def test_connects_on_fifth_attempt(self):
        clients = [client(error_temp("temporary")) for _ in range(4)] + [client()]
        result, factory, sleep = self.run_connect(clients)
        self.assertEqual(result._vrcatalog_attempt, 5)
        self.assertEqual(factory.call_count, 5)
        self.assertEqual(sleep.call_count, 4)

    def test_exhausts_all_attempts_for_timeout(self):
        clients = [client(TimeoutError("timeout")) for _ in range(5)]
        with patch("app.services.xml_auto_import.FTP", side_effect=clients) as factory, patch("app.services.xml_auto_import.time.sleep") as sleep:
            with self.assertRaises(TimeoutError) as raised:
                connect(setting())
        self.assertEqual(factory.call_count, 5)
        self.assertEqual(sleep.call_count, 4)
        self.assertEqual(raised.exception.vrcatalog_attempts, 5)

    def test_wrong_password_and_user_are_not_retried(self):
        for message in ("530 Login incorrect", "530 Invalid password"):
            with self.subTest(message=message), patch("app.services.xml_auto_import.FTP", return_value=client(login_error=error_perm(message))) as factory, patch("app.services.xml_auto_import.time.sleep") as sleep:
                with self.assertRaises(error_perm):
                    connect(setting())
                self.assertEqual(factory.call_count, 1)
                sleep.assert_not_called()

    def test_wrong_port_is_retried_as_connection_refused(self):
        clients = [client(ConnectionRefusedError("refused")) for _ in range(5)]
        with patch("app.services.xml_auto_import.FTP", side_effect=clients) as factory, patch("app.services.xml_auto_import.time.sleep"):
            with self.assertRaises(ConnectionRefusedError):
                connect(setting())
        self.assertEqual(factory.call_count, 5)

    def test_permanent_dns_error_and_invalid_config_are_not_retried(self):
        dns_error = socket.gaierror(socket.EAI_NONAME, "unknown host")
        with patch("app.services.xml_auto_import.FTP", return_value=client(dns_error)) as factory, patch("app.services.xml_auto_import.time.sleep") as sleep:
            with self.assertRaises(socket.gaierror):
                connect(setting())
            self.assertEqual(factory.call_count, 1)
            sleep.assert_not_called()
        with self.assertRaises(ValueError):
            connect(XmlServerSetting(protocol="SFTP", host="x", port=22, username="u", password="p", xml_dir="/", connection_attempts=5, retry_delay_seconds=3))

    def test_error_xml_files_are_not_selected_for_reimport(self):
        pending, failed = _pending_xml_files([
            "tov.xml", "ERROR_tov-old.xml", "folder/error_broken.XML", "readme.txt",
        ])

        self.assertEqual(pending, ["tov.xml"])
        self.assertEqual(failed, ["ERROR_tov-old.xml", "folder/error_broken.XML"])

    def test_download_reports_actual_byte_count(self):
        ftp = MagicMock()
        ftp.retrbinary.side_effect = lambda _command, callback: (
            callback(b"<catalog>"), callback(b"</catalog>")
        )
        destination = MagicMock()

        downloaded = _download_xml_file(ftp, "tov.xml", destination)

        self.assertEqual(downloaded, 19)
        self.assertEqual(destination.write.call_count, 2)


if __name__ == "__main__":
    unittest.main()
