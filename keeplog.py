#!/usr/bin/env python3

import hashlib
import json
import logging
import os
import re
import shutil
import sys
import gkeepapi
import argparse
import time
from inotify_simple import INotify, flags
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, LoggingEventHandler
from datetime import datetime
from os.path import expanduser, exists, join


class Keeplog:
    def __init__(self, logger, config):
        self.logger = logger
        self.config = config
        self.state = State()
        self.keep = gkeepapi.Keep()

    def sync(self):
        self._read_state()
        self._login()
        self._compare()
        self._write_state()

    def _read_state(self):
        self.state.load(self.config.state_file)

    def _login(self):
        logged_in = False

        if self.state.token:
            logged_in = self._login_with_token()

        if not logged_in:
            logged_in = self._login_with_password()

        if not logged_in:
            raise Exception("Failed to authenticate")

    def _login_with_token(self):
        self.logger.info('Logging in with token')
        logged_in = False

        try:
            self.keep.resume(self.config.username, self.state.token, state=self.state.internal, sync=True)
            self.logger.info('Successfully logged in')
            logged_in = True
        except gkeepapi.exception.LoginException:
            self.logger.warning('Invalid token, falling back to password')

        return logged_in

    def _login_with_password(self):
        self.logger.info('Logging in with password')
        logged_in = False

        try:
            self.keep.login(self.config.username, self.config.password, state=self.state.internal, sync=True)
            self.logger.info('Successfully logged in')
            self.state.token = self.keep.getMasterToken()
            logged_in = True
        except gkeepapi.exception.LoginException:
            self.logger.info('Login failed')

        return logged_in

    def _compare(self):
        self.logger.info("Comparing remote and local")

        local = self._read_local()
        local_updated = False
        remote = self._read_remote()
        remote_label = self.keep.getLabel(self.config.label)
        checksums = self.state.checksums

        # Iterate through local entries and compare with remote ones
        for id in local.keys():
            if id not in remote:
                self.logger.info(f"- Creating remotely: {id}")
                note = self.keep.createNote(id, local[id].text())
                note.labels.add(remote_label)
                remote[id] = RemoteNote(note)
                checksums[id] = local[id].checksum()
            elif remote[id].text() != local[id].text():
                if id in checksums:
                    local_changed = local[id].checksum() != checksums[id]
                    remote_changed = remote[id].checksum() != checksums[id]
                    if local_changed and not remote_changed:
                        self.logger.info(f"- Updating remotely: {id}")
                        remote[id].text(local[id].text())
                        checksums[id] = local[id].checksum()
                    elif not local_changed and remote_changed:
                        self.logger.info(f"- Updating locally: {id}")
                        local[id].text(remote[id].text())
                        checksums[id] = remote[id].checksum()
                        local_updated = True
                    elif self.config.on_conflict == "prefer-remote":
                        self.logger.info(f"- Updating locally (conflict override): {id}")
                        local[id].text(remote[id].text())
                        checksums[id] = remote[id].checksum()
                        local_updated = True
                    elif self.config.on_conflict == "prefer-local":
                        self.logger.info(f"- Updating remotely (conflict override): {id}")
                        remote[id].text(local[id].text())
                        checksums[id] = local[id].checksum()
                    else:
                        self.logger.info(f"- Conflict, doing nothing: {id}")
                elif self.config.on_conflict == "prefer-remote":
                    self.logger.info(f"- Updating locally (conflict override): {id}")
                    local[id].text(remote[id].text())
                    checksums[id] = remote[id].checksum()
                    local_updated = True
                elif self.config.on_conflict == "prefer-local":
                    self.logger.info(f"- Updating remotely (conflict override): {id}")
                    remote[id].text(local[id].text())
                    checksums[id] = local[id].checksum()
                else:
                    self.logger.info(f"- Conflict, doing nothing: {id}")
            else:
                checksums[id] = local[id].checksum()

        # Iterate through remote entries (to discover net new ones)
        for id in remote.keys():
            if not id in local:
                self.logger.info(f"- Creating locally: {id}")
                local[id] = LocalNote(remote[id].text())
                checksums[id] = remote[id].checksum()
                local_updated = True

        # Always sync remote (if there are no changes, this will do nothing)
        self.keep.sync()

        # Sync local file only if there are changes
        if local_updated:
            self._backup_local()
            self._write_local(local)
        else:
            self.logger.info("Nothing to update locally")

    def _read_local(self):
        self.logger.info("Reading local notes")
        local = {}

        # Parse file
        # TODO Parse file using "--" as entry separator instead of date format
        with open(self.config.file, encoding='utf-8') as f:
            for line in f:
                if re.search('^\\d+/\\d+/\\d+ ', line):
                    title = line.strip()
                    local[title] = LocalNote()
                elif line.strip() != "--" and title in local:
                    local[title].content += line

        # Fix empty lines between entries
        for title in local.keys():
            local[title].text(re.sub("\n\\s*\n$", "\n", local[title].text()))

        return local

    def _read_remote(self):
        self.logger.info("Reading remote notes")

        remote = {}
        label = self.keep.findLabel(self.config.label)

        note: gkeepapi.node.TopLevelNode
        for note in self.keep.find(labels=[label]):
            if re.search('^\\d+/\\d+/\\d+ ', note.title):
                remote[note.title] = RemoteNote(note)

        return remote

    def _backup_local(self):
        os.makedirs(self.config.backup_dir, exist_ok=True)
        backup_file = join(self.config.backup_dir, datetime.now().strftime("%y%m%d%H%M%S"))
        shutil.copyfile(self.config.file, backup_file)

    def _write_local(self, local):
        self.logger.info("Writing local notes")
        with open(self.config.file, mode="w", encoding="utf-8") as f:
            for title in local.keys():
                f.write(title + "\n")
                f.write("--\n")
                f.write(local[title].text() + "\n")
                if not local[title].text().endswith("\n"):
                    f.write("\n") # Ensure empty line between entries

    def _write_state(self):
        self.state.internal = self.keep.dump()
        self.state.write(self.config.state_file)


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
        self.internal = None
        self.checksums = {}

    def load(self, file):
        if exists(file):
            with open(file, encoding='utf-8') as f:
                state = json.load(f)
                if "token" in state:
                    self.token = state["token"]
                if "internal" in state:
                    self.internal = state["internal"]
                if "checksums" in state:
                    self.checksums = state["checksums"]
        return self

    def write(self, file):
        with open(file, mode="w", encoding="utf-8") as f:
            data = {
                "token": self.token,
                "internal": self.internal,
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


def load_config(file):
    return Config().load(expanduser(file))


def sync(args):
    logger = setup_logger()
    config = load_config(args.config)
    keeplog = Keeplog(logger, config)
    keeplog.sync()


def watch(args):
    logger = setup_logger()
    config = load_config(args.config)
    keeplog = Keeplog(logger, config)

    logger.info("Starting file watch for local log file")

    interval = args.interval * 1000
    delay = args.delay

    inotify = INotify()
    watch_flags = flags.MODIFY | flags.DELETE_SELF
    inotify.add_watch(config.file, watch_flags)

    while True:
        try:
            modified = False
            for event in inotify.read(timeout=interval):
                for flag in flags.from_mask(event.mask):
                    if flag == flags.MODIFY:
                        logger.info("File modified, triggering sync")
                        modified = True
                    elif flag == flags.DELETE_SELF:
                        logger.info("File deleted/replaced, triggering sync")
                        modified = True
                        inotify.add_watch(config.file, watch_flags)
            if not modified:
                logger.info("Local file unmodified, triggering scheduled sync")
            time.sleep(delay)
            keeplog.sync()
        except KeyboardInterrupt:
            logger.info("Interrupt received. Exiting.")
            break
        except:
            logger.warning("Unexpected error:", sys.exc_info()[0])
            logger.warning("Sleeping 10 seconds before trying again. Events may be missed.")
            time.sleep(10)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog='keeplog',
                                     description="Two-way sync tool between a local file and Google Keep")
    subparsers = parser.add_subparsers()

    parser.add_argument("-c", "--config", default="~/.keeplog/config", help="Alternate config file")

    parser_sync = subparsers.add_parser("sync", help="Synchronize local file with Google Keep")
    parser_sync.set_defaults(func=sync)

    parser_watch = subparsers.add_parser("watch", help="Watch local file for changes and sync when changed")
    parser_watch.add_argument("-i", "--interval", type=int, default=60,
                              help="Interval in seconds to sync if no local changes are detected")
    parser_watch.add_argument("-d", "--delay", type=float, default=2,
                              help="Delay in seconds before triggering a sync when local changes are detected")
    parser_watch.set_defaults(func=watch)

    args = parser.parse_args()
    if "func" not in args:
        parser.print_help()
        sys.exit(0)

    args.func(args)
