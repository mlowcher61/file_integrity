# AAP configuration as code

`configure_aap.yml` uses the validated collection
[`infra.aap_configuration`](https://github.com/redhat-cop/infra.aap_configuration)
(its `dispatch` role) to create everything the project needs in Ansible
Automation Platform 2.6:

| Object | Name | Defined in |
|---|---|---|
| Credential type | `AIDE Baseline Git Token` (secret field `token` → env `AIDE_BASELINE_GIT_TOKEN`) | `vars/credential_types.yml` |
| Credential | `file_integrity baseline repo token` | `vars/credentials.yml` |
| Execution environment | `ee-supported-rhel9` (optional) | `vars/execution_environments.yml` |
| Project | `file_integrity` (this repo, update on launch) | `vars/projects.yml` |
| Job templates | `AIDE - Deploy`, `AIDE - Check`, `AIDE - Rebaseline` (survey), `AIDE - Validate Config` | `vars/job_templates.yml` |
| Workflow | `AIDE - Change Rebaseline`: Validate Config → **Approval** → Rebaseline → Check | `vars/workflows.yml` |
| Schedule | `AIDE - Daily Check`: AIDE - Check daily at 03:00 America/Los_Angeles | `vars/schedules.yml` |

Every job template uses the `ee-supported-rhel9` execution environment and
has two credentials: your **Machine** credential and the
**baseline Git token** credential. Each one prompts for *Limit* on launch.

## 1. Fill in the placeholders

Edit **`vars/00_site.yml`**. Three values must be set, and the playbook
refuses to run until they are:

| Variable | What to put there |
|---|---|
| `aap_fim_organization` | An existing AAP organization, e.g. `Default` |
| `aap_fim_inventory` | An existing inventory containing your RHEL hosts (in group `aide`) |
| `aap_fim_machine_credential` | An existing Machine credential (SSH user with sudo) for those hosts |

Optional settings in the same file include the project URL and branch, the
baseline repo URL, EE image and registry credential, schedule time zone and
start, and approval timeout.

If your controller already has an execution environment called
`ee-supported-rhel9`, set `aap_fim_create_execution_environment: false`.
Otherwise it is created from
`registry.redhat.io/ansible-automation-platform-26/ee-supported-rhel9:latest`
using the registry credential named in `aap_fim_execution_environment_registry_credential`.

## 2. Install the collections

```bash
ansible-galaxy collection install -r aap/requirements.yml -p aap/collections
```

`infra.aap_configuration` depends on the certified `ansible.platform`
(gateway) and `ansible.controller` (controller objects) collections, which
come from Red Hat Automation Hub. Configure your `ansible.cfg` `[galaxy]`
section with an Automation Hub token first.

## 3. Provide credentials through the environment

Nothing secret is stored in this repository. `configure_aap.yml` reads:

| Environment variable | Purpose |
|---|---|
| `AAP_HOSTNAME` | Platform gateway URL, e.g. `https://aap.example.com` |
| `AAP_TOKEN` | OAuth2 token for an AAP admin (preferred), **or** ... |
| `AAP_USERNAME` / `AAP_PASSWORD` | ... username and password |
| `AAP_VALIDATE_CERTS` | `false` for lab systems with self-signed certificates (default `true`) |
| `AIDE_BASELINE_GIT_TOKEN` | Read/write token for the baseline repository. It is stored only inside the AAP credential. |

These are the AAP 2.5+/2.6 variable names used by `ansible.platform`
(`AAP_HOSTNAME`, `AAP_TOKEN`, `AAP_USERNAME`, `AAP_PASSWORD`,
`AAP_VALIDATE_CERTS`; `GATEWAY_*` aliases also exist). They replace the
AAP 2.4 `CONTROLLER_HOST` / `CONTROLLER_OAUTH_TOKEN` variables.
`configure_aap.yml` maps them to the collection's `aap_hostname`, `aap_token`,
`aap_username`, `aap_password` and `aap_validate_certs` variables.

```bash
export AAP_HOSTNAME=https://aap.example.com
export AAP_TOKEN='...'
export AIDE_BASELINE_GIT_TOKEN='github_pat_...'
```

## 4. Run it

```bash
ANSIBLE_COLLECTIONS_PATH=aap/collections ansible-playbook aap/configure_aap.yml
```

The playbook is idempotent; re-run it whenever you change `aap/vars/`.

**Rotating the baseline token:** the credential uses `update_secrets: false`,
so re-running does not overwrite an existing token. Rotate it in the AAP UI
(*Automation Execution → Infrastructure → Credentials*), or set
`update_secrets: true` in `vars/credentials.yml` for one run.

## Running from AAP itself (optional)

To manage this configuration from AAP, create a job template that runs
`aap/configure_aap.yml` from the `file_integrity` project with:

- an inventory containing `localhost`,
- an EE that contains `infra.aap_configuration`, `ansible.platform` and `ansible.controller`,
- a credential of type *Red Hat Ansible Automation Platform* (injects the
  `CONTROLLER_*`/`AAP_*` connection variables), and the *AIDE Baseline Git
  Token* credential (injects `AIDE_BASELINE_GIT_TOKEN`).

## What the workflow does

```mermaid
flowchart LR
    S([Launch: survey asks for change ref + target hosts; Limit prompt]) --> V[AIDE - Validate Config]
    V -->|success| A{{Approve AIDE re-baseline<br/>timeout 24h}}
    A -->|approved| R[AIDE - Rebaseline]
    R -->|success| C[AIDE - Check]
```

The workflow survey collects `aide_change_ref` and `aide_target_hosts`.
Workflow variables and the Limit are passed to every node. The approval
node's timeout is `aap_fim_approval_timeout` seconds (default 86400).
