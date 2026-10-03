#!/usr/bin/env python3
"""Validate release Sparkle configuration and build an architecture feed URL."""

import argparse
import base64
import binascii
import sys
from urllib.parse import urlsplit


SUPPORTED_ARCHES = {"arm64", "x86_64"}


def validate_public_key(public_key: str) -> None:
    try:
        decoded_key = base64.b64decode(public_key, validate=True)
    except (binascii.Error, ValueError, TypeError) as error:
        raise ValueError(
            "the Sparkle EdDSA public key must be valid base64 for 32 bytes"
        ) from error
    if (
        len(decoded_key) != 32
        or base64.b64encode(decoded_key).decode("ascii") != public_key
    ):
        raise ValueError(
            "the Sparkle EdDSA public key must be canonical base64 for 32 bytes"
        )


def build_feed_url(feed_base_url: str, arch: str) -> str:
    if arch not in SUPPORTED_ARCHES:
        raise ValueError(f"unsupported Sparkle architecture: {arch}")
    if not feed_base_url or any(
        character.isspace() or ord(character) < 0x20
        for character in feed_base_url
    ):
        raise ValueError("the Sparkle feed base URL must be a non-empty HTTPS URL")
    if any(character in feed_base_url for character in ('"', "\\", "$", "?", "#")):
        raise ValueError("the Sparkle feed base URL contains unsupported characters")

    try:
        parsed_url = urlsplit(feed_base_url)
        # Accessing .port validates an explicitly supplied port.
        _ = parsed_url.port
    except ValueError as error:
        raise ValueError("the Sparkle feed base URL is malformed") from error

    if (
        parsed_url.scheme != "https"
        or parsed_url.hostname is None
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.query
        or parsed_url.fragment
        or parsed_url.path.lower().endswith(".xml")
    ):
        raise ValueError(
            "the Sparkle feed base must be an HTTPS base URL without credentials, "
            "query, fragment, or an appcast filename"
        )

    return f"{feed_base_url.rstrip('/')}/mac/appcast-{arch}.xml"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-key", required=True)
    parser.add_argument("--feed-base-url", required=True)
    parser.add_argument("--arch", required=True, choices=sorted(SUPPORTED_ARCHES))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_public_key(args.public_key)
        feed_url = build_feed_url(args.feed_base_url, args.arch)
    except ValueError as error:
        print(f"Sparkle configuration error: {error}", file=sys.stderr)
        return 2

    print(feed_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
