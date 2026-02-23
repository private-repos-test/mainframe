import asyncio
import hashlib
import hmac
import json
from ipaddress import ip_address, ip_network

import environ
import requests
from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseServerError
from django.utils.encoding import force_bytes
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.exceptions import MethodNotAllowed
from telegram.constants import ParseMode

from mainframe.clients.chat import send_telegram_message
from mainframe.core.tasks import schedule_deploy

PREFIX = "[[GitHub]]"


def _validate_response(response, ip):
    if response.status_code != status.HTTP_200_OK:
        asyncio.run(
            send_telegram_message(
                f"{PREFIX} Warning, {ip} tried "
                f"to call mainframe github webhook URL"
            )
        )
        return False

    for valid_ip in response.json()["hooks"]:
        if ip in ip_network(valid_ip):
            break
    else:
        asyncio.run(
            send_telegram_message(
                f"{PREFIX} Warning, {ip} tried "
                f"to call mainframe github webhook URL"
            )
        )
        return False
    return True


def _verify_signature(request):
    header_signature = request.META.get("HTTP_X_HUB_SIGNATURE")
    if header_signature is None:
        asyncio.run(send_telegram_message(text=f"{PREFIX} No signature"))
        return False

    sha_name, signature = header_signature.split("=")
    if sha_name != "sha1":
        asyncio.run(send_telegram_message(text=f"{PREFIX} operation not supported"))
        return False

    mac = hmac.new(
        force_bytes(settings.SECRET_KEY),
        msg=force_bytes(request.body),
        digestmod=hashlib.sha1,
    )
    if not hmac.compare_digest(force_bytes(mac.hexdigest()), force_bytes(signature)):
        asyncio.run(send_telegram_message(text=f"{PREFIX} Invalid signature"))
        return False

    return True


@csrf_exempt
def mainframe(request):  # noqa: C901, PLR0911
    permission_denied = "Permission denied."

    if request.method != "POST":
        raise MethodNotAllowed(request.method)

    env = environ.Env()
    response = requests.get(
        "https://api.github.com/meta",
        headers={"Authorization": f"Bearer {env('GITHUB_ACCESS_TOKEN')}"},
        timeout=30,
    )
    # Verify if request came from GitHub
    ip = ip_address(
        request.META.get("HTTP_X_FORWARDED_FOR").split(", ")[0]
    )
    if not _validate_response(response, ip):
        return HttpResponseForbidden("Failed to validate GitHub IPs")

    if _verify_signature(request) is False:
        return HttpResponseForbidden(permission_denied)

    event = request.META.get("HTTP_X_GITHUB_EVENT", "ping")
    payload = json.loads(request.body)

    if event != "workflow_job":
        compare = payload.get("compare", "")
        new_changes_link = (
            f"<a target='_blank' href='{compare}'>new changes</a>" if compare else ""
        )
        branch = payload.get("ref", "").replace("refs/heads/", "")
        branch_message = f"on the <b>{branch}</b> branch" if branch else ""

        pusher = payload.get("pusher", {}).get("name", "")
        asyncio.run(
            send_telegram_message(
                text=f"<b>{pusher}</b> {event}ed {new_changes_link} "
                f"{branch_message}",
                parse_mode=ParseMode.HTML,
            )
        )
        return HttpResponse("pong")

    wf_data = payload.get(event)
    name = f"[{wf_data['workflow_name']}] {wf_data['name']}"
    if wf_data["head_branch"] != "main" or name != "[Mainframe pipeline] BE - Deploy":
        return HttpResponse(status=204)

    action = " ".join(payload["action"].split("_"))
    if action != "completed" or (conclusion := wf_data.get("conclusion")) != "success":
        return HttpResponse(status=204)

    message = (
        f"<a href='{wf_data['html_url']}'><b>{name}</b></a> {action}"
        f" {f'({conclusion.title()})' if conclusion else ''} "
    )
    message += "🎉\n🍓 Deployment scheduled 🚀"
    task = schedule_deploy()
    if result := task.get():
        message += f"\n{result}"

    asyncio.run(send_telegram_message(text=message, parse_mode=ParseMode.HTML))
    return HttpResponse(status=204)
