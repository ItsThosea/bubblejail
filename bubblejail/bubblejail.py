from subprocess import Popen, PIPE, STDOUT
from typing import List, IO, Optional, Iterator
from os import environ
from tempfile import TemporaryFile
from .bwrap_config import (
    DEFAULT_CONFIG, BwrapArgs, Bind)
from .profiles import applications
from pathlib import Path
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from json import load as json_load
from .exceptions import BubblejailException


@dataclass
class InstanceConfig:
    profile_name: str
    virt_home: Optional[str] = None


def get_config_directory() -> Path:
    # Check if XDG_CONFIG_HOME is set
    try:
        config_path = Path(environ['XDG_CONFIG_HOME'] + "/bubblejail")
    except KeyError:
        # Default to ~/.config/bubblejail
        config_path = Path(Path.home(), ".config/bubblejail")

    # Create directory if neccesary
    if not config_path.exists():
        config_path.mkdir(mode=0o700)

    return config_path


def get_data_directory() -> Path:
    # Check if XDG_DATA_HOME is set
    try:
        data_path = Path(environ['XDG_DATA_HOME'] + "/bubblejail")
    except KeyError:
        # Default to ~/.local/share/bubblejail
        data_path = Path(Path.home(), ".local/share/bubblejail")

    # Create directory if neccesary
    if not data_path.is_dir():
        data_path.mkdir(mode=0o700)

    return data_path


def copy_data_to_temp_file(data: bytes) -> IO[bytes]:
    temp_file = TemporaryFile()
    temp_file.write(data)
    temp_file.seek(0)
    return temp_file


def run_bwrap(args_to_target: List[str],
              bwrap_config: BwrapArgs = DEFAULT_CONFIG) -> 'Popen[bytes]':
    bwrap_args: List[str] = ['bwrap']

    for bind_entity in bwrap_config.binds:
        bwrap_args.extend(bind_entity.to_args())

    for ro_entity in bwrap_config.read_only_binds:
        bwrap_args.extend(ro_entity.to_args())

    for dir_entity in bwrap_config.dir_create:
        bwrap_args.extend(dir_entity.to_args())

    for symlink in bwrap_config.symlinks:
        bwrap_args.extend(symlink.to_args())

    # Proc
    bwrap_args.extend(('--proc', '/proc'))
    # Devtmpfs
    bwrap_args.extend(('--dev', '/dev'))
    # Unshare all
    bwrap_args.append('--unshare-all')
    # Die with parent
    bwrap_args.append('--die-with-parent')

    if bwrap_config.share_network:
        bwrap_args.append('--share-net')

    # Copy files
    # Prevent our temporary file from being garbage collected
    temp_files: List[IO[bytes]] = []
    file_descriptors_to_pass: List[int] = []
    for f in bwrap_config.files:
        temp_f = copy_data_to_temp_file(f.content)
        temp_files.append(temp_f)
        temp_file_descriptor = temp_f.fileno()
        file_descriptors_to_pass.append(temp_file_descriptor)
        bwrap_args.extend(('--file', str(temp_file_descriptor), f.dest))

    # Unset all variables
    for e in environ:
        if e not in bwrap_config.env_no_unset:
            bwrap_args.extend(('--unsetenv', e))

    # Set enviromental variables
    for env_var in bwrap_config.enviromental_variables:
        bwrap_args.extend(env_var.to_args())

    # Change directory
    bwrap_args.extend(('--chdir', '/home/user'))
    bwrap_args.extend(args_to_target)
    p = Popen(bwrap_args, pass_fds=file_descriptors_to_pass,
              stdout=PIPE, stderr=STDOUT)
    print("Bubblewrap started")
    try:
        while True:
            print(p.communicate())
    except ValueError:
        print("Bubblewrap terminated")

    return p


def get_home_bind(instance_name: str) -> Bind:
    data_dir = get_data_directory()
    home_path = data_dir / instance_name
    if not home_path.exists():
        home_path.mkdir(mode=0o700)

    return Bind(str(home_path), '/home/user')


def load_instance(instance_name: str) -> InstanceConfig:
    config_dir = get_config_directory()
    instance_config_file = config_dir / (instance_name+'.json')
    if not instance_config_file.is_file():
        raise BubblejailException("Failed to find instance config file")

    with instance_config_file.open() as icf:
        instance_config = InstanceConfig(**json_load(icf))

    return instance_config


class BubblejailInstance:
    def __init__(self, name: str):
        self.name = name
        self.instance_directory = get_data_directory() / self.name
        if not (
            (self.instance_directory.exists())
                and (self.instance_directory.is_dir())):
            raise BubblejailException("Instance directory does not exists")

    def _read_config(self) -> str:

        with (self.instance_directory / "config.json").open() as f:
            instance_config = json_load(f)

        profile_name: str = instance_config['profile']
        return profile_name

    def run(self) -> None:
        app_profile = applications[self._read_config()]
        run_bwrap([app_profile.executable_name],
                  app_profile.generate_bw_args(
                      self.instance_directory / 'home'))


def iter_instance_names() -> Iterator[str]:
    data_dir = get_data_directory()
    for x in data_dir.iterdir():
        if x.is_dir():
            yield str(x.stem)


def run_bjail(args: Namespace) -> None:
    instance_name = args.instance_name
    BubblejailInstance(instance_name).run()


def bjail_list(args: Namespace) -> None:
    ...


def bjail_create(args: Namespace) -> None:
    ...


def main() -> None:
    parser = ArgumentParser()
    subparcers = parser.add_subparsers()
    # run subcommand
    parser_run = subparcers.add_parser('run')
    parser_run.add_argument('instance_name')
    parser_run.set_defaults(func=run_bjail)
    # create subcommand
    parser_create = subparcers.add_parser('create')
    parser_create.set_defaults(func=bjail_create)
    # list subcommand
    parser_list = subparcers.add_parser('list')
    parser_list.set_defaults(func=bjail_list)

    args = parser.parse_args()
    args.func(args)
