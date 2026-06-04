#!/usr/bin/env python3

import argparse
import base64
import json
import logging
import time
import urllib.request
from pathlib import Path

# Bitcoin's difficulty adjustment interval, in blocks. Identical across all networks
# (mainnet, testnet, signet, regtest) per Bitcoin Core's consensus params.
DIFFICULTY_ADJUSTMENT_INTERVAL = 2016

GEN_DIR = Path(__file__).resolve().parent / "gen"
DEFAULT_PARAMS_PATH = GEN_DIR / "asm-params-sample.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bitcoin-rpc-url", required=True)
    parser.add_argument("--bitcoin-rpc-user", required=True)
    parser.add_argument("--bitcoin-rpc-password", required=True)
    parser.add_argument("--params", default=str(DEFAULT_PARAMS_PATH))
    return parser.parse_args()


def rpc_call(rpc_url: str, rpc_user: str, rpc_password: str, method: str, params: list):
    payload = json.dumps(
        {"jsonrpc": "1.0", "id": "asm-runner", "method": method, "params": params}
    ).encode()
    request = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    auth = base64.b64encode(f"{rpc_user}:{rpc_password}".encode()).decode()
    request.add_header("Authorization", f"Basic {auth}")

    with urllib.request.urlopen(request, timeout=5) as response:
        body = json.loads(response.read().decode())

    if body.get("error") is not None:
        raise RuntimeError(body["error"])

    return body["result"]


def fetch_block_header(bitcoin_cfg: dict, height: int) -> dict:
    block_hash = rpc_call(
        bitcoin_cfg["rpc_url"],
        bitcoin_cfg["rpc_user"],
        bitcoin_cfg["rpc_password"],
        "getblockhash",
        [height],
    )
    return rpc_call(
        bitcoin_cfg["rpc_url"],
        bitcoin_cfg["rpc_user"],
        bitcoin_cfg["rpc_password"],
        "getblockheader",
        [block_hash],
    )


def build_l1_anchor(genesis_height: int, network: str, bitcoin_cfg: dict) -> dict:
    """Builds the L1 anchor dict for the ASM params from on-chain context at ``genesis_height``.

    Records ``genesis_height``'s hash and ``bits`` on the anchor, plus the timestamp of the
    block at the start of the containing difficulty epoch — matching how the ASM recomputes
    the next difficulty target.
    """
    epoch_start_height = (
        genesis_height // DIFFICULTY_ADJUSTMENT_INTERVAL
    ) * DIFFICULTY_ADJUSTMENT_INTERVAL
    epoch_start_header = fetch_block_header(bitcoin_cfg, epoch_start_height)
    genesis_header = fetch_block_header(bitcoin_cfg, genesis_height)

    return {
        "block": {"height": genesis_height, "blkid": genesis_header["hash"]},
        "next_target": int(genesis_header["bits"], 16),
        "epoch_start_timestamp": int(epoch_start_header["time"]),
        "network": network,
    }


def main() -> None:
    args = parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info("Starting ASM params generation")

    bitcoin_cfg = {
        "rpc_url": args.bitcoin_rpc_url,
        "rpc_user": args.bitcoin_rpc_user,
        "rpc_password": args.bitcoin_rpc_password,
    }

    params = json.loads(Path(args.params).read_text())

    genesis_height = params["anchor"]["block"]["height"]
    network = params["anchor"]["network"]
    logging.info(f"Updating ASM params with chain context for {network} network")
    params["anchor"] = build_l1_anchor(genesis_height, network, bitcoin_cfg)

    GEN_DIR.mkdir(parents=True, exist_ok=True)
    output_path = GEN_DIR / f"{int(time.time())}.json"

    logging.info(f"Writing updated ASM params to {output_path}")
    output_path.write_text(json.dumps(params, indent=4) + "\n")


if __name__ == "__main__":
    main()
