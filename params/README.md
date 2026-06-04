# gen_asm_params

Generates ASM params by populating the L1 anchor (block hash, `next_target`,
epoch-start timestamp) from a running `bitcoind`. Output is written to
`gen/<unix-ts>.json` next to the script (`params/gen/`), independent of the
current working directory.

## Usage

```sh
python3 gen_asm_params.py \
  --bitcoin-rpc-url http://127.0.0.1:12301 \
  --bitcoin-rpc-user user \
  --bitcoin-rpc-password password
```

`--params` defaults to [`gen/asm-params-sample.json`](gen/asm-params-sample.json);
pass `--params <path>` to override.

## Arguments

- `--bitcoin-rpc-url` — Bitcoin Core JSON-RPC endpoint.
- `--bitcoin-rpc-user` / `--bitcoin-rpc-password` — RPC credentials.
- `--params` — Input ASM params JSON template. `anchor.block.height` and
  `anchor.network` are read from it; the rest of `anchor` is overwritten.
  Defaults to `gen/asm-params-sample.json`.

`bitcoind` must already be running and synced past `anchor.block.height` —
the script does not wait.
