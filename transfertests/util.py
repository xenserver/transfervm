#!/usr/bin/python

import subprocess

def doexec(args, expectedRC, inputtext=None):
    proc = subprocess.Popen(args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
            close_fds=True)
    (stdout, stderr) = proc.communicate(inputtext)
    stdout = str(stdout)
    stderr = str(stderr)
    rc = proc.returncode
    if type(expectedRC) != type([]):
        expectedRC = [expectedRC]
    if not rc in expectedRC:
        reason = stderr.strip()
        if stdout.strip():
            reason = "%s (stdout: %s)" % (reason, stdout.strip())
        raise Exception("Command %s failed: %s" % (args, reason))
    #print args
    return rc
