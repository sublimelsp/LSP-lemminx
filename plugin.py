import os
import hashlib
import shutil
import urllib.request
import sublime

from LSP.plugin import AbstractPlugin
from LSP.plugin import ClientConfig
from LSP.plugin import register_plugin  # https://github.com/sublimelsp/LSP/issues/899
from LSP.plugin import unregister_plugin  # https://github.com/sublimelsp/LSP/issues/899
from LSP.plugin import WorkspaceFolder
from LSP.plugin.core.typing import List, Optional


class Lemminx(AbstractPlugin):

    binary = None  # type: Optional[str]
    checksum = None  # type: Optional[str]
    url = None  # type: Optional[str]
    version = None  # type: Optional[str]

    @classmethod
    def name(cls) -> str:
        return cls.__name__.lower()

    @classmethod
    def configuration(cls) -> sublime.Settings:
        if not cls.binary:
            # mega hack, remove! https://github.com/sublimelsp/LSP/issues/899
            plugin_loaded()
        settings = super().configuration()
        settings.set("command", ["java", "-jar", cls.binary])
        return settings

    @classmethod
    def needs_update_or_installation(cls) -> bool:
        return not cls._is_valid_binary()

    @classmethod
    def install_or_update(cls) -> None:
        """
        Called after needs_update_or_installation returns True. Already runs
        in a separate thread from the UI thread, don't spawn threads.
        """
        urllib.request.urlretrieve(url=cls.url, filename=cls.binary)
        if not cls._is_valid_binary():
            try:
                os.remove(cls.binary)
            except OSError:
                pass
            raise RuntimeError("Error downloading XML server binary!")

    @classmethod
    def can_start(cls, window: sublime.Window, initiating_view: sublime.View,
                  workspace_folders: List[WorkspaceFolder],
                  configuration: ClientConfig) -> Optional[str]:
        """
        Called after needs_update_or_installation
        """
        if not shutil.which("java"):
            return "Please install Java Runtime for the XML language server to work."

    @classmethod
    def _is_valid_binary(cls) -> bool:
        """Check sha256 hash of downloaded binary.

        Make sure not to run malicious or corrupted code.
        """
        try:
            with open(cls.binary, "rb") as stream:
                checksum = hashlib.sha256(stream.read()).hexdigest()
                return cls.checksum == checksum
        except OSError:
            pass
        return False


def plugin_loaded() -> None:
    # read server source information
    filename = "Packages/{}/server.json".format(__package__)
    server_json = sublime.decode_value(sublime.load_resource(filename))
    Lemminx.version = server_json["version"]
    Lemminx.url = sublime.expand_variables(
        server_json["url"],
        {"version": Lemminx.version})
    Lemminx.checksum = server_json["sha256"].lower()
    # built local server binary path
    dest_path = _package_cache()
    Lemminx.binary = os.path.join(dest_path, os.path.basename(Lemminx.url))


def plugin_unloaded() -> None:
    Lemminx.binary = None
    Lemminx.checksum = None
    Lemminx.url = None
    Lemminx.version = None


def _package_cache() -> str:
    cache_path = os.path.join(sublime.cache_path(), __package__)
    os.makedirs(cache_path, exist_ok=True)
    return cache_path
