#!/usr/bin/env python3
import argparse
import json
import logging
import os.path
import re
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from ruamel.yaml import YAML
from ruamel.yaml.compat import StringIO
from typing import Any, Callable, List, Optional, TextIO, Union
from urllib import request

FLAGS = re.VERBOSE | re.MULTILINE | re.DOTALL
WHITESPACE = re.compile(r'[ \t\n\r]*', FLAGS)
WHITESPACE_STR = ' \t\n\r'


Package = Union['StoneYAML', 'ManifestJSONC']


def in_ci() -> bool:
    """Returns true if running in GitHub Actions or GitLab CI."""
    return os.environ.get('CI') == 'true'


class JSONWithCommentsDecoder(json.JSONDecoder):
    def __init__(self, **kw):
        super().__init__(**kw)

    def decode(self, s: str, _w=WHITESPACE.match) -> Any:
        s = '\n'.join(l for l in s.split('\n') if not l.lstrip(' ').startswith('/**'))
        return super().decode(s)

class ManifestJSONC:
    """Represents a Manifest_$ARCH.jsonc file produced by boulder"""

    def __init__(self, stream: Any):
        self._data = dict(json.load(stream, cls=JSONWithCommentsDecoder))

    @property
    def name(self) -> str:
        return str(self._data['source-name'])

    @property
    def release(self) -> int:
        return int(self._data["source-release"])

    @property
    def version(self) -> int:
        return int(self._data["source-version"])

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

class StoneYAML:
    """Represents a Stone YAML file."""

    def __init__(self, stream: Any):
        yaml = YAML(typ='safe', pure=True)
        yaml.default_flow_style = False
        self._data = dict(yaml.load(stream))

    @property
    def name(self) -> str:
        return str(self._data['name'])

    @property
    def version(self) -> str:
        return str(self._data['version'])

    @property
    def release(self) -> int:
        return int(self._data['release'])

    @property
    def homepage(self) -> Optional[str]:
        return self._data.get('homepage')

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

class Git:
    def __init__(self, path: str):
        self.path = path
        self.root = self._run(path, ['rev-parse', '--show-toplevel'])

    @staticmethod
    def _run(path: str, args: List[str]) -> str:
        res = subprocess.run(['git', '-C', path] + args, capture_output=True, text=True)
        if res.returncode != 0:
            raise Exception("git error: " + res.stderr)

        return res.stdout.strip()

    def run(self, *args: str) -> str:
        return self._run(self.root, list(args))

    def run_lines(self, *args: str) -> List[str]:
        return self.run(*args).splitlines()

    def changed_files(self, base: str, head: str) -> List[str]:
        return self.run_lines('diff', '--name-only', '--diff-filter=AM', base, head)

    def commit_message(self, ref: str) -> str:
        return self.run('log', '-1', '--format=%B', ref)

    def commit_refs(self, base: str, head: str) -> List[str]:
        return self.run_lines('log', '--no-merges', '--pretty=%H', base + '..' + head)

    def fetch(self, remote: List[str]) -> None:
        self.run('fetch', *remote)

    def file_from_commit(self, ref: str, file: str) -> str:
        return self.run('show', f'{ref}:{file}')

    def files_in_commit(self, ref: str) -> List[str]:
        return self.changed_files(ref + '~', ref)

    def merge_base(self, head: str, base: str) -> str:
        return self.run('merge-base', head, base)

    def modified_files(self) -> List[str]:
        return self.run_lines('ls-files', '--others', '--exclude-standard', self.root)

    def relpaths(self, files: List[str]) -> List[str]:
        return [os.path.relpath(os.path.realpath(f), self.root) for f in files]

    def untracked_files(self) -> List[str]:
        return self.run_lines('diff', '--name-only', '--diff-filter=AM')


class LogFormatter(logging.Formatter):
    fmt = '\033[0m \033[94m%(pathname)s:%(lineno)d:\033[0m %(message)s'
    formatters = {
        logging.DEBUG: logging.Formatter('\033[1;30mDBG' + fmt),
        logging.INFO: logging.Formatter('\033[34mINF' + fmt),
        logging.WARNING: logging.Formatter('\033[33mWRN' + fmt),
        logging.ERROR: logging.Formatter('\033[31mERR' + fmt),
        logging.CRITICAL: logging.Formatter('\033[31mCRI' + fmt),
    }

    def format(self, record: logging.LogRecord) -> str:
        return self.formatters[record.levelno].format(record)

    @staticmethod
    def handler() -> logging.Handler:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(LogFormatter())

        return handler


class Level(str, Enum):
    __str__ = Enum.__str__
    DEBUG = 'debug'
    NOTICE = 'notice'
    ERROR = 'error'
    WARNING = 'warning'

    @property
    def log_level(self) -> int:
        match self:
            case Level.DEBUG:
                return logging.DEBUG
            case Level.NOTICE:
                return logging.INFO
            case Level.WARNING:
                return logging.WARNING
            case Level.ERROR:
                return logging.ERROR
            case _:
                return 0


@dataclass
class Result:
    level: Level
    message: str
    title: Optional[str] = None
    file: Optional[str] = None
    col: Optional[int] = None
    endColumn: Optional[int] = None
    line: Optional[int] = None
    endLine: Optional[int] = None

    def __str__(self) -> str:
        return f'::{self.level.value}{self._meta}::{self._message}'

    def log(self) -> None:
        if in_ci():
            print(str(self))
            return

        logging.getLogger(__name__).handle(self._record)

    @property
    def _message(self) -> str:
        return self.message.replace('%', '%25').replace('\n', '%0A')

    @property
    def _meta(self) -> str:
        attrs = ['title', 'file', 'col', 'endColumn', 'line', 'endLine']
        meta = [self._property(key) for key in attrs
                if self._property(key) != '']
        if len(meta) == 0:
            return ''

        return ' ' + ",".join(meta)

    def _property(self, key: str) -> str:
        value = getattr(self, key)
        if value is None:
            return ''

        return f'{key}={value}'

    @property
    def _record(self) -> logging.LogRecord:
        return logging.LogRecord('',
                                 self.level.log_level,
                                 self.file or '',
                                 self.line or 1,
                                 self.message,
                                 None, None)

class PullRequestCheck:
    _package_files = ['stone.yaml']

    def __init__(self, git: Git, files: List[str], commits: List[str], base: Optional[str]):
        self.git = git
        self.files = files
        self.commits = commits
        self.base = base

    def run(self) -> List[Result]:
        raise NotImplementedError

    @property
    def package_files(self) -> List[str]:
        return self.filter_files(*self._package_files)

    def filter_files(self, *allowed: str) -> List[str]:
        return [f for f in self.files
                if os.path.basename(f) in allowed]

    def _path(self, path: str) -> str:
        return os.path.join(self.git.root, path)

    def _open(self, path: str) -> TextIO:
        return open(self._path(path), 'r')

    def _read(self, path: str) -> str:
        with self._open(path) as f:
            return str(f.read())

    def _exists(self, path: str) -> bool:
        return os.path.exists(self._path(path))

    def load_stone_yml(self, file: str) -> StoneYAML:
        with self._open(file) as f:
            return StoneYAML(f)

    def load_stone_yml_from_commit(self, ref: str, file: str) -> StoneYAML:
        return StoneYAML(self.git.file_from_commit(ref, file))

    def load_manifest_jsonc(self, file: str) -> ManifestJSONC | None:
        try:
            with self._open(file) as f:
                return ManifestJSONC(f)
        except FileNotFoundError:
            return None

    def load_manifest_jsonc_from_commit(self, ref: str, file: str) -> ManifestJSONC:
        return ManifestJSONC(self.git.file_from_commit(ref, file))

    def file_line(self, file: str, expr: str) -> Optional[int]:
        with self._open(file) as f:
            for i, line in enumerate(f.read().splitlines()):
                if re.match(expr, line):
                    return i + 1

        return None

    def package_file_line(self, package: str, file: str, expr: str) -> Optional[int]:
        return self.file_line(self.package_file(package, file), expr)

    def package_yml_path(self, package: str) -> str:
        return self.package_file(package, 'stone.yaml')

    def package_file(self, package: str, file: str) -> str:
        return os.path.join(self.package_dir(package), file)

    def package_dir(self, package: str) -> str:
        return os.path.join('packages', self._package_subdir(package), package)

    @staticmethod
    def package_for(path: str) -> str:
        parts = path.split("/")
        if len(parts) < 3 or parts[0] != "packages":
            return ""

        return parts[2]

    def _package_subdir(self, package: str) -> str:
        package = package.lower()

        return package[0]


class Homepage(PullRequestCheck):
    _error = '`homepage` is not set'
    _level = Level.ERROR

    def run(self) -> List[Result]:
        return [Result(message=self._error, file=f, level=self._level)
                for f in self.package_files
                if not self._includes_homepage(f)]

    def _includes_homepage(self, file: str) -> bool:
        with self._open(file) as f:
            yaml = YAML(typ='safe', pure=True)
            yaml.default_flow_style = False
            return 'homepage' in yaml.load(f)


class Monitoring(PullRequestCheck):
    _error = '`monitoring.yaml` is missing'
    _level = Level.ERROR

    def run(self) -> List[Result]:
        return [Result(message=self._error, file=f, level=self._level)
                for f in self.package_files
                if not self._has_monitoring_yaml(f)]

    def _has_monitoring_yaml(self, file: str) -> bool:
        return self._exists(os.path.join(os.path.dirname(file), 'monitoring.yaml'))


class PackageBumped(PullRequestCheck):
    _msg = 'Package release is not incremented by 1'
    _msg_new = 'Package release is not 1'

    def run(self) -> List[Result]:
        results = [self._check_commit(self.base or 'HEAD', file)
                   for file in self.files]

        return [result for result in results if result is not None]

    def _check_commit(self, base: str, file: str) -> Optional[Result]:
        match os.path.basename(file):
            case 'stone.yaml':
                return self._check(base, file, StoneYAML, Level.WARNING)
            case _:
                return None

    def _check(self, base: str, file: str, loader: Callable[[str], Package], level: Level) -> Optional[Result]:
        new = loader(self._read(file))

        try:
            old = loader(self.git.file_from_commit(base, file))
            if old.release + 1 != new.release:
                return Result(level=level, file=file, message=self._msg)

            return None
        except Exception as e:
            if 'exists on disk, but not in' in str(e):
                if new.release != 1:
                    return Result(level=level, file=file, message=self._msg_new)

                return None

            raise e


class PackageDependenciesOrder(PullRequestCheck):
    _deps_keys = ['builddeps', 'checkdeps', 'rundeps']
    _error = '`` are not in order'
    _level = Level.WARNING

    def run(self) -> List[Result]:
        results = [self._check_deps(deps, file)
                   for deps in self._deps_keys
                   for file in self.package_files]

        return [result for result in results if result is not None]

    def _check_deps(self, deps: str, file: str) -> Optional[Result]:
        cur = self.load_stone_yml(file).get(deps, [])
        exp = self._sorted(cur)

        if cur != exp:
            class Dumper(YAML):
                def dump(self, data: Any, stream: Optional[StringIO] = None, **kw: int) -> Any:
                    self.default_flow_style = False
                    self.indent(offset=4, sequence=4)
                    self.prefix_colon = ' '  # type: ignore[assignment]
                    stream = StringIO()
                    YAML.dump(self, data, stream, **kw)
                    return stream.getvalue()

            yaml = Dumper(typ='safe', pure=True)
            return Result(file=file, level=self._level, line=self.file_line(file, '^' + deps + r'\s*:'),
                          message=f'{deps} are not in order, expected: \n' + yaml.dump(exp))

        return None

    @staticmethod
    def _sorted(deps: List[str]) -> List[str]:
        providers = ['binary(', 'cmake(', 'font(', 'pkgconfig(', 'pkgconfig32(', 'sysbinary(']
        for dep in deps:
            if isinstance(dep, dict):
                for k, v in dep.items():
                    if isinstance(v, str):
                        print("what is?", v, str, dep[k])
                        dep[k] = v
                    else:
                        dep[k] = sorted(v, key=lambda x: (not any(x.startswith(provider) for provider in providers), x))

        return sorted(deps, key=lambda x: (not any(x.startswith(provider) for provider in providers), x))


class PackageDirectory(PullRequestCheck):
    _error = 'Package not in correct directory'
    _level = Level.ERROR

    def run(self) -> List[Result]:
        paths = [os.path.dirname(f) for f in self.package_files]

        return [Result(message=self._error, file=path, level=self._level) for path in paths
                if not self._check_path(path)]

    def _check_path(self, path: str) -> bool:
        pkg = os.path.basename(os.path.realpath(path))
        exp = [self._package_subdir(pkg), pkg]

        return path.split('/') == exp

class PackageVersion(PullRequestCheck):
    _error = 'Package version is not a string'
    _level = Level.ERROR

    def run(self) -> List[Result]:
        return [Result(message=self._error, level=self._level,
                       file=path, line=self.file_line(path, r'^version\s*:'), )
                for path in self.package_files
                if not self._check_version(path)]

    def _check_version(self, path: str) -> bool:
        return isinstance(self.load_stone_yml(path).version, str)


class SPDXLicense(PullRequestCheck):
    _licenses_url = 'https://raw.githubusercontent.com/spdx/license-list-data/main/json/licenses.json'
    _exceptions_url = 'https://raw.githubusercontent.com/spdx/license-list-data/main/json/exceptions.json'
    _licenses: Optional[List[str]] = None
    _exceptions: Optional[List[str]] = None
    _extra_licenses = ['Distributable', 'EULA', 'Public-Domain']
    _error = 'Invalid license identifier: '
    _level = Level.WARNING

    def run(self) -> List[Result]:
        return [r for f in self.package_files
                for r in self._validate_spdx(f) if r]

    def _validate_spdx(self, file: str) -> List[Optional[Result]]:
        license = self.load_stone_yml(file).get('license')
        if isinstance(license, list):
            return [self._validate_license(file, id) for id in license]

        return [self._validate_license(file, license)]

    def _validate_license(self, file: str, identifier: str) -> Optional[Result]:
        if self._valid_license(identifier):
            return None

        return Result(file=file, level=self._level,
                      message=f'invalid license identifier: {repr(identifier)}',
                      line=self.file_line(file, r'^license\s*:'))

    def _valid_license(self, identifier: str) -> bool:
        identifier = identifier.strip(" ()+")
        identifiers = [id_o
                       for id_a in identifier.split(' AND ')
                       for id_o in id_a.split(' OR ')]

        if len(identifiers) > 1:
            return all([self._valid_license(id) for id in identifiers])

        if ' WITH ' in identifier:
            identifier, exception = identifier.split(' WITH ', 1)

            if exception not in self._exception_ids():
                return False

        return identifier in self._license_ids()

    def _license_ids(self) -> List[str]:
        if self._licenses is None:
            with request.urlopen(self._licenses_url) as f:
                self._licenses = [license['licenseId'] for license in json.load(f)['licenses']]

        return self._licenses + self._extra_licenses

    def _exception_ids(self) -> List[str]:
        if self._exceptions is None:
            with request.urlopen(self._exceptions_url) as f:
                self._exceptions = [exception['licenseExceptionId'] for exception in json.load(f)['exceptions']]

        return self._exceptions


class UnwantedFiles(PullRequestCheck):
    _patterns = [r'.*\.stone^', r'.*\.tar\..*', r'^packages/[^/]+(/[^/]+)?$']
    _error = 'This file should not be included'
    _level = Level.ERROR

    def run(self) -> List[Result]:
        return [Result(message=self._error, file=f, level=self._level)
                for f in self.files
                for p in self._patterns
                if not os.path.isdir(f) and re.match(p, f)]


class Manifest(PullRequestCheck):
    _error = "`stone.yaml` and `manifest.x86_64.jsonc` are not consistent, or the manifest doesn't exist, please rebuild."
    _level = Level.ERROR

    def run(self) -> List[Result]:
        paths = [os.path.dirname(f) for f in self.package_files]

        return [Result(message=self._error, file=os.path.join(path, 'manifest.x86_64.jsonc'), level=self._level)
                for path in paths
                if not self._check_consistent(path)]

    def _check_consistent(self, package_dir: str) -> bool:
        jsonc = self._jsonc_file(package_dir)
        yml = self._yml_file(package_dir)

        if jsonc is None:
            return False

        return bool(yml.release == jsonc.release)

    def _yml_file(self, package_dir: str) -> StoneYAML:
        return self.load_stone_yml(os.path.join(package_dir, 'stone.yaml'))

    def _jsonc_file(self, package_dir: str) -> ManifestJSONC | None:
        return self.load_manifest_jsonc(os.path.join(package_dir, 'manifest.x86_64.jsonc'))


class SummaryGenerator(PullRequestCheck):
    def generate(self) -> str:
        s = "# Changelog entries\n\n"

        for commit in self.commits:
            package_tag = self._commit_package_tag(commit)
            if package_tag is None:
                continue

            s += f"## {package_tag}\n\n"
            s += self.git.commit_message(commit) + "\n\n"

        return s

    def _commit_package_tag(self, ref: str) -> Optional[str]:
        package = self._commit_package_yaml(ref)
        if package is None:
            return None

        return f"{package.name}-{package.version}-{package.release}"

    def _commit_package_yaml(self, ref: str) -> Optional[StoneYAML]:
        files = [f for f in self.git.files_in_commit(ref) if os.path.basename(f) == 'stone.yaml']
        if len(files) == 0:
            return None

        return self.load_stone_yml_from_commit(ref, files[0])


class Checker:
    checks = [
        Homepage,
        Manifest,
        Monitoring,
        PackageBumped,
        PackageDependenciesOrder,
        PackageDirectory,
        PackageVersion,
        SPDXLicense,
        #StaticLibs,
        UnwantedFiles,
    ]

    def __init__(self, base: Optional[str], head: str, path: str, files: List[str],
                 modified: bool, untracked: bool, results_only: bool, exit_warn: bool):
        self.results_only = results_only
        self.exit_warn = exit_warn
        self.base = base
        self.head = head
        self.git = Git(path)
        self.files = self.git.relpaths(files)
        self.commits = []
        self.summary_file = os.environ.get('GITHUB_STEP_SUMMARY', None)

        if base is not None:
            self.git.fetch(self._base_to_remote(base))
            self.files += self.git.changed_files(self.git.merge_base(base, head), head)
            self.commits = self.git.commit_refs(self.git.merge_base(base, head), head)

        if modified:
            self.files += self.git.modified_files()

        if untracked:
            self.files += self.git.untracked_files()

    def run(self) -> bool:
        if not self.results_only:
            print(f'Checking files: {", ".join(self.files)}')
            if self.commits:
                print(f'Checking commits: {", ".join(self.commits)}')

        results = [result for check in self.checks
                   for result in check(self.git, self.files, self.commits, self.base).run()]
        errors = [r for r in results if r.level == Level.ERROR]
        warnings = [r for r in results if r.level == Level.WARNING]

        if not self.results_only:
            print(f"Found {len(results)} result(s), {len(warnings)} warnings and {len(errors)} error(s)")

        for result in results:
            result.log()

        self.write_summary()

        return len(errors) > 0 or self.exit_warn and len(warnings) > 0

    def write_summary(self) -> None:
        if self.summary_file is None:
            return

        with open(self.summary_file, 'w') as f:
            f.write(SummaryGenerator(self.git, self.files, self.commits, self.base).generate())

    @staticmethod
    def _base_to_remote(base: str) -> List[str]:
        return base.split('~')[0].split('/')


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, handlers=[LogFormatter.handler()])

    parser = argparse.ArgumentParser()
    parser.add_argument('--base', type=str,
                        help='Optional reference to the base branch')
    parser.add_argument('--head', type=str, default='HEAD',
                        help='Optional reference to the current branch head')
    parser.add_argument('--root', type=str, default='.',
                        help='Repository root directory')
    parser.add_argument('--modified', action='store_true',
                        help='Include modified files')
    parser.add_argument('--untracked', action='store_true',
                        help='Include untracked files')
    parser.add_argument('--fail-on-warnings', action='store_true',
                        help='Exit with an error if warnings are encountered')
    parser.add_argument('--results-only', action='store_true',
                        help='Only show results, nothing else')
    parser.add_argument('filename', type=str, nargs="*",
                        help='Additional files to check')

    cli_args = parser.parse_args()
    checker = Checker(base=cli_args.base,
                      head=cli_args.head,
                      path=cli_args.root,
                      modified=cli_args.modified,
                      untracked=cli_args.untracked,
                      files=cli_args.filename,
                      results_only=cli_args.results_only,
                      exit_warn=cli_args.fail_on_warnings)
    exit(checker.run())
