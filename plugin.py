import os
import hashlib
import shutil
import threading
import urllib.request
import sublime

from sublime_lib import ActivityIndicator

from LSP.plugin.core.handlers import LanguageHandler
from LSP.plugin.core.settings import ClientConfig, read_client_config


def is_java_installed() -> bool:
    return shutil.which("java") is not None


def package_cache() -> str:
    cache_path = os.path.join(sublime.cache_path(), __package__)
    os.makedirs(cache_path, exist_ok=True)
    return cache_path


def merge_configs(target: dict, source: dict):
    for key, value in target.items():
        new_value = source.get(key)
        if new_value is not None:
            if isinstance(value, dict):
                yield key, dict(merge_configs(value, new_value))
            elif isinstance(value, list):
                if isinstance(value[0], dict):
                    # dicts are unhashable
                    yield key, new_value
                else:
                    # always merge user values into defaults
                    yield key, list(set(value) + set(new_value))
            else:
                yield key, new_value
        else:
            yield key, value
    return None


class LspXMLServer(object):
    binary = None
    checksum = None
    ready = False
    url = None
    version = None
    thread = None

    @classmethod
    def check_binary(cls) -> bool:
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

    @classmethod
    def download(cls) -> None:
        with ActivityIndicator(
            target=sublime.active_window(),
            label="Downloading XML language server binary",
        ):
            urllib.request.urlretrieve(url=cls.url, filename=cls.binary)
            cls.ready = cls.check_binary()
            if not cls.ready:
                try:
                    os.remove(cls.binary)
                except OSError:
                    pass

        if not cls.ready:
            sublime.error_message("Error downloading XML server binary!")

        cls.thread = None

    @classmethod
    def setup(cls) -> None:
        if cls.thread or cls.ready:
            return

        # read server source information
        filename = "Packages/{}/server.json".format(__package__)
        server_json = sublime.decode_value(sublime.load_resource(filename))

        cls.version = server_json["version"]
        cls.url = sublime.expand_variables(server_json["url"], {"version": cls.version})
        cls.checksum = server_json["sha256"].lower()

        # built local server binary path
        dest_path = package_cache()
        cls.binary = os.path.join(dest_path, os.path.basename(cls.url))

        # download server binary on demand
        cls.ready = cls.check_binary()
        if not cls.ready:
            cls.thread = threading.Thread(target=cls.download)
            cls.thread.start()

        # clear old server binaries
        for fn in os.listdir(dest_path):
            fp = os.path.join(dest_path, fn)
            if fn[-4:].lower() == ".jar" and not os.path.samefile(fp, cls.binary):
                try:
                    os.remove(fp)
                except OSError:
                    pass

    @classmethod
    def cleanup(cls) -> None:
        cls.binary = None
        cls.checksum = None
        cls.ready = False
        cls.url = None
        cls.version = None


class LspXMLPlugin(LanguageHandler):

    def __init__(self):
        super().__init__()
        LspXMLServer.setup()

    @property
    def name(self) -> str:
        return __package__.lower()

    @property
    def config(self) -> ClientConfig:
        settings_file = "LSP-lemminx.sublime-settings"
        
        client_config = {
            "enabled": True,
            "command": ["java", "-jar", LspXMLServer.binary],
        }

        default_config = sublime.decode_value(
            sublime.load_resource(
                "Packages/{}/{}".format(__package__, settings_file)
            )
        )

        user_config = sublime.load_settings(settings_file)
        for key, value in merge_configs(default_config, user_config):
            client_config[key] = value

        return read_client_config(self.name, client_config)

    def on_start(self, window) -> bool:
        if not is_java_installed():
            sublime.status_message(
                "Please install Java Runtime for the XML language server to work."
            )
            return False
        if not LspXMLServer.ready:
            sublime.status_message("Language server binary not yet downloaded.")
            return False
        return True


def plugin_loaded() -> None:
    LspXMLServer.setup()


def plugin_unloaded() -> None:
    LspXMLServer.cleanup()
