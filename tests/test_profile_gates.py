import pytest


@pytest.mark.skip(
    reason="P3 unavailable: Rust toolchain/native gateway, TLS test PKI and signed registry not provisioned"
)
def test_t08_native_gateway_certificate_key_expiry_revocation():
    raise AssertionError(
        "Must run against the original Rust gateway, never a Python policy substitute"
    )


@pytest.mark.skip(
    reason="P3 unavailable: workload OS egress is not fenced by the native gateway in P1-native"
)
def test_t09_direct_agent_egress_bypass():
    raise AssertionError("Requires real network paths from an egress-restricted workload")


@pytest.mark.skip(reason="P3 unavailable: no established native CONNECT tunnel or close manager")
def test_t25_established_tunnel_revocation():
    raise AssertionError(
        "Revoking new permissions cannot establish whether an existing TCP tunnel closes"
    )


@pytest.mark.skip(
    reason="No isolated PostgreSQL server provisioned; SQLite multi-instance path is tested separately"
)
def test_postgresql_runtime_acceptance():
    raise AssertionError("Generated PostgreSQL DDL is not runtime transaction evidence")


@pytest.mark.skip(
    reason="Cloud deployment intentionally not performed; no cloud credentials or spend authorized"
)
def test_cloud_identity_origin_and_iam_paths():
    raise AssertionError(
        "Prepared deployment guidance cannot verify live cloud IAM or network paths"
    )
