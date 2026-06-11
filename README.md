# Strata ASM (Anchor State Machine)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache-blue.svg)](https://opensource.org/licenses/apache-2-0)
[![ci](https://github.com/alpenlabs/asm/actions/workflows/lint.yml/badge.svg?event=push)](https://github.com/alpenlabs/asm/actions)

Rust workspace for Strata's Anchor State Machine (ASM): transaction parsing, subprotocol execution, state transitions, manifest/log generation, and worker orchestration.

## Utilities

`contrib/decode_signet_checkpoint_tx.py` is a self-serve helper for fetching a
signet transaction from mempool.space and decoding the ASM checkpoint payload
embedded in the first input's taproot witness.

Human-readable decode:

```bash
python3 contrib/decode_signet_checkpoint_tx.py c28842887344b2e27cea95826ee5f7c3c041caba633bafe601ebe82cbff0ace6
```

JSON decode:

```bash
python3 contrib/decode_signet_checkpoint_tx.py c28842887344b2e27cea95826ee5f7c3c041caba633bafe601ebe82cbff0ace6 --json
```

By default the script fetches transaction JSON from
`https://mempool.space/signet/api/tx/<txid>`. Use `--base-url` to point it at a
different compatible mempool API endpoint.

## Contributing

Contributions are generally welcome.  If you intend to make larger changes, please discuss them in an issue before opening a PR to avoid duplicate work and architectural mismatches.

For more information please see [`CONTRIBUTING.md`](/CONTRIBUTING.md).
