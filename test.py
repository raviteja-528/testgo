import argparse
import oci
import subprocess


def run_oci_cli(command):
    """Helper to run OCI CLI commands and return output."""
    result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        print(f"[ERROR] OCI CLI command failed: {result.stderr.strip()}")
    return result.stdout.strip()


def delete_resolver_rules_cli(resolver_id, region):
    """Delete DNS resolver rules using OCI CLI."""
    print(f"[INFO] Deleting rules for resolver: {resolver_id}")
    list_cmd = f"oci dns resolver rule list --resolver-id {resolver_id} --region {region} --query 'data[*].id' --raw-output"
    rule_ids = run_oci_cli(list_cmd).splitlines()

    for rule_id in rule_ids:
        if rule_id:
            print(f"[INFO] Deleting rule: {rule_id}")
            del_cmd = f"oci dns resolver rule delete --rule-id {rule_id} --region {region} --force"
            run_oci_cli(del_cmd)


def delete_resolver_endpoints(dns_client, resolver_id):
    """Delete DNS resolver endpoints using SDK."""
    endpoints = dns_client.list_resolver_endpoints(resolver_id).data
    for ep in endpoints:
        print(f"[INFO] Deleting endpoint: {ep.name}")
        dns_client.delete_resolver_endpoint(
            resolver_id=resolver_id,
            resolver_endpoint_name=ep.name
        )


def detach_and_delete_private_views(dns_client, resolver_id, region):
    """Detach and delete views associated with resolver."""
    list_cmd = f"oci dns resolver endpoint-association list --resolver-id {resolver_id} --region {region} --query 'data[*]'"
    output = run_oci_cli(list_cmd)

    if not output:
        print(f"[INFO] No views found for resolver {resolver_id}")
        return

    try:
        import json
        views = json.loads(output)
        for view in views:
            view_id = view.get("view-id")
            is_shared = view.get("is-shared", False)
            display_name = view.get("display-name", view_id)

            print(f"[INFO] Detaching view: {display_name}")
            dns_client.detach_view(view_id)

            if not is_shared:
                print(f"[INFO] Deleting private view: {display_name}")
                dns_client.delete_view(view_id)
            else:
                print(f"[SKIP] View is shared. Not deleting: {display_name}")

    except Exception as e:
        print(f"[ERROR] Failed to process views: {str(e)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compartment-id', required=True)
    parser.add_argument('--region', required=True)
    parser.add_argument('--config', default='~/.oci/config')
    parser.add_argument('--profile', default='DEFAULT')
    args = parser.parse_args()

    config = oci.config.from_file(args.config, args.profile)

    # Set region explicitly
    config["region"] = args.region

    dns_client = oci.dns.DnsClient(config)
    vcn_client = oci.core.VirtualNetworkClient(config)

    # Step 1: Get all VCNs
    vcns = vcn_client.list_vcns(compartment_id=args.compartment_id).data
    print(f"[INFO] Found {len(vcns)} VCN(s)")

    for vcn in vcns:
        vcn_id = vcn.id
        print(f"\n[INFO] Processing VCN: {vcn.display_name} ({vcn_id})")

        # Step 2: Get resolvers in this VCN using CLI
        resolver_cmd = (
            f"oci dns resolver list "
            f"--compartment-id {args.compartment_id} "
            f"--region {args.region} "
            f"--vcn-id {vcn_id} "
            f"--query 'data[*].id' --raw-output"
        )
        resolver_ids = run_oci_cli(resolver_cmd).splitlines()

        if not resolver_ids:
            print("[INFO] No DNS Resolvers found.")
            continue

        for resolver_id in resolver_ids:
            print(f"\n[INFO] Processing Resolver: {resolver_id}")
            delete_resolver_rules_cli(resolver_id, args.region)
            delete_resolver_endpoints(dns_client, resolver_id)
            detach_and_delete_private_views(dns_client, resolver_id, args.region)

    print("\n✅ DNS cleanup completed successfully.")


if __name__ == "__main__":
    main()
