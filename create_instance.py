import os
import json
import oci

from telegram_utils import send_telegram
from github_utils import disable_workflow

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

def notify_if_changed(status):

    state = load_state()

    if state["last_status"] != status:

        send_telegram(
            f"Oracle Status Changed\n\n{status}"
        )

        save_state(status)

config = {
    "user":
    os.environ["OCI_USER_OCID"],

    "fingerprint":
    os.environ["OCI_FINGERPRINT"],

    "tenancy":
    os.environ["OCI_TENANCY_OCID"],

    "region":
    os.environ["OCI_REGION"],

    "key_content":
    os.environ["OCI_PRIVATE_KEY"]
}

compartment_id = os.environ["OCI_COMPARTMENT_OCID"]

compute_client = oci.core.ComputeClient(
    config
)

identity_client = oci.identity.IdentityClient(
    config
)

instances = compute_client.list_instances(
    compartment_id
).data

for vm in instances:

    if vm.lifecycle_state in [
        "RUNNING",
        "STARTING",
        "PROVISIONING"
    ]:

        send_telegram(
            f"Instance already exists\n\n{vm.display_name}"
        )

        disable_workflow()

        raise SystemExit

ads = identity_client.list_availability_domains(
    compartment_id
).data

SHAPES = [

    {
        "shape":
        "VM.Standard.A1.Flex",

        "ocpus":
        4,

        "memory":
        24
    },

    {
        "shape":
        "VM.Standard.E2.1.Micro",

        "ocpus":
        None,

        "memory":
        None
    }
]

last_error = "UNKNOWN"

for shape_cfg in SHAPES:

    for ad in ads:

        try:

            source_details = (
                oci.core.models.InstanceSourceViaImageDetails(
                    source_type="image",
                    image_id=os.environ["OCI_IMAGE_ID"]
                )
            )

            create_vnic = (
                oci.core.models.CreateVnicDetails(
                    assign_public_ip=True,
                    subnet_id=os.environ["OCI_SUBNET_ID"]
                )
            )

            launch = (
                oci.core.models.LaunchInstanceDetails(
                    compartment_id=compartment_id,
                    availability_domain=ad.name,
                    display_name="oracle-free-tier",
                    shape=shape_cfg["shape"],
                    source_details=source_details,
                    create_vnic_details=create_vnic
                )
            )

            if shape_cfg["ocpus"]:

                launch.shape_config = (
                    oci.core.models.LaunchInstanceShapeConfigDetails(
                        ocpus=shape_cfg["ocpus"],
                        memory_in_gbs=shape_cfg["memory"]
                    )
                )

            response = (
                compute_client.launch_instance(
                    launch
                )
            )

            send_telegram(
                f"""
SUCCESS

Shape:
{shape_cfg['shape']}

AD:
{ad.name}

Instance:
{response.data.id}
"""
            )

            disable_workflow()

            raise SystemExit

        except Exception as e:

            err = str(e)

            print(err)

            if "Out of host capacity" in err:

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

            else:

                last_error = (
                    "OTHER_ERROR"
                )

notify_if_changed(
    last_error
)
