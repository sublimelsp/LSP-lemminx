import hashlib
import json
import os
import re
import sublime
import time
import zipfile

from http.client import HTTPException
from urllib.request import urlretrieve, urlopen

from LSP.plugin import (
    AbstractPlugin,
    register_plugin,
    filename_to_uri,
    unregister_plugin,
)

__all__ = [
    "LemminxPlugin",
    "plugin_loaded",
    "plugin_unloaded"
]


class BaseServerHandler:

    __slots__ = ["dest_checksum", "dest_version"]

    def needs_update_or_installation(self):
        self.dest_version = LemminxPlugin.settings.get("server_version", "latest")

        next_run, version, checksum = self.load_metadata()
        is_upgrade = os.path.isfile(self.server_binary())

        if (
            is_upgrade
            and self.dest_version == version
            and (self.dest_version != "latest" or int(time.time()) < next_run)
        ):
            return False

        try:
            self.dest_checksum = self.download_checksum()
        except (HTTPException, OSError, ValueError) as e:
            # downloading or parsing checksum failed
            if is_upgrade:
                self.save_metadata(False, version, checksum)
                print("LSP-lemminx: Update check failed - " + str(e))
                return False
            raise

        if self.dest_checksum == checksum:
            # installed binary up to date
            self.save_metadata(True, version, checksum)
            return False

        return True

    def download_checksum(self):
        """
        Build and return platform specific download url.
        """
        raise NotImplementedError()

    @staticmethod
    def server_binary():
        """
        Build and return absolute path to installed language server binary.
        """
        raise NotImplementedError()

    @staticmethod
    def metadata_file():
        """
        Build and return absolute path to meta data file
        storing language server's version and checksum.
        """
        raise NotImplementedError()

    @classmethod
    def load_metadata(cls):
        try:
            with open(cls.metadata_file()) as fobj:
                data = json.load(fobj)
                return (int(data['timestamp']), data['version'], data['checksum'])
        except (FileNotFoundError, KeyError, TypeError, ValueError):
            return (0, "", "")

    @classmethod
    def save_metadata(cls, success, version, checksum):
        next_run_delay = (7 * 24 * 60 * 60) if success else (6 * 60 * 60)
        with open(cls.metadata_file(), "w") as fobj:
            json.dump({
                "timestamp": int(time.time()) + next_run_delay,
                "version": version,
                "checksum": checksum
            }, fp=fobj)


class BinaryServerHandler(BaseServerHandler):
    """
    This class describes a binary server handler.

    It installs or upgrades compiled GraalVM LemMinX language server from
    https://github.com/redhat-developer/vscode-xml/releases

    The version to use is specified by `server_version` setting in LSP-lemminx.sublime-settings.
    If set to `latest` updates are checked once a week.

    Install & Upgrade steps
    ---

    1. compare `server_version` setting value with version from binary_server.json
       -> exit if equal
    2. download lemminx-<platform>.sha256
    3. compare checksum with value from binary_server.json
       -> exit if equal
    4. download lemminx-<platform>.zip
    5. extract zip to Package Storage/LSP-lemminx
    6. validate checksum of extracted binary file
    """

    # API methods

    def install_or_update(self):
        if not self.dest_checksum or not self.dest_version:
            raise RuntimeError()

        server_binary = self.server_binary()
        server_dir, server_name = os.path.split(server_binary)

        # downlad and unzip server binary (ignore any other files)
        path, _ = urlretrieve(self.make_url(self.dest_version, "zip"))
        with zipfile.ZipFile(path) as zf:
            zf.extract(server_name, server_dir)
        os.remove(path)

        # validate binary's checksum
        checksum = ""
        with open(server_binary, "rb") as fobj:
            checksum = hashlib.sha256(fobj.read()).hexdigest().lower()
        if checksum != self.dest_checksum:
            os.remove(server_binary)
            raise ValueError("Validating server binary failed!")

        # write update cookie
        self.save_metadata(True, self.dest_version, self.dest_checksum)

    def on_pre_start(self, window, initiating_view, workspace_folders, configuration):
        configuration.command = [
            self.server_binary()
        ]
        additional_args = LemminxPlugin.settings.get("server_binary_args", [])
        if additional_args:
            configuration.command.extend(additional_args)

    # server specific methods

    def download_checksum(self):
        # download checksum file
        response = urlopen(self.make_url(self.dest_version, "sha256"), timeout=2.0).read().decode("utf-8")

        # parse checksum file
        match = re.search(r"^([a-f0-9]{64})\b", response, re.IGNORECASE)
        if not match:
            raise ValueError("Failed to parse checksum file!")

        return match.group(1).lower()

    @staticmethod
    def make_url(version, ext):
        name = {
            "linux": "lemminx-linux",
            "osx": "lemminx-osx-x86_64",
            "windows": "lemminx-win32",
        }
        pattern = "https://github.com/redhat-developer/vscode-xml/releases/download/{0}/{1}.{2}"
        return pattern.format(version, name[sublime.platform()], ext)

    @staticmethod
    def metadata_file():
        return os.path.join(LemminxPlugin.server_dir(), "binary_server.json")

    @staticmethod
    def server_binary():
        name = {
            "linux": "lemminx-linux",
            "osx": "lemminx-osx-x86_64",
            "windows": "lemminx-win32.exe",
        }
        return os.path.join(LemminxPlugin.server_dir(), name[sublime.platform()])


class JavaServerHandler(BaseServerHandler):
    """
    This class describes a binary server handler.

    It installs or upgrades compiled GraalVM LemMinX language server from
    https://repo.eclipse.org/content/repositories/lemminx-releases/org/eclipse/lemminx/org.eclipse.lemminx

    The version to use is specified by `server_version` setting in LSP-lemminx.sublime-settings.
    If set to `latest` updates are checked once a week.

    Install & Upgrade steps
    ---

    1. compare `server_version` setting value with version from java_server.json
       -> exit if equal
    2. download org.eclipse.lemminx-<semver>-uber.sha1
    3. compare checksum with value from java_server.json
       -> exit if equal
    4. download org.eclipse.lemminx-<semver>-uber.jar
    5. validate checksum of downloaded jar file
    """

    # API methods

    def install_or_update(self):
        if not self.dest_checksum or not self.dest_version:
            raise RuntimeError()

        server_binary = self.server_binary()

        urlretrieve(self.make_url(self.dest_version, "jar"), server_binary)

        checksum = ""
        with open(server_binary, "rb") as fobj:
            checksum = hashlib.sha1(fobj.read()).hexdigest().lower()
        if checksum != self.dest_checksum:
            os.remove(server_binary)
            raise ValueError("Validating server binary failed!")

        # write update cookie
        self.save_metadata(True, self.dest_version, self.dest_checksum)

    def on_pre_start(self, window, initiating_view, workspace_folders, configuration):
        configuration.command = [
            "java", "-jar", self.server_binary()
        ]
        additional_args = LemminxPlugin.settings.get("java_vmargs", [])
        if additional_args:
            configuration.command.extend(additional_args)

    # server specific methods

    def download_checksum(self):
        # download checksum file
        response = urlopen(self.make_url(self.dest_version, "jar.sha1"), timeout=2.0).read().decode("utf-8")

        # parse checksum file
        match = re.search(r"^([a-f0-9]{40})\b", response, re.IGNORECASE)
        if not match:
            raise ValueError("Failed to parse checksum file!")

        return match.group(1).lower()

    @staticmethod
    def make_url(version, ext):
        base_url = "https://repo.eclipse.org/content/repositories/lemminx-releases/org/eclipse/lemminx/org.eclipse.lemminx"

        if version == "latest":
            match = re.search(
                r"<release>\s*(\d+\.\d+\.\d+)\s*</release>",
                urlopen(base_url + "/maven-metadata.xml").read().decode("utf-8"),
                re.IGNORECASE | re.MULTILINE
            )
            if not match:
                raise ValueError("Can't determine latest release!")
            version = match.group(1)

        return "{0}/{1}/org.eclipse.lemminx-{1}-uber.{2}".format(base_url, version, ext)

    @staticmethod
    def metadata_file():
        return os.path.join(LemminxPlugin.server_dir(), "java_server.json")

    @staticmethod
    def server_binary():
        return os.path.join(LemminxPlugin.server_dir(), "lemminx.jar")


class LemminxPlugin(AbstractPlugin):

    file_associations = [
        {
            "pattern": "**/*.sublime-snippet",
            "systemId": "$storage_uri/cache/sublime/sublime-snippet.xsd"
        },
        {
            "pattern": "**/*.tmPreferences",
            "systemId": "$storage_uri/cache/sublime/tmPreferences.xsd"
        },
        {
            "pattern": "**/*.hidden-tmPreferences",
            "systemId": "$storage_uri/cache/sublime/tmPreferences.xsd"
        },
        {
            "pattern": "**/*.tmTheme",
            "systemId": "$storage_uri/cache/sublime/tmTheme.xsd"
        },
        {
            "pattern": "**/*.hidden-tmTheme",
            "systemId": "$storage_uri/cache/sublime/tmTheme.xsd"
        }
    ]

    package_name: str = __spec__.parent
    """
    The package name on file system.

    Main purpose is to provide python version acnostic package name for use
    in path sensitive locations, to ensure plugin even works if user installs
    package with different name.
    """

    settings: sublime.Settings
    """
    Package settings
    """

    _server = None

    # LSP API methods

    @classmethod
    def name(cls):
        return "LemMinX"

    @classmethod
    def configuration(cls):
        settings_file_name = "LSP-lemminx.sublime-settings"
        cls.settings = sublime.load_settings(settings_file_name)
        return cls.settings, f"Packages/{cls.package_name}/{settings_file_name}"

    @classmethod
    def needs_update_or_installation(cls):
        return cls.server().needs_update_or_installation()

    @classmethod
    def install_or_update(cls):
        os.makedirs(cls.server_dir(), exist_ok=True)
        cls.server().install_or_update()

    @classmethod
    def on_pre_start(cls, window, initiating_view, workspace_folders, configuration):
        cls.server().on_pre_start(window, initiating_view, workspace_folders, configuration)

    @classmethod
    def on_settings_changed(cls, dotted):
        # invalidate server object
        cls._server = None
        # prepend a list of fixed file associations
        dotted.set(
            "xml.fileAssociations",
            cls.file_associations + (dotted.get("xml.fileAssociations") or [])
        )
        # adjust working dir to package storage directory
        dotted.set("xml.server.workDir", cls.server_dir())

    # LemMinX specific methods

    @classmethod
    def server(cls):
        if cls._server is None:
            if (
                cls.settings.get("server_binary", True)
                and sublime.platform() in ("linux", "osx", "windows")
                and sublime.arch() == "x64"
            ):
                cls._server = BinaryServerHandler()
            else:
                cls._server = JavaServerHandler()
        return cls._server

    @classmethod
    def additional_variables(cls):
        return {
            "package_path": cls.package_dir(),
            "storage_path": cls.server_dir(),
            "package_uri": cls.package_uri(),
            "storage_uri": cls.server_uri()
        }

    # internal methods

    @classmethod
    def cleanup(cls):
        try:
            from package_control import events  # type: ignore

            if events.remove(cls.package_name):
                sublime.set_timeout_async(cls.remove_server_path, 1000)
        except ImportError:
            pass  # Package Control is not required.

    @classmethod
    def remove_server_path(cls):
        from shutil import rmtree

        server_path = cls.server_dir()
        # Enable long path support on on Windows
        # to avoid errors when cleaning up paths with more than 256 chars.
        # see: https://stackoverflow.com/a/14076169/4643765
        # see: https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation
        if sublime.platform() == "windows":
            server_path = Rf"\\?\{server_path}"

        rmtree(server_path, ignore_errors=True)

    @classmethod
    def package_dir(cls):
        return os.path.join(sublime.packages_path(), cls.package_name)

    @classmethod
    def package_uri(cls):
        return filename_to_uri(cls.package_dir())

    @classmethod
    def server_dir(cls):
        return os.path.join(cls.storage_path(), cls.package_name)

    @classmethod
    def server_uri(cls):
        return filename_to_uri(cls.server_dir())

    @classmethod
    def install_schemas(cls):
        """
        Extract scheme files from sublime-package file.

        LemMinX can't read schemas or catalogs from zipped packages.
        """
        dest_path = os.path.join(cls.server_dir(), "cache", "sublime")
        pkg_path = os.path.dirname(__file__)
        if ".sublime-package" in pkg_path:
            with zipfile.ZipFile(file=pkg_path) as pkg:
                for zipinfo in pkg.infolist():
                    if zipinfo.filename.startswith("schemas/"):
                        zipinfo.filename = zipinfo.filename[len("schemas/"):]
                        if zipinfo.filename:
                            pkg.extract(zipinfo, path=dest_path)
        else:
            import shutil
            os.makedirs(dest_path, exist_ok=True)
            src_path = os.path.join(pkg_path, 'schemas')
            for f in os.listdir(src_path):
                shutil.copy(os.path.join(src_path, f), dest_path)


def plugin_loaded():
    try:
        LemminxPlugin.install_schemas()
    except OSError:
        print("LSP-lemminx: Unable to install schemes!")

    register_plugin(LemminxPlugin)


def plugin_unloaded():
    LemminxPlugin.cleanup()
    unregister_plugin(LemminxPlugin)
