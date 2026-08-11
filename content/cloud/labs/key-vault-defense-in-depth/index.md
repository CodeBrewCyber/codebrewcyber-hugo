+++
title = "Key Vault Defense in Depth and Policy Enforcement"
date = 2026-08-02T11:30:00-04:00
draft = false
description = "Three independent ways a Key Vault secret read can be refused: control-plane RBAC, data-plane RBAC, and the vault firewall. Then a custom Azure Policy that stops a badly configured vault from being created at all."
tags = ["azure", "key-vault", "azure-policy", "private-endpoint", "rbac", "sc-500"]
categories = ["labs"]
aliases = ["/writeups/labs/key-vault-defense-in-depth/"]
+++

Part of my SC-500 study series: hands-on labs in a test tenant, one concept at a time.

**Goal:** Finish able to explain, without notes, the three independent ways access to a Key Vault secret can be refused (control-plane RBAC, data-plane RBAC, and the vault firewall) and to write a custom Azure Policy that stops a badly configured vault from ever being created.

## Why this matters

An earlier lab covered the Key Vault *access model*, access policies versus RBAC, and stopped there. The SC-500 objectives go further: firewall settings, Defender for Key Vault, and secret scanning are each called out separately. This lab covers the two that do not need a paid Defender plan.

The thing worth internalizing is that **a refusal tells you which layer refused**:

1. **Control-plane RBAC** governs the vault as an Azure resource: create it, delete it, read its properties. `Owner` gets you all of this.
2. **Data-plane RBAC** governs the secrets inside it. `Owner` gets you *none* of this. This is the counterintuitive one and it is exam-relevant: a subscription Owner who can delete the entire vault cannot read a single secret out of it.
3. **The vault firewall** is evaluated before either. It does not care who you are.

Three layers, three different error messages. Most people never see them separately because they test with one over-privileged account from one machine.

The governance half then closes the loop: knowing the right configuration is worth little if nothing enforces it. Purge protection is the ideal example. It is the control that makes a vault genuinely recoverable, it is off by default, and once on it cannot be turned off.

## Prerequisites

- Owner, or Contributor plus User Access Administrator, on the subscription
- Permission to create policy definitions at subscription scope
- Azure CLI logged in if you want the sprinkled-in commands. Everything here is doable from the portal alone

## Step 0 - Read this first: purge protection is a one-way door

Two things to understand before you start, both of which will otherwise cost you an hour.

**Soft delete is no longer optional.** Microsoft made it mandatory in 2020. If a training module tells you to "enable soft delete," that instruction is stale: the flag exists but cannot be turned off.

**Purge protection cannot be disabled once enabled.** That is the whole point of the control, and it has a consequence for this lab. When you delete the resource group at the end, the vault enters a soft-deleted state for the retention period (7 days here) and you cannot purge it early. The name stays reserved. If you rebuild this lab before the retention window closes, bump the instance number.

Plan for it now rather than discovering it during teardown.

## Step 1 - Resource group and a hardened vault

**Key vaults** → **Create**.

| Tab | Setting | Value |
|---|---|---|
| Basics | Resource group | new, `rg-sc500wk5-dev-eus-01` |
| Basics | Key vault name | `kv-sc500wk5-dev-eus-01` |
| Basics | Pricing tier | Standard |
| Basics | Days to retain deleted vaults | 7 |
| Basics | Purge protection | **Enable purge protection** |
| Access configuration | Permission model | **Azure role-based access control** |
| Networking | Public access | leave enabled, locked down in Step 3 |

The permission model is the deliberate contrast with the earlier lab, which used the access-policy model. Everything below behaves differently because of this one choice.

![Key vault overview showing soft-delete and purge protection enabled](01-vault-overview-properties.png)

> **Key Vault names are globally unique and capped at 24 characters.** `kv-sc500wk5-dev-eus-01` is 22. If the name is taken, bump the instance number rather than restructuring.

### Verify

```bash
az keyvault show --name kv-sc500wk5-dev-eus-01 --resource-group rg-sc500wk5-dev-eus-01 --query "{purge:properties.enablePurgeProtection, rbac:properties.enableRbacAuthorization, softDelete:properties.enableSoftDelete}"
```

![CLI returning purge, rbac, and softDelete all true](02-verify-purge-rbac-softdelete.png)

All three return `true`. Note that you never asked for soft delete.

## Step 2 - Prove Owner cannot read a secret

Do this **before** granting yourself anything. This is the highest-value moment in the lab.

Vault → **Objects** → **Secrets** → **Generate/Import**. As subscription Owner with no data-plane role, the Secrets blade shows an RBAC access error and the create fails. `Owner` is control plane only.

The precise error string is easiest to get from the CLI:

```bash
az keyvault secret set --vault-name kv-sc500wk5-dev-eus-01 --name demo-secret --value "hello-sc500"
```

![Forbidden with ForbiddenByRbac when creating a secret as Owner](03-owner-forbidden-by-rbac.png)

Now grant yourself the data-plane role: Vault → **Access control (IAM)** → **Add role assignment** → **Key Vault Secrets Officer** → your account.

![Role assignments showing the account with Key Vault Secrets Officer](04-secrets-officer-assigned.png)

> **Secrets Officer versus Secrets User.** `Key Vault Secrets User` is read-only. Writing a secret needs `Key Vault Secrets Officer`. Getting this pair the wrong way round is a classic exam distractor.

Wait a minute or two for propagation, then retry the create. It now succeeds.

### Verify

```bash
az keyvault secret show --vault-name kv-sc500wk5-dev-eus-01 --name demo-secret --query value -o tsv
```

![The secret value returned successfully](05-secret-readable.png)

## Step 3 - Lock the firewall, then lock yourself out

Vault → **Settings** → **Networking** → **Firewalls and virtual networks** → **Allow public access from specific virtual networks and IP addresses**. Under **Firewall**, click **Add your client IP address**, then **Apply**. Use your public address, which a site like [ipchicken.com](https://ipchicken.com) will tell you. This flips the default action to Deny while allowing your address through.

![Key vault firewall with the client IP allowed](06-firewall-allow-client-ip.png)

The secret is still readable, because your IP is on the list.

![Secret still readable with the firewall on and the IP allowed](07-secret-still-readable.png)

Now remove that allowance: back on the same blade, delete your IP from the firewall list and **Apply**. With no rule matching and the default set to Deny, the read fails.

![Firewall list with no IP addresses](08-firewall-list-cleared.png)

![Forbidden with ForbiddenByFirewall](09-forbidden-by-firewall.png)

```bash
az keyvault network-rule add --name kv-sc500wk5-dev-eus-01 --resource-group rg-sc500wk5-dev-eus-01 --ip-address "$(curl -s https://api.ipify.org)"
```

```bash
az keyvault update --name kv-sc500wk5-dev-eus-01 --resource-group rg-sc500wk5-dev-eus-01 --default-action Deny
```

### Verify

Put Step 2's error next to this one. Both are HTTP 403, but the inner code differs and so does the reason:

| Step | Code | Meaning |
|---|---|---|
| 2, no data-plane role | `Forbidden` | Your identity lacks the role. The vault knows who you are and refuses. |
| 3, role present, IP blocked | `ForbiddenByFirewall` | Your network is not allowed. The vault refuses before it checks who you are. |

Same account, same role, same operation. Only the network rule changed. One refusal is "your identity can't," the other is "your network can't." If you cannot articulate the difference from memory tomorrow, the lab did not land.

## Step 4 - Private endpoint, and resolve it from inside the VNet

A private endpoint gives the vault a private IP on your VNet, and the linked private DNS zone makes the vault's *public* hostname resolve to that private IP, but only for clients inside the VNet. Build both, then prove the split from a VM that lives in the VNet against a workstation that does not.

### 4a - VNet with two subnets

Create `vnet-sc500wk5-dev-eus-01` with address space `10.20.0.0/16` and two subnets:

| Subnet | Range | Purpose |
|---|---|---|
| `snet-pe` | `10.20.1.0/24` | holds the private endpoint |
| `snet-vm` | `10.20.2.0/24` | holds the test VM |

The VM would resolve the vault to its private IP from *either* subnet, because the private DNS zone is linked at the VNet level rather than per-subnet. Endpoints get their own subnet anyway because that is Microsoft's recommended pattern: it keeps any NSG or route table scoped to just the endpoints, and reserves address space for more of them later.

### 4b - The private endpoint

Vault → **Networking** → **Private endpoint connections** → **Create**:

| Tab | Setting | Value |
|---|---|---|
| Basics | Name | `pe-sc500wk5-dev-eus-01` |
| Resource | Target sub-resource | **vault** |
| Virtual Network | VNet / subnet | `vnet-sc500wk5-dev-eus-01` / `snet-pe` |
| DNS | Integrate with private DNS zone | **Yes**, `privatelink.vaultcore.azure.net` |

Letting the wizard create and link the private DNS zone is the step people skip. Without it, name resolution never changes and the endpoint looks broken.

![Private endpoint DNS configuration mapping the vault FQDN to a private IP](11-private-endpoint-dns.png)

Same shape as the storage private endpoint in [Lock Down a Storage Account End-to-End]({{< ref "lock-down-storage-account" >}}). The only real difference is the zone name: `privatelink.vaultcore.azure.net`, not `privatelink.blob.core.windows.net`.

### 4c - A VM inside the VNet

Ubuntu Server, `Standard_B1s` or whatever is available, **Public inbound ports: None**, **Public IP: None**, in `snet-vm`.

No public IP, no inbound rules, no NAT gateway. You reach the VM through **Run command**, which flows over the Azure control plane rather than the network. The VM needs no connectivity of its own, and DNS resolution uses the VNet's default Azure DNS (`168.63.129.16`), which honors the linked private zone.

### 4d - Prove the split

From the VM: **Operations** → **Run command** → **RunShellScript**:

```bash
getent hosts kv-sc500wk5-dev-eus-01.vault.azure.net
```

It returns `10.20.1.x`, the private endpoint's IP. (`getent` is built in. `nslookup` would need the `dnsutils` package, which this VM cannot reach without outbound internet.)

![Run command output resolving the vault to a 10.20.1.x address](12-vm-resolves-private.png)

Now run the lookup from your own workstation:

```bash
nslookup kv-sc500wk5-dev-eus-01.vault.azure.net
```

It returns a **public** address.

![Workstation nslookup returning public addresses via traffic manager](13-workstation-resolves-public.png)

Same hostname, two different answers. The VM sees the private record because the private DNS zone is linked to its VNet. The workstation, outside the VNet, never consults that zone and gets the public CNAME. That split, resolution depending on *where you ask*, is the entire point of the private endpoint.

## Step 5 - Custom policy that denies vaults without purge protection

There *is* a built-in for this, "Key vaults should have deletion protection enabled," but it ships as `Audit`. The objective explicitly names custom policy definitions, so author one with a `Deny` effect.

**Policy** → **Authoring** → **Definitions** → **Policy definition**, definition location set to your subscription, category **Key Vault**.

The portal's **POLICY RULE** box expects a top-level `policyRule` wrapper around the `if`/`then`, so paste it exactly like this:

```json
{
  "policyRule": {
    "if": {
      "allOf": [
        { "field": "type", "equals": "Microsoft.KeyVault/vaults" },
        {
          "anyOf": [
            { "field": "Microsoft.KeyVault/vaults/enablePurgeProtection", "exists": "false" },
            { "field": "Microsoft.KeyVault/vaults/enablePurgeProtection", "equals": "false" }
          ]
        }
      ]
    },
    "then": { "effect": "deny" }
  }
}
```

![The saved custom policy definition and its JSON](14-custom-policy-definition.png)

> **The portal and the CLI want different shapes.** The portal box needs the `policyRule` wrapper above. The CLI `--rules` file wants the bare rule, the `if`/`then` object *without* the wrapper. Pasting the CLI shape into the portal box gives `Could not find member 'if' ... Path 'properties.if'`, and the reverse leaves the CLI unable to find the rule.

Save, then **Assign** the definition with the scope set to `rg-sc500wk5-dev-eus-01`.

> **Assignment does not take effect immediately.** Allow up to 15 minutes, occasionally longer, before the deny fires. If the next step succeeds when it should not, you almost certainly tested too early. Wait and retry before concluding the policy is wrong. This burns more lab time than any other single thing here.

```bash
az policy assignment create --name assign-deny-kv-purge --policy deny-kv-without-purge-protection --scope "$(az group show --name rg-sc500wk5-dev-eus-01 --query id -o tsv)"
```

## Step 6 - Watch it block a deployment

Create a second vault **without** purge protection: name `kv-sc500wk5-dev-eus-02`, same resource group, purge protection left at its default (off), then **Review + create**. Validation fails.

![Deployment error, resource disallowed by policy](15-deployment-denied-by-policy.png)

### Verify

Re-run the same create with purge protection **enabled** and confirm it now succeeds. Same target, same scope, one setting. That is the control working.

## Teardown

Delete the policy assignment *before* the resource group, because an assignment scoped to a deleted RG is orphaned and confusing to clean up later.

```bash
az policy assignment delete --name assign-deny-kv-purge --scope "$(az group show --name rg-sc500wk5-dev-eus-01 --query id -o tsv)"
```

```bash
az policy definition delete --name deny-kv-without-purge-protection
```

```bash
az group delete --name rg-sc500wk5-dev-eus-01 --yes --no-wait
```

> **The vaults survive the resource group.** Purge protection means both vaults enter soft-delete for 7 days and cannot be purged early. `az keyvault list-deleted` will show them, and their names stay reserved until the window closes. This is the control behaving correctly, not a failure, but it means an early rebuild needs new instance numbers.

![Manage deleted key vaults showing both vaults with scheduled purge dates](16-deleted-vaults-retained.png)

To pause between sessions, deallocate the VM with the portal **Stop** button or `az vm deallocate`. A plain `shutdown` from inside the OS leaves it billing.

## Key takeaways

- Three independent layers can refuse a secret read, and the error string tells you which one did. `Forbidden` with `ForbiddenByRbac` is identity; `ForbiddenByFirewall` is network. The firewall is evaluated first and does not care who you are.
- Subscription Owner is control plane. It can delete the entire vault and cannot read one secret out of it. In RBAC mode, data-plane access is a separate, explicit role assignment.
- Secrets User reads, Secrets Officer writes, Reader sees names but not values, Contributor manages the resource but never its contents.
- Soft delete is mandatory and cannot be turned off. Purge protection is optional, off by default, and irreversible once on.
- A private endpoint changes *where* a name resolves, not the name itself. The split-horizon answer depends on whether the client's VNet is linked to the private DNS zone.
- Built-in policies often ship as `Audit`. Authoring the same check with a `Deny` effect is what turns detection into prevention, and policy assignments take up to 15 minutes to start enforcing.

## Related labs

- [Secretless VM: Managed Identity, Bastion, and Key Vault]({{< ref "secretless-vm-managed-identity-key-vault" >}}) approaches the same vault from the workload side
- [Lock Down a Storage Account End-to-End]({{< ref "lock-down-storage-account" >}}) is the same private endpoint and split-horizon DNS pattern on storage
- [Custom RBAC Role + Azure Policy + Resource Lock]({{< ref "custom-role-azure-policy-resource-lock" >}}) covers the policy engine and the built-in definitions
