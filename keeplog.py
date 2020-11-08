#!/usr/bin/env python3

import sys
import gkeepapi
import re
import json
import hashlib
import os
import shutil
import logging
from datetime import datetime
from os.path import expanduser, exists, join

def main():
    # set up logging
    logger = logging.getLogger('keeplog')
    logger.setLevel(logging.INFO)
    ch = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # read config
    config = Config()
    config.load(expanduser("~/.keeplog/config"))

    # parse log
    logger.info("Parsing local log " + config.file)

    local = {}
    with open(config.file, encoding='utf-8') as f:
        for line in f:
            if re.search('^(\d+)/(\d+)/(\d+) ', line):
                title = line.strip()
                local[title] = {"text": ""}
            elif line.strip() != "--" and title in local:
                local[title]["text"] = local[title]["text"] + line

    for title in local.keys():
        new_text = re.sub("\n\s*\n$", "\n", local[title]["text"])  # remove empty line between entries
        local[title]["text"] = new_text
        local[title]["checksum"] = md5(new_text)

    logger.info("Read " + str(len(local)) + " entries")

    # read keep
    keep = gkeepapi.Keep()
    logged_in = False

    token = read_token(config.token_file)
    state = read_state(config.state_file)

    if token:
        logger.info('Authenticating with token')

        try:
            keep.resume(config.username, token, state=state, sync=True)
            logged_in = True
            del token
            logger.info('Successfully logged in and synced state')
        except gkeepapi.exception.LoginException:
            logger.warning('Invalid token, falling back to password')

    if not logged_in:
        logger.info('Authenticating with password')

        try:
            keep.login(config.username, config.password, state=state, sync=True)
            logged_in = True

            token = keep.getMasterToken()
            with open(config.token_file, 'w') as f:
                f.write(token)

            logger.info('Successfully logged in')
        except gkeepapi.exception.LoginException:
            logger.info('Login failed')

    if not logged_in:
        logger.error('Failed to authenticate')
        sys.exit(1)

    # Read notes
    logger.info("Reading Keep notes")

    remote = {}
    label = keep.findLabel('log')

    note: gkeepapi.node.TopLevelNode
    for note in keep.find(labels=[label]):
        if not re.search('^\d+/\d+/\d+ ', note.title):
            logger.warning(f"{note.title} - Skipping, title mismatch")
            continue
        remote[note.title] = {
            "checksum": md5(note.text),
            "note": note
        }

    logger.info("Read " + str(len(remote)) + " notes from Keep")

    # read sync file
    sync = {}
    if exists(config.sync_file):
        with open(config.sync_file, encoding='utf-8') as f:
            data = json.load(f)
            if not "notes" in data:
                raise ValueError(f"Invalid sync file format in file {config.sync_file}")
            notes = data["notes"]
            for title in notes.keys():
                sync[title] = notes[title]

    # synchronizing
    logger.info("Updating remote")
    updated = 0
    local_updated = False

    for title in local.keys():
        if not title in remote:
            logger.info(f"- Creating remotely: {title}")
            note = keep.createNote(title, local[title]["text"])
            note.labels.add(label)
            sync[title] = {"checksum": md5(local[title]["text"])}
            updated += 1
        elif remote[title]["note"].text != local[title]["text"]:
            if title in sync:
                local_changed = local[title]["checksum"] != sync[title]["checksum"]
                remote_changed = remote[title]["checksum"] != sync[title]["checksum"]
                if local_changed and not remote_changed:
                    logger.info(f"- Updating remotely: {title}")
                    remote[title]["note"].text = local[title]["text"]
                    sync[title] = {"checksum": md5(local[title]["text"])}
                    updated += 1
                elif not local_changed and remote_changed:
                    logger.info(f"- Updating locally: {title}")
                    local[title]["text"] = remote[title]["note"].text
                    sync[title] = {"checksum": md5(remote[title]["note"].text)}
                    local_updated = True
                    updated += 1
                elif config.on_conflict == "prefer-remote":
                    logger.info(f"- Updating locally (conflict override): {title}")
                    local[title]["text"] = remote[title]["note"].text
                    sync[title] = {"checksum": md5(remote[title]["note"].text)}
                    local_updated = True
                    updated += 1
                elif config.on_conflict == "prefer-local":
                    logger.info(f"- Updating remotely (conflict override): {title}")
                    remote[title]["note"].text = local[title]["text"]
                    sync[title] = {"checksum": md5(local[title]["text"])}
                    updated += 1
                else:
                    logger.info(f"- Conflict, doing nothing: {title}")
            elif config.on_conflict == "prefer-remote":
                logger.info(f"- Updating locally (conflict override): {title}")
                local[title]["text"] = remote[title]["note"].text
                sync[title] = {"checksum": md5(remote[title]["note"].text)}
                local_updated = True
                updated += 1
            elif config.on_conflict == "prefer-local":
                logger.info(f"- Updating remotely (conflict override): {title}")
                remote[title]["note"].text = local[title]["text"]
                sync[title] = {"checksum": md5(local[title]["text"])}
                updated += 1
            else:
                logger.info(f"- Conflict, doing nothing: {title}")
        else:
            sync[title] = {"checksum": md5(local[title]["text"])}

    keep.sync()
    state = keep.dump()
    with open(config.state_file, 'w') as f:
        json.dump(state, f)
    logger.info("Done")

    if local_updated:
        logger.info("Updating log file")

        os.makedirs(config.backup_dir, exist_ok=True)
        backup_file = join(config.backup_dir, datetime.now().strftime("%y%m%d%H%M%S"))
        shutil.copyfile(config.file, backup_file)

        with open(config.file, mode="w", encoding="utf-8") as f:
            for title in local.keys():
                f.write(title + "\n")
                f.write("--\n")
                f.write(local[title]["text"] + "\n")
                if not local[title]["text"].endswith("\n"):
                    f.write("\n")  # ensure empty line between entries
    else:
        logger.info("Nothing to update locally")

    # write sync file
    logger.info("Writing sync file")
    with open(config.sync_file, mode="w", encoding="utf-8") as f:
        data = {"notes": sync}
        json.dump(data, f)

def md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def read_token(token_file):
    if exists(token_file):
        with open(token_file) as f:
            return f.read().strip()
    return None

def read_state(state_file):
    if exists(state_file):
        with open(state_file) as f:
            return json.load(f)
    return None

class Config:
    def __init__(self):
        self.username = None
        self.password = None
        self.file = None
        self.on_conflict = "prefer-local"
        self.sync_file = expanduser("~/.keeplog/state/sync")
        self.state_file = expanduser("~/.keeplog/state/state")
        self.token_file = expanduser("~/.keeplog/state/token")
        self.backup_dir = expanduser("~/.keeplog/backups")

    def load(self, config_file):
        if not exists(config_file):
            raise Exception("Config file " + config_file + " does not exist")

        with open(config_file, encoding='utf-8') as cfg:
            for line in cfg:
                match = re.search("^([^=]+)=(.+)", line)
                if match:
                    if match.group(1) == "user":
                        self.username = match.group(2)
                    elif match.group(1) == "pass":
                        self.password = match.group(2)
                    elif match.group(1) == "file":
                        self.file = expanduser(match.group(2))
                    elif match.group(1) == "sync-file":
                        self.sync_file = expanduser(match.group(2))
                    elif match.group(1) == "state-file":
                        self.state_file = expanduser(match.group(2))
                    elif match.group(1) == "token-file":
                        self.token_file = expanduser(match.group(2))
                    elif match.group(1) == "on-conflict":
                        self.on_conflict = match.group(2)
                    elif match.group(1) == "backup-dir":
                        self.backup_dir = match.group(2)

        if not self.username or not self.password or not self.file:
            raise Exception("Invalid config file, need at least 'user=', 'pass=' and 'file='.")

        if not self.on_conflict in ["prefer-local", "prefer-remote", "do-nothing"]:
            raise Exception("Invalid config file, on-conflict needs to be 'prefer-local', 'prefer-remote' or 'do-nothing'.")

class Keeplog:
    def __init__(self):
        pass


if __name__ == '__main__':
    main()
