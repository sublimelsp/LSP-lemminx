from __future__ import annotations

import contextlib
import json
import os
import re
import sublime
import time
import zipfile
from io import BytesIO
from typing import Any, ClassVar
from urllib.request import Request as HttpRequest, urlopen, urlretrieve

from LSP.plugin import (
    ClientConfig,
    LspPlugin,
    OnPreStartContext,
    filename_to_uri,
)

__all__ = ["LemminxPlugin", "plugin_loaded", "plugin_unloaded"]


class BaseServerHandler:
    resolved_server_version: ClassVar[str] = ''

    @classmethod
    def needs_update_or_installation(cls):
        server_file = cls.server_binary()
        is_upgrade = os.path.isfile(server_file)
        if is_upgrade:
            next_update_check, installed_server_version = cls.load_metadata()
        else:
            next_update_check, installed_server_version = 0, ""

        cls.resolved_server_version = str(LemminxPlugin.root_settings.get("server_version", "latest"))
        if cls.resolved_server_version == "latest":
            if int(time.time()) >= next_update_check:
                try:
                    available_version = cls.available_version()
                    if available_version != installed_server_version:
                        cls.resolved_server_version = available_version
                        return True
                except BaseException:
                    cls.save_metadata(False, installed_server_version)

            return False

        return cls.resolved_server_version != installed_server_version

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
        if not cls.resolved_server_version:
            raise RuntimeError()

        server_binary = cls.server_binary()
        server_path, server_name = os.path.split(server_binary)

        # downlad and unzip server binary (ignore any other files)
        with contextlib.closing(urlopen(cls.download_url())) as response:
            with zipfile.ZipFile(BytesIO(response.read())) as arc:
                arc.extractall(server_path)

        os.chmod(server_binary, 0o755)

        # write update cookie
        cls.save_metadata(True, cls.resolved_server_version)

    @classmethod
    def configure(cls, configuration: ClientConfig) -> None:
        configuration.command = [cls.server_binary()]
        additional_args = LemminxPlugin.root_settings.get("server_binary_args", [])
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
            "linux-x64": "lemminx-linux.zip" if version_tuple(cls.resolved_server_version) < version_tuple('0.29.1') else "lemminx-linux-x86_64.zip",
            "osx-arm64": "lemminx-osx-aarch_64.zip",
            "osx-x64": "lemminx-osx-x86_64.zip",
            "windows-x64": "lemminx-win32.zip",
        }
        try:
            asset = release_assets[f"{sublime.platform()}-{sublime.arch()}"]
            return f"{cls.repo_url()}/releases/download/{cls.resolved_server_version}/{asset}"
        except KeyError:
            raise RuntimeError("Binary server not supported on this platform!")

    @classmethod
    def metadata_file(cls) -> str:
        return os.path.join(LemminxPlugin.storage_path(), "binary_server.json")

    @classmethod
    def server_binary(cls) -> str:
        names = {
            "linux-x64": "lemminx-linux" if version_tuple(cls.resolved_server_version) < version_tuple('0.29.1') else "lemminx-linux-x86_64",
            "osx-arm64": "lemminx-osx-aarch_64",
            "osx-x64": "lemminx-osx-x86_64",
            "windows-x64": "lemminx-win32.exe",
        }
        try:
            name = names[f"{sublime.platform()}-{sublime.arch()}"]
            return os.path.join(LemminxPlugin.storage_path(), name)
        except KeyError:
            raise RuntimeError("Binary server not supported on this platform!")

    @classmethod
    def is_supported(cls):
        arch = sublime.arch()
        os = sublime.platform()
        return arch == "x64" or os == "osx" and arch == "arm64"


def version_tuple(value: str) -> tuple[int, int, int]:
    ''' Naive function to compare versions. '''
    if value == 'latest':
        return (999, 0, 0)
    try:
        v = value.split(".")
        return (int(v[0]), int(v[1]), int(v[2]))
    except Exception:
        return (0, 0, 0)


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
        if not cls.resolved_server_version:
            raise RuntimeError()

        urlretrieve(cls.download_url(), cls.server_binary())
        # write update cookie
        cls.save_metadata(True, cls.resolved_server_version)

    @classmethod
    def configure(cls, configuration: ClientConfig) -> None:
        configuration.command = ["java", "-jar", cls.server_binary()]
        additional_args = LemminxPlugin.root_settings.get("java_vmargs", [])
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
        return f"{cls.repo_url()}/{cls.resolved_server_version}/org.eclipse.lemminx-{cls.resolved_server_version}-uber.jar"

    @classmethod
    def metadata_file(cls) -> str:
        return os.path.join(LemminxPlugin.storage_path(), "java_server.json")

    @classmethod
    def server_binary(cls) -> str:
        return os.path.join(LemminxPlugin.storage_path(), "lemminx.jar")


class LemminxPlugin(LspPlugin):

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

    Main purpose is to provide python version agnostic package name for use
    in path sensitive locations, to ensure plugin even works if user installs
    package with different name.
    """

    root_settings: dict[str, Any] = {}
    """
    Root package settings (updated when the server starts).
    """

    _server: type[BinaryServerHandler] | type[JavaServerHandler] | None = None

    # LSP API methods

    @classmethod
    def on_pre_start_async(cls, context: OnPreStartContext) -> None:
        configuration = context.configuration
        cls.root_settings = configuration.root_settings
        if cls.needs_update_or_installation():
            cls.install_or_update()
        context.variables.update(cls.additional_variables())
        # add hard-coded and dynamic settings (not advertised via schema)
        configuration.settings.set(
            "xml.fileAssociations",
            cls.file_associations + (configuration.settings.get("xml.fileAssociations") or []),
        )
        configuration.settings.set("xml.server.workDir", cls.storage_path())
        configuration.settings.set("xml.telemetry.enabled", False)
        # apply settings to initialization options
        configuration.initialization_options.set("settings.xml", configuration.settings.get("xml"))
        # apply hard coded initialization options
        configuration.initialization_options.set("extendedClientCapabilities", {
            "actionableNotificationSupport": False,
            "openSettingsCommandSupport": False,
            "bindingWizardSupport": False,
            "shouldLanguageServerExitOnShutdown": True,
        })
        # forward request to server provider
        cls.server().configure(configuration)

    @classmethod
    def needs_update_or_installation(cls) -> bool:
        return cls.server().needs_update_or_installation()

    @classmethod
    def install_or_update(cls) -> None:
        os.makedirs(cls.storage_path(), exist_ok=True)
        return cls.server().install_or_update()

    # LemMinX specific methods

    @classmethod
    def server(cls) -> type[BinaryServerHandler] | type[JavaServerHandler]:
        if cls._server is None:
            if cls.root_settings.get("server_binary", True) and BinaryServerHandler.is_supported():
                cls._server = BinaryServerHandler
            else:
                cls._server = JavaServerHandler
        return cls._server

    @classmethod
    def additional_variables(cls) -> dict[str, str]:
        return {
            "package_path": cls.package_path(),
            "storage_path": cls.storage_path(),
            "package_uri": cls.package_uri(),
            "storage_uri": cls.storage_uri(),
        }

    # internal methods

    @classmethod
    def cleanup(cls) -> None:
        try:
            from package_control import events  # type: ignore

            if events.remove(cls.package_name):
                sublime.set_timeout_async(cls.remove_storage_path, 1000)
        except ImportError:
            pass  # Package Control is not required.

    @classmethod
    def remove_storage_path(cls) -> None:
        from shutil import rmtree

        storage_path = cls.storage_path()
        # Enable long path support on on Windows
        # to avoid errors when cleaning up paths with more than 256 chars.
        # see: https://stackoverflow.com/a/14076169/4643765
        # see: https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation
        if sublime.platform() == "windows":
            storage_path = Rf"\\?\{storage_path}"

        rmtree(storage_path, ignore_errors=True)

    @classmethod
    def package_path(cls) -> str:
        return os.path.join(sublime.packages_path(), cls.package_name)

    @classmethod
    def package_uri(cls) -> str:
        return filename_to_uri(cls.package_path())

    @classmethod
    def storage_path(cls) -> str:
        return str(cls.plugin_storage_path)

    @classmethod
    def storage_uri(cls) -> str:
        return filename_to_uri(cls.storage_path())

    @classmethod
    def install_schemas(cls) -> None:
        """
        Extract scheme files from sublime-package file.

        LemMinX can't read schemas or catalogs from zipped packages.
        """
        dest_path = os.path.join(cls.storage_path(), "cache", "sublime")
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

    LemminxPlugin.register()


def plugin_unloaded() -> None:
    LemminxPlugin.cleanup()
    LemminxPlugin.unregister()
