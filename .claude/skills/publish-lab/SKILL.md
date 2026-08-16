---
name: publish-lab
description: Publish an SC-500 lab from the Obsidian vault to the Hugo site at content/cloud/labs/. Use this whenever the user wants to ship, publish, post, or push a lab to the site, mentions "this week's lab", or asks to turn a vault note into a lab post. Covers the whole path: converting and redacting screenshots, cutting the vault note down to house length, matching the existing structure, building, pushing, and verifying the live URL. Use it even if the user only asks for part of the job (for example "just redact these screenshots" or "is this lab too long?"), because the length targets and the redaction checklist are easy to get wrong from memory.
---

# Publishing a lab to the site

## The one idea that matters

The vault note and the published lab are **different documents with different jobs**.

The vault note is a working record. It carries cost warnings, teardown order, self-check
questions, "what broke," and CLI alternates because those matter to Brent while running the
lab. The published lab has exactly one job: **let a stranger follow along and complete the
objectives.** Everything that does not serve that job comes out.

This is not a copy-paste with light editing. Expect to delete 50 to 60 percent of the words.

**Draft at the target length instead of transcribing then trimming.** This is the single
biggest time sink. If you write out the full note and then try to cut it, you end up
polishing sentences (which recovers maybe 5 percent) rather than deleting whole sections
(which is where the 50 percent lives). Decide what dies *before* you write, then write the
short version once.

## Length targets

Run this before you start editing, to see the band you are aiming for, and again after:

```bash
.claude/skills/publish-lab/scripts/length-check.sh
```

| Metric | Range | Notes |
|---|---|---|
| Body words, excluding front matter | 600 to 1300 | Hard ceiling around 1300 |
| Words per screenshot | 40 to 120 | The better signal |

Words-per-screenshot is what catches bloat in a lab that looks short. The real test is
positional: a new lab should **interleave** with the existing ones when sorted, not sort to
the bottom. If it sorts last, it is not finished.

A lab that is mostly dashboard reading (few screenshots, more explanation) runs higher on
words-per-screenshot legitimately. Hold it to the word ceiling instead. If a lab is running
hot on the ratio because it genuinely covers a lot of ground on few captures, say so plainly
rather than deleting substance to hit a number, and suggest more captures next time.

## Step 1 - Find the lab and read it

Labs live at `~/codebrew-vault/01-Projects/SC-500 Cert Prep/Labs/`. Sort by modification
time to find this week's. Screenshots live at `~/codebrew-vault/Files/`, named
`<Note Title>-<epoch-ms>.webp`.

Check the front matter `status:` field. `complete` and `draft` are both shippable;
`incomplete` is not. (`draft` is the vault template's default, so shipped labs often still
say it. Do not read it as "unfinished.")

Brent keeps the master checklist at
`~/codebrew-vault/01-Projects/CodeBrew Cyber Site/Publishing Labs to the Site.md`. This skill
carries the same procedure, but that note is his working document and may have picked up
lessons this skill has not. Skim it if anything here looks stale.

## Step 2 - Build the page bundle

The published lab is a Hugo page bundle: `content/cloud/labs/<slug>/index.md` with its
images beside it.

Pick the slug by shortening the title, not by transliterating it. Existing slugs drop filler
and abbreviate: "Virtual Network Manager Security Admin Rules" became
`vnet-manager-security-admin-rules`, and "Secretless VM: Managed Identity, Bastion, and Key
Vault" became `secretless-vm-managed-identity-key-vault`. The `aliases` entry in the front
matter has to use the same slug.

Get the screenshots in **document order** from the note's embeds. Do not sort by filename:
the epoch-ms in the name is capture time, which usually matches document order but does not
have to, and a note that references an earlier capture again later will silently misorder.

```bash
NOTE="$HOME/codebrew-vault/01-Projects/SC-500 Cert Prep/Labs/<Note Title>.md"
grep -o '!\[\[[^]]*\]\]' "$NOTE" | sed 's/!\[\[//; s/\]\]//' | nl
```

Then convert each one to PNG in that order, named `NN-descriptive-name.png`:

```bash
sips -s format png "$HOME/codebrew-vault/Files/<src>.webp" \
  --out "content/cloud/labs/<slug>/01-create-vnet.png"
```

Descriptive names matter more than they look: they are how you keep track of which capture
is which during redaction, and they make a missing reference obvious later.

## Step 3 - Redact, and actually look

Review **every** screenshot before publishing, not just the ones you remember. Read them all
with the Read tool. Things that hide mid-string are the ones that get through.

| Redact | Leave |
|---|---|
| Subscription ID | Managed identity `oid` / `appid` when matching them is the lab's point |
| Tenant / Directory ID | Tenant display name |
| Home or ISP public IP (`Last login: ... from <ip>`) | Torn-down Azure resource IPs |
| Anything inside `Caller:` / `iss=` / `xms_mirid` / `_ResourceId` | Fake secret values (`hello-sc500`) |
| The **Created by** column in Foundry and other portal list views | |

That last row is easy to miss: portal list views render the signed-in account's email
address, which appears nowhere else on the site. Black it out.

The hard ones hide inside long strings: `iss=https://sts.windows.net/<tenant>/` and
`Resource: '/subscriptions/<sub>/...'` in CLI error output, and the `Identity` column in Log
Analytics results.

There is no ImageMagick or Pillow on this Mac. Use the bundled pure-stdlib script:

```bash
# Black out one or more boxes, in place
.claude/skills/publish-lab/scripts/redact.py shot.png 1538,244,1730,274

# Then verify by re-cropping at zoom, and READ the crop
.claude/skills/publish-lab/scripts/redact.py shot.png \
  --inspect 1300,220,1800,310 --zoom 4 --out /tmp/crop.png
```

Always do the verify pass. First-pass coordinates are usually a little short and leave the
tail of a GUID or an email domain visible, which is the exact failure that matters.

## Step 4 - Cut

Cut on sight. Every item here is a vault-note artifact, and none of them appear in any
published lab:

- **"The CLI equivalent, if you prefer it"** blocks. Keep a command only when it *is* the
  action: a KQL query, an IMDS `curl`, a setting the portal cannot express correctly.
- **Full Tab / Setting / Value wizard tables.** Replace with a sentence naming only the
  fields you actually change. Nobody needs a row saying a default stayed default.
- **"Step 0 (read this first)" theory preambles.** Compress the one genuine gotcha into a
  blockquote near the top and drop the rest.
- **Credit-burner and cost warnings.** A personal budgeting concern, not reader
  instructions, and they date the post.
- **Teardown sections.** One short paragraph at most, or fold it into the last step.
- **`## Self-check` Q&A** and **`### Variant:`** sections. Those live in the vault.
- **`## What broke`.** Fold each real gotcha into the step where it bites, in one sentence.
  This is usually the highest-value cut: the gotchas are good, but they belong inline where
  the reader hits them, not in a postmortem list at the end.
- **Resource naming tables.** Name resources inline as you create them.
- **Repeated restatements.** Vault notes make the same point in the intro, the step, and the
  takeaway. Pick one place. When you are over length, this is where the words are.

Keep:

- **Every screenshot.** The images are the substance.
- **Every command the reader actually runs.**
- **Every verification step** (what proves this worked).
- **The failure captures.** A `Forbidden` with the error string legible is worth more than
  three success screenshots.
- **One blockquote per genuine trap**, in the step where it bites.

## Step 5 - Structure

Match the existing labs. In order:

```markdown
+++
title = "..."
date = <staggered, see below>
draft = false
description = "One sentence. What the reader will have done by the end."
tags = ["azure", "<service>", ..., "sc-500"]
categories = ["labs"]
aliases = ["/writeups/labs/<slug>/"]
+++

Part of my SC-500 study series: hands-on labs in a test tenant, one concept at a time.

**Goal:** <one or two sentences, a capability rather than a task list>

## Why this matters          <- ONE short paragraph, or a table instead
## Prerequisites             <- 2 to 3 bullets
## Step 1 - <name>           <- hyphen, not colon
## Key takeaways             <- 4 to 6 bullets
## Related labs              <- 1 to 3 bullets, always {{< ref >}} links
```

Within a step: one or two sentences of instruction, then the screenshots, then a sentence on
what the screenshot proves. Stack consecutive images with no commentary between them when
they are one continuous sequence.

Alt text describes what the capture shows, not "screenshot of step 3."

**Voice:** first person for Brent's own labs, neutral for external resources. Past tense is
fine for things he did once ("Re-opened public access to leave a path for the next lab").
Imperative for what the reader does.

**No em dashes anywhere in site copy.** Restructure the sentence instead.

**Dates:** stagger them so a batch does not look like a batch. Anchor on the real capture
timestamps, keep chronological order, and vary the time of day.

```bash
# What day was this capture actually taken?
python3 -c "import datetime;print(datetime.datetime.fromtimestamp(1786754406784/1000))"

# Check for collisions with what is already published
grep -h '^date' content/cloud/labs/*/index.md | sort
```

## Step 6 - Verify before building

```bash
# Every image reference resolves to a file that exists, and vice versa
cd content/cloud/labs/<slug>
grep -o '](\([0-9][^)]*\.png\))' index.md | sed 's/](//; s/)//' | sort > /tmp/ref
ls *.png | sort | diff /tmp/ref - && echo "IMAGE REFS OK"

# No em dashes
grep -n '—' index.md || echo "none"
```

Then the length check again, and the build:

```bash
hugo build --gc --minify
```

Confirm the page appears under `public/cloud/labs/<slug>/` and that the labs index links it.
Verify the `{{< ref >}}` links resolved by grepping the rendered HTML. Hugo's output is
minified with unquoted attributes, so match loosely (`grep -o 'id=related-labs.\{0,500\}'`)
rather than searching for `href="..."`.

## Step 7 - Ship

Commit the content bundle only. `CLAUDE.md` is gitignored; `.claude/` and `_vendor/` are
untracked and stay that way, so stage the bundle path explicitly rather than using `git add -A`.

Pushing to `main` triggers `.github/workflows/hugo.yaml`, which builds and deploys to GitHub
Pages. There is no manual deploy step. Watch it land and confirm the live URL:

```bash
gh run watch <run-id> --exit-status
curl -sL -o /dev/null -w "%{http_code}\n" https://codebrewcyber.github.io/cloud/labs/<slug>/
```

Follow redirects with `-L`. Without it you get a 301 from the trailing-slash redirect and it
looks like a failure when the page is fine.

Finally, confirm the labs index actually lists the new lab:

```bash
curl -sL https://codebrewcyber.github.io/cloud/labs/ | grep -c '<slug>'
```

## Report back honestly

Tell Brent where the lab landed on both metrics and whether it interleaved. If you made a
judgment call he did not ask for, especially a redaction, say what you changed and why. If
the lab is outside a target band and getting inside it would mean deleting something real,
say that plainly and name what you would have to cut, rather than quietly shipping outside
the band or quietly gutting the content.
