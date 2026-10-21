# -*- coding: utf-8 -*-
"""
ClickTask - release_key.py
Description: Public key pinning the official release signature. Kept in the
             source tree on purpose: the updater compares every signed release
             against this key, so a compromised GitHub account cannot push code
             without the matching private key.

             Fill SIGNER_PUBLIC_KEY with the contents of the `.pub` file used to
             sign releases (`ssh-keygen -t ed25519`). While it stays empty the
             updater accepts releases without a signature and only checks the
             SHA256SUMS digest, which catches corruption but not tampering.
Author: JADRT22 (https://github.com/JADRT22)
License: MIT
"""

# Example: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... clicktask-release"
SIGNER_PUBLIC_KEY = ""
SIGNER_IDENTITY = "clicktask"
SIGNER_NAMESPACE = "clicktask"
