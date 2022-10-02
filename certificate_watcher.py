#!/usr/bin/env python3

"""Prints (on stderr) the list and expiration time ssl certificats of
all given domains like:

   ./warn_expire.py mdk.fr python.org duckduckgo.com
   mdk.fr expire in 2 days

"""

import argparse
import csv
from datetime import datetime, timedelta
import re
import socket
import ssl
import sys

from ocspchecker import ocspchecker


__version__ = "0.0.6"


def get_server_certificate(service, timeout=10):
    """Retrieve the certificate from the server at the specified address" """
    context = ssl.create_default_context()
    context.options &= ssl.CERT_REQUIRED
    # context.verify_flags = ssl.VERIFY_CRL_CHECK_LEAF
    context.check_hostname = True
    with socket.create_connection(
        (service.ip or service.hostname, service.port), timeout
    ) as sock:
        with context.wrap_socket(sock, server_hostname=service.hostname) as sslsock:
            return sslsock.getpeercert()


def parse_args():
    parser = argparse.ArgumentParser(
        prog="Certificate Watcher",
        description="Watch expiration of certificates of a bunch of websites.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="Add OK lines if all tests are OK",
    )
    parser.add_argument(
        "--csv",
        "-c",
        action="count",
        default=0,
        help="replace ': ' by ',' in order to generate a CSV file",
    )
    parser.add_argument(
        "--attention",
        "-a",
        action="count",
        default=0,
        help="add '\a' in case of KO in order to generate beeps (depending of the terminal)",
    )
    parser.add_argument(
        "--ocsp",
        "-o",
        action="count",
        default=0,
        help="OCSP CRL check, time consuming, advance checks not supported currently",
    )
    parser.add_argument(
        "--low",
        "-l",
        default=15,
        help="Number of days before expiration considered as low (default 15 days)",
    )
    parser.add_argument(
        "--high",
        "-H",
        default=365,
        help="Number of days after validation considered as high (default 365 days)",
    )
    parser.add_argument(
        "--delay",
        "-d",
        default=10.0,
        help="Number of seconds (real) before timeout (default 10.0 seconds)",
    )

    parser.add_argument(
        "-f",
        "--from-file",
        type=argparse.FileType("r"),
        help="Check host from this file (one per line)",
    )
    parser.add_argument("hosts", nargs="*", help="Hosts to check")
    parser.add_argument(
        "--version", action="version", version="%(prog)s " + __version__
    )
    return parser.parse_args()


class Service:
    SPEC = "(?P<ip>@[^@:]+)|(?P<port>:[^@:]+)|(?P<hostname>[^@:]+)"

    def __init__(self, description):
        self.description = description
        self.ip = None
        self.port = 443
        self.hostname = None
        for token in re.finditer(Service.SPEC, description):
            kind = token.lastgroup
            value = token.group()
            if kind == "ip":
                self.ip = value[1:]
            if kind == "port":
                self.port = int(value[1:])
            if kind == "hostname":
                self.hostname = value

    def __repr__(self):
        return self.description


class CertificateValidationError(Exception):
    pass


def validate_certificate(
    service: Service,
    limitlow: timedelta,
    limithigh: timedelta = timedelta(days=365),
    check_ocsp: bool = False,
    delay=10,
):
    try:
        cert = get_server_certificate(service, timeout=delay)
    except socket.timeout as err:
        raise CertificateValidationError("connect timeout") from err
    except ConnectionResetError as err:
        raise CertificateValidationError("Connection reset") from err
    except Exception as err:
        raise CertificateValidationError(str(err)) from err
    else:
        not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y GMT")
        not_before = datetime.strptime(cert["notBefore"], "%b %d %H:%M:%S %Y GMT")
        expire_in = not_after - datetime.utcnow()
        certificate_age = datetime.utcnow() - not_before
        if (
            bool(check_ocsp)
            and ocspchecker.get_ocsp_status(service)[2] == "OCSP Status: REVOKED"
        ):
            raise CertificateValidationError("OCSP Satus: REVOKED")
        if expire_in < limitlow:
            raise CertificateValidationError(
                f"Certificate expires in {expire_in.total_seconds() // 86400:.0f} days"
            )
        if certificate_age > limithigh:
            raise CertificateValidationError(
                f"Certificate is too old (has been created {certificate_age.total_seconds() // 86400:.0f} days ago)"
            )


def main():
    args = parse_args()
    hosts = args.hosts
    verbose = args.verbose
    attention = args.attention
    ocsp = args.ocsp
    low = int(args.low)
    high = int(args.high)
    delay = float(args.delay)
    if args.csv > 0:
        writer = csv.writer(sys.stdout, delimiter=";")
        writer.writerow(["Service", "Status"])
    else:
        writer = csv.writer(sys.stdout, delimiter=":")
    if args.from_file:
        hosts.extend(
            host.strip()
            for host in args.from_file.read().split("\n")
            if host and not host.startswith("#")
        )
        args.from_file.close()

    for service in map(Service, hosts):
        try:
            validate_certificate(
                service,
                limitlow=timedelta(days=low),
                limithigh=timedelta(days=high),
                check_ocsp=ocsp,
                delay=delay,
            )
        except CertificateValidationError as error:
            writer.writerow([str(service), str(error)])
            if not args.csv and args.attention:
                print("\a")
        else:
            if verbose:
                writer.writerow([str(service), "OK"])


if __name__ == "__main__":
    main()
