"""Provision the first administrator device from the deployment host."""
import argparse
import sys

from cryptography.hazmat.primitives.serialization import Encoding
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.device_access import IssueDevice, add_device, issue_certificate, registered_certificate
from app.db.session import SessionLocal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--register", action="store_true", help="Read a signed client certificate instead of a CSR")
    args = parser.parse_args()
    try:
        details = IssueDevice(name=args.name, owner=args.owner, pem=sys.stdin.read(16385))
        cert = registered_certificate(details.pem) if args.register else issue_certificate(details.pem)
        with SessionLocal() as db:
            add_device(db, details, cert)
    except HTTPException as exc:
        parser.exit(1, f"{exc.detail}\n")
    except ValidationError:
        parser.exit(1, "Некорректное имя, владелец или PEM\n")
    sys.stdout.buffer.write(cert.public_bytes(Encoding.PEM))


if __name__ == "__main__":
    main()
