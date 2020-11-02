#!/usr/bin/env python3

import gkeepapi
import re
import json
import hashlib
from os.path import expanduser, exists

def main():
    # read config
    config = expanduser("~/.config/keeplog.conf")

    username = None
    password = None
    file = None
    sync_file = None
    conflict_strategy = None

    with open(config, encoding='utf-8') as cfg:
        for line in cfg:
            match = re.search("^([^=]+)=(.+)", line)
            if match:
                if match.group(1) == "user":
                    username = match.group(2)
                elif match.group(1) == "pass":
                    password = match.group(2)
                elif match.group(1) == "file":
                    file = expanduser(match.group(2))
                elif match.group(1) == "sync-file":
                    sync_file = expanduser(match.group(2))
                elif match.group(1) == "on-conflict":
                    conflict_strategy = match.group(2)

    if not username or not password or not file:
        raise Exception("Invalid config file, need at least 'user=', 'pass=' and 'file='.")

    if not conflict_strategy:
        conflict_strategy = "prefer-local"

    if not sync_file:
        sync_file = file + ".sync"

    # parse log
    print("Parsing log ... ", end="", flush=True)

    local = {}
    with open(file, encoding='utf-8') as f:
        for line in f:
            if re.search('^(\d+)/(\d+)/(\d+) ', line):
                title = line.strip()
                local[title] = ""
            elif line.strip() != "--" and title in local:
                local[title] = local[title] + line

    print(str(len(local)) + " entries.")

    # read keep
    print("Reading Keep notes ... ", end="", flush=True)

    keep = gkeepapi.Keep()
    keep.login(username, password)

    remote = {}
    label = keep.findLabel('log')

    note: gkeepapi.node.TopLevelNode
    for note in keep.find(labels=[label]):
        if not re.search('^\d+/\d+/\d+ ', note.title):
            print(f"{note.title} - Skipping, title mismatch")
            continue
        remote[note.title] = note

    print(str(len(remote)) + " notes.")

    # read sync file
    sync = {}
    if exists(sync_file):
        with open(sync_file, encoding='utf-8') as f:
            data = json.load(f)
            if not "notes" in data:
                raise ValueError(f"Invalid sync file format in file {sync_file}")
            notes = data["notes"]
            for title in notes.keys():
                sync[title] = notes[title]

    # update keep
    print("Updating Keep ... ", end="", flush=True)
    updated = 0

    for title in local.keys():
        text = local[title]
        if not title in remote:
            if updated == 0: print()
            print(f"- Creating: {title}")
            note = keep.createNote(title, text)
            note.labels.add(label)
            updated += 1
        elif remote[title].text != text:
            if updated == 0: print()
            print(f"- Updating: {title}")
            remote[title].text = text
            updated += 1
        sync[title] = {
            "checksum": hashlib.md5(text.encode("utf-8")).hexdigest()
        }

    keep.sync()
    print(str(updated) + " updated.")

    # write sync file
    print("Writing sync file ... ", end="", flush=True)
    with open(sync_file, mode="w", encoding="utf-8") as f:
        data = { "notes" : sync }
        json.dump(data, f)
    print("Done.")

if __name__ == '__main__':
    main()
