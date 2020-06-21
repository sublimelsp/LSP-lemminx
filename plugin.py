import os
import hashlib
import sublime

from urllib.request import urlretrieve

from LSP.plugin.core.sessions import AbstractPlugin
from LSP.plugin.core.sessions import register_plugin
from LSP.plugin.core.sessions import unregister_plugin


SERVER_URL = "https://repo.eclipse.org/content/repositories/lemminx-releases/org/eclipse/lemminx/org.eclipse.lemminx/0.12.0/org.eclipse.lemminx-0.12.0-uber.jar"
SERVER_SHA256 = "09c0ef7c7802f958f9e8f0184641837d4410b6ca0c9adbebc29b96cca3e6cb2c"


class LemminxPlugin(AbstractPlugin):

    server_dir = ""
    server_jar = ""

    @classmethod
    def name(cls):
        return "lemminx"

    @classmethod
    def configuration(cls):
        name = "LSP-" + cls.name()
        base_name = name + ".sublime-settings"
        file_path = "Packages/{}/{}".format(__package__, base_name)
        settings = sublime.load_settings(base_name)

        # prepare server command
        cls.server_dir = os.path.join(sublime.cache_path(), __package__)
        cls.server_jar = os.path.join(cls.server_dir, SERVER_URL.rsplit("/", 1)[1])
        settings.set("command", ["java", "-jar", cls.server_jar])

        # setup scheme cache directory
        client_settings = settings.get("settings")
        client_settings["xml.server.workDir"] = cls.server_dir
        settings.set("settings", client_settings)

        return settings, file_path

    @classmethod
    def needs_update_or_installation(cls):
        try:
            with open(cls.server_jar, "rb") as stream:
                checksum = hashlib.sha256(stream.read()).hexdigest()
                return checksum.lower() != SERVER_SHA256.lower()
        except OSError:
            pass
        return True

    @classmethod
    def install_or_update(cls):
        # clear old server binaries
        for file_name in os.listdir(cls.server_dir):
            if file_name.splitext()[1].lower() != ".jar":
                continue

            try:
                file_path = os.path.join(cls.server_dir, file_name)
                if not os.path.samefile(file_path, cls.server_jar):
                    os.remove(file_path)
            except FileNotFoundError:
                pass

        # download new server binary
        urlretrieve(url=SERVER_URL, filename=cls.server_jar)
        if cls.needs_update_or_installation():
            os.remove(cls.server_jar)
            raise RuntimeError("Error downloading XML server binary!")


def plugin_loaded():
    register_plugin(LemminxPlugin)


def plugin_unloaded():
    unregister_plugin(LemminxPlugin)
