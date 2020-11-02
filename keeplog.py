#!/usr/bin/env python3

import gkeepapi
import re
from datetime import datetime
from os.path import expanduser, getmtime

def main():
    # read config
    config = expanduser("~/.config/keeplog.conf")
    try:
        with open(config) as cfg:
            for line in cfg:
                match = re.search("^([^=]+)=(.+)", line)
                if match:
                    if match.group(1) == "user":
                        username = match.group(2)
                    elif match.group(1) == "pass":
                        password = match.group(2)
                    elif match.group(1) == "file":
                        file = match.group(2)
    except:
        print("Cannot read config file " + config)

    if not username or not password or not file:
        print("Invalid config file, need at least 'user=', 'pass=' and 'log='.")

    # parse log
    print("Parsing log ... ", end="", flush=True)

    log = {}
    log_modified = datetime.utcfromtimestamp(getmtime(expanduser(file)))

    with open(expanduser(file)) as f:
        for line in f:
            if re.search('^(\d+)/(\d+)/(\d+) ', line):
                title = line.strip()
                log[title] = ""
            elif line.strip() != "--" and title in log:
                log[title] = log[title] + line

    print(str(len(log)) + " entries.")

    # read keep (using aap password, see https://myaccount.google.com/apppasswords)
    print("Reading Keep notes ... ", end="", flush=True)

    keep = gkeepapi.Keep()
    keep.login(username, password)

    notes = {}
    notes_modified = None # Keep timestamps are UTC!
    label = keep.findLabel('log')

    note: gkeepapi.node.TopLevelNode
    for note in keep.find(labels=[label]):
        if not re.search('^\d+/\d+/\d+ ', note.title):
            print(f"{note.title} - Skipping, title mismatch")
            continue
        notes[note.title] = note
        if notes_modified is None or note.timestamps.edited > notes_modified:
            notes_modified = note.timestamps.edited

    print(str(len(notes)) + " notes.")

    #print("log modified = " + log_modified.ctime())
    #print("notes modified = " + notes_modified.ctime())

    # update keep
    print("Updating Keep ... ", end="", flush=True)
    updated = 0

    for title in log.keys():
        text = log[title]
        if not title in notes:
            if updated == 0: print()
            print(f"- Creating: {title}")
            note = keep.createNote(title, text)
            note.labels.add(label)
            updated += 1
        elif notes[title].text != text:
            if updated == 0: print()
            print(f"- Updating: {title}")
            notes[title].text = text
            updated += 1

    keep.sync()
    print(str(updated) + " updated.")

if __name__ == '__main__':
    main()
