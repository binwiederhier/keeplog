#!/usr/bin/env python3

import hashlib
import json
import logging
import os
import re
import shutil
import sys
import gkeepapi
from datetime import datetime
from os.path import expanduser, exists, join

class Keeplog:
    def __init__(self, logger, config):
        self.logger = logger
        self.config = config
        self.state = State()
        self.keep = gkeepapi.Keep()

    def sync(self):
        self.read_state()
        self.login()
        self.compare()
        self.write_state()

    def read_state(self):
        self.state.load(self.config.state_file)

    def write_state(self):
        self.state.keep = self.keep.dump()
        self.state.write(self.config.state_file)

    def read_local(self):
        self.logger.info("Reading local notes")
        local = {}

        # parse file
        with open(self.config.file, encoding='utf-8') as f:
            for line in f:
                if re.search('^\\d+/\\d+/\\d+ ', line):
                    title = line.strip()
                    local[title] = LocalNote()
                elif line.strip() != "--" and title in local:
                    local[title].content += line

        # fix empty lines between entries
        for title in local.keys():
            local[title].text(re.sub("\n\\s*\n$", "\n", local[title].text()))

        return local

    def read_remote(self):
        self.logger.info("Reading remote notes")

        remote = {}
        label = self.keep.findLabel(self.config.label)

        note: gkeepapi.node.TopLevelNode
        for note in self.keep.find(labels=[label]):
            if re.search('^\\d+/\\d+/\\d+ ', note.title):
                remote[note.title] = RemoteNote(note)

        return remote

    def backup_local(self):
        os.makedirs(self.config.backup_dir, exist_ok=True)
        backup_file = join(self.config.backup_dir, datetime.now().strftime("%y%m%d%H%M%S"))
        shutil.copyfile(self.config.file, backup_file)

    def login(self):
        logged_in = False

        if self.state.token:
            logged_in = self.login_with_token()

        if not logged_in:
            logged_in = self.login_with_password()

        if not logged_in:
            raise Exception("Failed to authenticate")

    def login_with_token(self):
        self.logger.info('Logging in with token')
        logged_in = False

        try:
            self.keep.resume(self.config.username, self.state.token, state=self.state.keep, sync=True)
            self.logger.info('Successfully logged in')
            logged_in = True
        except gkeepapi.exception.LoginException:
            self.logger.warning('Invalid token, falling back to password')

        return logged_in

    def login_with_password(self):
        self.logger.info('Logging in with password')
        logged_in = False

        try:
            self.keep.login(self.config.username, self.config.password, state=self.state.keep, sync=True)
            self.logger.info('Successfully logged in')
            self.state.token = self.keep.getMasterToken()
            logged_in = True
        except gkeepapi.exception.LoginException:
            self.logger.info('Login failed')

        return logged_in

    def write_local(self, local):
        self.logger.info("Writing local notes")
        with open(self.config.file, mode="w", encoding="utf-8") as f:
            for title in local.keys():
                f.write(title + "\n")
                f.write("--\n")
                f.write(local[title]["text"] + "\n")
                if not local[title]["text"].endswith("\n"):
                    f.write("\n")  # ensure empty line between entries

    def compare(self):
        self.logger.info("Comparing remote and local")

        local = self.read_local()
        local_updated = False
        remote = self.read_remote()
        remote_label = self.keep.getLabel(self.config.label)
        checksums = self.state.checksums

        for title in local.keys():
            if title not in remote:
                self.logger.info(f"- Creating remotely: {title}")
                note = self.keep.createNote(title, local[title].text())
                note.labels.add(remote_label)
                checksums[title] = local[title].checksum()
            elif remote[title].text() != local[title].text():
                if title in checksums:
                    local_changed = local[title].checksum() != checksums[title]
                    remote_changed = remote[title].checksum() != checksums[title]
                    if local_changed and not remote_changed:
                        self.logger.info(f"- Updating remotely: {title}")
                        remote[title].text(local[title].text())
                        checksums[title] = local[title].checksum()
                    elif not local_changed and remote_changed:
                        self.logger.info(f"- Updating locally: {title}")
                        local[title].text(remote[title].text())
                        checksums[title] = remote[title].checksum()
                        local_updated = True
                    elif self.config.on_conflict == "prefer-remote":
                        self.logger.info(f"- Updating locally (conflict override): {title}")
                        local[title].text(remote[title].text())
                        checksums[title] = remote[title].checksum()
                        local_updated = True
                    elif self.config.on_conflict == "prefer-local":
                        self.logger.info(f"- Updating remotely (conflict override): {title}")
                        remote[title].text(local[title].text())
                        checksums[title] = local[title].checksum()
                    else:
                        self.logger.info(f"- Conflict, doing nothing: {title}")
                elif self.config.on_conflict == "prefer-remote":
                    self.logger.info(f"- Updating locally (conflict override): {title}")
                    local[title].text(remote[title].text())
                    checksums[title] = remote[title].checksum()
                    local_updated = True
                elif self.config.on_conflict == "prefer-local":
                    self.logger.info(f"- Updating remotely (conflict override): {title}")
                    remote[title].text(local[title].text())
                    checksums[title] = local[title].checksum()
                else:
                    self.logger.info(f"- Conflict, doing nothing: {title}")
            else:
                checksums[title] = local[title].checksum()

        self.keep.sync()

        if local_updated:
            self.backup_local()
            self.write_local(local)
        else:
            self.logger.info("Nothing to update locally")

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


class State:
    def __init__(self):
        self.token = None
        self.keep = None
        self.checksums = {}

    def load(self, file):
        if exists(file):
            with open(file, encoding='utf-8') as f:
                state = json.load(f)
                if "token" in state:
                    self.token = state["token"]
                if "keep" in state:
                    self.keep = state["keep"]
                if "checksums" in state:
                    self.checksums = state["checksums"]
        return self

    def write(self, file):
        with open(file, mode="w", encoding="utf-8") as f:
            data = {
                "token": self.token,
                "keep": self.keep,
                "checksums": self.checksums
            }
            json.dump(data, f)

class Config:
    def __init__(self):
        self.username = None
        self.password = None
        self.file = None
        self.label = "keeplog"
        self.on_conflict = "prefer-local"
        self.state_file = expanduser("~/.keeplog/state")
        self.backup_dir = expanduser("~/.keeplog/backups")

    def load(self, file):
        if not exists(file):
            raise Exception("Config file " + file + " does not exist")

        with open(file, encoding='utf-8') as cfg:
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
                    elif match.group(1) == "state-file":
                        self.state_file = expanduser(match.group(2))
                    elif match.group(1) == "on-conflict":
                        self.on_conflict = match.group(2)
                    elif match.group(1) == "backup-dir":
                        self.backup_dir = match.group(2)

        if not self.username or not self.password or not self.file:
            raise Exception("Invalid config file, need at least 'user=', 'pass=' and 'file='.")

        if self.on_conflict not in ["prefer-local", "prefer-remote", "do-nothing"]:
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
