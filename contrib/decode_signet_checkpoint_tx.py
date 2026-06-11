#!/usr/bin/env python3
"""Fetch and decode an ASM signet checkpoint transaction from mempool.space.

This utility is meant for self-serve inspection of ASM checkpoint transactions
posted to signet. Give it a signet txid and it will fetch the transaction JSON
from mempool.space, extract the checkpoint payload from the first input's
taproot witness script, and print the fields that are most useful for
correlating the tx back to Strata/Alpen state.

Important details:
- The useful payload is not in the `OP_RETURN`; the `OP_RETURN` only carries the
  short ALPN tag.
- The checkpoint data is embedded in the first input's witness tapscript
  envelope.
- The main correlation handles are the checkpoint epoch, covered L1 height, OL
  tip slot, and OL tip block id.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


DEFAULT_MEMPOOL_SIGNET_API = "https://mempool.space/signet/api"
OP_CHECKSIG = 0xAC
OP_IF = 0x63
OP_ENDIF = 0x68


class DecodeError(Exception):
    """Raised when the transaction cannot be interpreted as a checkpoint tx."""


@dataclass
class ScriptItem:
    kind: str
    value: bytes | int


@dataclass
class CheckpointDecode:
    txid: str
    signet_block_height: int | None
    signet_block_hash: str | None
    signet_block_time: int | None
    signet_block_time_iso: str | None
    envelope_pubkey: str | None
    codec_prefix_len: int
    codec_prefix_hex: str
    payload_len: int
    checkpoint_epoch: int
    covered_l1_height: int
    ol_tip_slot: int
    ol_tip_blkid: str
    sidecar_offset: int
    proof_offset: int
    proof_len: int
    ol_state_diff_len: int
    ol_logs_count: int | None
    ol_logs_blob_len: int
    terminal_timestamp_ms: int
    terminal_timestamp_iso: str
    terminal_parent_blkid: str
    terminal_body_root: str
    terminal_logs_root: str


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch a signet transaction from mempool.space and decode the ASM "
            "checkpoint payload carried in the first input's taproot witness "
            "script."
        ),
        epilog=(
            "The default source is "
            "https://mempool.space/signet/api/tx/<txid>. "
            "Human-readable output prints the key correlation fields; "
            "--json emits a machine-readable version of the same data."
        ),
    )
    parser.add_argument("txid", help="Signet txid to fetch from mempool.space")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_MEMPOOL_SIGNET_API,
        help=f"Mempool API base URL (default: {DEFAULT_MEMPOOL_SIGNET_API})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="HTTP timeout in seconds (default: 20)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the decoded result as JSON instead of human-readable text",
    )
    return parser.parse_args(argv[1:])


def validate_txid(txid: str) -> str:
    if len(txid) != 64 or any(c not in "0123456789abcdefABCDEF" for c in txid):
        raise DecodeError(f"invalid txid: {txid!r}")
    return txid.lower()


def fetch_tx_json(txid: str, base_url: str, timeout: float) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/tx/{txid}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "asm-checkpoint-decoder/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return json.loads(resp.read().decode(charset))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise DecodeError(f"mempool API returned HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise DecodeError(f"failed to reach mempool API: {exc.reason}") from exc


def parse_script(script_hex: str) -> list[ScriptItem]:
    script = bytes.fromhex(script_hex)
    items: list[ScriptItem] = []
    pos = 0

    while pos < len(script):
        opcode = script[pos]
        pos += 1

        if opcode <= 75:
            items.append(ScriptItem("push", script[pos : pos + opcode]))
            pos += opcode
            continue

        if opcode == 76:
            if pos >= len(script):
                raise DecodeError("truncated OP_PUSHDATA1")
            length = script[pos]
            pos += 1
            items.append(ScriptItem("push", script[pos : pos + length]))
            pos += length
            continue

        if opcode == 77:
            if pos + 2 > len(script):
                raise DecodeError("truncated OP_PUSHDATA2")
            length = struct.unpack_from("<H", script, pos)[0]
            pos += 2
            items.append(ScriptItem("push", script[pos : pos + length]))
            pos += length
            continue

        if opcode == 78:
            if pos + 4 > len(script):
                raise DecodeError("truncated OP_PUSHDATA4")
            length = struct.unpack_from("<I", script, pos)[0]
            pos += 4
            items.append(ScriptItem("push", script[pos : pos + length]))
            pos += length
            continue

        items.append(ScriptItem("op", opcode))

    return items


def extract_envelope(items: list[ScriptItem]) -> tuple[str | None, bytes]:
    envelope_pubkey: str | None = None
    for idx in range(len(items) - 1):
        cur = items[idx]
        nxt = items[idx + 1]
        if (
            cur.kind == "push"
            and isinstance(cur.value, bytes)
            and len(cur.value) == 32
            and nxt.kind == "op"
            and nxt.value == OP_CHECKSIG
        ):
            envelope_pubkey = cur.value.hex()
            break

    # The checkpoint payload is carried inside the witness tapscript envelope.
    # The OP_RETURN tag in vout[0] only identifies the tx as ALPN/SPS-50.
    payload_parts: list[bytes] = []
    inside_envelope = False
    depth = 0

    for item in items:
        if item.kind == "op" and item.value == OP_IF:
            depth += 1
            if depth == 1:
                inside_envelope = True
            continue

        if item.kind == "op" and item.value == OP_ENDIF:
            if depth == 1:
                inside_envelope = False
            if depth > 0:
                depth -= 1
            continue

        if inside_envelope and item.kind == "push":
            assert isinstance(item.value, bytes)
            payload_parts.append(item.value)

    if not payload_parts:
        raise DecodeError("no envelope payload found in witness script")

    return envelope_pubkey, b"".join(payload_parts)


def unpack_u32(buf: bytes, offset: int) -> int:
    if offset + 4 > len(buf):
        raise DecodeError("unexpected end of buffer while reading u32")
    return struct.unpack_from("<I", buf, offset)[0]


def unpack_u64(buf: bytes, offset: int) -> int:
    if offset + 8 > len(buf):
        raise DecodeError("unexpected end of buffer while reading u64")
    return struct.unpack_from("<Q", buf, offset)[0]


def maybe_count_ol_logs(logs_blob: bytes) -> int | None:
    if not logs_blob:
        return 0
    if len(logs_blob) < 4:
        return None

    first_offset = unpack_u32(logs_blob, 0)
    if first_offset == 0 or first_offset > len(logs_blob) or first_offset % 4 != 0:
        return None

    return first_offset // 4


def parse_candidate_payload(
    tx_json: dict[str, Any],
    envelope_pubkey: str | None,
    raw_payload: bytes,
    prefix_len: int,
) -> CheckpointDecode:
    if prefix_len >= len(raw_payload):
        raise DecodeError("payload prefix consumes the full raw payload")

    payload = raw_payload[prefix_len:]
    if len(payload) < 56:
        raise DecodeError("payload too short for CheckpointPayload head")

    checkpoint_epoch = unpack_u32(payload, 0)
    covered_l1_height = unpack_u32(payload, 4)
    ol_tip_slot = unpack_u64(payload, 8)
    ol_tip_blkid = payload[16:48].hex()
    sidecar_offset = unpack_u32(payload, 48)
    proof_offset = unpack_u32(payload, 52)

    if sidecar_offset < 56:
        raise DecodeError("invalid sidecar offset")
    if proof_offset <= sidecar_offset or proof_offset > len(payload):
        raise DecodeError("invalid proof offset")

    sidecar = payload[sidecar_offset:proof_offset]
    proof = payload[proof_offset:]
    if len(sidecar) < 112:
        raise DecodeError("sidecar too short for fixed header")

    ol_state_diff_offset = unpack_u32(sidecar, 0)
    ol_logs_offset = unpack_u32(sidecar, 4)
    if ol_state_diff_offset < 112:
        raise DecodeError("invalid state diff offset")
    if ol_logs_offset < ol_state_diff_offset or ol_logs_offset > len(sidecar):
        raise DecodeError("invalid OL logs offset")

    terminal_timestamp_ms = unpack_u64(sidecar, 8)
    terminal_parent_blkid = sidecar[16:48].hex()
    terminal_body_root = sidecar[48:80].hex()
    terminal_logs_root = sidecar[80:112].hex()

    ol_state_diff_len = ol_logs_offset - ol_state_diff_offset
    logs_blob = sidecar[ol_logs_offset:]
    ol_logs_count = maybe_count_ol_logs(logs_blob)

    status = tx_json.get("status") or {}
    signet_block_time = status.get("block_time")

    return CheckpointDecode(
        txid=tx_json.get("txid", ""),
        signet_block_height=status.get("block_height"),
        signet_block_hash=status.get("block_hash"),
        signet_block_time=signet_block_time,
        signet_block_time_iso=unix_to_iso(signet_block_time),
        envelope_pubkey=envelope_pubkey,
        codec_prefix_len=prefix_len,
        codec_prefix_hex=raw_payload[:prefix_len].hex(),
        payload_len=len(payload),
        checkpoint_epoch=checkpoint_epoch,
        covered_l1_height=covered_l1_height,
        ol_tip_slot=ol_tip_slot,
        ol_tip_blkid=ol_tip_blkid,
        sidecar_offset=sidecar_offset,
        proof_offset=proof_offset,
        proof_len=len(proof),
        ol_state_diff_len=ol_state_diff_len,
        ol_logs_count=ol_logs_count,
        ol_logs_blob_len=len(logs_blob),
        terminal_timestamp_ms=terminal_timestamp_ms,
        terminal_timestamp_iso=unix_ms_to_iso(terminal_timestamp_ms),
        terminal_parent_blkid=terminal_parent_blkid,
        terminal_body_root=terminal_body_root,
        terminal_logs_root=terminal_logs_root,
    )


def decode_checkpoint_tx(tx_json: dict[str, Any]) -> CheckpointDecode:
    vins = tx_json.get("vin")
    if not isinstance(vins, list) or not vins:
        raise DecodeError("transaction has no inputs")

    witness = vins[0].get("witness")
    if not isinstance(witness, list) or len(witness) < 2:
        raise DecodeError("first input does not contain a taproot witness script")

    script_items = parse_script(witness[1])
    envelope_pubkey, raw_payload = extract_envelope(script_items)

    last_error: DecodeError | None = None
    for prefix_len in range(0, min(8, len(raw_payload)) + 1):
        try:
            return parse_candidate_payload(tx_json, envelope_pubkey, raw_payload, prefix_len)
        except DecodeError as exc:
            last_error = exc

    raise DecodeError(f"failed to locate SSZ payload start: {last_error}")


def unix_to_iso(ts: int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def unix_ms_to_iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()


def print_human(decoded: CheckpointDecode) -> None:
    lines = [
        f"txid: {decoded.txid}",
        f"signet block: {decoded.signet_block_height} ({decoded.signet_block_hash})",
        f"signet block time: {decoded.signet_block_time_iso}",
        f"envelope pubkey: {decoded.envelope_pubkey}",
        f"codec prefix: len={decoded.codec_prefix_len} hex={decoded.codec_prefix_hex or '(none)'}",
        f"checkpoint epoch: {decoded.checkpoint_epoch}",
        f"covered L1 height: {decoded.covered_l1_height}",
        f"OL tip slot: {decoded.ol_tip_slot}",
        f"OL tip blkid: {decoded.ol_tip_blkid}",
        f"sidecar offset: {decoded.sidecar_offset}",
        f"proof offset: {decoded.proof_offset}",
        f"proof len: {decoded.proof_len}",
        f"OL state diff len: {decoded.ol_state_diff_len}",
        f"OL logs count: {decoded.ol_logs_count}",
        f"OL logs blob len: {decoded.ol_logs_blob_len}",
        f"terminal timestamp: {decoded.terminal_timestamp_ms} ({decoded.terminal_timestamp_iso})",
        f"terminal parent blkid: {decoded.terminal_parent_blkid}",
        f"terminal body root: {decoded.terminal_body_root}",
        f"terminal logs root: {decoded.terminal_logs_root}",
    ]
    print("\n".join(lines))


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        txid = validate_txid(args.txid)
        tx_json = fetch_tx_json(txid, args.base_url, args.timeout)
        decoded = decode_checkpoint_tx(tx_json)
    except DecodeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(asdict(decoded), indent=2, sort_keys=True))
    else:
        print_human(decoded)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
