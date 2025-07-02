import argparse
import subprocess
import oci


def get_dns_resolvers(dns_client, compartment_id):
    """Fetch all DNS resolvers in a given compartment."""
    resolvers = dns_client.list_resolvers(compartment_id=compartment_id).data
    return resolvers


def delete_resolver_rules_cli(resolver_id, region):
    """Delete resolver rules using OCI CLI."""
    try:
        print(f"[INFO] Deleting rules for resolver: {resolver_id}")
        result = subprocess.run(
            [
                "oci", "dns", "resolver", "rule", "list",
                "--resolver-id", resolver_id,
                "--region", region,
                "--query", "data[*].id",
                "--raw-output"
            ],
            capture_output=True, text=True, check=True
        )
        rule_ids = result.stdout.strip().splitlines()
        for rule_id in rule_ids:
            if rule_id.strip():
                print(f"[DELETE] DNS Resolver Rule -> {rule_id}")
                subprocess.run(
                    [
                        "oci", "dns", "resolver", "rule", "delete",
                        "--rule-id", rule_id,
                        "--region", region,
                        "--force"
                    ],
                    check=True
                )
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to delete resolver rules for {resolver_id}: {e.stderr}")


def delete_resolver_endpoints(dns_client, resolver_id):
    """Delete all resolver endpoints."""
    try:
        endpoints = dns_client.list_resolver_endpoints(resolver_id).data
        for ep in endpoints:
            print(f"[DELETE] DNS Resolver Endpoint -> {ep.name} ({ep.id})")
            dns_client.delete_resolver_endpoint(ep.id)
    except Exception as e:
        print(f"[ERROR] Failed to delete resolver endpoints: {str(e)}")


def detach_and_delete_private_views_cli(dns_client, resolver_id, region):
    """Detach views using CLI and delete private ones using SDK."""
    try:
        print(f"[INFO] Checking view associations for resolver: {resolver_id}")
        result = subprocess.run(
            [
                "oci", "dns", "resolver", "endpoint-association", "list",
                "--resolver-id", resolver_id,
                "--region", region,
                "--query", "data[*].{id:view-id,shared:is-shared}",
                "--raw-output"
            ],
            capture_output=True, text=True, check=True
        )

        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue
            parts = line.strip().split()
            view_id = parts[0]
            is_shared = parts[1].lower() == "true"

            if is_shared:
                print(f"[SKIP] Shared view: {view_id}")
                continue

            print(f"[DETACH] View: {view_id}")
            subprocess.run(
                [
                    "oci", "dns", "view", "detach",
                    "--view-id", view_id,
                    "--region", region,
                    "--resolver-id", resolver_id,
                    "--force"
                ],
                check=True
            )

            print(f"[DELETE] View: {view_id}")
            dns_client.delete_view(view_id)

    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to detach/delete views for resolver {resolver_id}: {e.stderr}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compartment-id', required=True, help='OCID of the target compartment')
    parser.add_argument('--region', required=True, help='OCI region name (e.g., us-ashburn-1)')
    parser.add_argument('--config', default='~/.oci/config', help='Path to OCI config file')
    parser.add_argument('--profile', default='DEFAULT', help='Profile name in config file')
    args = parser.parse_args()

    config = oci.config.from_file(args.config, args.profile)
    dns_client = oci.dns.DnsClient(config)
    virtual_network_client = oci.core.VirtualNetworkClient(config)

    # Set explicit region
    dns_client.base_client.set_region(args.region)
    virtual_network_client.base_client.set_region(args.region)

    # List all VCNs
    vcn_list = virtual_network_client.list_vcns(compartment_id=args.compartment_id).data
    print(f"[INFO] Found {len(vcn_list)} VCN(s) in compartment {args.compartment_id}")

    resolvers = get_dns_resolvers(dns_client, args.compartment_id)

    for vcn in vcn_list:
        print(f"\n[INFO] Checking VCN: {vcn.display_name} ({vcn.id})")
        for resolver in resolvers:
            if resolver.vcn_id != vcn.id:
                continue
            print(f"[INFO] Processing DNS Resolver: {resolver.display_name} ({resolver.id})")
            delete_resolver_rules_cli(resolver.id, args.region)
            delete_resolver_endpoints(dns_client, resolver.id)
            detach_and_delete_private_views_cli(dns_client, resolver.id, args.region)


if __name__ == "__main__":
    main()
