import os
import hashlib
import shutil
import sublime

from urllib.request import urlretrieve

from LSP.plugin import AbstractPlugin, register_plugin, unregister_plugin


SERVER_URL = "https://repo.eclipse.org/content/repositories/lemminx-releases/org/eclipse/lemminx/org.eclipse.lemminx/0.14.1/org.eclipse.lemminx-0.14.1-uber.jar"
SERVER_SHA256 = "fb38a67211b53c86ee96892a600760b3085e942ceb1c6249e8edc52993304a03"


def plugin_loaded():
    register_plugin(LemminxPlugin)


def plugin_unloaded():
    unregister_plugin(LemminxPlugin)


class LemminxPlugin(AbstractPlugin):
    @classmethod
    def name(cls):
        return "lemminx"

    @classmethod
    def configuration(cls):
        return (
            sublime.load_settings("LSP-lemminx.sublime-settings"),
            "Packages/" + __package__ + "/LSP-lemminx.sublime-settings"
        )

    @classmethod
    def needs_update_or_installation(cls):
        try:
            # move from cache path to package storage
            old_server_dir = os.path.join(sublime.cache_path(), __package__)
            if os.path.isdir(old_server_dir):
                shutil.move(old_server_dir, cls.server_dir())
            # check hash
            with open(cls.server_jar(), "rb") as stream:
                checksum = hashlib.sha256(stream.read()).hexdigest()
                return checksum.lower() != SERVER_SHA256.lower()
        except OSError:
            pass
        return True

    @classmethod
    def install_or_update(cls):
        server_dir = cls.server_dir()
        server_jar = cls.server_jar()

        # download new server binary
        os.makedirs(server_dir, exist_ok=True)
        urlretrieve(url=SERVER_URL, filename=server_jar)
        if cls.needs_update_or_installation():
            os.remove(server_jar)
            raise RuntimeError("Error downloading XML server binary!")

        # clear old server binaries
        for file_name in os.listdir(server_dir):
            if os.path.splitext(file_name)[1].lower() != ".jar":
                continue

            try:
                file_path = os.path.join(server_dir, file_name)
                if not os.path.samefile(file_path, server_jar):
                    os.remove(file_path)
            except FileNotFoundError:
                pass

    @classmethod
    def on_pre_start(cls, window, initiating_view, workspace_folders, configuration):
        configuration.command = [
            "java",
            "-Xmx64M",
            "-XX:+UseG1GC",
            "-XX:+UseStringDeduplication",
            "-DwatchParentProcess=false",
            "-jar", cls.server_jar()
        ]

    @classmethod
    def on_settings_changed(cls, dotted):
        dotted.set("xml.server.workDir", cls.server_dir())

    # internal methods

    @classmethod
    def server_dir(cls):
        return os.path.join(cls.storage_path(), __package__)

    @classmethod
    def server_jar(cls):
        return os.path.join(cls.server_dir(), SERVER_URL.rsplit("/", 1)[1])
