# -*- coding: utf-8 -*-
# command line for running the same command on all workers,
# > mba od_reading
# > mba stirring
import importlib
from subprocess import run
import hashlib
import click

import paramiko
from morbidostat.whoami import am_I_leader

UNITS = ["morbidostat2", "morbidostat3"]


def checksum_config_file(s):
    cksum_command = "cksum ~/morbidostat/morbidostat/config.ini"
    (stdin, stdout, stderr) = s.exec_command(cksum_command)
    checksum_worker = stdout.readlines()[0].split(" ")[0]
    checksum_leader = run(cksum_command, shell=True, capture_output=True, universal_newlines=True).strip().split(" ")[0]
    assert checksum_worker == checksum_leader, "checksum on config.ini failed"


def checksum_git(s):
    cksum_command = "cd ~/morbidostat/ && git rev-parse HEAD"
    (stdin, stdout, stderr) = s.exec_command(cksum_command)
    checksum_worker = stdout.readlines()[0]
    checksum_leader = run(cksum_command, shell=True, capture_output=True, universal_newlines=True).strip()
    assert checksum_worker == checksum_leader, "checksum on git failed"


def setup_workers(extra_args):
    cd = "cd ~/morbidostat"
    gitp = "git pull origin master"
    setup = "sudo python3 setup.py install"
    command = " && ".join([cd, gitp, setup])

    confirm = input(f"Confirm running `{command}` on units? Y/n").strip()
    if confirm != "Y":
        return

    s = paramiko.SSHClient()
    s.load_system_host_keys()

    for unit in UNITS:
        s.connect(unit, username="pi")
        s.exec_command(command)
        checksum_git(s)
        checksum_config_file(s)
        s.close()


def run_mb_command(job, extra_args):
    extra_args = list(extra_args)

    command = ["mb", job] + extra_args + ["-b"]
    command = " ".join(command)

    confirm = input(f"Confirm running `{command}` on units? Y/n").strip()
    if confirm != "Y":
        return

    s = paramiko.SSHClient()
    s.load_system_host_keys()

    for unit in UNITS:
        s.connect(unit, username="pi")

        try:
            checksum_config_file(s)
            checksum_git(s)
        except AssertionError as e:
            print(e)
            continue

        (stdin, stdout, stderr) = s.exec_command(command)
        for line in stdout.readlines():
            print(unit + ":" + line)
        s.close()

    return


@click.command(context_settings=dict(ignore_unknown_options=True))
@click.argument("job")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
def cli(job, extra_args):
    if not am_I_leader():
        print("workers are not suppose to run morbidostat-all commands.")
        return

    if job == "setup":
        return setup_workers(extra_args)
    else:
        return run_mb_command(job, extra_args)


if __name__ == "__main__":
    cli()