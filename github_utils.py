import os
import requests

def disable_workflow():

    token = os.environ["GITHUB_TOKEN"]

    repo = os.environ["GITHUB_REPOSITORY"]

    workflow = "create-vm.yml"

    url = (
        f"https://api.github.com/repos/"
        f"{repo}/actions/workflows/"
        f"{workflow}/disable"
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
