import os
import json
import requests
import oci

# ==========================================

# State

# ==========================================

STATE_FILE = "state.json"

def load_state():
try:
with open(STATE_FILE, "r") as f:
return json.load(f)
except:
return {
"last_status": ""
}

def save_state(status):
with open(STATE_FILE, "w") as f:
json.dump(
{
"last_status": status
},
f
)

# ==========================================

# Telegram

# ==========================================

def send_telegram(message):

```
token = os.getenv(
    "TELEGRAM_BOT_TOKEN"
)

chat_id = os.getenv(
    "TELEGRAM_CHAT_ID"
)

if not token or not chat_id:
    return

requests.post(
    f"https://api.telegram.org/bot{token}/sendMessage",
    json={
        "chat_id": chat_id,
        "text": message
    },
    timeout=30
)
```

def notify_if_changed(status):

```
state = load_state()

if state["last_status"] != status:

    send_telegram(
        f"Oracle Status Changed\n\n{status}"
    )

    save_state(status)
```

# ==========================================

# GitHub Workflow Disable

# ==========================================

def disable_workflow():

```
token = os.getenv(
    "GITHUB_TOKEN"
)

repo = os.getenv(
    "GITHUB_REPOSITORY"
)

if not token or not repo:
    return

workflow_name = (
    "create-vm.yml"
)

url = (
    f"https://api.github.com/repos/"
    f"{repo}/actions/workflows/"
    f"{workflow_name}/disable"
)

requests.put(
    url,
    headers={
        "Authorization":
        f"Bearer {token}",

        "Accept":
        "application/vnd.github+json"
    },
    timeout=30
)
```

# ==========================================

# OCI Config

# ==========================================

config = {
"user":
os.environ["OCI_USER_OCID"],

```
"fingerprint":
os.environ["OCI_FINGERPRINT"],

"tenancy":
os.environ["OCI_TENANCY_OCID"],

"region":
os.environ["OCI_REGION"],

"key_content":
os.environ["OCI_PRIVATE_KEY"]
```

}

compartment_id = os.environ[
"OCI_COMPARTMENT_OCID"
]

subnet_id = os.environ[
"OCI_SUBNET_ID"
]

compute_client = (
oci.core.ComputeClient(config)
)

identity_client = (
oci.identity.IdentityClient(config)
)

# ==========================================

# Find Ubuntu Image

# ==========================================

def get_latest_ubuntu_image():

```
candidates = []

searches = [

    (
        "Canonical Ubuntu",
        "24.04"
    ),

    (
        "Canonical Ubuntu",
        "22.04"
    )
]

for os_name, os_version in searches:

    try:

        images = (
            compute_client.list_images(
                compartment_id=
                compartment_id,

                operating_system=
                os_name,

                operating_system_version=
                os_version
            ).data
        )

        candidates.extend(images)

    except Exception:
        pass

if not candidates:

    raise Exception(
        "No Ubuntu image found"
    )

candidates.sort(
    key=lambda x:
    x.time_created,
    reverse=True
)

return candidates[0]
```

ubuntu_image = (
get_latest_ubuntu_image()
)

image_id = ubuntu_image.id

print(
f"Using image: "
f"{ubuntu_image.display_name}"
)

# ==========================================

# Existing Instance Check

# ==========================================

instances = (
compute_client.list_instances(
compartment_id
).data
)

for vm in instances:

```
if vm.lifecycle_state in [

    "RUNNING",
    "STARTING",
    "PROVISIONING"

]:

    send_telegram(
        f"""
```

Instance already exists

Name:
{vm.display_name}

State:
{vm.lifecycle_state}

Workflow disabled.
"""
)

```
    disable_workflow()

    raise SystemExit
```

# ==========================================

# Availability Domains

# ==========================================

ads = (
identity_client
.list_availability_domains(
compartment_id
).data
)

# ==========================================

# Shapes Priority

# ==========================================

SHAPES = [

```
{
    "shape":
    "VM.Standard.A1.Flex",

    "ocpus":
    1,

    "memory":
    6
},

{
    "shape":
    "VM.Standard.A1.Flex",

    "ocpus":
    2,

    "memory":
    12
},

{
    "shape":
    "VM.Standard.E2.1.Micro",

    "ocpus":
    None,

    "memory":
    None
}
```

]

# ==========================================

# Launch Attempts

# ==========================================

last_error = "UNKNOWN"

for shape_cfg in SHAPES:

```
for ad in ads:

    try:

        print(
            f"Trying "
            f"{shape_cfg['shape']} "
            f"{ad.name}"
        )

        source_details = (
            oci.core.models
            .InstanceSourceViaImageDetails(
                source_type="image",
                image_id=image_id
            )
        )

        create_vnic = (
            oci.core.models
            .CreateVnicDetails(
                assign_public_ip=True,
                subnet_id=subnet_id
            )
        )

        launch = (
            oci.core.models
            .LaunchInstanceDetails(
                compartment_id=
                compartment_id,

                availability_domain=
                ad.name,

                display_name=
                "oracle-free-tier",

                shape=
                shape_cfg["shape"],

                source_details=
                source_details,

                create_vnic_details=
                create_vnic
            )
        )

        if shape_cfg["ocpus"]:

            launch.shape_config = (
                oci.core.models
                .LaunchInstanceShapeConfigDetails(
                    ocpus=
                    shape_cfg["ocpus"],

                    memory_in_gbs=
                    shape_cfg["memory"]
                )
            )

        response = (
            compute_client
            .launch_instance(
                launch
            )
        )

        send_telegram(
            f"""
```

✅ ORACLE VM CREATED

Region:
{config['region']}

Shape:
{shape_cfg['shape']}

AD:
{ad.name}

Image:
{ubuntu_image.display_name}

Instance:
{response.data.id}
"""
)

```
        disable_workflow()

        raise SystemExit

    except Exception as e:

        err = str(e)

        print(err)

        if (
            "Out of host capacity"
            in err
        ):

            last_error = (
                "OUT_OF_CAPACITY"
            )

        elif (
            "LimitExceeded"
            in err
        ):

            last_error = (
                "LIMIT_EXCEEDED"
            )

        elif (
            "NotAuthorized"
            in err
        ):

            last_error = (
                "NOT_AUTHORIZED"
            )

        elif (
            "QuotaExceeded"
            in err
        ):

            last_error = (
                "QUOTA_EXCEEDED"
            )

        else:

            last_error = (
                "OTHER_ERROR"
            )
```

# ==========================================

# Notify Only If Status Changed

# ==========================================

notify_if_changed(
last_error
)

print(
f"Final status: "
f"{last_error}"
)
