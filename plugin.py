from __future__ import annotations
import contextlib
import json
import os
import re
import sublime
import time
import zipfile

from http.client import HTTPException
from io import BytesIO
from urllib.request import urlretrieve, urlopen, Request as HttpRequest

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
    server_version: str = ""

    @classmethod
    def needs_update_or_installation(cls):
        server_file = cls.server_binary()
        is_upgrade = os.path.isfile(server_file)
        if is_upgrade:
            next_update_check, server_version = cls.load_metadata()
        else:
            next_update_check, server_version = 0, ""

        cls.server_version = str(LemminxPlugin.settings.get("server_version", "latest"))
        if cls.server_version == "latest":
            if int(time.time()) >= next_update_check:
                try:
                    available_version = cls.available_version()
                    if available_version != server_version:
                        cls.server_version = available_version
                        return True
                except BaseException:
                    cls.save_metadata(False, server_version)

            return False

        return cls.server_version != server_version

    @classmethod
    def available_version(cls) -> str:
        """
        Fetch and return available version to upgrade to.
        """
        raise NotImplementedError()

    @classmethod
    def server_binary(cls) -> str:
        """
        Build and return absolute path to installed language server binary.
        """
        raise NotImplementedError()

    @classmethod
    def metadata_file(cls) -> str:
        """
        Build and return absolute path to meta data file
        storing language server's version and checksum.
        """
        raise NotImplementedError()

    @classmethod
    def load_metadata(cls) -> tuple[int, str]:
        try:
            with open(cls.metadata_file()) as fobj:
                data = json.load(fobj)
                return int(data["timestamp"]), data["version"]
        except (FileNotFoundError, KeyError, TypeError, ValueError):
            return 0, ""

    @classmethod
    def save_metadata(cls, success: bool, version: str) -> None:
        next_run_delay = (7 * 24 * 60 * 60) if success else (6 * 60 * 60)
        with open(cls.metadata_file(), "w") as fobj:
            json.dump(
                {
                    "timestamp": int(time.time()) + next_run_delay,
                    "version": version,
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
        if not cls.server_version:
            raise RuntimeError()

        server_binary = cls.server_binary()
        server_path, server_name = os.path.split(server_binary)

        # downlad and unzip server binary (ignore any other files)
        with contextlib.closing(urlopen(cls.download_url())) as response:
            with zipfile.ZipFile(BytesIO(response.read())) as arc:
                arc.extractall(server_path)

        os.chmod(server_binary, 0o755)

        # write update cookie
        cls.save_metadata(True, cls.server_version)

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
    def available_version(cls):
        # response url ends with latest available version number
        request = HttpRequest(url=f"{cls.repo_url()}/releases/latest", method="HEAD")
        with contextlib.closing(urlopen(request)) as response:
            return response.url.rstrip("/").rsplit("/", 1)[1]

    @classmethod
    def repo_url(cls) -> str:
        return "https://github.com/redhat-developer/vscode-xml"

    @classmethod
    def download_url(cls) -> str:
        release_assets = {
            "linux-x64": "lemminx-linux.zip",
            "osx-arm64": "lemminx-osx-aarch_64.zip",
            "osx-x64": "lemminx-osx-x86_64.zip",
            "windows-x64": "lemminx-win32.zip",
        }
        try:
            asset = release_assets[f"{sublime.platform()}-{sublime.arch()}"]
            return f"{cls.repo_url()}/releases/download/{cls.server_version}/{asset}"
        except KeyError:
            raise RuntimeError("Binary server not supported on this platform!")

    @classmethod
    def metadata_file(cls) -> str:
        return os.path.join(LemminxPlugin.server_path(), "binary_server.json")

    @classmethod
    def server_binary(cls) -> str:
        names = {
            "linux-x64": "lemminx-linux",
            "osx-arm64": "lemminx-osx-aarch_64",
            "osx-x64": "lemminx-osx-x86_64",
            "windows-x64": "lemminx-win32.exe",
        }
        try:
            name = names[f"{sublime.platform()}-{sublime.arch()}"]
            return os.path.join(LemminxPlugin.server_path(), name)
        except KeyError:
            raise RuntimeError("Binary server not supported on this platform!")

    @classmethod
    def is_supported(cls):
        arch = sublime.arch()
        os = sublime.platform()
        return arch == "x64" or os == "osx" and arch == "arm64"


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
    2. if `server_version` is "latest"...
       a) download maven-metadata.xml
       b) read latest version from <release> node
    3. download org.eclipse.lemminx-<semver>-uber.jar
    """

    # API methods

    @classmethod
    def install_or_update(cls) -> None:
        if not cls.server_version:
            raise RuntimeError()

        urlretrieve(cls.download_url(), cls.server_binary())
        # write update cookie
        cls.save_metadata(True, cls.server_version)

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
    def available_version(cls):
        with contextlib.closing(urlopen(f"{cls.repo_url()}/maven-metadata.xml")) as response:
            content = response.read().decode("utf-8")

        match = re.search(
            r"<release>\s*(\d+\.\d+\.\d+)\s*</release>",
            content,
            re.IGNORECASE | re.MULTILINE,
        )
        if not match:
            raise ValueError("Can't determine latest release!")
        return match.group(1)

    @classmethod
    def repo_url(cls) -> str:
        return "https://repo.eclipse.org/content/repositories/lemminx-releases/org/eclipse/lemminx/org.eclipse.lemminx"

    @classmethod
    def download_url(cls) -> str:
        return f"{cls.repo_url()}/{cls.server_version}/org.eclipse.lemminx-{cls.server_version}-uber.jar"

    @classmethod
    def metadata_file(cls) -> str:
        return os.path.join(LemminxPlugin.server_path(), "java_server.json")

    @classmethod
    def server_binary(cls) -> str:
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
            if cls.settings.get("server_binary", True) and BinaryServerHandler.is_supported():
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
