#!/usr/bin/env python3

import hashlib
import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime
from os.path import expanduser, exists, join
from pathlib import Path

import gkeepapi

class Keeplog:
    def __init__(self, logger, config):
        self.logger = logger
        self.config = config
        self.keep = gkeepapi.Keep()

    def sync(self):
        self.login()
        self.write_token()

        local = self.read_local()
        remote = self.read_remote()
        sync = self.read_sync()

        # synchronizing
        self.logger.info("Comparing remote and local")
        local_updated = False
        label = self.keep.getLabel(self.config.label)

        for title in local.keys():
            if not title in remote:
                self.logger.info(f"- Creating remotely: {title}")
                note = self.keep.createNote(title, local[title].text())
                note.labels.add(label)
                sync[title] = {"checksum": local[title].checksum()}
            elif remote[title].text() != local[title].text():
                if title in sync:
                    local_changed = local[title].checksum() != sync[title]["checksum"]
                    remote_changed = remote[title].checksum() != sync[title]["checksum"]
                    if local_changed and not remote_changed:
                        self.logger.info(f"- Updating remotely: {title}")
                        remote[title].text(local[title].text())
                        sync[title] = {"checksum": local[title].checksum()}
                    elif not local_changed and remote_changed:
                        self.logger.info(f"- Updating locally: {title}")
                        local[title].text(remote[title].text())
                        sync[title] = {"checksum": remote[title].checksum()}
                        local_updated = True
                    elif self.config.on_conflict == "prefer-remote":
                        self.logger.info(f"- Updating locally (conflict override): {title}")
                        local[title].text(remote[title].text())
                        sync[title] = {"checksum": remote[title].checksum()}
                        local_updated = True
                    elif self.config.on_conflict == "prefer-local":
                        self.logger.info(f"- Updating remotely (conflict override): {title}")
                        remote[title].text(local[title].text())
                        sync[title] = {"checksum": local[title].checksum()}
                    else:
                        self.logger.info(f"- Conflict, doing nothing: {title}")
                elif self.config.on_conflict == "prefer-remote":
                    self.logger.info(f"- Updating locally (conflict override): {title}")
                    local[title].text(remote[title].text())
                    sync[title] = {"checksum": remote[title].checksum()}
                    local_updated = True
                elif self.config.on_conflict == "prefer-local":
                    self.logger.info(f"- Updating remotely (conflict override): {title}")
                    remote[title].text(local[title].text())
                    sync[title] = {"checksum": local[title].checksum()}
                else:
                    self.logger.info(f"- Conflict, doing nothing: {title}")
            else:
                sync[title] = {"checksum": local[title].checksum()}

        self.keep.sync()
        self.write_state()

        if local_updated:
            self.backup_local()
            self.write_local(local)
        else:
            self.logger.info("Nothing to update locally")

        self.write_sync(sync)

    def read_local(self):
        self.logger.info("Reading local notes")
        local = {}

        # parse file
        with open(self.config.file, encoding='utf-8') as f:
            for line in f:
                if re.search('^\d+/\d+/\d+ ', line):
                    title = line.strip()
                    local[title] = LocalNote()
                elif line.strip() != "--" and title in local:
                    local[title].content += line

        # fix empty lines between entries
        for title in local.keys():
            local[title].text(re.sub("\n\s*\n$", "\n", local[title].text()))

        return local

    def read_remote(self):
        self.logger.info("Reading remote notes")

        remote = {}
        label = self.keep.findLabel(self.config.label)

        note: gkeepapi.node.TopLevelNode
        for note in self.keep.find(labels=[label]):
            if re.search('^\d+/\d+/\d+ ', note.title):
                remote[note.title] = RemoteNote(note)

        return remote

    def read_token(self):
        token = None
        if exists(self.config.token_file):
            with open(self.config.token_file) as f:
                token = f.read().strip()
        return token

    def read_state(self):
        state = None
        if exists(self.config.state_file):
            with open(self.config.state_file) as f:
                state = json.load(f)
        return state

    def read_sync(self):
        sync = {}
        if exists(self.config.sync_file):
            with open(self.config.sync_file, encoding='utf-8') as f:
                data = json.load(f)
                if not "notes" in data:
                    raise ValueError(f"Invalid sync file format in file {self.config.sync_file}")
                notes = data["notes"]
                for title in notes.keys():
                    sync[title] = notes[title]
        return sync

    def backup_local(self):
        os.makedirs(self.config.backup_dir, exist_ok=True)
        backup_file = join(self.config.backup_dir, datetime.now().strftime("%y%m%d%H%M%S"))
        shutil.copyfile(self.config.file, backup_file)

    def login(self):
        logged_in = False

        token = self.read_token()
        state = self.read_state()

        if token:
            logged_in = self.login_with_token(token, state)

        if not logged_in:
            logged_in = self.login_with_password(state)

        if not logged_in:
            raise Exception("Failed to authenticate")

    def login_with_token(self, token, state):
        self.logger.info('Logging in with token')
        logged_in = False

        try:
            self.keep.resume(self.config.username, token, state=state, sync=True)
            self.logger.info('Successfully logged in')
            logged_in = True
        except gkeepapi.exception.LoginException:
            self.logger.warning('Invalid token, falling back to password')

        return logged_in

    def login_with_password(self, state):
        self.logger.info('Logging in with password')
        logged_in = False

        try:
            self.keep.login(self.config.username, self.config.password, state=state, sync=True)
            self.logger.info('Successfully logged in')
            logged_in = True
        except gkeepapi.exception.LoginException:
            self.logger.info('Login failed')

        return logged_in

    def write_token(self):
        self.make_parent(self.config.token_file)
        token = self.keep.getMasterToken()
        with open(self.config.token_file, 'w') as f:
            f.write(token)

    def write_state(self):
        self.make_parent(self.config.state_file)
        state = self.keep.dump()
        with open(self.config.state_file, 'w') as f:
            json.dump(state, f)

    def write_sync(self, sync):
        self.make_parent(self.config.sync_file)
        with open(self.config.sync_file, mode="w", encoding="utf-8") as f:
            data = {"notes": sync}
            json.dump(data, f)

    def write_local(self, local):
        self.logger.info("Writing local notes")
        with open(self.config.file, mode="w", encoding="utf-8") as f:
            for title in local.keys():
                f.write(title + "\n")
                f.write("--\n")
                f.write(local[title]["text"] + "\n")
                if not local[title]["text"].endswith("\n"):
                    f.write("\n")  # ensure empty line between entries

    def make_parent(self, file):
        Path(file).parent.mkdir(mode=0o755, parents=True, exist_ok=True)

class Note:
    def text(self, v=None):
        raise Exception("Not implemented")

    def checksum(self):
        return hashlib.md5(self.text().encode("utf-8")).hexdigest()

class RemoteNote(Note):
    def __init__(self, note):
        self.note = note

    def text(self, v=None):
        if v is not None:
            self.note.text = v
        return self.note.text

class LocalNote(Note):
    def __init__(self, content=""):
        self.content = content

    def text(self, v=None):
        if v is not None:
            self.content = v
        return self.content

class Config:
    def __init__(self):
        self.username = None
        self.password = None
        self.file = None
        self.label = "log"
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
                    elif match.group(1) == "label":
                        self.label = match.group(2)
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
            raise Exception(
                "Invalid config file, on-conflict needs to be 'prefer-local', 'prefer-remote' or 'do-nothing'.")

        return self


def setup_logger():
    logger = logging.getLogger('keeplog')
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logger.addHandler(handler)
    return logger


def load_config():
    return Config().load(expanduser("~/.keeplog/config"))


if __name__ == '__main__':
    logger = setup_logger()
    config = load_config()

    keeplog = Keeplog(logger, config)
    keeplog.sync()