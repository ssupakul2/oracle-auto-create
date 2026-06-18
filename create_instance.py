import os
import json
import time
import requests
import oci

STATE_FILE = "state.json"


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_status": ""}


def save_state(status):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_status": status}, f)


def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=30,
        )
    except Exception:
        pass


def notify_if_changed(status):
    state = load_state()

    if state.get("last_status") != status:
        send_telegram(f"Oracle Status Changed\n\n{status}")
        save_state(status)


def disable_workflow():
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")

    if not token or not repo:
        return

    try:
        requests.put(
            f"https://api.github.com/repos/{repo}/actions/workflows/create-vm.yml/disable",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=30,
        )
    except Exception:
        pass


config = {
    "user": os.environ["OCI_USER_OCID"],
    "fingerprint": os.environ["OCI_FINGERPRINT"],
    "tenancy": os.environ["OCI_TENANCY_OCID"],
    "region": os.environ["OCI_REGION"],
    "key_content": os.environ["OCI_PRIVATE_KEY"],
}

compartment_id = os.environ["OCI_COMPARTMENT_OCID"]
subnet_id = os.environ["OCI_SUBNET_ID"]

compute_client = oci.core.ComputeClient(config)
identity_client = oci.identity.IdentityClient(config)


def get_latest_image(arch):
    candidates = []

    search_list = [
        ("Canonical Ubuntu", "24.04"),
        ("Canonical Ubuntu", "22.04"),
    ]

    for os_name, os_version in search_list:
        try:
            images = compute_client.list_images(
                compartment_id=compartment_id,
                operating_system=os_name,
                operating_system_version=os_version,
            ).data

            for img in images:
                name = (img.display_name or "").lower()

                if arch == "ARM":
                    if "aarch64" in name:
                        candidates.append(img)

                if arch == "X86":
                    if "x86_64" in name or "amd64" in name:
                        candidates.append(img)

        except Exception:
            pass

    if not candidates:
        raise RuntimeError(f"No {arch} image found")

    candidates.sort(key=lambda x: x.time_created, reverse=True)

    return candidates[0]


instances = compute_client.list_instances(compartment_id).data

for vm in instances:

    if vm.lifecycle_state in [
        "RUNNING",
        "STARTING",
        "PROVISIONING",
    ]:

        send_telegram(
            f"""Instance already exists

Name: {vm.display_name}
State: {vm.lifecycle_state}

Workflow disabled.
"""
        )

        disable_workflow()
        raise SystemExit(0)


ads = identity_client.list_availability_domains(compartment_id).data

print("ADS FOUND")

for ad in ads:
    print(ad.name)


SHAPES = [
    {
        "shape": "VM.Standard.A1.Flex",
        "ocpus": 1,
        "memory": 6,
        "arch": "ARM",
    },
    {
        "shape": "VM.Standard.A1.Flex",
        "ocpus": 2,
        "memory": 12,
        "arch": "ARM",
    },
    {
        "shape": "VM.Standard.E2.1.Micro",
        "ocpus": None,
        "memory": None,
        "arch": "X86",
    },
]

last_error = "UNKNOWN"

for shape_cfg in SHAPES:

    try:

        image = get_latest_image(shape_cfg["arch"])

        print(
            f"Using image {image.display_name} "
            f"for {shape_cfg['shape']}"
        )

    except Exception as e:

        print(e)

        continue

    for ad in ads:

        try:

            print(
                f"Trying {shape_cfg['shape']} "
                f"{ad.name}"
            )

            source_details = (
                oci.core.models.InstanceSourceViaImageDetails(
                    source_type="image",
                    image_id=image.id,
                )
            )

            create_vnic = (
                oci.core.models.CreateVnicDetails(
                    assign_public_ip=True,
                    subnet_id=subnet_id,
                )
            )

            launch = (
                oci.core.models.LaunchInstanceDetails(
                    compartment_id=compartment_id,
                    availability_domain=ad.name,
                    display_name="oracle-free-tier",
                    shape=shape_cfg["shape"],
                    source_details=source_details,
                    create_vnic_details=create_vnic,
                )
            )

            if shape_cfg["ocpus"] is not None:

                launch.shape_config = (
                    oci.core.models.LaunchInstanceShapeConfigDetails(
                        ocpus=shape_cfg["ocpus"],
                        memory_in_gbs=shape_cfg["memory"],
                    )
                )

            response = compute_client.launch_instance(
                launch
            )

            send_telegram(
                f"""✅ ORACLE VM CREATED

Region:
{config['region']}

Shape:
{shape_cfg['shape']}

AD:
{ad.name}

Image:
{image.display_name}

Instance:
{response.data.id}
"""
            )

            disable_workflow()

            raise SystemExit(0)

        except Exception as e:

            err = str(e).lower()

            print(err)

            if "out of host capacity" in err:

                last_error = "OUT_OF_CAPACITY"

                time.sleep(30)

            elif "toomanyrequests" in err:

                last_error = "RATE_LIMIT"

                time.sleep(90)

            elif "limitexceeded" in err:

                last_error = "LIMIT_EXCEEDED"

                time.sleep(30)

            elif "quotaexceeded" in err:

                last_error = "QUOTA_EXCEEDED"

                time.sleep(30)

            elif "notauthorized" in err:

                last_error = "NOT_AUTHORIZED"

                time.sleep(30)

            elif "invalidparameter" in err:

                last_error = "INVALID_PARAMETER"

                time.sleep(10)

            else:

                last_error = "OTHER_ERROR"

                time.sleep(15)

notify_if_changed(last_error)

print(f"Final status: {last_error}")
