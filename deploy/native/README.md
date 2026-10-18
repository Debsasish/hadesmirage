# Native deployment profile

The runnable deployment is the root `setup.cmd` and `start.cmd`, described in [native setup](../../docs/native-setup.md). No Docker, Compose or Kubernetes manifests are used.

Only loopback API/console and the fixed signed backend are listeners. The Wasmtime decoy is a no-import capability sandbox, not a network-attached native service. Data, credentials and logs live in the configured ignored local directory.

This profile is suitable for synthetic demonstration and local verification. It is not a public Windows service installer, OS firewall policy, enterprise identity provider or native gateway host.
