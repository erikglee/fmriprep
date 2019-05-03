# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
"""Stripped out routines for Sentry"""
import re
from niworkflows.utils.misc import read_crashfile
import sentry_sdk

CHUNK_SIZE = 16384
# Group common events with pre specified fingerprints
KNOWN_ERRORS = {
    'permission-denied': [
        "PermissionError: [Errno 13] Permission denied"
    ],
    'memory-error': [
        "MemoryError",
        "Cannot allocate memory",
        "Return code: 134",
    ],
    'reconall-already-running': [
        "ERROR: it appears that recon-all is already running"
    ],
    'no-disk-space': [
        "[Errno 28] No space left on device",
        "[Errno 122] Disk quota exceeded"
    ],
    'segfault': [
        "Segmentation Fault",
        "Segfault",
        "Return code: 139",
    ],
    'potential-race-condition': [
        "[Errno 39] Directory not empty",
        "_unfinished.json",
    ],
    'keyboard-interrupt': [
        "KeyboardInterrupt",
    ],
}


def process_crashfile(crashfile):
    """Parse the contents of a crashfile and submit sentry messages"""
    crash_info = read_crashfile(str(crashfile))
    with sentry_sdk.push_scope() as scope:
        scope.level = 'fatal'

        # Extract node name
        node_name = crash_info.pop('node').split('.')[-1]
        scope.set_tag("node_name", node_name)

        # Massage the traceback, extract the gist
        traceback = crash_info.pop('traceback')
        # last line is probably most informative summary
        gist = traceback.splitlines()[-1]
        exception_text_start = 1
        for line in traceback.splitlines()[1:]:
            if not line[0].isspace():
                break
            exception_text_start += 1

        exception_text = '\n'.join(
            traceback.splitlines()[exception_text_start:])

        # Extract inputs, if present
        inputs = crash_info.pop('inputs', None)
        if inputs:
            scope.set_extra('inputs', dict(inputs))

        # Extract any other possible metadata in the crash file
        for k, v in crash_info.items():
            strv = list(_chunks(str(v)))
            if len(strv) == 1:
                scope.set_extra(k, strv[0])
            else:
                for i, chunk in enumerate(strv):
                    scope.set_extra('%s_%02d' % (k, i), chunk)

        fingerprint = ''
        issue_title = '{}: {}'.format(node_name, gist)
        for new_fingerprint, error_snippets in KNOWN_ERRORS.items():
            for error_snippet in error_snippets:
                if error_snippet in traceback:
                    fingerprint = new_fingerprint
                    issue_title = new_fingerprint
                    break
            if fingerprint:
                break

        message = issue_title + '\n\n'
        message += exception_text[-(8192 - len(message)):]
        if fingerprint:
            sentry_sdk.add_breadcrumb(message=fingerprint, level='fatal')
        else:
            # remove file paths
            fingerprint = re.sub(r"(/[^/ ]*)+/?", '', message)
            # remove words containing numbers
            fingerprint = re.sub(r"([a-zA-Z]*[0-9]+[a-zA-Z]*)+", '', fingerprint)
            # adding the return code if it exists
            for line in message.splitlines():
                if line.startswith("Return code"):
                    fingerprint += line
                    break

        scope.fingerprint = [fingerprint]
        sentry_sdk.capture_message(message, 'fatal')


def _chunks(string, length=CHUNK_SIZE):
    """
    Splits a string into smaller chunks
    >>> list(_chunks('some longer string.', length=3))
    ['som', 'e l', 'ong', 'er ', 'str', 'ing', '.']
    """
    return (string[i:i + length]
            for i in range(0, len(string), length))