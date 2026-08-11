+++
title = "Virtual Network Manager Security Admin Rules"
date = 2026-08-10T18:05:00-04:00
draft = false
description = "Prove a central security admin rule sits above a VM's own NSG: deny SSH from a network manager, watch it beat an explicit NSG allow, then flip Deny to Allow and watch control hand back."
tags = ["azure", "networking", "virtual-network-manager", "nsg", "network-watcher", "sc-500"]
categories = ["labs"]
aliases = ["/writeups/labs/vnet-manager-security-admin-rules/"]
+++

Part of my SC-500 study series: hands-on labs in a test tenant, one concept at a time.

**Goal:** Prove that an Azure Virtual Network Manager **security admin rule** sits *above* a VM's own NSG and cannot be overridden by the resource owner. Deny inbound SSH from a central network manager, watch it beat an NSG rule that explicitly allows SSH, and confirm it in the NIC's **Effective security rules**, where the manager's rules and the NSG's rules sit on **separate tabs**. Then flip the action from **Deny** to **Allow** and watch enforcement hand control back to the NSG, which is the whole point of the three-action model.

## Why this matters

[NSG Priority Ordering + Network Watcher Verification]({{< ref "nsg-priority-network-watcher" >}}) answered "who wins when two NSG rules disagree": lowest priority number, first match. This lab answers the harder version the exam actually leans on: **who wins when two different controls disagree**, and specifically whether a resource owner can undo a central security control from inside their own resource. It is the network twin of "a resource lock beats Owner RBAC."

The setup is the dilemma Microsoft's own docs frame. A central team wants to block risky inbound ports everywhere, but the app teams own their NSGs. Three failed models:

1. **Central team owns every NSG.** Enforcement works, operational overhead is brutal and does not scale.
2. **App teams own their NSGs.** Flexible, but the central team cannot enforce anything, and a team can forget to attach an NSG at all.
3. **NSGs created by Azure Policy.** The central team gets *notified* when a rule changes, but cannot *prevent* it. The owner still has the last word.

**Security admin rules** break the trade-off. The central team sets guard rails in a network manager, the rules are enforced in the host fabric *above* NSGs, and an app-team owner literally cannot see or edit them from the NSG blade. They are not there to override NSGs: a Deny guard rail plus NSGs the teams still tune is the design. The exam-relevant nuance is the three actions:

| Action | What it does | NSG still evaluated? |
|---|---|---|
| **Deny** | Blocks the traffic before NSGs see it | No, evaluation stops |
| **Allow** | Passes the traffic *down* to NSG evaluation | **Yes**, the NSG can still deny it |
| **Always Allow** | Forces the traffic through | No, evaluation stops and the NSG cannot deny |

"Allow" not being a hard allow is the trap. Use **Always Allow** for traffic that must never be blocked by a local NSG mistake (health probes, monitoring agents), and **Allow** when you want to permit a port centrally but still let teams tighten it further.

## Prerequisites

- **Contributor** on the subscription for the VNet and VM, plus **Network Contributor** or Owner. The network manager also needs its **scope** to cover the subscription, which requires you to be able to grant that scope. On a personal single-subscription tenant you already have this.
- The lab is doable **entirely from the portal**. The CLI is optional and, for the network-manager pieces specifically, genuinely fiddly because of the nested JSON. The CLI for AVNM lives in an extension: `az extension add --name virtual-network-manager` if the `az network manager` group is missing.
- Single region throughout. Security admin configs deploy **per region**, and the deploy must target the VNet's region or nothing happens.

## Step 0 - Read this first: the two things that will bite you

> **Nothing is enforced until you deploy.** Creating the network manager, the network group, the config, the rule collection, and the rule changes **nothing** on the wire. Security admin rules only take effect after you deploy the configuration to a region, and the deploy is asynchronous: a few minutes to commit, then more time to show up in effective rules. This is the AVNM equivalent of "a diagnostic setting does nothing until it is saved on the source." If your effective rules look unchanged, you almost certainly skipped or mis-targeted the deploy in Step 6.

> **The network manager meters until it is deleted.** Newer network-manager instances bill roughly $0.02 per hour per managed VNet; older ones bill per managed subscription under a legacy model. For one VNet across a two-hour lab the rate is trivial. The risk is that the manager keeps metering after you delete the VM, because it has no power state and no obvious "on." Tearing down the VM is not tearing down the lab. See Teardown for the unwind order.

The verification that matters here is control-plane, the **Effective security rules** blade, so you do not actually need the VM reachable from the internet to prove the point. The public IP and the live SSH test are included because watching the connection hang is more convincing than reading a table. If you want zero inbound exposure, skip the public IP and rely on effective rules alone.

## Step 1 - Resource group, VNet, and subnet

**Virtual networks** → **Create**, into a new resource group `rg-sc500w6-lab-eastus2-001`, VNet `vnet-sc500w6-lab-eastus2-001` with address space `10.60.0.0/16` and subnet `snet-sc500w6-lab-eastus2-001` at `10.60.0.0/24`.

Leave the subnet with no NSG and no NAT gateway. The VM gets its own NIC NSG in Step 2.

![Virtual network overview with a 10.60.0.0/16 address space](01-vnet-overview.png)

```bash
az network vnet create -g rg-sc500w6-lab-eastus2-001 -n vnet-sc500w6-lab-eastus2-001 --address-prefix 10.60.0.0/16 --subnet-name snet-sc500w6-lab-eastus2-001 --subnet-prefix 10.60.0.0/24
```

## Step 2 - A VM whose own NSG allows SSH

This is the app team's resource, configured the way they want it, with SSH open. That NSG allow is what the security admin Deny will later beat.

| Tab | Setting | Value |
|---|---|---|
| Basics | Name | `vm-sc500w6-lab-001` |
| Basics | Image | Ubuntu Server LTS |
| Basics | Authentication | SSH public key, generate new and download the key |
| Basics | Public inbound ports | **Allow selected** → **SSH (22)** |
| Networking | Virtual network / subnet | the ones from Step 1 |
| Networking | Public IP | new |
| Networking | NIC network security group | **Basic**, confirming it has an inbound allow SSH 22 rule |

Either let the wizard name the auto-created NSG, or pre-create one with a single inbound rule (allow TCP 22 from Any) and attach it. Either way, the NIC's NSG must **allow SSH inbound**, because that is the control the owner "trusts."

![NSG inbound rules showing SSH allowed at priority 300](02-nsg-allows-ssh.png)

> **VM size and the new-subscription quota trap.** The legacy B-series (`B1s`, `B2s`) is closed to newer subscriptions: it auto-denies at deploy and no quota request lifts it. `B2ls_v2` is the current-gen replacement, but a fresh pay-as-you-go subscription often has the Bsv2 family capped at 0, and the increase request can bounce with `ContactSupport`. If `B2ls_v2` will not deploy, fall back to any family you already have quota for. See what is deployable right now with `az vm list-usage --location eastus2 -o table | awk '$NF > 0'`.

### Baseline: confirm the owner's NSG works

Once the VM is running, SSH to it from your machine using the downloaded key. You get a login prompt. The owner's NSG is doing exactly what they intend. Exit, because you never need to be *inside* the VM again. The rest is control-plane.

![SSH session connected to the VM before any security admin rule exists](03-baseline-ssh-works.png)

## Step 3 - Create the network manager

**Network Managers** → **Create**.

| Tab | Setting | Value |
|---|---|---|
| Basics | Name | `vnm-sc500w6-lab-eastus2-001` |
| Features | Features | tick **Security admin** only |
| Management scope | Scope | **Add** → your subscription |

The **scope** is the boundary of what the manager can govern: only VNets inside a subscription or management group in scope are eligible for its network groups. Scoping to the subscription is enough here. Selecting only the Security admin feature keeps the blade focused and avoids the connectivity meters.

![Network manager overview with SecurityAdmin as the only enabled feature](04-network-manager-overview.png)

## Step 4 - Network group with the VNet as a static member

The network manager → **Network groups** → **Create** → name `ng-sc500w6-servers-001`. Then open the group → **Add virtual networks** → tick the lab VNet → **Add**.

A network group is just a container the rules target. Membership can be **static** (hand-pick VNets, as here) or **dynamic** (Azure Policy conditions, see the variant at the end). Only VNets inside the manager's scope appear in the picker. If yours is missing, the scope in Step 3 did not cover it.

![Network group members listing the lab VNet as manually added](05-network-group-members.png)

## Step 5 - Security admin configuration, rule collection, Deny rule

The network manager → **Configurations** → **Create** → **Security configuration**, named `sac-sc500w6-lab-001`. Add a rule collection `rc-sc500w6-lab-001` targeting `ng-sc500w6-servers-001`, then add a rule inside it:

| Setting | Value |
|---|---|
| Name | `deny-ssh-inbound` |
| Priority | `100` |
| Action | **Deny** |
| Direction | **Inbound** |
| Protocol | **TCP** |
| Source | Any |
| Destination port | `22` |

![Rule collection with the deny-ssh-inbound rule](06-rule-collection-deny-ssh.png)

This says: across every VNet in the network group, deny inbound TCP 22, regardless of what any NSG says. Priority is the ordering *within* security admin rules, lower first, exactly like NSGs. It does not compete with NSG priorities, because security admin rules are a separate, earlier evaluation stage.

## Step 6 - Deploy the configuration to the region

**This is the step that makes it real.** The network manager → **Deployments** → **Deploy configurations**.

| Setting | Value |
|---|---|
| Configuration type | Include security admin configurations in your goal state |
| Security configuration | `sac-sc500w6-lab-001` |
| Target regions | the VNet's region |

Confirm, then **Deploy**. The status moves through *Deploying* to *Deployed*. Give it a few minutes to commit and a few more before checking effective rules, because the host fabric is what is being programmed, not a portal object.

![Deployments blade showing the SecurityAdmin config succeeded](07-deployment-succeeded.png)

## Step 7 - Verify the rule sits above the NSG

The VM must be **running** for effective rules to compute. VM → **Networking** → **Network settings** → the NIC → **Effective security rules**.

The view now has **two tabs**, one per source: one named after the NSG, one named after the network manager. They are separate panes, not one merged list, and this is the detail to get right. The **NSG tab looks completely normal**, with the owner's allow-SSH right there, untouched.

![Effective security rules, NSG tab, showing the SSH allow at priority 300](08-effective-rules-nsg-tab.png)

Switch to the **network manager tab** and there is `deny-ssh-inbound` (Deny, TCP, 22, Inbound), a tab that did not exist before the deploy. The Deny is evaluated *before* the NSG, so SSH is blocked even though the NSG tab still says allow. Two tabs, two stories, and the manager's wins.

![Effective security rules, network manager tab, showing the deny rule](09-effective-rules-manager-tab.png)

### Live confirmation

SSH again, the connection that worked in Step 2's baseline. It hangs and eventually times out. The security admin Deny drops the SYN before the NSG's allow is ever consulted. Nothing about the NSG changed, and the owner's rule is still "allow."

![SSH connection timing out](10-ssh-times-out.png)

## Step 8 - The override attempt: prove the owner cannot win

Now play the app-team owner trying to "fix" their broken SSH. Add the most aggressive allow an NSG permits, at the lowest usable priority.

| Setting | Value |
|---|---|
| Source | Any |
| Destination port | `22` |
| Protocol | TCP |
| Action | **Allow** |
| Priority | `100` |
| Name | `owner-force-allow-ssh` |

![NSG inbound rules with owner-force-allow-ssh at priority 100](11-owner-force-allow-rule.png)

Re-open **Effective security rules** and re-run the SSH:

- On the **NSG tab**, `owner-force-allow-ssh` shows at priority 100. The owner's tab looks like SSH should absolutely work.
- The **network manager tab** is unchanged, still `deny-ssh-inbound`. The owner added the strongest NSG allow available and nothing about the manager's tab moved, because their tab was never the one that decides.
- SSH still hangs.

![Network manager tab unchanged after the owner's override attempt](12-manager-tab-unchanged.png)

This is the exam's whole point. A security admin **Deny** is enforced above NSGs and is not visible or editable from the NSG blade at all. The owner cannot override it because, from where they sit, it is not even there to override.

## Step 9 - Flip Deny to Allow and watch control hand back

This is the beat that separates the three actions. Edit `deny-ssh-inbound`, change **Action** to **Allow**, save, then **redeploy**. Edits are inert until redeployed, which is the one thing that broke for me on the first pass.

After it commits, on the **network manager tab** the security admin rule now reads **Allow**, and because "Allow" defers to NSG evaluation, the NSG tab's allow-SSH is now reached.

![Network manager tab showing the rule with Access set to Allow](13-manager-tab-now-allow.png)

SSH connects again.

![SSH session reconnected after the action was flipped to Allow](14-ssh-connects-again.png)

Contrast worth recording, with no need to test it: had you chosen **Always Allow** instead, SSH would connect *even if the owner set the NSG to Deny 22*. The security admin rule would force it through and the NSG would never be consulted. **Allow defers to the NSG. Always Allow forces, and the NSG cannot deny. Deny blocks, and the NSG cannot allow.**

## Teardown

Deallocate the VM first so compute stops the instant the captures are done, then delete the whole resource group, which contains the manager, VNet, VM, NSG, and public IP.

```bash
az vm deallocate -g rg-sc500w6-lab-eastus2-001 -n vm-sc500w6-lab-001
```

```bash
az group delete -n rg-sc500w6-lab-eastus2-001 --yes --no-wait
```

> **The network manager can refuse to delete while a config is deployed.** If the resource group delete stalls on the manager, it is because the security admin config is still deployed. Unwind in order: remove the deployment (deploy a goal state with the config unselected for the region, committing "none"), then delete the config and rule collection, then the network group, then the manager. Portal delete flows now offer a force delete that does this for you. Confirm the manager is actually gone afterward, because this is the resource that keeps metering if it lingers.

## Variant: dynamic membership via Azure Policy

Swap Step 4's static member for **dynamic membership**: define the network group with an Azure Policy condition, such as VNets tagged `env=prod` or matching a name prefix. Any VNet that matches, including ones created *after* the rule is deployed, is pulled into the group automatically and inherits the Deny with no further action. This is the "scales to the whole org" property that makes security admin rules more than a fancy NSG, and it is worth a five-minute read even if you do not build it, because "new VNets are covered automatically" is a distinguishing exam detail.

## Key takeaways

- Security admin rules are evaluated in the host fabric *before* NSGs. A Deny stops evaluation, so the NSG allow behind it is never reached, and the resource owner cannot see or edit the rule from the NSG blade.
- The three actions are not symmetric. Deny blocks outright, Always Allow forces through, and **Allow** only means "stop enforcing a block here and let the NSG decide," which is the most-missed detail.
- Effective security rules splits into one tab per source. The NSG tab and the network manager tab are separate lists, not a merged one, and only the manager's tab shows the rule doing the blocking.
- Nothing is enforced until the configuration is deployed to the VNet's region, and edits to an already-deployed rule need a fresh deploy. Unchanged effective rules almost always mean a missing or mis-targeted deployment.
- Priority orders rules *within* the security admin stage. It does not compete with NSG priorities, because the two stages never share a number space.
- The network manager itself meters and has no power state. Deleting the VM does not stop it, and a deployed config can block its deletion.

## Related labs

- [NSG Priority Ordering + Network Watcher Verification]({{< ref "nsg-priority-network-watcher" >}}) is the intra-NSG version of "who wins," and this lab is the cross-control sequel
- [Custom RBAC Role + Azure Policy + Resource Lock]({{< ref "custom-role-azure-policy-resource-lock" >}}) is the governance twin: a resource lock beating Owner RBAC is the same shape as a security admin rule beating an NSG owner
- [Hub-Spoke Topology with VNet Peering]({{< ref "hub-spoke-vnet-peering" >}}) for the multi-VNet topology these rules would govern at scale
