#!/usr/bin/python3

import os
import sys
import subprocess
import json
import requests
import webhook_listener

env_val = {
    "identity_file": "~/.ssh/id_rsa.drone",
    "gerrit_host": "gerrit.tower.ztluo.dev",
    "gerrit_ssh_port": "29418",
    "gerrit_namespace": "ztluo-gerrit",
    "gerrit_trigger_user": "gerrit",
    "comment_verify_key": "verify",
    "drone_ci_url": "https://drone.tower.ztluo.dev/",
    "drone_ci_name": "drone",
    "drone_ci_token": "",
}


pending_patch_builds = dict()


def gerrit_get_latest_comment(change_id):
    with subprocess.Popen(["ssh",
                           "-i", env_val["identity_file"],
                           "-p", env_val["gerrit_ssh_port"], env_val["drone_ci_name"] +
                           "@" + env_val["gerrit_host"],
                           "gerrit", "query",
                           "--comments",
                           "--current-patch-set",
                           "--format=JSON",
                           change_id,
                           ],
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE) as proc:
        line = proc.stdout.readline()
        data = json.loads(line)
        # print(json.dumps(data, indent=2))

        current_comments = data["currentPatchSet"]["comments"]
        latest_comment = current_comments[-1]["message"]

        verify_value = "0"
        if "approvals" in data["currentPatchSet"]:
            approvals = data["currentPatchSet"]["approvals"]
            for approval in approvals:
                if approval["type"] == "Verified" and \
                        approval["by"]["username"] == env_val["drone_ci_name"]:
                    verify_value = approval["value"]

        return latest_comment, verify_value


def gerrit_set_verify_label(change_num, patch_num, value, message):
    with subprocess.Popen(["ssh",
                           "-i", env_val["identity_file"],
                           "-p", env_val["gerrit_ssh_port"], env_val["drone_ci_name"] +
                           "@" + env_val["gerrit_host"],
                           "gerrit", "review",
                           "--verified", value,
                           "-m", "\'\"" + message + "\"\'",
                           str(change_num) + "," + str(patch_num),
                           ],
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE) as proc:
        pass


def drone_create_build(project, branch, args):
    post_url = env_val["drone_ci_url"] + "api/repos/" + env_val["gerrit_namespace"] + "/" + project \
        + "/builds?branch=" + branch

    for i in args:
        post_url = post_url + "&" + i["key"] + "=" + i["value"]

    headers = {'Authorization': 'Bearer %s' % env_val["drone_ci_token"]}
    r = requests.post(post_url, headers=headers, params=None, data=None)
    if not r.ok:
        r.raise_for_status()

    data = r.json()
    # print(json.dumps(data, indent=2))
    patch_build_num = data["number"]

    return patch_build_num


def process_post_request(request, *args, **kwargs):
    # print(
    #     "Received request:\n"
    #     + "Method: {}\n".format(request.method)
    #     + "Headers: {}\n".format(request.headers)
    #     + "Args (url path): {}\n".format(args)
    #     + "Keyword Args (url parameters): {}\n".format(kwargs)
    #     + "Body: {}".format(
    #         request.body.read(int(request.headers["Content-Length"]))
    #         if int(request.headers.get("Content-Length", 0)) > 0
    #         else ""
    #     )
    # )

    # TODO: check token

    content_len = int(request.headers.get("Content-Length", 0))
    if content_len > 0:
        content = request.body.read(content_len)
        data = json.loads(content)
        event = data["event"]
        action = data["action"]

        if event == "build" and action == "updated":
            repo_namespace = data["repo"]["namespace"]
            repo_name = data["repo"]["name"]

            build_status = data["build"]["status"]
            build_num = data["build"]["number"]
            build_trigger = data["build"]["trigger"]
            # build_branch = data["build"]["target"]

            if repo_namespace != env_val["gerrit_namespace"] or \
                    build_status == "running" or \
                    build_trigger != env_val["gerrit_trigger_user"]:
                # print("skip update event", repo_namespace,
                #       build_status, build_trigger)
                return

            print("build status update event:", build_status)
            patch_build_key = repo_name + str(build_num)
            cur_patch_build = pending_patch_builds.pop(patch_build_key)

            change_num = cur_patch_build["change_num"]
            patch_num = cur_patch_build["patch_num"]
            ci_url = cur_patch_build["ci_url"]

            if (build_status == "success"):
                gerrit_set_verify_label(change_num, patch_num, "+1",
                                        "Drone CI Verified Success: " + ci_url)
            else:
                gerrit_set_verify_label(change_num, patch_num, "-1",
                                        "Drone CI Verified Failed: " + ci_url)

            # print(json.dumps(data, indent=2))

    return


def get_env():
    for key in env_val.keys():
        environ = os.environ.get(key)
        if environ != None:
            print("environ:", "set", key, "to", environ)
            env_val[key] = environ

    print("Final env:")
    for key in env_val.keys():
        print(key, ":", env_val[key])
    return


if __name__ == '__main__':
    print("Exec From", sys.path[0])

    get_env()

    webhooks = webhook_listener.Listener(
        handlers={"POST": process_post_request})
    webhooks.start()

    with subprocess.Popen(["ssh",
                           "-i", env_val["identity_file"],
                           "-p", env_val["gerrit_ssh_port"], env_val["drone_ci_name"] +
                           "@" + env_val["gerrit_host"],
                           "gerrit", "stream-events",
                           "-s", "comment-added",
                           ],
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE) as proc:

        while True:
            try:
                line = proc.stdout.readline()
                data = json.loads(line)
                project = data["project"]
                event_type = data["type"]
                change_id = data["change"]["id"]
                change_num = data["change"]["number"]
                change_branch = data["change"]["branch"]
                patch_num = data["patchSet"]["number"]
                patch_ref = data["patchSet"]["ref"]

                print("Gerrit event,",
                      "project:", project,
                      "type:", event_type,
                      "change_id:", change_id
                      )

                # print(json.dumps(data, indent=2))

                if event_type == "comment-added":
                    # print(json.dumps(data, indent=2))
                    author_name = data["author"]["name"]
                    if author_name != env_val["drone_ci_name"]:

                        comment, verify = gerrit_get_latest_comment(change_id)
                        if comment != env_val["comment_verify_key"] or \
                                verify == "1":
                            continue

                        build_arg = [
                            {"key": "gerrit_host",
                                "value": env_val["gerrit_host"]},
                            {"key": "fetch_project", "value": project},
                            {"key": "fetch_ref", "value": patch_ref}]

                        patch_build_num = drone_create_build(
                            project, change_branch, build_arg)

                        ci_url = env_val["drone_ci_url"] + env_val["gerrit_namespace"] + \
                            "/" + project + "/" + str(patch_build_num)

                        patch_build_key = project + str(patch_build_num)
                        pending_patch_builds[patch_build_key] = {
                            "change_num": change_num, "patch_num": patch_num,
                            "ci_url": ci_url,
                        }

                        gerrit_set_verify_label(change_num, patch_num,
                                                "-1", "Start Drone CI Verify: " + ci_url)

                        print("Start CI verify...")
                    else:
                        pass
                else:
                    pass

            except BaseException as err:
                proc.terminate()
                webhooks.stop()
                raise err
