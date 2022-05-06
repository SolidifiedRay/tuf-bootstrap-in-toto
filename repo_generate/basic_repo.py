"""
Copied and modified from upstream

A TUF repository example using the low-level TUF Metadata API.

The example code in this file demonstrates how to *manually* create and
maintain repository metadata using the low-level Metadata API. It implements
similar functionality to that of the deprecated legacy 'repository_tool' and
'repository_lib'. (see ADR-0010 for details about repository library design)

Contents:
 * creation of top-level metadata
 * target file handling
 * consistent snapshots
 * key management
 * top-level delegation and signing thresholds
 * target delegation
 * in-band and out-of-band metadata signing
 * writing and reading metadata files
 * root key rotation

NOTE: Metadata files will be written to a 'tmp*'-directory in CWD.

"""
import os
import tempfile
from datetime import datetime, timedelta
from typing import Any, Dict

from securesystemslib.keys import generate_ed25519_key
from securesystemslib.signer import SSlibSigner

from tuf.api.metadata import (
    SPECIFICATION_VERSION,
    Key,
    Metadata,
    Root,
    Snapshot,
    TargetFile,
    Targets,
    Timestamp,
)
from tuf.api.serialization.json import JSONSerializer


def _in(days: float) -> datetime:
    """Adds 'days' to now and returns datetime object w/o microseconds."""
    return datetime.utcnow().replace(microsecond=0) + timedelta(days=days)


# Create top-level metadata
# =========================
# Every TUF repository has at least four roles, i.e. the top-level roles
# 'targets', 'snapshot', 'timestamp' and 'root'. Below we will discuss their
# purpose, show how to create the corresponding metadata, and how to use them
# to provide integrity, consistency and freshness for the files TUF aims to
# protect, i.e. target files.

# Common fields
# -------------
# All roles have the same metadata container format, for which the metadata API
# provides a generic 'Metadata' class. This class has two fields, one for
# cryptographic signatures, i.e. 'signatures', and one for the payload over
# which signatures are generated, i.e. 'signed'. The payload must be an
# instance of either 'Targets', 'Snapshot', 'Timestamp' or 'Root' class. Common
# fields in all of these 'Signed' classes are:
#
# spec_version -- The supported TUF specification version number.
# version -- The metadata version number.
# expires -- The metadata expiry date.
#
# The 'version', which is incremented on each metadata change, is used to
# reference metadata from within other metadata, and thus allows for repository
# consistency in addition to protecting against rollback attacks.
#
# The date the metadata 'expires' protects against freeze attacks and allows
# for implicit key revocation. Choosing an appropriate expiration interval
# depends on the volatility of a role and how easy it is to re-sign them.
# Highly volatile roles (timestamp, snapshot, targets), usually have shorter
# expiration intervals, whereas roles that change less and might use offline
# keys (root, delegating targets) may have longer expiration intervals.

SPEC_VERSION = ".".join(SPECIFICATION_VERSION)

# Define containers for role objects and cryptographic keys created below. This
# allows us to sign and write metadata in a batch more easily.
roles: Dict[str, Metadata] = {}
keys: Dict[str, Dict[str, Any]] = {}


# Targets (integrity)
# -------------------
# The targets role guarantees integrity for the files that TUF aims to protect,
# i.e. target files. It does so by listing the relevant target files, along
# with their hash and length.
roles["targets"] = Metadata(Targets(expires=_in(7)))

# For the purpose of this example we use the top-level targets role to protect
# the integrity of this very example script. The metadata entry contains the
# hash and length of this file at the local path. In addition, it specifies the
# 'target path', which a client uses to locate the target file relative to a
# configured mirror base URL.
#
#      |----base URL---||-------target path-------|
# e.g. tuf-in-toto-examples.org/root.layout

target1_local_path = os.getcwd() + "/root.layout"
target2_local_path = os.getcwd() + "/alice.pub"
target1_path = f"root.layout"
target2_path = f"alice.pub"

target1_file_info = TargetFile.from_file(target1_path, target1_local_path)
target2_file_info = TargetFile.from_file(target1_path, target2_local_path)
roles["targets"].signed.targets[target1_path] = target1_file_info
roles["targets"].signed.targets[target2_path] = target2_file_info

# Snapshot (consistency)
# ----------------------
# The snapshot role guarantees consistency of the entire repository. It does so
# by listing all available targets metadata files at their latest version. This
# becomes relevant, when there are multiple targets metadata files in a
# repository and we want to protect the client against mix-and-match attacks.
roles["snapshot"] = Metadata(Snapshot(expires=_in(7)))

# Timestamp (freshness)
# ---------------------
# The timestamp role guarantees freshness of the repository metadata. It does
# so by listing the latest snapshot (which in turn lists all the latest
# targets) metadata. A short expiration interval requires the repository to
# regularly issue new timestamp metadata and thus protects the client against
# freeze attacks.
#
# Note that snapshot and timestamp use the same generic wireline metadata
# format. But given that timestamp metadata always has only one entry in its
# 'meta' field, i.e. for the latest snapshot file, the timestamp object
# provides the shortcut 'snapshot_meta'.
roles["timestamp"] = Metadata(Timestamp(expires=_in(1)))

# Root (root of trust)
# --------------------
# The root role serves as root of trust for all top-level roles, including
# itself. It does so by mapping cryptographic keys to roles, i.e. the keys that
# are authorized to sign any top-level role metadata, and signing thresholds,
# i.e. how many authorized keys are required for a given role (see 'roles'
# field). This is called top-level delegation.
#
# In addition, root provides all public keys to verify these signatures (see
# 'keys' field), and a configuration parameter that describes whether a
# repository uses consistent snapshots (see section 'Persist metadata' below
# for more details).

# Create root metadata object
roles["root"] = Metadata(Root(expires=_in(365)))

# For this example, we generate one 'ed25519' key pair for each top-level role
# using python-tuf's in-house crypto library.
# See https://github.com/secure-systems-lab/securesystemslib for more details
# about key handling, and don't forget to password-encrypt your private keys!
for name in ["targets", "snapshot", "timestamp", "root"]:
    keys[name] = generate_ed25519_key()
    roles["root"].signed.add_key(
        name, Key.from_securesystemslib_key(keys[name])
    )

# NOTE: We only need the public part to populate root, so it is possible to use
# out-of-band mechanisms to generate key pairs and only expose the public part
# to whoever maintains the root role. As a matter of fact, the very purpose of
# signature thresholds is to avoid having private keys all in one place.

# Signature thresholds
# --------------------
# Given the importance of the root role, it is highly recommended to require a
# threshold of multiple keys to sign root metadata. For this example we
# generate another root key (you can pretend it's out-of-band) and increase the
# required signature threshold.
another_root_key = generate_ed25519_key()
roles["root"].signed.add_key(
    "root", Key.from_securesystemslib_key(another_root_key)
)
roles["root"].signed.roles["root"].threshold = 1


# Sign top-level metadata (in-band)
# =================================
# In this example we have access to all top-level signing keys, so we can use
# them to create and add a signature for each role metadata.
for name in ["targets", "snapshot", "timestamp", "root"]:
    key = keys[roles[name].signed.type]
    signer = SSlibSigner(key)
    roles[name].sign(signer)


# Persist metadata (consistent snapshot)
# ======================================
# It is time to publish the first set of metadata for a client to safely
# download the target file that we have registered for this example repository.
#
# For the purpose of this example we will follow the consistent snapshot naming
# convention for all metadata. This means that each metadata file, must be
# prefixed with its version number, except for timestamp. The naming convention
# also affects the target files, but we don't cover this in the example. See
# the TUF specification for more details:
# https://theupdateframework.github.io/specification/latest/#writing-consistent-snapshots
#
# Also note that the TUF specification does not mandate a wireline format. In
# this demo we use a non-compact JSON format and store all metadata in
# temporary directory at CWD for review.
PRETTY = JSONSerializer(compact=False)
TMP_DIR = tempfile.mkdtemp(dir=os.getcwd())

for name in ["root", "targets", "snapshot"]:
    filename = f"{roles[name].signed.version}.{roles[name].signed.type}.json"
    path = os.path.join(TMP_DIR, filename)
    roles[name].to_file(path, serializer=PRETTY)

roles["timestamp"].to_file(
    os.path.join(TMP_DIR, "timestamp.json"), serializer=PRETTY
)
