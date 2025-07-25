from __future__ import annotations
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
    ClientConfig,
    DottedDict,
    WorkspaceFolder,
    register_plugin,
    filename_to_uri,
    unregister_plugin,
)

__all__ = ["LemminxPlugin", "plugin_loaded", "plugin_unloaded"]


class BaseServerHandler:
    dest_checksum: str = ""
    dest_version: str = ""

    @classmethod
    def needs_update_or_installation(cls) -> bool:
        cls.dest_version = str(LemminxPlugin.settings.get("server_version", "latest"))

        next_run, version, checksum = cls.load_metadata()
        is_upgrade = os.path.isfile(cls.server_binary())

        if (
            is_upgrade
            and cls.dest_version == version
            and (cls.dest_version != "latest" or int(time.time()) < next_run)
        ):
            return False

        try:
            cls.dest_checksum = cls.download_checksum()
        except (HTTPException, OSError, ValueError) as e:
            # downloading or parsing checksum failed
            if is_upgrade:
                cls.save_metadata(False, version, checksum)
                print("LSP-lemminx: Update check failed - " + str(e))
                return False
            raise

        if cls.dest_checksum == checksum:
            # installed binary up to date
            cls.save_metadata(True, version, checksum)
            return False

        return True

    @classmethod
    def download_checksum(cls) -> str:
        """
        Build and return platform specific download url.
        """
        raise NotImplementedError()

    @staticmethod
    def server_binary() -> str:
        """
        Build and return absolute path to installed language server binary.
        """
        raise NotImplementedError()

    @staticmethod
    def metadata_file() -> str:
        """
        Build and return absolute path to meta data file
        storing language server's version and checksum.
        """
        raise NotImplementedError()

    @classmethod
    def load_metadata(cls) -> tuple[int, str, str]:
        try:
            with open(cls.metadata_file()) as fobj:
                data = json.load(fobj)
                return (int(data["timestamp"]), data["version"], data["checksum"])
        except (FileNotFoundError, KeyError, TypeError, ValueError):
            return (0, "", "")

    @classmethod
    def save_metadata(cls, success: bool, version: str, checksum: str) -> None:
        next_run_delay = (7 * 24 * 60 * 60) if success else (6 * 60 * 60)
        with open(cls.metadata_file(), "w") as fobj:
            json.dump(
                {
                    "timestamp": int(time.time()) + next_run_delay,
                    "version": version,
                    "checksum": checksum,
                },
                fp=fobj,
            )


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

    @classmethod
    def install_or_update(cls) -> None:
        if not cls.dest_checksum or not cls.dest_version:
            raise RuntimeError()

        server_binary = cls.server_binary()
        server_path, server_name = os.path.split(server_binary)

        # downlad and unzip server binary (ignore any other files)
        path, _ = urlretrieve(cls.make_url(cls.dest_version, "zip"))
        with zipfile.ZipFile(path) as zf:
            zf.extract(server_name, server_path)
        os.remove(path)

        # validate binary's checksum
        checksum = ""
        with open(server_binary, "rb") as fobj:
            checksum = hashlib.sha256(fobj.read()).hexdigest().lower()
        if checksum != cls.dest_checksum:
            os.remove(server_binary)
            raise ValueError("Validating server binary failed!")

        # write update cookie
        cls.save_metadata(True, cls.dest_version, cls.dest_checksum)

    @classmethod
    def can_start(
        cls,
        window: sublime.Window,
        initiating_view: sublime.View,
        workspace_folders: list[WorkspaceFolder],
        configuration: ClientConfig,
    ) -> str | None:
        configuration.command = [cls.server_binary()]
        additional_args = LemminxPlugin.settings.get("server_binary_args", [])
        if additional_args:
            configuration.command.extend(additional_args)

    # server specific methods

    @classmethod
    def download_checksum(cls) -> str:
        # download checksum file
        response = (
            urlopen(cls.make_url(cls.dest_version, "sha256"), timeout=2.0).read().decode("utf-8")
        )

        # parse checksum file
        match = re.search(r"^([a-f0-9]{64})\b", response, re.IGNORECASE)
        if not match:
            raise ValueError("Failed to parse checksum file!")

        return match.group(1).lower()

    @staticmethod
    def make_url(version: str, ext: str) -> str:
        name = {
            "linux": "lemminx-linux",
            "osx": "lemminx-osx-x86_64",
            "windows": "lemminx-win32",
        }
        pattern = "https://github.com/redhat-developer/vscode-xml/releases/download/{0}/{1}.{2}"
        return pattern.format(version, name[sublime.platform()], ext)

    @staticmethod
    def metadata_file() -> str:
        return os.path.join(LemminxPlugin.server_path(), "binary_server.json")

    @staticmethod
    def server_binary() -> str:
        name = {
            "linux": "lemminx-linux",
            "osx": "lemminx-osx-x86_64",
            "windows": "lemminx-win32.exe",
        }
        return os.path.join(LemminxPlugin.server_path(), name[sublime.platform()])


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

    @classmethod
    def install_or_update(cls) -> None:
        if not cls.dest_checksum or not cls.dest_version:
            raise RuntimeError()

        server_binary = cls.server_binary()

        urlretrieve(cls.make_url(cls.dest_version, "jar"), server_binary)

        checksum = ""
        with open(server_binary, "rb") as fobj:
            checksum = hashlib.sha1(fobj.read()).hexdigest().lower()
        if checksum != cls.dest_checksum:
            os.remove(server_binary)
            raise ValueError("Validating server binary failed!")

        # write update cookie
        cls.save_metadata(True, cls.dest_version, cls.dest_checksum)

    @classmethod
    def can_start(
        cls,
        window: sublime.Window,
        initiating_view: sublime.View,
        workspace_folders: list[WorkspaceFolder],
        configuration: ClientConfig,
    ) -> str | None:
        configuration.command = ["java", "-jar", cls.server_binary()]
        additional_args = LemminxPlugin.settings.get("java_vmargs", [])
        if additional_args:
            configuration.command.extend(additional_args)

    # server specific methods

    @classmethod
    def download_checksum(cls) -> str:
        # download checksum file
        response = (
            urlopen(cls.make_url(cls.dest_version, "jar.sha1"), timeout=2.0)
            .read()
            .decode("utf-8")
        )

        # parse checksum file
        match = re.search(r"^([a-f0-9]{40})\b", response, re.IGNORECASE)
        if not match:
            raise ValueError("Failed to parse checksum file!")

        return match.group(1).lower()

    @staticmethod
    def make_url(version: str, ext: str) -> str:
        base_url = "https://repo.eclipse.org/content/repositories/lemminx-releases/org/eclipse/lemminx/org.eclipse.lemminx"

        if version == "latest":
            match = re.search(
                r"<release>\s*(\d+\.\d+\.\d+)\s*</release>",
                urlopen(base_url + "/maven-metadata.xml").read().decode("utf-8"),
                re.IGNORECASE | re.MULTILINE,
            )
            if not match:
                raise ValueError("Can't determine latest release!")
            version = match.group(1)

        return "{0}/{1}/org.eclipse.lemminx-{1}-uber.{2}".format(base_url, version, ext)

    @staticmethod
    def metadata_file() -> str:
        return os.path.join(LemminxPlugin.server_path(), "java_server.json")

    @staticmethod
    def server_binary() -> str:
        return os.path.join(LemminxPlugin.server_path(), "lemminx.jar")


class LemminxPlugin(AbstractPlugin):

    file_associations: list[dict[str, str]] = [
        {
            "pattern": "**/*.sublime-snippet",
            "systemId": "$storage_uri/cache/sublime/sublime-snippet.xsd",
        },
        {
            "pattern": "**/*.tmPreferences",
            "systemId": "$storage_uri/cache/sublime/tmPreferences.xsd",
        },
        {
            "pattern": "**/*.hidden-tmPreferences",
            "systemId": "$storage_uri/cache/sublime/tmPreferences.xsd",
        },
        {
            "pattern": "**/*.tmTheme",
            "systemId": "$storage_uri/cache/sublime/tmTheme.xsd",
        },
        {
            "pattern": "**/*.hidden-tmTheme",
            "systemId": "$storage_uri/cache/sublime/tmTheme.xsd",
        },
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

    _server: type[BinaryServerHandler] | type[JavaServerHandler] | None = None

    # LSP API methods

    @classmethod
    def name(cls) -> str:
        return "LemMinX"

    @classmethod
    def configuration(cls) -> tuple[sublime.Settings, str]:
        settings_file_name = "LSP-lemminx.sublime-settings"
        cls.settings = sublime.load_settings(settings_file_name)
        return cls.settings, f"Packages/{cls.package_name}/{settings_file_name}"

    @classmethod
    def needs_update_or_installation(cls) -> bool:
        return cls.server().needs_update_or_installation()

    @classmethod
    def install_or_update(cls) -> None:
        os.makedirs(cls.server_path(), exist_ok=True)
        cls.server().install_or_update()

    @classmethod
    def can_start(
        cls,
        window: sublime.Window,
        initiating_view: sublime.View,
        workspace_folders: list[WorkspaceFolder],
        configuration: ClientConfig,
    ) -> str | None:
        cls.server().can_start(window, initiating_view, workspace_folders, configuration)

    @classmethod
    def on_settings_changed(cls, dotted: DottedDict) -> None:
        # invalidate server object
        cls._server = None
        # prepend a list of fixed file associations
        dotted.set(
            "xml.fileAssociations",
            cls.file_associations + (dotted.get("xml.fileAssociations") or []),
        )
        # adjust working dir to package storage directory
        dotted.set("xml.server.workDir", cls.server_path())

    # LemMinX specific methods

    @classmethod
    def server(cls) -> type[BinaryServerHandler] | type[JavaServerHandler]:
        if cls._server is None:
            if (
                cls.settings.get("server_binary", True)
                and sublime.platform() in ("linux", "osx", "windows")
                and sublime.arch() == "x64"
            ):
                cls._server = BinaryServerHandler
            else:
                cls._server = JavaServerHandler
        return cls._server

    @classmethod
    def additional_variables(cls) -> dict[str, str]:
        return {
            "package_path": cls.package_path(),
            "storage_path": cls.server_path(),
            "package_uri": cls.package_uri(),
            "storage_uri": cls.server_uri(),
        }

    # internal methods

    @classmethod
    def cleanup(cls) -> None:
        try:
            from package_control import events  # type: ignore

            if events.remove(cls.package_name):
                sublime.set_timeout_async(cls.remove_server_dir, 1000)
        except ImportError:
            pass  # Package Control is not required.

    @classmethod
    def remove_server_dir(cls) -> None:
        from shutil import rmtree

        server_path = cls.server_path()
        # Enable long path support on on Windows
        # to avoid errors when cleaning up paths with more than 256 chars.
        # see: https://stackoverflow.com/a/14076169/4643765
        # see: https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation
        if sublime.platform() == "windows":
            server_path = Rf"\\?\{server_path}"

        rmtree(server_path, ignore_errors=True)

    @classmethod
    def package_path(cls) -> str:
        return os.path.join(sublime.packages_path(), cls.package_name)

    @classmethod
    def package_uri(cls) -> str:
        return filename_to_uri(cls.package_path())

    @classmethod
    def server_path(cls) -> str:
        return os.path.join(cls.storage_path(), cls.package_name)

    @classmethod
    def server_uri(cls) -> str:
        return filename_to_uri(cls.server_path())

    @classmethod
    def install_schemas(cls) -> None:
        """
        Extract scheme files from sublime-package file.

        LemMinX can't read schemas or catalogs from zipped packages.
        """
        dest_path = os.path.join(cls.server_path(), "cache", "sublime")
        pkg_path = os.path.dirname(__file__)
        if ".sublime-package" in pkg_path:
            with zipfile.ZipFile(file=pkg_path) as pkg:
                for zipinfo in pkg.infolist():
                    if zipinfo.filename.startswith("schemas/"):
                        zipinfo.filename = zipinfo.filename[len("schemas/") :]
                        if zipinfo.filename:
                            pkg.extract(zipinfo, path=dest_path)
        else:
            import shutil

            os.makedirs(dest_path, exist_ok=True)
            src_path = os.path.join(pkg_path, "schemas")
            for f in os.listdir(src_path):
                shutil.copy(os.path.join(src_path, f), dest_path)


def plugin_loaded() -> None:
    try:
        LemminxPlugin.install_schemas()
    except OSError:
        print("LSP-lemminx: Unable to install schemes!")

    register_plugin(LemminxPlugin)


def plugin_unloaded() -> None:
    LemminxPlugin.cleanup()
    unregister_plugin(LemminxPlugin)
