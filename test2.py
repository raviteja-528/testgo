import argparse
import subprocess
import oci


def get_dns_resolvers(dns_client, compartment_id, vcn_list):
    matched_resolvers = []
    try:
        resolvers = dns_client.list_resolvers(compartment_id=compartment_id).data
        for resolver in resolvers:
            if hasattr(resolver, 'vcn_id') and any(resolver.vcn_id == vcn.id for vcn in vcn_list):
                matched_resolvers.append(resolver)
    except Exception as e:
        print(f"[ERROR] Failed to fetch DNS resolvers: {str(e)}")
    return matched_resolvers


def delete_resolver_rules(resolver_id, region, config_file, profile):
    try:
        result = subprocess.run([
            "oci", "dns", "resolver", "rule", "list",
            "--resolver-id", resolver_id,
            "--region", region,
            "--query", "data[*].id",
            "--raw-output",
            "--config-file", config_file,
            "--profile", profile
        ], capture_output=True, text=True, check=True)

        rule_ids = result.stdout.strip().splitlines()
        for rule_id in rule_ids:
            print(f"[INFO] Deleting rule: {rule_id}")
            subprocess.run([
                "oci", "dns", "resolver", "rule", "delete",
                "--rule-id", rule_id,
                "--region", region,
                "--force",
                "--config-file", config_file,
                "--profile", profile
            ], check=True)

    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to delete resolver rules: {e.stderr.strip()}")


def delete_resolver_endpoints(dns_client, resolver_id):
    try:
        endpoints = dns_client.list_resolver_endpoints(resolver_id).data
        for ep in endpoints:
            print(f"[INFO] Deleting endpoint: {ep.name}")
            dns_client.delete_resolver_endpoint(resolver_id=resolver_id, resolver_endpoint_name=ep.name)
    except Exception as e:
        print(f"[ERROR] Failed to delete endpoints: {str(e)}")


def detach_and_delete_private_views(dns_client, resolver_id, region, config_file, profile):
    try:
        views = dns_client.list_resolver_endpoint_associations(resolver_id).data

        for view in views:
            view_id = view.view_id
            is_shared = getattr(view, 'is_shared', False)
            display_name = getattr(view, 'display_name', view_id)

            if is_shared:
                print(f"[INFO] Skipping shared view: {display_name}")
            else:
                print(f"[INFO] Detaching and deleting private view: {display_name}")
                subprocess.run([
                    "oci", "dns", "view", "detach",
                    "--resolver-id", resolver_id,
                    "--view-id", view_id,
                    "--region", region,
                    "--force",
                    "--config-file", config_file,
                    "--profile", profile
                ], check=True)

                subprocess.run([
                    "oci", "dns", "view", "delete",
                    "--view-id", view_id,
                    "--region", region,
                    "--force",
                    "--config-file", config_file,
                    "--profile", profile
                ], check=True)

    except Exception as e:
        print(f"[ERROR] Failed to detach/delete private views: {str(e)}")



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compartment-id', required=True)
    parser.add_argument('--region', required=True)
    parser.add_argument('--config', default='~/.oci/config')
    parser.add_argument('--profile', default='DEFAULT')
    args = parser.parse_args()

    config = oci.config.from_file(args.config, args.profile)
    signer = oci.signer.Signer(
        tenancy=config["tenancy"],
        user=config["user"],
        fingerprint=config["fingerprint"],
        private_key_file_location=config["key_file"],
        pass_phrase=config.get("pass_phrase")
    )

    dns_client = oci.dns.DnsClient(config, signer=signer)
    virtual_network_client = oci.core.VirtualNetworkClient(config, signer=signer)

    # ✅ Correct: Get VCNs here, NOT inside get_dns_resolvers
    vcn_list = virtual_network_client.list_vcns(compartment_id=args.compartment_id).data
    print(f"[INFO] Found {len(vcn_list)} VCN(s)")

    resolvers = get_dns_resolvers(dns_client, args.compartment_id, vcn_list)

    for resolver in resolvers:
        print(f"[INFO] Processing DNS Resolver: {resolver.display_name}")
        delete_resolver_rules(resolver.id, args.region, args.config, args.profile)
        delete_resolver_endpoints(dns_client, resolver.id)
        detach_and_delete_private_views(dns_client, resolver.id, args.region, args.config, args.profile)


if __name__ == "__main__":
    main()
